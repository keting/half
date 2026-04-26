import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from auth import hash_password
from models import Project, ProjectPlan, Task, TaskEvent, User
from routers.tasks import (
    TaskDispatchRequest,
    _compute_predecessor_status,
    dispatch_task,
    list_project_predecessor_status,
    mark_complete,
    redispatch_task,
)


class TaskPredecessorStatusTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = self.SessionLocal()
        self.user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        self.db.add(self.user)
        self.db.commit()
        self.addCleanup(self.db.close)

    def _seed_task_chain(self, predecessor_status: str, task_status: str = "pending") -> Task:
        project = Project(
            id=1,
            name="Demo",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir="outputs/proj-1",
            status="executing",
            created_by=self.user.id,
        )
        plan = ProjectPlan(id=1, project_id=1, status="final")
        predecessor = Task(
            id=1,
            project_id=1,
            plan_id=1,
            task_code="TASK-001",
            task_name="前序任务",
            status=predecessor_status,
            expected_output_path="outputs/proj-1/TASK-001/result.json",
            completed_at=datetime.now(timezone.utc) if predecessor_status == "completed" else None,
        )
        task = Task(
            id=2,
            project_id=1,
            plan_id=1,
            task_code="TASK-002",
            task_name="后继任务",
            status=task_status,
            depends_on_json='["TASK-001"]',
            expected_output_path="outputs/proj-1/TASK-002/result.json",
        )
        self.db.add_all([project, plan, predecessor, task])
        self.db.commit()
        return task

    def test_predecessor_status_ignores_abandoned_predecessor_output(self):
        task = self._seed_task_chain("abandoned")
        with patch("routers.tasks.git_service.file_exists", return_value=False):
            result = _compute_predecessor_status(self.db, task, refresh=False)
        self.assertTrue(result.ready)
        self.assertEqual(result.missing, [])

    def test_predecessor_status_blocks_on_non_completed_predecessor(self):
        task = self._seed_task_chain("running")
        with patch("routers.tasks.git_service.file_exists") as mock_file_exists:
            result = _compute_predecessor_status(self.db, task, refresh=False)
        mock_file_exists.assert_not_called()
        self.assertFalse(result.ready)
        self.assertEqual([item.task_code for item in result.missing], ["TASK-001"])

    def test_project_predecessor_status_marks_dependency_chain_ready_and_blocked(self):
        project = Project(
            id=10,
            name="Demo chain",
            git_repo_url="https://github.com/example/demo.git",
            collaboration_dir="demo/outputs",
            status="executing",
            created_by=self.user.id,
        )
        plan = ProjectPlan(id=10, project_id=10, status="final")
        tasks = [
            Task(
                id=10,
                project_id=10,
                plan_id=10,
                task_code="T1_DEV",
                task_name="开发",
                status="completed",
                depends_on_json="[]",
                result_file_path="demo/outputs/T1_DEV/result.json",
                completed_at=datetime.now(timezone.utc),
            ),
            Task(
                id=11,
                project_id=10,
                plan_id=10,
                task_code="T2_TEST",
                task_name="测试",
                status="pending",
                depends_on_json='["T1_DEV"]',
                expected_output_path="demo/outputs/T2_TEST/result.json",
            ),
            Task(
                id=12,
                project_id=10,
                plan_id=10,
                task_code="T3_REVIEW",
                task_name="审查",
                status="pending",
                depends_on_json='["T1_DEV"]',
                expected_output_path="demo/outputs/T3_REVIEW/result.json",
            ),
            Task(
                id=13,
                project_id=10,
                plan_id=10,
                task_code="T4_EVAL",
                task_name="评估",
                status="pending",
                depends_on_json='["T2_TEST", "T3_REVIEW"]',
                expected_output_path="demo/outputs/T4_EVAL/result.json",
            ),
            Task(
                id=14,
                project_id=10,
                plan_id=10,
                task_code="T5_SYNC",
                task_name="同步",
                status="pending",
                depends_on_json='["T4_EVAL"]',
                expected_output_path="demo/outputs/T5_SYNC/result.json",
            ),
        ]
        self.db.add(project)
        self.db.add(plan)
        self.db.add_all(tasks)
        self.db.commit()

        with patch("routers.tasks.git_service.file_exists") as mock_file_exists:
            statuses = list_project_predecessor_status(10, db=self.db, user=self.user)

        mock_file_exists.assert_not_called()
        by_task_id = {status.task_id: status for status in statuses}
        self.assertTrue(by_task_id[10].ready)
        self.assertTrue(by_task_id[11].ready)
        self.assertTrue(by_task_id[12].ready)
        self.assertFalse(by_task_id[13].ready)
        self.assertEqual([item.task_code for item in by_task_id[13].missing], ["T2_TEST", "T3_REVIEW"])
        self.assertFalse(by_task_id[14].ready)
        self.assertEqual([item.task_code for item in by_task_id[14].missing], ["T4_EVAL"])

    def test_dispatch_does_not_check_predecessor_files_on_server(self):
        # Server-side dispatch must NOT trigger git fetch/pull and must NOT
        # block on remote file existence: that check is the executing Agent's
        # responsibility on its own machine.
        task = self._seed_task_chain("completed")
        with patch("routers.tasks.git_service.ensure_repo") as mock_ensure, patch(
            "routers.tasks.git_service.file_exists",
            return_value=False,
        ):
            dispatched = dispatch_task(task.id, TaskDispatchRequest(), self.db, self.user)
        self.assertEqual(dispatched.status, "running")
        mock_ensure.assert_not_called()

    def test_redispatch_archives_last_error_into_event_detail(self):
        task = self._seed_task_chain("completed", task_status="needs_attention")
        task.last_error = "boom: timeout"
        self.db.commit()
        with patch("routers.tasks.git_service.ensure_repo"), patch(
            "routers.tasks.git_service.file_exists",
            return_value=True,
        ):
            updated = redispatch_task(task.id, TaskDispatchRequest(), self.db, self.user)
        self.assertEqual(updated.status, "running")
        self.assertIsNone(updated.last_error)
        event = (
            self.db.query(TaskEvent)
            .filter(TaskEvent.task_id == task.id, TaskEvent.event_type == "redispatched")
            .one()
        )
        self.assertIn("boom: timeout", event.detail)

    def test_redispatch_does_not_check_predecessor_files_on_server(self):
        task = self._seed_task_chain("completed", task_status="needs_attention")
        with patch("routers.tasks.git_service.ensure_repo") as mock_ensure, patch(
            "routers.tasks.git_service.file_exists",
            return_value=False,
        ):
            updated = redispatch_task(task.id, TaskDispatchRequest(), self.db, self.user)
        self.assertEqual(updated.status, "running")
        mock_ensure.assert_not_called()

    def test_mark_complete_clears_last_error(self):
        task = self._seed_task_chain("completed", task_status="needs_attention")
        task.last_error = "boom: timeout"
        self.db.commit()

        updated = mark_complete(task.id, self.db, self.user)

        self.assertEqual(updated.status, "completed")
        self.assertIsNone(updated.last_error)


if __name__ == "__main__":
    unittest.main()
