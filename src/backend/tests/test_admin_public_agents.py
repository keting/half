import sys
import unittest
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from access import list_visible_agents
from models import Agent, Base, User
from routers.users import UserRoleUpdateRequest, update_user_role


class AdminPublicAgentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.db = self.SessionLocal()
        self.super_admin = User(username="admin", password_hash="x", role="admin", status="active")
        self.admin_b = User(username="ops", password_hash="x", role="admin", status="active")
        self.alice = User(username="alice", password_hash="x", role="user", status="active")
        self.bob = User(username="bob", password_hash="x", role="user", status="active")
        self.db.add_all([self.super_admin, self.admin_b, self.alice, self.bob])
        self.db.flush()
        self.public_active = self._agent("Public Active", self.super_admin.id, is_active=True)
        self.public_inactive = self._agent("Public Inactive", self.super_admin.id, is_active=False)
        self.other_public = self._agent("Ops Public", self.admin_b.id, is_active=True)
        self.alice_private = self._agent("Alice Private", self.alice.id, is_active=True)
        self.bob_private = self._agent("Bob Private", self.bob.id, is_active=True)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _agent(self, name: str, owner_id: int, *, is_active: bool) -> Agent:
        agent = Agent(
            name=name,
            slug=name.lower().replace(" ", "-"),
            agent_type="codex",
            created_by=owner_id,
            is_active=is_active,
        )
        self.db.add(agent)
        self.db.flush()
        return agent

    def test_regular_user_sees_own_private_and_active_public_only(self):
        names = {agent.name for agent in list_visible_agents(self.db, self.alice)}

        self.assertIn("Alice Private", names)
        self.assertIn("Public Active", names)
        self.assertIn("Ops Public", names)
        self.assertNotIn("Public Inactive", names)
        self.assertNotIn("Bob Private", names)

    def test_admin_sees_admin_public_pool_but_not_user_private_agents(self):
        names = {agent.name for agent in list_visible_agents(self.db, self.admin_b)}

        self.assertIn("Public Active", names)
        self.assertIn("Public Inactive", names)
        self.assertIn("Ops Public", names)
        self.assertNotIn("Alice Private", names)
        self.assertNotIn("Bob Private", names)

    def test_promoting_user_requires_confirmation_when_agents_become_public(self):
        with self.assertRaises(HTTPException) as raised:
            update_user_role(
                self.alice.id,
                UserRoleUpdateRequest(role="admin"),
                db=self.db,
                admin=self.super_admin,
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertTrue(raised.exception.detail["requires_confirmation"])
        self.assertEqual(raised.exception.detail["agents"][0]["name"], "Alice Private")

    def test_demoting_admin_migrates_agents_to_super_admin(self):
        response = update_user_role(
            self.admin_b.id,
            UserRoleUpdateRequest(role="user"),
            db=self.db,
            admin=self.super_admin,
        )

        self.assertEqual(response.role, "user")
        self.db.refresh(self.other_public)
        self.assertEqual(self.other_public.created_by, self.super_admin.id)


if __name__ == "__main__":
    unittest.main()
