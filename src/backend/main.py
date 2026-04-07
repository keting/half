import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import inspect, text
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import engine, SessionLocal, Base
from models import User, AgentTypeConfig, ModelDefinition, AgentTypeModelMap, ProjectPlan, Task, GlobalSetting
from auth import hash_password
from routers import auth as auth_router
from routers import agents as agents_router
from routers import projects as projects_router
from routers import plans as plans_router
from routers import tasks as tasks_router
from routers import polling as polling_router
from routers import agent_settings as agent_settings_router
from routers import settings as settings_router
from services.polling_service import polling_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("half")


def migrate_task_code_unique_constraint():
    """Migrate task_code from global unique to (project_id, task_code) composite unique."""
    with engine.begin() as conn:
        ensure_app_meta(conn)
        migrated = conn.execute(
            text("SELECT value FROM app_meta WHERE key = 'task_code_composite_unique_v1'")
        ).scalar()
        if migrated:
            return

        # Check if old global unique index exists on task_code
        indexes = conn.execute(text("PRAGMA index_list('tasks')")).fetchall()
        has_old_unique = False
        for idx in indexes:
            idx_name = idx[1]
            cols = conn.execute(text(f"PRAGMA index_info('{idx_name}')")).fetchall()
            col_names = [c[2] for c in cols]
            if col_names == ["task_code"] and idx[2]:  # unique index on task_code alone
                has_old_unique = True
                break

        if has_old_unique:
            # SQLite cannot drop constraints directly; recreate the table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tasks_new (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    plan_id INTEGER NOT NULL REFERENCES project_plans(id),
                    task_code TEXT NOT NULL,
                    task_name TEXT NOT NULL,
                    description TEXT,
                    assignee_agent_id INTEGER REFERENCES agents(id),
                    status TEXT DEFAULT 'pending',
                    depends_on_json TEXT DEFAULT '[]',
                    expected_output_path TEXT,
                    result_file_path TEXT,
                    usage_file_path TEXT,
                    last_error TEXT,
                    timeout_minutes INTEGER DEFAULT 10,
                    dispatched_at DATETIME,
                    completed_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE(project_id, task_code)
                )
            """))
            conn.execute(text("INSERT INTO tasks_new SELECT * FROM tasks"))
            conn.execute(text("DROP TABLE tasks"))
            conn.execute(text("ALTER TABLE tasks_new RENAME TO tasks"))
            logger.info("Migrated tasks table: task_code unique constraint changed to (project_id, task_code)")

        conn.execute(
            text("INSERT INTO app_meta(key, value) VALUES ('task_code_composite_unique_v1', 'done')")
        )


def ensure_schema_updates():
    inspector = inspect(engine)
    required_columns = {
        "agents": {
            "capability": "TEXT",
            "models_json": "TEXT DEFAULT '[]'",
            "short_term_reset_at": "DATETIME",
            "short_term_reset_interval_hours": "INTEGER",
            "short_term_reset_needs_confirmation": "BOOLEAN DEFAULT 0",
            "long_term_reset_at": "DATETIME",
            "long_term_reset_interval_days": "INTEGER",
            "long_term_reset_needs_confirmation": "BOOLEAN DEFAULT 0",
            "long_term_reset_mode": "TEXT DEFAULT 'days'",
            "display_order": "INTEGER DEFAULT 0",
        },
        "projects": {
            "collaboration_dir": "TEXT",
            "polling_interval_min": "INTEGER",
            "polling_interval_max": "INTEGER",
            "polling_start_delay_minutes": "INTEGER",
            "polling_start_delay_seconds": "INTEGER",
        },
        "project_plans": {
            "prompt_text": "TEXT",
            "status": "TEXT DEFAULT 'completed'",
            "source_path": "TEXT",
            "include_usage": "BOOLEAN DEFAULT 0",
            "selected_agent_ids_json": "TEXT DEFAULT '[]'",
            "selected_agent_models_json": "TEXT DEFAULT '{}'",
            "dispatched_at": "DATETIME",
            "detected_at": "DATETIME",
            "last_error": "TEXT",
        },
        "agent_type_configs": {
            "description": "TEXT",
            "display_order": "INTEGER DEFAULT 0",
        },
        "agent_type_model_map": {
            "display_order": "INTEGER DEFAULT 0",
        },
    }

    with engine.begin() as conn:
        for table_name, columns in required_columns.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}'))
                    logger.info("Added missing column %s.%s", table_name, column_name)


def ensure_app_meta(conn):
    conn.execute(text("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"))


def repair_legacy_agent_reset_times():
    with engine.begin() as conn:
        ensure_app_meta(conn)
        migrated = conn.execute(
            text("SELECT value FROM app_meta WHERE key = 'agent_reset_times_beijing_v1'")
        ).scalar()
        if migrated:
            return
        updated = conn.execute(
            text(
                """
                UPDATE agents
                SET short_term_reset_at = CASE
                        WHEN short_term_reset_at IS NOT NULL THEN datetime(short_term_reset_at, '+8 hours')
                        ELSE NULL
                    END,
                    long_term_reset_at = CASE
                        WHEN long_term_reset_at IS NOT NULL THEN datetime(long_term_reset_at, '+8 hours')
                        ELSE NULL
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE short_term_reset_at IS NOT NULL OR long_term_reset_at IS NOT NULL
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_meta(key, value) VALUES ('agent_reset_times_beijing_v1', 'done')"
            )
        )
        if updated.rowcount:
            logger.info("Adjusted legacy agent reset times to Beijing-local storage for %s rows", updated.rowcount)


