"""Tests covering the acceptance criteria for the auto-dispatch agents PRD.

AC-1  After plan finalization, auto tasks execute and complete without manual
      intervention; project transitions to completed when all tasks finish.
AC-2  Auto agent with missing/invalid API credentials → task enters
      needs_attention; no API key is exposed in responses or event logs.
AC-3  Mode mismatch between project and agent → backend returns 400.
AC-4  Multiple ready auto tasks are all returned for concurrent dispatch;
      the _running_auto_tasks guard prevents duplicate execution of the same
      task.
AC-5  All existing agents/projects default to manual mode; existing workflows
      are unaffected.
AC-6  API Key never appears in any API response, event log, or task detail.
"""

import asyncio
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database
from auth import hash_password
from models import (
    Agent,
    AgentTypeConfig,
    Base,
    GlobalSetting,
    Project,
    ProjectPlan,
    Task,
    TaskEvent,
    User,
)
from routers import agent_settings as agent_settings_router
from routers import auth as auth_router
from routers import projects as projects_router
from services.agent_credentials import encrypt_api_key
from services.auto_dispatch import (
    _complete_project_if_done,
    get_ready_auto_tasks,
    is_auto_agent_type,
    is_task_ready,
    run_auto_task,
)


# ---------------------------------------------------------------------------
# Helpers shared across multiple test classes
# ---------------------------------------------------------------------------

def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _add_global_settings(db):
    db.add_all([
        GlobalSetting(key="polling_interval_min", value="15"),
        GlobalSetting(key="polling_interval_max", value="30"),
        GlobalSetting(key="polling_start_delay_minutes", value="0"),
        GlobalSetting(key="polling_start_delay_seconds", value="0"),
    ])


# ---------------------------------------------------------------------------
# AC-1 / AC-2 (service layer) — DAG readiness and credential validation
# ---------------------------------------------------------------------------

class TestIsTaskReady(unittest.TestCase):
    """Unit tests for the DAG dependency resolver used by auto-dispatch."""

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        project = Project(
            id=1, name="P",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/1",
            status="executing",
            created_by=1,
        )
        plan = ProjectPlan(id=1, project_id=1, status="final")
        self.db.add_all([user, project, plan])
        self.db.commit()
        self.addCleanup(self.db.close)
        self._next_id = 1

    def _task(self, code: str, status: str, depends_on: list | None = None) -> Task:
        t = Task(
            id=self._next_id,
            project_id=1, plan_id=1,
            task_code=code, task_name=code,
            status=status,
            depends_on_json=json.dumps(depends_on or []),
            expected_output_path=f"o/1/{code}/result.json",
        )
        self._next_id += 1
        self.db.add(t)
        self.db.commit()
        return t

    def test_no_deps_is_always_ready(self):
        t = self._task("T1", "pending")
        self.assertTrue(is_task_ready(self.db, t))

    def test_completed_dep_makes_task_ready(self):
        self._task("T1", "completed")
        t2 = self._task("T2", "pending", depends_on=["T1"])
        self.assertTrue(is_task_ready(self.db, t2))

    def test_abandoned_dep_makes_task_ready(self):
        self._task("T1", "abandoned")
        t2 = self._task("T2", "pending", depends_on=["T1"])
        self.assertTrue(is_task_ready(self.db, t2))

    def test_pending_dep_blocks_task(self):
        self._task("T1", "pending")
        t2 = self._task("T2", "pending", depends_on=["T1"])
        self.assertFalse(is_task_ready(self.db, t2))

    def test_running_dep_blocks_task(self):
        self._task("T1", "running")
        t2 = self._task("T2", "pending", depends_on=["T1"])
        self.assertFalse(is_task_ready(self.db, t2))

    def test_partial_deps_block_task(self):
        """AC-1: all predecessors must finish before downstream is ready."""
        self._task("T1", "completed")
        self._task("T2", "pending")
        t3 = self._task("T3", "pending", depends_on=["T1", "T2"])
        self.assertFalse(is_task_ready(self.db, t3))


# ---------------------------------------------------------------------------

