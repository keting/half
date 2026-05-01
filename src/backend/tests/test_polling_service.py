import asyncio
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
from services.polling_service import _task_usage_path, get_effective_task_timeout_minutes, poll_project


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
            task_timeout_minutes=20,
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

    def _seed_running_plan(self, *, dispatched_minutes_ago: int) -> tuple[Project, ProjectPlan]:
        db = self.SessionLocal()
        self.addCleanup(db.close)

        project = Project(
            id=37,
            name="Plan Polling Demo",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir="outputs/proj-37-plan",
            status="planning",
        )
        plan = ProjectPlan(
            id=38,
            project_id=37,
            status="running",
            dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=dispatched_minutes_ago),
        )
        db.add_all([project, plan])
        db.commit()
        db.refresh(project)
        db.refresh(plan)
        return project, plan

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

    def test_poll_project_uses_task_timeout_before_timing_out(self):
        project, task = self._seed_running_task(
            "outputs/proj-7-7b145d/TASK-001/result.json",
            dispatched_minutes_ago=11,
        )
        db = self.SessionLocal()
        stored = db.query(Task).filter(Task.id == task.id).first()
        stored.timeout_minutes = 15
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
        self.assertEqual(refreshed.status, "running")
        self.assertIsNone(refreshed.last_error)

    def test_effective_timeout_falls_back_from_task_to_project_to_global(self):
        db = self.SessionLocal()
        self.addCleanup(db.close)
        project = Project(
            id=27,
            name="Timeout Project",
            task_timeout_minutes=33,
        )
        task = Task(
            id=28,
            project_id=27,
            plan_id=1,
            task_code="TASK-028",
            task_name="Timeout",
            timeout_minutes=None,
        )
        db.add_all([project, task])
        db.commit()

        self.assertEqual(get_effective_task_timeout_minutes(db, project, task), 33)

        task.timeout_minutes = 44
        db.commit()
        self.assertEqual(get_effective_task_timeout_minutes(db, project, task), 44)

        project.task_timeout_minutes = None
        task.timeout_minutes = None
        db.commit()
        self.assertEqual(get_effective_task_timeout_minutes(db, project, task), 10)

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

    def test_poll_project_logs_git_sync_warning_without_recording_error(self):
        project, task = self._seed_running_task(
            "outputs/proj-7-7b145d/TASK-001/result.md",
            dispatched_minutes_ago=1,
        )

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
        error_events = verify_db.query(TaskEvent).filter(
            TaskEvent.task_id == task.id,
            TaskEvent.event_type == "error",
        ).all()
        self.assertEqual(refreshed.status, "running")
        self.assertIsNone(refreshed.last_error)
        self.assertEqual(error_events, [])

    def test_poll_project_git_sync_warning_does_not_block_timeout(self):
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
        error_events = verify_db.query(TaskEvent).filter(
            TaskEvent.task_id == task.id,
            TaskEvent.event_type == "error",
        ).all()
        timeout_events = verify_db.query(TaskEvent).filter(
            TaskEvent.task_id == task.id,
            TaskEvent.event_type == "timeout",
        ).all()
        self.assertEqual(refreshed.status, "needs_attention")
        self.assertIn("Timeout: result not found", refreshed.last_error)
        self.assertNotIn("Git sync warning", refreshed.last_error)
        self.assertEqual(error_events, [])
        self.assertEqual(len(timeout_events), 1)

    def test_poll_project_plan_git_sync_warning_without_recording_error(self):
        project, plan = self._seed_running_plan(dispatched_minutes_ago=1)

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
            "services.polling_service.git_service.read_json",
            return_value=None,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(ProjectPlan).filter(ProjectPlan.id == plan.id).first()
        self.assertEqual(refreshed.status, "running")
        self.assertIsNone(refreshed.last_error)

    def test_poll_project_plan_git_sync_warning_does_not_block_timeout(self):
        project, plan = self._seed_running_plan(dispatched_minutes_ago=31)

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
            "services.polling_service.git_service.read_json",
            return_value=None,
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(ProjectPlan).filter(ProjectPlan.id == plan.id).first()
        self.assertEqual(refreshed.status, "needs_attention")
        self.assertIn("Plan JSON not found", refreshed.last_error)
        self.assertNotIn("Git sync warning", refreshed.last_error)

    def test_poll_project_skips_template_source_path_for_running_plan(self):
        project, plan = self._seed_running_plan(dispatched_minutes_ago=31)
        db = self.SessionLocal()
        stored = db.query(ProjectPlan).filter(ProjectPlan.id == plan.id).first()
        stored.source_path = "template:123"
        db.commit()
        db.close()

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.read_json",
            side_effect=AssertionError("template source paths must not be read from git"),
        ):
            poll_project(self.SessionLocal(), project)

        verify_db = self.SessionLocal()
        self.addCleanup(verify_db.close)
        refreshed = verify_db.query(ProjectPlan).filter(ProjectPlan.id == plan.id).first()
        self.assertEqual(refreshed.status, "running")
        self.assertIsNone(refreshed.last_error)


