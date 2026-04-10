import json
import sys
import unittest
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
from auth import create_token, hash_password
from models import Agent, AgentTypeConfig, AuditLog, Base, GlobalSetting, Project, User
from routers import agent_settings as agent_settings_router
from routers import agents as agents_router
from routers import auth as auth_router
from routers import projects as projects_router
from routers import settings as settings_router
from routers import users as users_router


class RQ04101Tests(unittest.TestCase):
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
        app.include_router(agent_settings_router.router)
        app.include_router(settings_router.router)
        app.include_router(users_router.router)
        app.include_router(users_router.audit_router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[database.get_db] = override_get_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            admin = User(username="admin", password_hash=hash_password("Admin123"), role="admin", status="active")
            alice = User(username="alice", password_hash=hash_password("Alice123"), role="user", status="active")
            bob = User(username="bob", password_hash=hash_password("Bob123"), role="user", status="active")
            frozen = User(username="frozen", password_hash=hash_password("Frozen123"), role="user", status="frozen")
            db.add_all([admin, alice, bob, frozen])
            db.flush()
            db.add(AgentTypeConfig(name="codex"))
            db.add(GlobalSetting(key="polling_interval_min", value="15"))
            db.add(GlobalSetting(key="polling_interval_max", value="30"))
            db.add(GlobalSetting(key="polling_start_delay_minutes", value="0"))
            db.add(GlobalSetting(key="polling_start_delay_seconds", value="0"))
            db.commit()

    def _login_headers(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_change_password_success_and_new_password_can_login(self):
        headers = self._login_headers("alice", "Alice123")

        response = self.client.put(
            "/api/auth/password",
            json={"current_password": "Alice123", "new_password": "NewAlice456"},
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], "密码修改成功")

        old_login = self.client.post("/api/auth/login", json={"username": "alice", "password": "Alice123"})
        new_login = self.client.post("/api/auth/login", json={"username": "alice", "password": "NewAlice456"})
        self.assertEqual(old_login.status_code, 401)
        self.assertEqual(new_login.status_code, 200)

    def test_change_password_rejects_wrong_current_password(self):
        headers = self._login_headers("alice", "Alice123")
        response = self.client.put(
            "/api/auth/password",
            json={"current_password": "Wrong123", "new_password": "NewAlice456"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "当前密码错误")

    def test_change_password_rejects_weak_new_password(self):
        headers = self._login_headers("alice", "Alice123")
        response = self.client.put(
            "/api/auth/password",
            json={"current_password": "Alice123", "new_password": "alllowercase"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_change_password_rejects_same_password(self):
        headers = self._login_headers("alice", "Alice123")
        response = self.client.put(
            "/api/auth/password",
            json={"current_password": "Alice123", "new_password": "Alice123"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_frozen_user_cannot_change_password(self):
        admin_headers = self._login_headers("admin", "Admin123")
        freeze = self.client.put("/api/admin/users/4/status", json={"status": "frozen"}, headers=admin_headers)
        self.assertEqual(freeze.status_code, 200)

        frozen_token = create_token(user_id=4, username="frozen", role="user")
        response = self.client.put(
            "/api/auth/password",
            json={"current_password": "Frozen123", "new_password": "Frozen456A"},
            headers={"Authorization": f"Bearer {frozen_token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_agent_created_by_is_not_null(self):
        headers = self._login_headers("alice", "Alice123")
        response = self.client.post(
            "/api/agents",
            json={"name": "Alice Agent", "agent_type": "codex"},
            headers=headers,
        )

        self.assertEqual(response.status_code, 201)
        agent_id = response.json()["id"]

        with self.SessionLocal() as db:
            agent = db.query(Agent).filter(Agent.id == agent_id).one()
            self.assertIsNotNone(agent.created_by)

    def test_project_created_by_is_not_null(self):
        headers = self._login_headers("alice", "Alice123")
        agent_response = self.client.post(
            "/api/agents",
            json={"name": "Project Agent", "agent_type": "codex"},
            headers=headers,
        )
        self.assertEqual(agent_response.status_code, 201)
        agent_id = agent_response.json()["id"]

        response = self.client.post(
            "/api/projects",
            json={"name": "Alpha Project", "goal": "Ship it", "agent_ids": [agent_id]},
            headers=headers,
        )

        self.assertEqual(response.status_code, 201)
        project_id = response.json()["id"]

        with self.SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).one()
            self.assertIsNotNone(project.created_by)

    def test_role_update_writes_audit_log(self):
        headers = self._login_headers("admin", "Admin123")
        response = self.client.put("/api/admin/users/2/role", json={"role": "admin"}, headers=headers)
        self.assertEqual(response.status_code, 200)

        with self.SessionLocal() as db:
            audit = db.query(AuditLog).filter(AuditLog.action == "user.role.update").one()
            self.assertEqual(audit.operator_id, 1)
            detail = json.loads(audit.detail)
            self.assertEqual(detail["old_role"], "user")
            self.assertEqual(detail["new_role"], "admin")

    def test_status_update_writes_audit_log(self):
        headers = self._login_headers("admin", "Admin123")
        response = self.client.put("/api/admin/users/3/status", json={"status": "frozen"}, headers=headers)
        self.assertEqual(response.status_code, 200)

        with self.SessionLocal() as db:
            audit = db.query(AuditLog).filter(AuditLog.action == "user.status.update").one()
            self.assertEqual(audit.operator_id, 1)
            detail = json.loads(audit.detail)
            self.assertEqual(detail["old_status"], "active")
            self.assertEqual(detail["new_status"], "frozen")

    def test_change_password_writes_audit_log_without_password_content(self):
        headers = self._login_headers("alice", "Alice123")
        response = self.client.put(
            "/api/auth/password",
            json={"current_password": "Alice123", "new_password": "NewAlice456"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)

        with self.SessionLocal() as db:
            audit = db.query(AuditLog).filter(AuditLog.action == "user.password.change").one()
            self.assertEqual(audit.operator_id, 2)
            detail = json.loads(audit.detail)
            self.assertEqual(detail, {"user_id": 2})
            self.assertNotIn("password", audit.detail.lower())

    def test_non_admin_cannot_query_audit_logs(self):
        headers = self._login_headers("alice", "Alice123")
        response = self.client.get("/api/admin/audit-logs", headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_change_password_requires_authentication(self):
        response = self.client.put(
            "/api/auth/password",
            json={"current_password": "Alice123", "new_password": "NewAlice456"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Not authenticated")

    def test_admin_can_query_audit_logs(self):
        admin_headers = self._login_headers("admin", "Admin123")
        self.client.put("/api/admin/users/2/role", json={"role": "admin"}, headers=admin_headers)

        response = self.client.get(
            "/api/admin/audit-logs",
            params={"action": "user.role.update", "limit": 10},
            headers=admin_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["action"], "user.role.update")
        self.assertEqual(payload[0]["operator_username"], "admin")


if __name__ == "__main__":
    unittest.main()