class TestGetReadyAutoTasks(unittest.TestCase):
    """Tests for get_ready_auto_tasks including credential and DAG checks."""

    _VALID_KEY = "super-secret-key-for-testing"

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        project = Project(
            id=1, name="P",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/1",
            status="executing",
            is_auto=True,
            created_by=1,
        )
        plan = ProjectPlan(id=1, project_id=1, status="final")

        # Auto agent type — valid credentials
        self.auto_type = AgentTypeConfig(
            id=1, name="gpt-auto",
            sdk_type="claude",
            api_base_url="https://api.example.com/v1",
            api_key_encrypted=encrypt_api_key(self._VALID_KEY),
        )
        # Auto agent type — missing credentials (sdk_type set but no key/url)
        self.no_creds_type = AgentTypeConfig(
            id=2, name="gpt-no-creds",
            sdk_type="claude",
            api_base_url=None,
            api_key_encrypted=None,
        )
        # Manual agent type (no sdk_type at all)
        self.manual_type = AgentTypeConfig(id=3, name="manual-type")

        self.auto_agent = Agent(
            id=1, name="Auto", slug="auto-1", agent_type="gpt-auto", created_by=1
        )
        self.no_creds_agent = Agent(
            id=2, name="NoCreds", slug="nocreds-1", agent_type="gpt-no-creds", created_by=1
        )
        self.manual_agent = Agent(
            id=3, name="Manual", slug="manual-1", agent_type="manual-type", created_by=1
        )

        self.db.add_all([
            user, project, plan,
            self.auto_type, self.no_creds_type, self.manual_type,
            self.auto_agent, self.no_creds_agent, self.manual_agent,
        ])
        self.db.commit()
        self.addCleanup(self.db.close)
        self._task_seq = 1

    def _task(self, code: str, agent_id: int, depends_on: list | None = None) -> Task:
        t = Task(
            id=self._task_seq,
            project_id=1, plan_id=1,
            task_code=code, task_name=code,
            status="pending",
            assignee_agent_id=agent_id,
            depends_on_json=json.dumps(depends_on or []),
            expected_output_path=f"o/1/{code}/result.json",
        )
        self._task_seq += 1
        self.db.add(t)
        self.db.commit()
        return t

    def test_ready_task_returned_when_credentials_valid(self):
        """AC-1: valid auto task appears in ready list."""
        t = self._task("T1", self.auto_agent.id)
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(t.id, ready)

    def test_missing_credentials_marks_task_needs_attention(self):
        """AC-2: missing credentials → task becomes needs_attention, not returned."""
        t = self._task("T1", self.no_creds_agent.id)
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertNotIn(t.id, ready)
        self.db.refresh(t)
        self.assertEqual(t.status, "needs_attention")
        self.assertIsNotNone(t.last_error)
        self.assertIn("API credentials", t.last_error)

    def test_missing_credentials_records_failed_event(self):
        """AC-2: a task event with type auto_dispatch_failed is created."""
        t = self._task("T1", self.no_creds_agent.id)
        get_ready_auto_tasks(self.db, project_id=1)
        event = (
            self.db.query(TaskEvent)
            .filter(TaskEvent.task_id == t.id)
            .first()
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "auto_dispatch_failed")

    def test_failed_event_detail_does_not_contain_api_key(self):
        """AC-6: error event detail must not leak any stored API key."""
        t = self._task("T1", self.no_creds_agent.id)
        get_ready_auto_tasks(self.db, project_id=1)
        events = self.db.query(TaskEvent).filter(TaskEvent.task_id == t.id).all()
        for event in events:
            self.assertNotIn(self._VALID_KEY, event.detail or "")

    def test_manual_agent_task_not_returned(self):
        """AC-5: tasks assigned to manual agents are ignored by auto-dispatch."""
        self._task("T1", self.manual_agent.id)
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertEqual(ready, [])

    def test_blocked_task_not_returned(self):
        """AC-1: task with unsatisfied dependency is not dispatched."""
        dep = self._task("T1", self.auto_agent.id)          # pending
        t2 = self._task("T2", self.auto_agent.id, depends_on=["T1"])
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(dep.id, ready)          # T1 has no deps, it's ready
        self.assertNotIn(t2.id, ready)        # T2 is blocked

    def test_multiple_independent_ready_tasks_all_returned(self):
        """AC-4: all ready tasks are returned so they can be dispatched in parallel."""
        t1 = self._task("T1", self.auto_agent.id)
        t2 = self._task("T2", self.auto_agent.id)
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(t1.id, ready)
        self.assertIn(t2.id, ready)


# ---------------------------------------------------------------------------
# AC-1, AC-2, AC-4 (service layer) — run_auto_task state transitions
# ---------------------------------------------------------------------------

