import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

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
from models import Agent, Base, GlobalSetting, Project, ProjectPlan, Task, User
from routers import agents as agents_router
from routers import auth as auth_router
from routers import plans as plans_router
from routers import polling as polling_router
from routers import projects as projects_router
from routers import tasks as tasks_router


class ProjectIsolationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        app = FastAPI()
        app.include_router(auth_router.router)
        app.include_router(agents_router.router)
        app.include_router(projects_router.router)
        app.include_router(plans_router.router)
        app.include_router(tasks_router.router)
        app.include_router(polling_router.router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[database.get_db] = override_get_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            alice = User(username="alice", password_hash=hash_password("Alice123"))
            bob = User(username="bob", password_hash=hash_password("Bob12345"))
            db.add_all([alice, bob])
            db.flush()
            alice_agent = Agent(
                name="alice-agent",
                slug="alice-agent",
                agent_type="claude",
                co_located=True,
                created_by=alice.id,
            )
            bob_agent = Agent(
                name="bob-agent",
                slug="bob-agent",
                agent_type="codex",
                co_located=False,
                created_by=bob.id,
            )
            db.add_all([alice_agent, bob_agent])
            db.flush()
            alice_agent.short_term_reset_at = datetime.utcnow() + timedelta(hours=1)
            alice_agent.short_term_reset_interval_hours = 12
            alice_agent.long_term_reset_at = datetime.utcnow() + timedelta(days=1)
            alice_agent.long_term_reset_interval_days = 30
            bob_agent.short_term_reset_at = datetime.utcnow() + timedelta(hours=1)
            bob_agent.short_term_reset_interval_hours = 12
            bob_agent.long_term_reset_at = datetime.utcnow() + timedelta(days=1)
            bob_agent.long_term_reset_interval_days = 30
            db.add_all([
                Project(
                    name="alice-project",
                    git_repo_url="https://github.com/keting/half",
                    created_by=alice.id,
                    agent_ids_json=f"[{alice_agent.id}]",
                ),
                Project(
                    name="bob-project",
                    git_repo_url="https://github.com/keting/half",
                    created_by=bob.id,
                    agent_ids_json=f"[{bob_agent.id}]",
                ),
            ])
            db.add(GlobalSetting(key="task_timeout_minutes", value="37"))
            db.flush()
            bob_project = db.query(Project).filter(Project.name == "bob-project").first()
            bob_plan = ProjectPlan(
                project_id=bob_project.id,
                plan_type="candidate",
                plan_json='{"tasks":[]}',
                status="completed",
                source_path="outputs/plan.json",
                selected_agent_ids_json="[]",
                selected_agent_models_json="{}",
            )
            db.add(bob_plan)
            db.flush()
            db.add(Task(
                project_id=bob_project.id,
                plan_id=bob_plan.id,
                task_code="T1",
                task_name="bob task",
                status="pending",
                depends_on_json="[]",
            ))
            alice_project = db.query(Project).filter(Project.name == "alice-project").first()
            alice_plan = ProjectPlan(
                project_id=alice_project.id,
                plan_type="candidate",
                plan_json=json.dumps({
                    "tasks": [
                        {
                            "task_code": "A1",
                            "task_name": "alice finalize task",
                            "assignee": bob_agent.slug,
                            "expected_output": "outputs/alice/result.json",
                        }
                    ]
                }),
                status="completed",
                source_path="outputs/alice-plan.json",
                selected_agent_ids_json="[]",
                selected_agent_models_json="{}",
            )
            db.add(alice_plan)
            db.commit()

    def _login_headers(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_project_list_is_scoped_to_current_user(self):
        response = self.client.get("/api/projects", headers=self._login_headers("alice", "Alice123"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "alice-project")
        self.assertEqual(payload[0]["agent_ids"], [1])
        self.assertEqual(payload[0]["agent_assignments"], [{"id": 1, "co_located": False}])

    def test_create_project_accepts_agent_assignments(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "assigned-project",
                "goal": "x",
                "git_repo_url": "https://github.com/keting/half",
                "agent_assignments": [{"id": 1, "co_located": True}],
            },
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["agent_ids"], [1])
        self.assertEqual(payload["agent_assignments"], [{"id": 1, "co_located": True}])

    def test_create_and_update_project_planning_mode(self):
        headers = self._login_headers("alice", "Alice123")
        response = self.client.post(
            "/api/projects",
            json={
                "name": "mode-project",
                "goal": "x",
                "git_repo_url": "https://github.com/keting/half",
                "agent_ids": [1],
                "planning_mode": "quality",
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 201)
        project_id = response.json()["id"]
        self.assertEqual(response.json()["planning_mode"], "quality")

        response = self.client.put(
            f"/api/projects/{project_id}",
            json={"planning_mode": "speed"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["planning_mode"], "speed")

    def test_create_project_rejects_invalid_planning_mode(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "invalid-mode-project",
                "goal": "x",
                "git_repo_url": "https://github.com/keting/half",
                "agent_ids": [1],
                "planning_mode": "unknown",
            },
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 400)

    def test_create_project_agent_ids_use_agent_default_co_located(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "default-project",
                "goal": "x",
                "git_repo_url": "https://github.com/keting/half",
                "agent_ids": [1],
            },
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["agent_assignments"], [{"id": 1, "co_located": True}])

    def test_update_project_agent_assignment_overrides_default(self):
        response = self.client.put(
            "/api/projects/1",
            json={"agent_assignments": [{"id": 1, "co_located": False}]},
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_assignments"], [{"id": 1, "co_located": False}])

        with self.SessionLocal() as db:
            agent = db.query(Agent).filter(Agent.id == 1).one()
            agent.co_located = True
            db.commit()

        response = self.client.get("/api/projects/1", headers=self._login_headers("alice", "Alice123"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_assignments"], [{"id": 1, "co_located": False}])

    def test_project_detail_of_other_user_is_hidden(self):
        response = self.client.get("/api/projects/2", headers=self._login_headers("alice", "Alice123"))
        self.assertEqual(response.status_code, 404)

    def test_project_timeout_null_update_snapshots_global_default(self):
        response = self.client.put(
            "/api/projects/1",
            json={"task_timeout_minutes": None},
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["task_timeout_minutes"], 37)

        with self.SessionLocal() as db:
            project = db.query(Project).filter(Project.id == 1).one()
            self.assertEqual(project.task_timeout_minutes, 37)

    def test_agent_list_is_scoped_to_current_user(self):
        response = self.client.get("/api/agents", headers=self._login_headers("alice", "Alice123"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "alice-agent")

    def test_agent_detail_of_other_user_is_hidden_for_update(self):
        response = self.client.put(
            "/api/agents/2",
            json={"name": "renamed"},
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 404)

    def test_agent_delete_of_other_user_is_hidden(self):
        response = self.client.delete(
            "/api/agents/2",
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 404)

    def test_agent_status_patch_of_other_user_is_hidden(self):
        response = self.client.patch(
            "/api/agents/2/status",
            json={"availability_status": "available"},
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 404)

    def test_agent_short_reset_of_other_user_is_hidden(self):
        response = self.client.post(
            "/api/agents/2/short-term-reset/reset",
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 404)

    def test_agent_long_reset_of_other_user_is_hidden(self):
        response = self.client.post(
            "/api/agents/2/long-term-reset/reset",
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 404)

    def test_agent_reorder_rejects_other_users_agent(self):
        response = self.client.put(
            "/api/agents/reorder",
            json={"agent_ids": [1, 2]},
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 400)

    def test_create_project_rejects_other_users_agent(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "bad-project",
                "goal": "x",
                "git_repo_url": "https://github.com/keting/half",
                "agent_ids": [2],
            },
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 400)

    def test_update_project_rejects_other_users_agent(self):
        response = self.client.put(
            "/api/projects/1",
            json={"agent_ids": [2]},
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 400)

    def test_plan_generate_prompt_rejects_other_users_agent(self):
        response = self.client.post(
            "/api/projects/1/plans/generate-prompt",
            json={"selected_agent_ids": [2], "include_usage": False, "selected_agent_models": {}},
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 400)

    def test_finalize_does_not_resolve_other_users_agent_by_slug(self):
        headers = self._login_headers("alice", "Alice123")
        response = self.client.post(
            "/api/projects/1/plans/finalize",
            json={"plan_id": 2},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        with self.SessionLocal() as db:
            task = db.query(Task).filter(Task.project_id == 1, Task.task_code == "A1").one()
            self.assertIsNone(task.assignee_agent_id)

    def test_delete_agent_ignores_other_users_dirty_task_reference(self):
        with self.SessionLocal() as db:
            bob_task = db.query(Task).filter(Task.project_id == 2, Task.task_code == "T1").one()
            bob_task.assignee_agent_id = 1
            alice_project = db.query(Project).filter(Project.id == 1).one()
            alice_project.agent_ids_json = "[]"
            db.commit()

        response = self.client.delete(
            "/api/agents/1",
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_agent_is_blocked_by_own_task_reference(self):
        with self.SessionLocal() as db:
            bob_task = db.query(Task).filter(Task.project_id == 2, Task.task_code == "T1").one()
            bob_task.assignee_agent_id = 1
            alice_project = db.query(Project).filter(Project.id == 1).one()
            alice_project.agent_ids_json = "[]"
            alice_plan = db.query(ProjectPlan).filter(ProjectPlan.project_id == 1).first()
            db.add(Task(
                project_id=1,
                plan_id=alice_plan.id,
                task_code="A2",
                task_name="alice owned task",
                status="pending",
                assignee_agent_id=1,
                depends_on_json="[]",
            ))
            db.commit()

        response = self.client.delete(
            "/api/agents/1",
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_agent_is_blocked_by_project_assignment_object(self):
        with self.SessionLocal() as db:
            alice_project = db.query(Project).filter(Project.id == 1).one()
            alice_project.agent_ids_json = json.dumps([{"id": 1, "co_located": True}])
            db.commit()

        response = self.client.delete(
            "/api/agents/1",
            headers=self._login_headers("alice", "Alice123"),
        )
        self.assertEqual(response.status_code, 400)

    def test_project_task_endpoint_of_other_user_is_hidden(self):
        response = self.client.get("/api/projects/2/tasks", headers=self._login_headers("alice", "Alice123"))
        self.assertEqual(response.status_code, 404)

    def test_task_detail_of_other_user_is_hidden(self):
        response = self.client.get("/api/tasks/1", headers=self._login_headers("alice", "Alice123"))
        self.assertEqual(response.status_code, 404)

    def test_project_plans_endpoint_of_other_user_is_hidden(self):
        response = self.client.get("/api/projects/2/plans", headers=self._login_headers("alice", "Alice123"))
        self.assertEqual(response.status_code, 404)

    def test_project_polling_endpoint_of_other_user_is_hidden(self):
        response = self.client.get("/api/projects/2/polling-config", headers=self._login_headers("alice", "Alice123"))
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
