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
from models import Project, Task, ProjectPlan
from services.polling_service import poll_project


class PollingServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _seed_running_task(self, expected_output_path: str, status: str = "running") -> tuple[Project, Task]:
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
            dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            timeout_minutes=10,
        )
        db.add_all([project, plan, task])
        db.commit()
        db.refresh(project)
        db.refresh(task)
        return project, task

    def test_poll_project_marks_markdown_output_as_completed_when_file_exists(self):
        project, task = self._seed_running_task("outputs/proj-7-7b145d/TASK-001/requirements.md")

        with patch("services.polling_service.git_service.ensure_repo"), patch(
            "services.polling_service.git_service.file_exists",
            side_effect=lambda project_id, relative_path, git_repo_url=None: relative_path == "outputs/proj-7-7b145d/TASK-001/requirements.md",
        ), patch(
            "services.polling_service.git_service.read_json",
            return_value=None,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.result_file_path, "outputs/proj-7-7b145d/TASK-001/requirements.md")
        self.assertIsNotNone(refreshed.completed_at)

    def test_poll_project_still_requires_task_code_for_json_result(self):
        project, task = self._seed_running_task("outputs/proj-7-7b145d/TASK-001/result.json")

        with patch("services.polling_service.git_service.ensure_repo"), patch(
            "services.polling_service.git_service.read_json",
            return_value={"task_code": "TASK-999"},
        ), patch(
            "services.polling_service.git_service.file_exists",
            return_value=True,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(Task).filter(Task.id == task.id).first()
        self.assertEqual(refreshed.status, "running")
        self.assertIsNone(refreshed.result_file_path)


if __name__ == "__main__":
    unittest.main()