def seed_agent_type_configs():
    """Seed agent type configs and model definitions from hardcoded defaults if tables are empty."""
    db = SessionLocal()
    try:
        if db.query(AgentTypeConfig).first() is not None:
            return  # Already seeded

        SEED_TYPES = {
            "claude": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet-latest"],
            "codex": ["codex-mini-latest", "codex-1", "gpt-5-codex"],
            "cursor": ["cursor-default", "gpt-5", "claude-sonnet-4-5"],
            "windsurf": ["windsurf-default", "claude-sonnet-4-5", "gpt-5"],
        }

        model_cache: dict[str, ModelDefinition] = {}
        for type_name, model_names in SEED_TYPES.items():
            agent_type = AgentTypeConfig(name=type_name)
            db.add(agent_type)
            db.flush()
            for model_name in model_names:
                if model_name not in model_cache:
                    model_def = ModelDefinition(name=model_name)
                    db.add(model_def)
                    db.flush()
                    model_cache[model_name] = model_def
                db.add(AgentTypeModelMap(
                    agent_type_id=agent_type.id,
                    model_definition_id=model_cache[model_name].id,
                ))
        db.commit()
        logger.info("Seeded agent type configs with %d types and %d models", len(SEED_TYPES), len(model_cache))
    finally:
        db.close()


def seed_global_polling_settings():
    """Initialize global polling settings with defaults if not already set."""
    db = SessionLocal()
    try:
        # Check if settings already exist
        existing = db.query(GlobalSetting).filter(GlobalSetting.key == "polling_interval_min").first()
        if existing is not None:
            return  # Already seeded

        defaults = {
            "polling_interval_min": "15",  # seconds
            "polling_interval_max": "30",  # seconds
            "polling_start_delay_minutes": "0",
            "polling_start_delay_seconds": "0",
        }

        descriptions = {
            "polling_interval_min": "Minimum polling interval in seconds",
            "polling_interval_max": "Maximum polling interval in seconds",
            "polling_start_delay_minutes": "Minutes to delay before starting polling",
            "polling_start_delay_seconds": "Seconds to delay before starting polling (added to minutes)",
        }

        for key, value in defaults.items():
            setting = GlobalSetting(
                key=key,
                value=value,
                description=descriptions.get(key),
            )
            db.add(setting)

        db.commit()
        logger.info("Global polling settings initialized with defaults")
    except Exception as e:
        logger.error("Failed to seed global polling settings: %s", e)
    finally:
        db.close()


def repair_unassigned_tasks_from_plan_json():
    db = SessionLocal()
    repaired = 0
    try:
        tasks = db.query(Task).filter(Task.assignee_agent_id.is_(None)).all()
        if not tasks:
            return

        plans_by_id = {
            plan.id: plan
            for plan in db.query(ProjectPlan).filter(ProjectPlan.id.in_([task.plan_id for task in tasks])).all()
        }

        for task in tasks:
            plan = plans_by_id.get(task.plan_id)
            if not plan or not plan.plan_json:
                continue
            try:
                plan_data = json.loads(plan.plan_json)
            except json.JSONDecodeError:
                repaired_json = plans_router._try_repair_json(plan.plan_json)
                if repaired_json is None:
                    continue
                plan_data = repaired_json

            tasks_data = plan_data.get("tasks", [])
            if not isinstance(tasks_data, list):
                continue

            matched_task = next(
                (item for item in tasks_data if isinstance(item, dict) and item.get("task_code") == task.task_code),
                None,
            )
            if not matched_task:
                continue

            assignee_agent_id = plans_router._resolve_assignee_agent_id(db, matched_task.get("assignee"))
            if not assignee_agent_id:
                continue

            task.assignee_agent_id = assignee_agent_id
            repaired += 1

        if repaired:
            db.commit()
            logger.info("Repaired %s unassigned tasks from plan JSON assignee mappings", repaired)
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_schema_updates()
    migrate_task_code_unique_constraint()
    repair_legacy_agent_reset_times()
    seed_agent_type_configs()
    seed_global_polling_settings()
    repair_unassigned_tasks_from_plan_json()
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                password_hash=hash_password(settings.ADMIN_PASSWORD),
            )
            db.add(admin)
            db.commit()
            logger.info("Default admin user created")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    logger.info("Database initialized")
    poller_task = asyncio.create_task(polling_loop(settings.POLL_INTERVAL_SECONDS))
    logger.info("Background poller started")
    yield
    # Shutdown
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    logger.info("Background poller stopped")


app = FastAPI(title="HALF Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(agents_router.router)
app.include_router(projects_router.router)
app.include_router(plans_router.router)
app.include_router(tasks_router.router)
app.include_router(polling_router.router)
app.include_router(agent_settings_router.router)
app.include_router(settings_router.router)


@app.get("/")
def root():
    return {"name": "HALF Backend", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "ok"}