class PollingLoopExecutorTests(unittest.IsolatedAsyncioTestCase):
    """Regression tests for the fix that prevents event-loop blocking in polling_loop.

    Root cause: poll_project performs blocking git I/O (subprocess.run + time.sleep).
    Calling it directly inside an async function pins the event loop thread for the
    entire duration.  Threads that are running synchronous FastAPI dependencies via
    anyio.to_thread.run_sync need to hand their results back through the event loop;
    while the loop is blocked those threads stay alive.  New requests keep spawning
    more threads until the OS limit is reached and uvicorn raises
        RuntimeError: can't start new thread
    on the next GET /api/projects/<id>/plans dependency call.

    The fix: submit poll_project to a thread-pool executor so the event loop remains
    free to process callbacks while git I/O runs in a worker thread.
    """

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from database import Base

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    async def test_polling_loop_dispatches_poll_project_via_run_in_executor(self):
        """polling_loop must use run_in_executor, not a direct blocking call."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from services.polling_service import poll_project, polling_loop

        project = MagicMock()
        project.id = 42

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [project]

        loop = asyncio.get_running_loop()
        executor_mock = AsyncMock(return_value=None)

        with (
            patch("services.polling_service.SessionLocal", return_value=mock_db),
            patch(
                "services.polling_service._compute_next_poll_time",
                return_value=datetime.now(timezone.utc),
            ),
            patch.object(loop, "run_in_executor", executor_mock),
            # Raise CancelledError at the end of the first tick to exit the loop.
            # CancelledError inherits from BaseException so it is not caught by
            # the inner `except Exception` guard and propagates cleanly.
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            try:
                await polling_loop(30)
            except asyncio.CancelledError:
                pass

        self.assertTrue(
            executor_mock.called,
            "run_in_executor was never invoked; poll_project may be blocking the event loop",
        )
        submitted_fns = [c.args[1] for c in executor_mock.call_args_list]
        self.assertIn(
            poll_project,
            submitted_fns,
            "poll_project was not submitted via run_in_executor; a direct call blocks "
            "the event loop and causes thread exhaustion (RuntimeError: can't start new thread)",
        )

    async def test_polling_loop_remains_responsive_while_poll_project_runs(self):
        """The event loop must be able to schedule coroutines while poll_project runs.

        If poll_project were called directly, the event loop would be frozen for the
        duration of the git I/O and the side-channel coroutine below would never run.
        """
        from unittest.mock import MagicMock, patch
        from services.polling_service import polling_loop

        project = MagicMock()
        project.id = 43

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [project]

        event_loop_ran_concurrently = asyncio.Event()
        main_loop = asyncio.get_running_loop()

        async def side_channel():
            """Scheduled during poll_project; only runs if the event loop is free."""
            event_loop_ran_concurrently.set()

        def fake_poll_project(db, proj):
            # While running in the executor thread, schedule a coroutine on the loop.
            # If the event loop is free (correct behaviour), it will be executed.
            # main_loop is captured from the outer async scope; executor threads have
            # no running event loop themselves, so asyncio.get_running_loop() would fail.
            main_loop.call_soon_threadsafe(
                asyncio.ensure_future, side_channel()
            )

        with (
            patch("services.polling_service.SessionLocal", return_value=mock_db),
            patch(
                "services.polling_service._compute_next_poll_time",
                return_value=datetime.now(timezone.utc),
            ),
            patch("services.polling_service.poll_project", side_effect=fake_poll_project),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            try:
                await polling_loop(30)
            except asyncio.CancelledError:
                pass

        # Allow the scheduled coroutine to complete.
        await asyncio.sleep(0)

        self.assertTrue(
            event_loop_ran_concurrently.is_set(),
            "The event loop did not process callbacks while poll_project was running; "
            "poll_project is likely blocking the event loop thread directly",
        )


if __name__ == "__main__":
    unittest.main()
