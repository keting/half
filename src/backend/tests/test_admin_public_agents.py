import sys
import unittest
import json
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from access import get_mutable_agent, list_visible_agents
from models import Agent, Base, Project, ProjectPlan, User
from routers.agents import (
    AgentUpdate,
    StatusUpdate,
    confirm_long_term,
    confirm_short_term,
    delete_agent,
    reset_long_term,
    reset_short_term,
    update_agent,
    update_agent_status,
)
from routers.projects import ProjectCreate, ProjectUpdate, create_project, update_project
from routers.users import UserRoleUpdateRequest, UserStatusUpdateRequest, update_user_role, update_user_status


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

    def _agent(self, name: str, owner_id: int, *, is_active: bool, slug: str | None = None) -> Agent:
        agent = Agent(
            name=name,
            slug=slug or name.lower().replace(" ", "-"),
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

    def test_visible_public_agent_is_not_mutable_by_non_creator(self):
        with self.assertRaises(HTTPException) as regular_user_error:
            get_mutable_agent(self.db, self.public_active.id, self.alice)

        self.assertEqual(regular_user_error.exception.status_code, 403)
        self.assertEqual(regular_user_error.exception.detail, "公共 Agent 仅创建者可维护")

        with self.assertRaises(HTTPException) as other_admin_error:
            get_mutable_agent(self.db, self.public_active.id, self.admin_b)

        self.assertEqual(other_admin_error.exception.status_code, 403)

    def test_non_creator_cannot_modify_public_agent_actions(self):
        action_calls = [
            lambda: update_agent(self.public_active.id, AgentUpdate(name="renamed"), self.db, self.alice),
            lambda: update_agent_status(
                self.public_active.id,
                StatusUpdate(availability_status="available"),
                self.db,
                self.alice,
            ),
            lambda: reset_short_term(self.public_active.id, self.db, self.alice),
            lambda: confirm_short_term(self.public_active.id, self.db, self.alice),
            lambda: reset_long_term(self.public_active.id, self.db, self.alice),
            lambda: confirm_long_term(self.public_active.id, self.db, self.alice),
            lambda: delete_agent(self.public_active.id, self.db, self.alice),
        ]

        for call in action_calls:
            with self.subTest(call=call):
                with self.assertRaises(HTTPException) as raised:
                    call()
                self.assertEqual(raised.exception.status_code, 403)

    def test_project_lifecycle_respects_inactive_public_agent_history(self):
        created = create_project(
            ProjectCreate(
                name="uses-public",
                goal="x",
                git_repo_url="https://github.com/keting/half",
                agent_ids=[self.public_active.id],
            ),
            db=self.db,
            user=self.alice,
        )
        self.assertEqual(created.agent_ids, [self.public_active.id])

        with self.assertRaises(HTTPException) as create_error:
            create_project(
                ProjectCreate(
                    name="cannot-add-inactive-public",
                    goal="x",
                    git_repo_url="https://github.com/keting/half",
                    agent_ids=[self.public_inactive.id],
                ),
                db=self.db,
                user=self.alice,
            )
        self.assertEqual(create_error.exception.status_code, 400)

        project = Project(
            name="historical-public",
            goal="x",
            git_repo_url="https://github.com/keting/half",
            created_by=self.alice.id,
            agent_ids_json=json.dumps([{"id": self.public_inactive.id, "co_located": False}]),
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)

        kept = update_project(
            project.id,
            ProjectUpdate(agent_ids=[self.public_inactive.id]),
            db=self.db,
            user=self.alice,
        )
        self.assertEqual(kept.agent_ids, [self.public_inactive.id])
        self.assertEqual(kept.inactive_agent_ids, [self.public_inactive.id])

        removed = update_project(
            project.id,
            ProjectUpdate(agent_ids=[self.public_active.id]),
            db=self.db,
            user=self.alice,
        )
        self.assertEqual(removed.agent_ids, [self.public_active.id])

        with self.assertRaises(HTTPException) as readd_error:
            update_project(
                project.id,
                ProjectUpdate(agent_ids=[self.public_active.id, self.public_inactive.id]),
                db=self.db,
                user=self.alice,
            )
        self.assertEqual(readd_error.exception.status_code, 400)

    def test_delete_public_agent_is_blocked_by_cross_user_references(self):
        project = Project(
            name="alice-public-ref",
            goal="x",
            git_repo_url="https://github.com/keting/half",
            created_by=self.alice.id,
            agent_ids_json="[]",
        )
        self.db.add(project)
        self.db.flush()
        plan = ProjectPlan(
            project_id=project.id,
            plan_type="candidate",
            status="completed",
            plan_json=json.dumps({"tasks": []}),
            selected_agent_ids_json=json.dumps([str(self.public_active.id)]),
        )
        self.db.add(plan)
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            delete_agent(self.public_active.id, self.db, self.super_admin)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("公共 Agent 已被引用", raised.exception.detail)
        self.assertIn("请先禁用", raised.exception.detail)

    def test_frozen_admin_public_agents_remain_visible(self):
        response = update_user_status(
            self.admin_b.id,
            UserStatusUpdateRequest(status="frozen"),
            db=self.db,
            admin=self.super_admin,
        )

        self.assertEqual(response.status, "frozen")
        names = {agent.name for agent in list_visible_agents(self.db, self.alice)}
        self.assertIn("Ops Public", names)

    def test_demoting_super_admin_is_rejected_even_by_another_admin(self):
        with self.assertRaises(HTTPException) as raised:
            update_user_role(
                self.super_admin.id,
                UserRoleUpdateRequest(role="user"),
                db=self.db,
                admin=self.admin_b,
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "超级管理员不可降级")

    def test_demoting_admin_reports_agent_name_conflicts(self):
        self._agent("Ops Public", self.super_admin.id, is_active=True, slug="ops-public-super-admin")
        with self.assertRaises(HTTPException) as raised:
            update_user_role(
                self.admin_b.id,
                UserRoleUpdateRequest(role="user"),
                db=self.db,
                admin=self.super_admin,
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["message"], "Agent name conflicts prevent admin downgrade")
        self.assertEqual(raised.exception.detail["conflicts"][0]["name"], "Ops Public")


if __name__ == "__main__":
    unittest.main()