class TestRunAutoTask(unittest.TestCase):
    """Tests for run_auto_task — state machine and concurrent-dispatch guard."""

    _VALID_KEY = "super-secret-key"

    def setUp(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        with self.SessionLocal() as db:
            user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
            project = Project(
                id=1, name="P",
                git_repo_url="https://github.com/x/y",
                collaboration_dir="o/1",
                status="executing",
                is_auto=True,
                created_by=1,
            )
            plan = ProjectPlan(id=1, project_id=1, status="final")
            auto_type = AgentTypeConfig(
                id=1, name="gpt-auto",
                sdk_type="claude",
                api_base_url="https://api.example.com/v1",
                api_key_encrypted=encrypt_api_key(self._VALID_KEY),
            )
            auto_agent = Agent(
                id=1, name="Auto", slug="auto-1", agent_type="gpt-auto", created_by=1
            )
            db.add_all([user, project, plan, auto_type, auto_agent])
            db.commit()

        import services.auto_dispatch as _mod
        self._orig_SessionLocal = _mod.SessionLocal
        _mod.SessionLocal = self.SessionLocal
        # Clean the in-progress guard set before each test
        _mod._running_auto_tasks.clear()
        self.addCleanup(setattr, _mod, "SessionLocal", self._orig_SessionLocal)
        self.addCleanup(_mod._running_auto_tasks.clear)
        self._task_seq = 1

    def _add_task(self, code: str, depends_on: list | None = None) -> int:
        with self.SessionLocal() as db:
            t = Task(
                id=self._task_seq,
                project_id=1, plan_id=1,
                task_code=code, task_name=code,
                status="pending",
                assignee_agent_id=1,
                depends_on_json=json.dumps(depends_on or []),
                expected_output_path=f"o/1/{code}/result.json",
            )
            self._task_seq += 1
            db.add(t)
            db.commit()
            return t.id

    def test_successful_run_marks_task_completed(self):
        """AC-1: pending → running → completed on successful runner invocation."""
        task_id = self._add_task("T1")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            self.assertEqual(task.status, "completed")
            self.assertIsNotNone(task.completed_at)

    def test_successful_run_records_started_and_completed_events(self):
        """AC-1: both auto_dispatch_started and auto_dispatch_completed events logged."""
        task_id = self._add_task("T1")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            events = db.query(TaskEvent).filter(TaskEvent.task_id == task_id).all()
            event_types = {e.event_type for e in events}
            self.assertIn("auto_dispatch_started", event_types)
            self.assertIn("auto_dispatch_completed", event_types)

    def test_event_details_do_not_contain_api_key(self):
        """AC-6: task events must never leak the stored API key."""
        task_id = self._add_task("T1")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            events = db.query(TaskEvent).filter(TaskEvent.task_id == task_id).all()
            for event in events:
                self.assertNotIn(self._VALID_KEY, event.detail or "")

    def test_runner_exception_marks_task_needs_attention(self):
        """AC-2: runner failure → task enters needs_attention with error info."""
        task_id = self._add_task("T1")
        with patch(
            "services.auto_dispatch.run_task_for_agent",
            new_callable=AsyncMock,
            side_effect=RuntimeError("auth failed: 401 Unauthorized"),
        ):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            self.assertEqual(task.status, "needs_attention")
            self.assertIsNotNone(task.last_error)
            self.assertIn("auth failed", task.last_error)

    def test_runner_exception_records_failed_event(self):
        """AC-2: auto_dispatch_failed event recorded on runner error."""
        task_id = self._add_task("T1")
        with patch(
            "services.auto_dispatch.run_task_for_agent",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection timeout"),
        ):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            events = db.query(TaskEvent).filter(TaskEvent.task_id == task_id).all()
            failed = [e for e in events if e.event_type == "auto_dispatch_failed"]
            self.assertGreater(len(failed), 0)

    def test_project_completed_when_all_tasks_finish(self):
        """AC-1: project transitions to completed once all tasks are done."""
        task_id = self._add_task("T1")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            project = db.query(Project).filter(Project.id == 1).first()
            self.assertEqual(project.status, "completed")

    def test_running_guard_prevents_duplicate_dispatch(self):
        """AC-4: _running_auto_tasks guard skips re-entrant execution of the same task."""
        import services.auto_dispatch as _mod
        task_id = self._add_task("T1")
        _mod._running_auto_tasks.add(task_id)
        with patch(
            "services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock
        ) as mock_runner:
            asyncio.run(run_auto_task(task_id))
            mock_runner.assert_not_called()

    def test_dag_chain_downstream_task_dispatched_after_upstream_completes(self):
        """AC-1: T2 is automatically dispatched once T1 completes."""
        t1_id = self._add_task("T1")
        t2_id = self._add_task("T2", depends_on=["T1"])
        call_order: list[int] = []

        async def _mock_runner(task_id: int, project_id: int) -> None:
            call_order.append(task_id)

        with patch(
            "services.auto_dispatch.run_task_for_agent",
            new=AsyncMock(side_effect=_mock_runner),
        ):
            asyncio.run(run_auto_task(t1_id))

        self.assertIn(t1_id, call_order)
        self.assertIn(t2_id, call_order)
        # T1 must have been dispatched before T2
        self.assertLess(call_order.index(t1_id), call_order.index(t2_id))


# ---------------------------------------------------------------------------
# AC-3 — project/agent mode compatibility via HTTP API
# ---------------------------------------------------------------------------

def _build_app(session_factory):
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(projects_router.router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = override_db
    return app


class TestProjectAgentModeCompatibility(unittest.TestCase):
    """AC-3: adding a mismatched-mode agent to a project must return HTTP 400."""

    def setUp(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.client = TestClient(_build_app(self.SessionLocal))

        with self.SessionLocal() as db:
            user = User(
                username="owner",
                password_hash=hash_password("Owner123"),
                role="user",
                status="active",
            )
            db.add(user)
            db.flush()
            self._user_id = user.id

            auto_type = AgentTypeConfig(
                name="gpt-auto",
                sdk_type="claude",
                api_base_url="https://api.example.com/v1",
                api_key_encrypted=encrypt_api_key("some-key"),
            )
            manual_type = AgentTypeConfig(name="manual-type")
            db.add_all([auto_type, manual_type])
            db.flush()

            self._auto_agent_id = self._seed_agent(db, user.id, "auto-a1", "gpt-auto")
            self._manual_agent_id = self._seed_agent(db, user.id, "manual-a1", "manual-type")
            _add_global_settings(db)
            db.commit()

    def _seed_agent(self, db, user_id: int, slug: str, agent_type: str) -> int:
        agent = Agent(
            name=slug, slug=slug,
            agent_type=agent_type,
            availability_status="available",
            subscription_expires_at=datetime.utcnow() + timedelta(days=30),
            created_by=user_id,
        )
        db.add(agent)
        db.flush()
        return agent.id

    def _login(self) -> dict:
        r = self.client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "Owner123"},
        )
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def test_auto_project_with_manual_agent_returns_400(self):
        """AC-3: auto project cannot include a manual-mode agent."""
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Test",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": True,
                "agent_ids": [self._manual_agent_id],
            },
            headers=self._login(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("手动模式", r.json()["detail"])

    def test_manual_project_with_auto_agent_returns_400(self):
        """AC-3: manual project cannot include an auto-mode agent."""
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Test",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": False,
                "agent_ids": [self._auto_agent_id],
            },
            headers=self._login(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("自动模式", r.json()["detail"])

    def test_auto_project_with_auto_agent_accepted(self):
        """AC-3: matching auto modes are accepted (positive case)."""
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Auto Project",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": True,
                "agent_ids": [self._auto_agent_id],
            },
            headers=self._login(),
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["is_auto"])

    def test_manual_project_with_manual_agent_accepted(self):
        """AC-3: matching manual modes are accepted (positive case)."""
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Manual Project",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": False,
                "agent_ids": [self._manual_agent_id],
            },
            headers=self._login(),
        )
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.json()["is_auto"])

    def test_update_project_with_mismatched_agent_returns_400(self):
        """AC-3: updating a project to add a mode-mismatched agent returns 400."""
        headers = self._login()
        # Create a valid auto project first
        create_resp = self.client.post(
            "/api/projects",
            json={
                "name": "Auto",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": True,
                "agent_ids": [self._auto_agent_id],
            },
            headers=headers,
        )
        self.assertEqual(create_resp.status_code, 201)
        project_id = create_resp.json()["id"]

        # Try to swap to a manual agent
        r = self.client.put(
            f"/api/projects/{project_id}",
            json={"agent_ids": [self._manual_agent_id]},
            headers=headers,
        )
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# AC-5 — backward compatibility defaults
# ---------------------------------------------------------------------------

