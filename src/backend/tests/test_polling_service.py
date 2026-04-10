import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from models import Project, Task, ProjectPlan, TaskEvent
from services.git_service import RepoSyncStatus
from services.polling_service import _task_usage_path, poll_project


class PollingServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _seed_running_task(
        self,
        expected_output_path: str,
        status: str = "running",
        *,
        dispatched_minutes_ago: int = 11,
    ) -> tuple[Project, Task]:
        db = self.SessionLocal()
        self.addCleanup(db.close)

        project = Project(
            id=7,
            name="Demo",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir="outputs/proj-7-7b145d",
            status="executing",
        )
        plan = ProjectPlan(
            id=8,
            project_id=7,
            status="final",
        )
        task = Task(
            id=1,
            project_id=7,
            plan_id=8,
            task_code="TASK-001",
            task_name="需求梳理与功能清单",
            status=status,
            expected_output_path=expected_output_path,
            dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=dispatched_minutes_ago),
            timeout_minutes=10,
        )
        db.add_all([project, plan, task])
        db.commit()
        db.refresh(project)
        db.refresh(task)
        return project, task

    def test_poll_project_marks_markdown_output_as_completed_when_file_exists(self):
        project, task = self._seed_running_task("outputs/proj-7-7b145d/TASK-001/requirements.md")
        result_path = "outputs/proj-7-7b145d/TASK-001/result.json"

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.file_exists",
            side_effect=lambda project_id, relative_path, git_repo_url=None, prefer_remote=False: relative_path == result_path,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.result_file_path, result_path)
        self.assertIsNotNone(refreshed.completed_at)

    def test_poll_project_times_out_when_fixed_result_json_is_missing(self):
        project, task = self._seed_running_task("outputs/proj-7-7b145d/TASK-001/result.json")

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.file_exists",
            return_value=False,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "needs_attention")
        self.assertIsNone(refreshed.result_file_path)
        self.assertIn("Timeout: result not found", refreshed.last_error)

    def test_poll_project_ignores_invalid_expected_output_path_and_uses_fixed_result_path(self):
        project, task = self._seed_running_task("outputs/proj-7-7b145d/代码变更提交")
        result_path = "outputs/proj-7-7b145d/TASK-001/result.json"

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.file_exists",
            side_effect=lambda project_id, relative_path, git_repo_url=None, prefer_remote=False: relative_path == result_path,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.result_file_path, result_path)
        self.assertIsNone(refreshed.last_error)

    def test_poll_project_uses_fixed_result_json_instead_of_stored_result_file_path(self):
        project, task = self._seed_running_task("outputs/proj-7-7b145d/TASK-001/result")
        db = self.SessionLocal()
        stored = db.query(Task).filter(Task.id == task.id).first()
        stored.result_file_path = "outputs/proj-7-7b145d/TASK-001/result.md"
        db.commit()
        db.close()
        result_path = "outputs/proj-7-7b145d/TASK-001/result.json"

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.file_exists",
            side_effect=lambda project_id, relative_path, git_repo_url=None, prefer_remote=False: relative_path == result_path,
        ) as mock_exists:
            poll_project(self.SessionLocal(), project)

        self.assertTrue(mock_exists.called)
        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.result_file_path, result_path)

    def test_poll_project_needs_attention_task_can_recover_when_result_appears(self):
        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.file_exists",
            return_value=True,
        ):
            project, task = self._seed_running_task(
                "outputs/proj-7-7b145d/TASK-001/result.json",
                status="needs_attention",
            )
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.result_file_path, "outputs/proj-7-7b145d/TASK-001/result.json")
        self.assertIsNone(refreshed.last_error)

    def test_task_usage_path_uses_fixed_task_directory(self):
        project, task = self._seed_running_task(
            "outputs/proj-7-7b145d/TASK-001-artifacts",
            dispatched_minutes_ago=1,
        )

        usage_path = _task_usage_path(project, task)

        self.assertEqual(usage_path, "outputs/proj-7-7b145d/TASK-001/usage.json")

    def test_fixed_paths_work_without_collaboration_dir(self):
        db = self.SessionLocal()
        self.addCleanup(db.close)
        project = Project(
            id=17,
            name="No Collab",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir=None,
            status="executing",
        )
        plan = ProjectPlan(id=18, project_id=17, status="final")
        task = Task(
            id=19,
            project_id=17,
            plan_id=18,
            task_code="TASK-XYZ",
            task_name="No collab task",
            status="running",
            expected_output_path="自然语言描述",
            dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=11),
            timeout_minutes=10,
        )
        db.add_all([project, plan, task])
        db.commit()

        self.assertEqual(_task_usage_path(project, task), "TASK-XYZ/usage.json")

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.file_exists",
            side_effect=lambda project_id, relative_path, git_repo_url=None, prefer_remote=False: relative_path == "TASK-XYZ/result.json",
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.result_file_path, "TASK-XYZ/result.json")

    def test_needs_attention_without_result_does_not_create_repeated_timeout_events(self):
        project, task = self._seed_running_task(
            "outputs/proj-7-7b145d/TASK-001/result.json",
            status="needs_attention",
        )
        db = self.SessionLocal()
        existing = db.query(Task).filter(Task.id == task.id).first()
        existing.last_error = "Timeout: result not found at outputs/proj-7-7b145d/TASK-001/result.json after 10.0 minutes"
        db.add(TaskEvent(
            task_id=task.id,
            event_type="timeout",
            detail="Timeout after 10.0 minutes",
        ))
        db.commit()
        db.close()

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.file_exists",
            return_value=False,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        timeout_events = verify_db.query(TaskEvent).filter(
            TaskEvent.task_id == task.id,
            TaskEvent.event_type == "timeout",
        ).all()
        self.assertEqual(refreshed.status, "needs_attention")
        self.assertEqual(len(timeout_events), 1)
        self.assertEqual(
            refreshed.last_error,
            "Timeout: result not found at outputs/proj-7-7b145d/TASK-001/result.json after 10.0 minutes",
        )

    def test_poll_project_records_git_sync_failure_without_timing_out(self):
        project, task = self._seed_running_task("outputs/proj-7-7b145d/TASK-001/result.json")

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", remote_ready=False, error="git fetch origin failed: network is unreachable"),
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "running")
        self.assertIn("Git sync failed", refreshed.last_error)
        self.assertNotIn("Timeout: result not found", refreshed.last_error)

    def test_poll_project_records_git_sync_warning_and_keeps_running(self):
        project, task = self._seed_running_task("outputs/proj-7-7b145d/TASK-001/result.md")

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(
                repo_dir="/tmp/repo",
                fetched=True,
                pulled=False,
                remote_ready=True,
                warnings=["git pull --ff-only failed: working tree contains unstaged changes"],
            ),
        ), patch(
            "services.polling_service.git_service.file_exists",
            return_value=False,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "running")
        self.assertIn("Git sync warning", refreshed.last_error)
        self.assertNotIn("Timeout: result not found", refreshed.last_error)


if __name__ == "__main__":
    unittest.main()
