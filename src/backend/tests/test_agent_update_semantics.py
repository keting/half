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
from auth import hash_password
from models import Agent, AgentTypeConfig, Base, User
from routers import agents as agents_router
from routers import auth as auth_router
from services.agent_credentials import decrypt_api_key


class AgentUpdateSemanticsTests(unittest.TestCase):
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

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[database.get_db] = override_get_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            user = User(username="alice", password_hash=hash_password("Alice123"))
            db.add(user)
            db.flush()
            db.add(AgentTypeConfig(name="claude", sdk_type="claude"))
            agent = Agent(
                name="alice-agent",
                slug="alice-agent",
                agent_type="claude",
                model_name="gpt-5.4",
                models_json='[{"model_name":"gpt-5.4","capability":"原始能力"}]',
                capability="原始能力",
                co_located=False,
                created_by=user.id,
            )
            db.add(agent)
            db.commit()

    def _headers(self) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "Alice123"},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_partial_capability_update_preserves_model_fields(self):
        response = self.client.put(
            "/api/agents/1",
            json={"capability": "更新后的能力"},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["capability"], "更新后的能力")
        self.assertEqual(payload["model_name"], "gpt-5.4")
        self.assertEqual(payload["models"][0]["model_name"], "gpt-5.4")

        with self.SessionLocal() as db:
            agent = db.query(Agent).filter(Agent.id == 1).one()
            self.assertEqual(agent.model_name, "gpt-5.4")
            self.assertEqual(agent.capability, "更新后的能力")
            self.assertIn("gpt-5.4", agent.models_json or "")

    def test_partial_co_located_update_preserves_models_and_capability(self):
        response = self.client.put(
            "/api/agents/1",
            json={"co_located": True},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["co_located"], True)
        self.assertEqual(payload["model_name"], "gpt-5.4")
        self.assertEqual(payload["capability"], "原始能力")
        self.assertEqual(payload["models"][0]["capability"], "原始能力")

    def test_models_update_refreshes_model_name_capability_and_models(self):
        response = self.client.put(
            "/api/agents/1",
            json={
                "models": [
                    {"model_name": "claude-4", "capability": "新能力"},
                ]
            },
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["model_name"], "claude-4")
        self.assertEqual(payload["capability"], "新能力")
        self.assertEqual(payload["models"], [{"model_name": "claude-4", "capability": "新能力"}])

        with self.SessionLocal() as db:
            agent = db.query(Agent).filter(Agent.id == 1).one()
            self.assertEqual(agent.model_name, "claude-4")
            self.assertEqual(agent.capability, "新能力")
            self.assertEqual(agent.models_json, '[{"model_name": "claude-4", "capability": "新能力"}]')

    def test_models_update_can_also_update_api_credentials(self):
        response = self.client.put(
            "/api/agents/1",
            json={
                "models": [
                    {"model_name": "claude-4", "capability": "新能力"},
                ],
                "api_base_url": "https://api.example.com/",
                "api_key": "secret-key",
            },
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["model_name"], "claude-4")
        self.assertEqual(payload["api_base_url"], "https://api.example.com")
        self.assertEqual(payload["has_api_key"], True)
        self.assertNotIn("api_key", payload)

        with self.SessionLocal() as db:
            agent = db.query(Agent).filter(Agent.id == 1).one()
            self.assertEqual(agent.api_base_url, "https://api.example.com")
            self.assertEqual(decrypt_api_key(agent.api_key_encrypted), "secret-key")

    def test_partial_model_name_update_preserves_other_fields(self):
        response = self.client.put(
            "/api/agents/1",
            json={"model_name": "gpt-5.5"},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["model_name"], "gpt-5.5")
        self.assertEqual(payload["capability"], "原始能力")
        self.assertEqual(payload["co_located"], False)
        self.assertEqual(payload["models"][0]["model_name"], "gpt-5.4")
        self.assertEqual(payload["models"][0]["capability"], "原始能力")


if __name__ == "__main__":
    unittest.main()