class TestBackwardCompatibility(unittest.TestCase):
    """AC-5: all legacy agents and projects default to manual (non-auto) mode."""

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        self.db.add(user)
        self.db.commit()
        self.addCleanup(self.db.close)

    def test_project_defaults_to_manual_mode(self):
        """AC-5: Project.is_auto is False by default."""
        project = Project(
            name="Legacy",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/legacy",
            status="draft",
            created_by=1,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        self.assertFalse(project.is_auto)

    def test_agent_type_without_sdk_type_is_manual(self):
        """AC-5: AgentTypeConfig without sdk_type is treated as manual by is_auto_agent_type."""
        manual_type = AgentTypeConfig(name="legacy-type")
        self.assertFalse(is_auto_agent_type(manual_type))

    def test_agent_type_with_sdk_type_is_auto(self):
        """Positive check: sdk_type present → is_auto_agent_type returns True."""
        auto_type = AgentTypeConfig(name="auto-type", sdk_type="claude")
        self.assertTrue(is_auto_agent_type(auto_type))

    def test_none_agent_type_config_is_not_auto(self):
        """AC-5: None agent type config is treated as manual."""
        self.assertFalse(is_auto_agent_type(None))

    def test_manual_agent_tasks_excluded_from_auto_dispatch(self):
        """AC-5: tasks assigned to legacy manual agents are never auto-dispatched."""
        project = Project(
            id=2, name="Legacy",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/2",
            status="executing",
            created_by=1,
        )
        plan = ProjectPlan(id=2, project_id=2, status="final")
        manual_type = AgentTypeConfig(id=10, name="legacy-manual")   # no sdk_type
        agent = Agent(
            id=10, name="LegacyAgent", slug="legacy-1",
            agent_type="legacy-manual", created_by=1,
        )
        task = Task(
            project_id=2, plan_id=2,
            task_code="T1", task_name="T1",
            status="pending",
            assignee_agent_id=10,
            depends_on_json="[]",
            expected_output_path="o/2/T1/result.json",
        )
        self.db.add_all([project, plan, manual_type, agent, task])
        self.db.commit()
        ready = get_ready_auto_tasks(self.db, project_id=2)
        self.assertEqual(ready, [])


# ---------------------------------------------------------------------------
# AC-6 — API key never exposed in HTTP responses
# ---------------------------------------------------------------------------

class TestApiKeyNotExposed(unittest.TestCase):
    """AC-6: raw API Key must never appear in any API response payload."""

    _SECRET = "ultra-secret-api-key-must-not-leak"

    def setUp(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        app = FastAPI()
        app.include_router(auth_router.router)
        app.include_router(agent_settings_router.router)

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[database.get_db] = override_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            admin = User(
                username="admin",
                password_hash=hash_password("Admin123"),
                role="admin",
                status="active",
            )
            db.add(admin)
            db.commit()

    def _admin_headers(self) -> dict:
        r = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "Admin123"},
        )
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def _create_auto_type(self, headers: dict, name: str = "gpt-auto") -> dict:
        r = self.client.post(
            "/api/agent-settings/types",
            json={
                "name": name,
                "sdk_type": "claude",
                "api_base_url": "https://api.example.com/v1",
                "api_key": self._SECRET,
            },
            headers=headers,
        )
        self.assertEqual(r.status_code, 201)
        return r.json()

    def test_create_response_does_not_contain_raw_api_key(self):
        """AC-6: POST /api/agent-settings/types response must not expose the key."""
        headers = self._admin_headers()
        data = self._create_auto_type(headers)
        self.assertNotIn(self._SECRET, json.dumps(data))
        self.assertNotIn("api_key_encrypted", data)
        self.assertTrue(data.get("has_api_key"))

    def test_list_response_does_not_contain_raw_api_key(self):
        """AC-6: GET /api/agent-settings/types response must not expose the key."""
        headers = self._admin_headers()
        self._create_auto_type(headers)
        r = self.client.get("/api/agent-settings/types", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(self._SECRET, json.dumps(r.json()))

    def test_update_response_does_not_contain_raw_api_key(self):
        """AC-6: PUT /api/agent-settings/types/{id} response must not expose new key."""
        headers = self._admin_headers()
        data = self._create_auto_type(headers)
        type_id = data["id"]
        updated_secret = "brand-new-secret-key"
        r = self.client.put(
            f"/api/agent-settings/types/{type_id}",
            json={"api_key": updated_secret},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200)
        payload = json.dumps(r.json())
        self.assertNotIn(updated_secret, payload)
        self.assertNotIn(self._SECRET, payload)

    def test_agent_type_out_schema_exposes_only_has_api_key_flag(self):
        """AC-6: AgentTypeOut schema has has_api_key flag but no raw key fields."""
        from routers.agent_settings import AgentTypeOut
        fields = set(AgentTypeOut.model_fields.keys())
        self.assertNotIn("api_key", fields)
        self.assertNotIn("api_key_encrypted", fields)
        self.assertIn("has_api_key", fields)


if __name__ == "__main__":
    unittest.main()
