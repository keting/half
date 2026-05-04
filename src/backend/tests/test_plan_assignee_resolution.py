import json
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models import Agent, Base, Project, User
from routers.plans import _resolve_assignee_agent_id


class PlanAssigneeResolutionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.owner = User(id=1, username="owner", password_hash="x", role="user", status="active")
        self.admin = User(id=2, username="admin", password_hash="x", role="admin", status="active")
        self.db.add_all([self.owner, self.admin])
        self.db.add_all([
            Agent(id=1, slug="codex-plus", name="Codex Plus", agent_type="chatgpt-plus", created_by=1),
            Agent(id=2, slug="claude-max", name="Claude Max", agent_type="claude-max", created_by=1),
            Agent(id=3, slug="public-active", name="Shared Agent", agent_type="shared-type", created_by=2),
            Agent(
                id=4,
                slug="public-inactive",
                name="Legacy Public",
                agent_type="legacy-type",
                created_by=2,
                is_active=False,
            ),
            Agent(id=5, slug="private-shared", name="Shared Agent", agent_type="shared-type", created_by=1),
        ])
        self.project = Project(id=10, name="demo", created_by=1, agent_ids_json=json.dumps([1, 2]))
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_resolves_assignee_by_slug(self):
        self.assertEqual(_resolve_assignee_agent_id(self.db, "codex-plus", self.project, self.owner), 1)

    def test_resolves_assignee_by_display_name(self):
        self.assertEqual(_resolve_assignee_agent_id(self.db, "Claude Max", self.project, self.owner), 2)

    def test_resolves_assignee_by_agent_type(self):
        self.assertEqual(_resolve_assignee_agent_id(self.db, "chatgpt-plus", self.project, self.owner), 1)

    def test_returns_none_when_unmatched(self):
        self.assertIsNone(_resolve_assignee_agent_id(self.db, "unknown-agent", self.project, self.owner))

    def test_resolves_project_bound_public_agent(self):
        self.project.agent_ids_json = json.dumps([3])
        self.db.commit()

        self.assertEqual(_resolve_assignee_agent_id(self.db, "public-active", self.project, self.owner), 3)

    def test_resolves_inactive_public_agent_kept_on_project(self):
        self.project.agent_ids_json = json.dumps([4])
        self.db.commit()

        self.assertEqual(_resolve_assignee_agent_id(self.db, "legacy-type", self.project, self.owner), 4)

    def test_prefers_private_agent_over_public_agent_with_same_name(self):
        self.project.agent_ids_json = "[]"
        self.db.commit()

        self.assertEqual(_resolve_assignee_agent_id(self.db, "Shared Agent", self.project, self.owner), 5)


if __name__ == "__main__":
    unittest.main()
