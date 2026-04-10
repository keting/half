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
import routers.projects as projects_router
import routers.agents as agents_router
from auth import create_token, hash_password
from config import settings
from models import AgentTypeConfig, Base, GlobalSetting, User
from routers import agent_settings as agent_settings_router
from routers import auth as auth_router
from routers import settings as settings_router
from routers import users as users_router


class AdminUserManagementTests(unittest.TestCase):
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
            user = User(username="alice", password_hash=hash_password("Alice123"), role="user", status="active")
            frozen = User(username="frozen", password_hash=hash_password("Frozen123"), role="user", status="frozen")
            db.add_all([admin, user, frozen])
            db.flush()
            db.add(AgentTypeConfig(name="codex"))
            db.add(GlobalSetting(key="polling_interval_min", value="15"))
            db.add(GlobalSetting(key="polling_interval_max", value="30"))
            db.add(GlobalSetting(key="polling_start_delay_minutes", value="0"))
            db.add(GlobalSetting(key="polling_start_delay_seconds", value="0"))
            db.commit()

        self.original_allow_register = settings.ALLOW_REGISTER
        settings.ALLOW_REGISTER = True

    def tearDown(self):
        settings.ALLOW_REGISTER = self.original_allow_register

    def _login_headers(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_auth_me_includes_role_and_status(self):
        response = self.client.get("/api/auth/me", headers=self._login_headers("admin", "Admin123"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["role"], "admin")
        self.assertEqual(payload["status"], "active")

    def test_register_defaults_to_active_user_role(self):
        response = self.client.post("/api/auth/register", json={"username": "newbie", "password": "Newbie123"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["role"], "user")
        self.assertEqual(payload["status"], "active")

    def test_frozen_user_cannot_login(self):
        response = self.client.post("/api/auth/login", json={"username": "frozen", "password": "Frozen123"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "账号已被冻结，请联系管理员")

    def test_frozen_user_existing_token_is_rejected(self):
        token = create_token(user_id=3, username="frozen", role="user")
        response = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "账号已被冻结，请联系管理员")

    def test_non_admin_cannot_access_admin_routes(self):
        headers = self._login_headers("alice", "Alice123")
        user_list = self.client.get("/api/admin/users", headers=headers)
        agent_types = self.client.get("/api/agent-settings/types", headers=headers)
        update_settings = self.client.put("/api/settings/polling", json={"polling_interval_min": 20}, headers=headers)

        self.assertEqual(user_list.status_code, 403)
        self.assertEqual(agent_types.status_code, 403)
        self.assertEqual(update_settings.status_code, 403)

    def test_regular_user_can_read_agent_catalog_and_polling_defaults(self):
        headers = self._login_headers("alice", "Alice123")
        agent_catalog = self.client.get("/api/agents/config/types", headers=headers)
        polling_defaults = self.client.get("/api/settings/polling", headers=headers)

        self.assertEqual(agent_catalog.status_code, 200)
        self.assertEqual(len(agent_catalog.json()), 1)
        self.assertEqual(polling_defaults.status_code, 200)

    def test_login_records_forwarded_client_ip(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "Alice123"},
            headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        with self.SessionLocal() as db:
            user = db.query(User).filter(User.username == "alice").one()
            self.assertEqual(user.last_login_ip, "203.0.113.7")
            self.assertIsNotNone(user.last_login_at)

    def test_admin_can_list_users_and_change_user_state(self):
        headers = self._login_headers("admin", "Admin123")

        list_response = self.client.get("/api/admin/users", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual({user["username"] for user in list_response.json()}, {"admin", "alice", "frozen"})

        promote = self.client.put("/api/admin/users/2/role", json={"role": "admin"}, headers=headers)
        self.assertEqual(promote.status_code, 200)
        self.assertEqual(promote.json()["role"], "admin")

        freeze = self.client.put("/api/admin/users/2/status", json={"status": "frozen"}, headers=headers)
        self.assertEqual(freeze.status_code, 200)
        self.assertEqual(freeze.json()["status"], "frozen")

        unfreeze = self.client.put("/api/admin/users/2/status", json={"status": "active"}, headers=headers)
        self.assertEqual(unfreeze.status_code, 200)
        self.assertEqual(unfreeze.json()["status"], "active")

    def test_frozen_user_is_blocked_from_business_endpoints(self):
        alice_headers = self._login_headers("alice", "Alice123")
        headers = self._login_headers("admin", "Admin123")
        freeze = self.client.put("/api/admin/users/2/status", json={"status": "frozen"}, headers=headers)
        self.assertEqual(freeze.status_code, 200)

        projects = self.client.get("/api/projects", headers=alice_headers)
        agents = self.client.get("/api/agents", headers=alice_headers)
        self.assertEqual(projects.status_code, 403)
        self.assertEqual(agents.status_code, 403)

    def test_admin_cannot_change_own_role_or_freeze_self(self):
        headers = self._login_headers("admin", "Admin123")

        role_response = self.client.put("/api/admin/users/1/role", json={"role": "user"}, headers=headers)
        status_response = self.client.put("/api/admin/users/1/status", json={"status": "frozen"}, headers=headers)

        self.assertEqual(role_response.status_code, 400)
        self.assertEqual(status_response.status_code, 400)

    def test_cannot_remove_last_active_admin(self):
        headers = self._login_headers("admin", "Admin123")

        demote = self.client.put("/api/admin/users/1/role", json={"role": "user"}, headers=headers)
        freeze = self.client.put("/api/admin/users/1/status", json={"status": "frozen"}, headers=headers)

        self.assertEqual(demote.status_code, 400)
        self.assertEqual(freeze.status_code, 400)

    def test_multi_admin_can_demote_other_admin_but_not_last_one(self):
        headers = self._login_headers("admin", "Admin123")
        promote = self.client.put("/api/admin/users/2/role", json={"role": "admin"}, headers=headers)
        self.assertEqual(promote.status_code, 200)

        demote_other = self.client.put("/api/admin/users/2/role", json={"role": "user"}, headers=headers)
        self.assertEqual(demote_other.status_code, 200)
        self.assertEqual(demote_other.json()["role"], "user")

        demote_self = self.client.put("/api/admin/users/1/role", json={"role": "user"}, headers=headers)
        self.assertEqual(demote_self.status_code, 400)


if __name__ == "__main__":
    unittest.main()
