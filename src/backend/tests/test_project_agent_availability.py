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
from models import Agent, Base, Project, User
from routers import auth as auth_router
from routers import projects as projects_router
from services.agents import derive_agent_status


class ProjectAgentAvailabilityTests(unittest.TestCase):
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
        app.include_router(projects_router.router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[database.get_db] = override_get_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            owner = User(username="owner", password_hash=hash_password("Owner123"))
            db.add(owner)
            db.flush()

            self.available_agent_id = self._add_agent(
                db,
                owner.id,
                "available-agent",
                subscription_expires_at=datetime.utcnow() + timedelta(days=30),
            )
            self.kept_unavailable_agent_id = self._add_agent(
                db,
                owner.id,
                "kept-unavailable-agent",
                subscription_expires_at=datetime.utcnow() - timedelta(days=1),
            )
            self.new_unavailable_agent_id = self._add_agent(
                db,
                owner.id,
                "new-unavailable-agent",
                subscription_expires_at=datetime.utcnow() - timedelta(hours=2),
            )
            self.short_reset_agent_id = self._add_agent(
                db,
                owner.id,
                "short-reset-agent",
                availability_status="short_reset_pending",
                short_term_reset_at=datetime.utcnow() + timedelta(hours=3),
                subscription_expires_at=datetime.utcnow() + timedelta(days=10),
            )

            project = Project(
                name="existing-project",
                goal="demo",
                git_repo_url="https://github.com/keting/half",
                created_by=owner.id,
                agent_ids_json=json.dumps([{"id": self.kept_unavailable_agent_id, "co_located": False}]),
            )
            db.add(project)
            db.commit()
            self.project_id = project.id

    def _add_agent(
        self,
        db,
        owner_id: int,
        slug: str,
        *,
        availability_status: str = "available",
        subscription_expires_at: datetime | None = None,
        short_term_reset_at: datetime | None = None,
    ) -> int:
        agent = Agent(
            name=slug,
            slug=slug,
            agent_type="claude",
            created_by=owner_id,
            availability_status=availability_status,
            subscription_expires_at=subscription_expires_at,
            short_term_reset_at=short_term_reset_at,
        )
        db.add(agent)
        db.flush()
        return agent.id

    def _headers(self) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "Owner123"},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_create_project_rejects_unavailable_agent(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "bad-project",
                "goal": "x",
                "git_repo_url": "https://github.com/keting/half",
                "agent_ids": [self.new_unavailable_agent_id],
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["message"], "Some selected agents are unavailable")
        self.assertEqual(response.json()["detail"]["unavailable_agent_ids"], [self.new_unavailable_agent_id])

    def test_create_project_rejects_invalid_repo_url(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "bad-repo-project",
                "goal": "x",
                "git_repo_url": "https://www.baidu.com/",
                "agent_ids": [self.available_agent_id],
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Git 仓库地址必须", response.json()["detail"])

    def test_create_project_rejects_missing_repo_url(self):
        response = self.client.post(
            "/api/projects",
            json={"name": "missing-repo-url-project", "goal": "x", "agent_ids": [self.available_agent_id]},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Git 仓库地址不能为空。")

    def test_create_project_rejects_empty_repo_url(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "empty-repo-url-project",
                "goal": "x",
                "git_repo_url": "   ",
                "agent_ids": [self.available_agent_id],
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Git 仓库地址不能为空。")

    def test_create_project_accepts_gitlab_repo_url(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "gitlab-project",
                "goal": "x",
                "git_repo_url": "https://gitlab.com/group/repo.git",
                "agent_ids": [self.available_agent_id],
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["git_repo_url"], "https://gitlab.com/group/repo.git")

    def test_create_project_accepts_valid_but_unverified_repo_url(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "missing-repo-project",
                "goal": "x",
                "git_repo_url": "https://github.com/beautyarbutin/1",
                "agent_ids": [self.available_agent_id],
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["git_repo_url"], "https://github.com/beautyarbutin/1")

    def test_create_project_allows_short_reset_pending_agent(self):
        response = self.client.post(
            "/api/projects",
            json={
                "name": "pending-project",
                "goal": "x",
                "git_repo_url": "https://github.com/keting/half",
                "agent_ids": [self.short_reset_agent_id],
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["agent_ids"], [self.short_reset_agent_id])

    def test_update_project_allows_keeping_existing_unavailable_agent(self):
        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"agent_ids": [self.kept_unavailable_agent_id]},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_ids"], [self.kept_unavailable_agent_id])

    def test_update_project_rejects_new_unavailable_agent(self):
        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"agent_ids": [self.kept_unavailable_agent_id, self.new_unavailable_agent_id]},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["message"], "Some selected agents are unavailable")
        self.assertEqual(response.json()["detail"]["unavailable_agent_ids"], [self.new_unavailable_agent_id])

    def test_update_project_rejects_invalid_repo_url(self):
        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"git_repo_url": "https://www.baidu.com/"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Git 仓库地址必须", response.json()["detail"])

    def test_update_project_rejects_clearing_repo_url(self):
        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"git_repo_url": "https://github.com/keting/half"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["git_repo_url"], "https://github.com/keting/half")

        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"git_repo_url": None},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Git 仓库地址不能为空。")

        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"git_repo_url": ""},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Git 仓库地址不能为空。")

        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"git_repo_url": "   "},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Git 仓库地址不能为空。")

    def test_update_project_rejects_legacy_empty_repo_url_final_state(self):
        with self.SessionLocal() as db:
            project = db.query(Project).filter(Project.id == self.project_id).one()
            project.git_repo_url = None
            db.commit()

        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"name": "renamed-project"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Git 仓库地址不能为空。")

        response = self.client.put(
            f"/api/projects/{self.project_id}",
            json={"git_repo_url": "https://github.com/keting/half"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["git_repo_url"], "https://github.com/keting/half")

    def test_derive_agent_status_treats_expiry_equal_now_as_unavailable(self):
        boundary = datetime(2026, 4, 20, 12, 0, 0)
        agent = Agent(
            name="boundary-agent",
            slug="boundary-agent",
            agent_type="claude",
            availability_status="available",
            subscription_expires_at=boundary,
        )

        self.assertEqual(derive_agent_status(agent, now=boundary), "unavailable")


if __name__ == "__main__":
    unittest.main()
