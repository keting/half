import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth import hash_password
from database import Base
from models import ProcessTemplate, Project, ProjectPlan, Task, User
from routers.tasks import TaskDispatchRequest, dispatch_task
from services.issue_review_loop import (
    FLOW_TYPE,
    TEMPLATE_NAME,
    ensure_issue_review_loop_template,
    get_issue_review_flow_state,
    issue_review_loop_required_inputs,
)


class IssueReviewLoopTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = self.SessionLocal()
        self.user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        self.project = Project(
            id=10,
            name="Loop",
            git_repo_url="git@github.com:example-org/half-collab.git",
            project_repo_url="git@github.com:example-org/app.git",
            collaboration_dir="outputs/proj-10",
            status="executing",
            created_by=self.user.id,
            default_max_review_rounds=3,
        )
        self.plan = ProjectPlan(
            id=20,
            project_id=10,
            plan_type="final",
            status="final",
            is_selected=True,
            plan_json=json.dumps({"flow_type": FLOW_TYPE, "tasks": []}),
        )
        self.tasks = [
            Task(
                id=index,
                project_id=10,
                plan_id=20,
                task_code=f"TASK-00{index}",
                task_name=f"Task {index}",
                status="pending",
                depends_on_json="[]",
            )
            for index in range(1, 6)
        ]
        self.db.add_all([self.user, self.project, self.plan, *self.tasks])
        self.db.commit()
        self.addCleanup(self.db.close)

    def _flow_state(self) -> dict:
        return {
            "schema_version": 1,
            "flow_type": FLOW_TYPE,
            "current_round": 1,
            "round_id": "round-001-abc123",
            "phase": "awaiting_review",
            "work_branch": "issue-123",
            "head_commit": "abc123",
            "max_review_rounds": 3,
            "task_states": {
                "TASK-001": "completed",
                "TASK-002": "waiting_review",
                "TASK-003": "unlocked",
                "TASK-004": "unlocked",
                "TASK-005": "frozen",
            },
        }

    def _review(self, approve_merge: bool) -> dict:
        return {
            "round": 1,
            "round_id": "round-001-abc123",
            "work_branch": "issue-123",
            "head_commit": "abc123",
            "approve_merge": approve_merge,
        }

    def test_builtin_required_inputs_do_not_include_branch_fields(self):
        keys = {item["key"] for item in issue_review_loop_required_inputs()}

        self.assertNotIn("base_branch", keys)
        self.assertNotIn("work_branch_name", keys)
        self.assertNotIn("pr_target_branch", keys)
        self.assertEqual(keys, {"issue_url", "review_prompt", "test_command", "max_review_rounds"})

    def test_ensure_builtin_template_refreshes_existing_branch_inputs(self):
        old_required_inputs = [
            {"key": "issue_url", "label": "Issue URL", "required": True, "sensitive": False},
            {"key": "base_branch", "label": "基准分支", "required": True, "sensitive": False},
            {"key": "work_branch_name", "label": "工作分支名", "required": False, "sensitive": False},
            {"key": "pr_target_branch", "label": "PR 目标分支", "required": False, "sensitive": False},
        ]
        template = ProcessTemplate(
            name=TEMPLATE_NAME,
            description="old",
            prompt_source_text="old",
            agent_count=1,
            agent_slots_json=json.dumps(["agent-1"]),
            agent_roles_description_json="{}",
            required_inputs_json=json.dumps(old_required_inputs, ensure_ascii=False),
            template_json=json.dumps({"tasks": [], "flow_type": FLOW_TYPE}, ensure_ascii=False),
            created_by=self.user.id,
            updated_by=self.user.id,
        )
        self.db.add(template)
        self.db.commit()

        ensure_issue_review_loop_template(self.db, self.user)
        self.db.refresh(template)
        keys = {item["key"] for item in json.loads(template.required_inputs_json)}

        self.assertNotIn("base_branch", keys)
        self.assertNotIn("work_branch_name", keys)
        self.assertNotIn("pr_target_branch", keys)
        self.assertEqual(template.agent_count, 3)
        self.assertEqual(template.updated_by, self.user.id)

    def test_missing_flow_state_only_unlocks_task_001(self):
        with patch("services.issue_review_loop.git_service.read_file", return_value=None):
            state = get_issue_review_flow_state(self.db, self.project)

        self.assertTrue(state["enabled"])
        self.assertFalse(state["exists"])
        self.assertEqual(state["effective_task_states"]["TASK-001"], "unlocked")
        self.assertEqual(state["effective_task_states"]["TASK-002"], "frozen")

    def test_two_valid_reviews_unlock_decision_task(self):
        files = {
            "outputs/proj-10/flow-state.json": json.dumps(self._flow_state()),
            "outputs/proj-10/TASK-003/reviews/round-001/review.json": json.dumps(self._review(False)),
            "outputs/proj-10/TASK-004/reviews/round-001/review.json": json.dumps(self._review(True)),
        }

        with patch("services.issue_review_loop.git_service.read_file", side_effect=lambda _project_id, path, **_kw: files.get(path)):
            state = get_issue_review_flow_state(self.db, self.project)

        self.assertTrue(state["valid"])
        self.assertEqual(state["derived_phase"], "awaiting_decision")
        self.assertEqual(state["effective_task_states"]["TASK-005"], "unlocked")
        self.assertEqual(state["reviews"]["TASK-003"]["approve_merge"], False)
        self.assertEqual(state["reviews"]["TASK-004"]["approve_merge"], True)

    def test_mismatched_review_does_not_unlock_decision_task(self):
        bad_review = self._review(True)
        bad_review["head_commit"] = "old"
        files = {
            "outputs/proj-10/flow-state.json": json.dumps(self._flow_state()),
            "outputs/proj-10/TASK-003/reviews/round-001/review.json": json.dumps(bad_review),
            "outputs/proj-10/TASK-004/reviews/round-001/review.json": json.dumps(self._review(True)),
        }

        with patch("services.issue_review_loop.git_service.read_file", side_effect=lambda _project_id, path, **_kw: files.get(path)):
            state = get_issue_review_flow_state(self.db, self.project)

        self.assertEqual(state["effective_task_states"]["TASK-005"], "frozen")
        self.assertEqual(state["effective_task_states"]["TASK-003"], "needs_attention")
        self.assertIn("head_commit", state["errors"][0])

    def test_dispatch_uses_loop_business_state_instead_of_db_predecessors(self):
        flow = self._flow_state()
        flow["task_states"]["TASK-003"] = "frozen"
        files = {"outputs/proj-10/flow-state.json": json.dumps(flow)}
        task_3 = self.tasks[2]

        with patch("services.issue_review_loop.git_service.read_file", side_effect=lambda _project_id, path, **_kw: files.get(path)):
            with self.assertRaises(Exception) as ctx:
                dispatch_task(task_3.id, TaskDispatchRequest(), self.db, self.user)
        self.assertIn("issue review loop state is: frozen", str(ctx.exception))

        flow["task_states"]["TASK-003"] = "unlocked"
        files["outputs/proj-10/flow-state.json"] = json.dumps(flow)
        with patch("services.issue_review_loop.git_service.read_file", side_effect=lambda _project_id, path, **_kw: files.get(path)):
            updated = dispatch_task(task_3.id, TaskDispatchRequest(), self.db, self.user)

        self.assertEqual(updated.status, "running")


if __name__ == "__main__":
    unittest.main()
