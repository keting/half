"""Tests covering the acceptance criteria for the auto-dispatch agents PRD.

AC-1  After plan finalization, auto tasks execute and complete without manual
      intervention; project transitions to completed when all tasks finish.
AC-2  Auto agent with missing/invalid API credentials → task enters
      needs_attention; no API key is exposed in responses or event logs.
AC-3  Mode mismatch between project and agent → backend returns 400.
AC-4  Multiple ready auto tasks are all returned for concurrent dispatch;
      the _running_auto_tasks guard prevents duplicate execution of the same
      task.
AC-5  All existing agents/projects default to manual mode; existing workflows
      are unaffected.
AC-6  API Key never appears in any API response, event log, or task detail.
"""

import asyncio
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
from models import (
    Agent,
    AgentTypeConfig,
    Base,
    GlobalSetting,
    Project,
    ProjectPlan,
    Task,
    TaskEvent,
    User,
)
from routers import agent_settings as agent_settings_router
from routers import auth as auth_router
from routers import projects as projects_router
from services.agent_credentials import encrypt_api_key
from services.auto_dispatch import (
    _complete_project_if_done,
    get_ready_auto_tasks,
    is_auto_agent_type,
    is_auto_task,
    is_task_ready,
    run_auto_task,
)
from services.git_service import RepoSyncStatus
from services.polling_service import TaskResultDetection


# ---------------------------------------------------------------------------
# Helpers shared across multiple test classes
# ---------------------------------------------------------------------------

def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _add_global_settings(db):
    db.add_all([
        GlobalSetting(key="polling_interval_min", value="15"),
        GlobalSetting(key="polling_interval_max", value="30"),
        GlobalSetting(key="polling_start_delay_minutes", value="0"),
        GlobalSetting(key="polling_start_delay_seconds", value="0"),
    ])


# ---------------------------------------------------------------------------
# AC-1 / AC-2 (service layer) — DAG readiness and credential validation
# ---------------------------------------------------------------------------

class TestIsTaskReady(unittest.TestCase):
    """Unit tests for the DAG dependency resolver used by auto-dispatch."""

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        project = Project(
            id=1, name="P",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/1",
            status="executing",
            created_by=1,
        )
        plan = ProjectPlan(id=1, project_id=1, status="final")
        self.db.add_all([user, project, plan])
        self.db.commit()
        self.addCleanup(self.db.close)
        self._next_id = 1

    def _task(self, code: str, status: str, depends_on: list | None = None) -> Task:
        t = Task(
            id=self._next_id,
            project_id=1, plan_id=1,
            task_code=code, task_name=code,
            status=status,
            depends_on_json=json.dumps(depends_on or []),
            expected_output_path=f"o/1/{code}/result.json",
        )
        self._next_id += 1
        self.db.add(t)
        self.db.commit()
        return t

    def test_no_deps_is_always_ready(self):
        t = self._task("T1", "pending")
        self.assertTrue(is_task_ready(self.db, t))

    def test_completed_dep_makes_task_ready(self):
        self._task("T1", "completed")
        t2 = self._task("T2", "pending", depends_on=["T1"])
        self.assertTrue(is_task_ready(self.db, t2))

    def test_abandoned_dep_makes_task_ready(self):
        self._task("T1", "abandoned")
        t2 = self._task("T2", "pending", depends_on=["T1"])
        self.assertTrue(is_task_ready(self.db, t2))

    def test_pending_dep_blocks_task(self):
        self._task("T1", "pending")
        t2 = self._task("T2", "pending", depends_on=["T1"])
        self.assertFalse(is_task_ready(self.db, t2))

    def test_running_dep_blocks_task(self):
        self._task("T1", "running")
        t2 = self._task("T2", "pending", depends_on=["T1"])
        self.assertFalse(is_task_ready(self.db, t2))

    def test_partial_deps_block_task(self):
        """AC-1: all predecessors must finish before downstream is ready."""
        self._task("T1", "completed")
        self._task("T2", "pending")
        t3 = self._task("T3", "pending", depends_on=["T1", "T2"])
        self.assertFalse(is_task_ready(self.db, t3))


# ---------------------------------------------------------------------------

class TestGetReadyAutoTasks(unittest.TestCase):
    """Tests for get_ready_auto_tasks including credential and DAG checks."""

    _VALID_KEY = "super-secret-key-for-testing"

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        project = Project(
            id=1, name="P",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/1",
            status="executing",
            is_auto=True,
            created_by=1,
        )
        plan = ProjectPlan(id=1, project_id=1, status="final")

        # Auto agent type — valid credentials
        self.auto_type = AgentTypeConfig(
            id=1, name="gpt-auto",
            sdk_type="claude",
        )
        # Auto agent type — missing credentials (sdk_type set but no key/url on instance)
        self.no_creds_type = AgentTypeConfig(
            id=2, name="gpt-no-creds",
            sdk_type="claude",
        )
        # Manual agent type (no sdk_type at all)
        self.manual_type = AgentTypeConfig(id=3, name="manual-type")

        self.auto_agent = Agent(
            id=1, name="Auto", slug="auto-1", agent_type="gpt-auto", created_by=1,
            api_base_url="https://api.example.com/v1",
            api_key_encrypted=encrypt_api_key(self._VALID_KEY),
        )
        self.no_creds_agent = Agent(
            id=2, name="NoCreds", slug="nocreds-1", agent_type="gpt-no-creds", created_by=1,
        )
        self.manual_agent = Agent(
            id=3, name="Manual", slug="manual-1", agent_type="manual-type", created_by=1
        )

        self.db.add_all([
            user, project, plan,
            self.auto_type, self.no_creds_type, self.manual_type,
            self.auto_agent, self.no_creds_agent, self.manual_agent,
        ])
        self.db.commit()
        self.addCleanup(self.db.close)
        self._task_seq = 1

    def _task(self, code: str, agent_id: int, depends_on: list | None = None) -> Task:
        t = Task(
            id=self._task_seq,
            project_id=1, plan_id=1,
            task_code=code, task_name=code,
            status="pending",
            assignee_agent_id=agent_id,
            depends_on_json=json.dumps(depends_on or []),
            expected_output_path=f"o/1/{code}/result.json",
        )
        self._task_seq += 1
        self.db.add(t)
        self.db.commit()
        return t

    def test_ready_task_returned_when_credentials_valid(self):
        """AC-1: valid auto task appears in ready list."""
        t = self._task("T1", self.auto_agent.id)
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(t.id, ready)

    def test_missing_credentials_marks_task_needs_attention(self):
        """AC-2: missing credentials → task becomes needs_attention, not returned."""
        t = self._task("T1", self.no_creds_agent.id)
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertNotIn(t.id, ready)
        self.db.refresh(t)
        self.assertEqual(t.status, "needs_attention")
        self.assertIsNotNone(t.last_error)
        self.assertIn("API credentials", t.last_error)

    def test_missing_credentials_records_failed_event(self):
        """AC-2: a task event with type auto_dispatch_failed is created."""
        t = self._task("T1", self.no_creds_agent.id)
        get_ready_auto_tasks(self.db, project_id=1)
        event = (
            self.db.query(TaskEvent)
            .filter(TaskEvent.task_id == t.id)
            .first()
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "auto_dispatch_failed")

    def test_failed_event_detail_does_not_contain_api_key(self):
        """AC-6: error event detail must not leak any stored API key."""
        t = self._task("T1", self.no_creds_agent.id)
        get_ready_auto_tasks(self.db, project_id=1)
        events = self.db.query(TaskEvent).filter(TaskEvent.task_id == t.id).all()
        for event in events:
            self.assertNotIn(self._VALID_KEY, event.detail or "")

    def test_manual_agent_task_not_returned(self):
        """AC-5: tasks assigned to manual agents are ignored by auto-dispatch."""
        self._task("T1", self.manual_agent.id)
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertEqual(ready, [])

    def test_blocked_task_not_returned(self):
        """AC-1: task with unsatisfied dependency is not dispatched."""
        dep = self._task("T1", self.auto_agent.id)          # pending
        t2 = self._task("T2", self.auto_agent.id, depends_on=["T1"])
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(dep.id, ready)          # T1 has no deps, it's ready
        self.assertNotIn(t2.id, ready)        # T2 is blocked

    def test_multiple_independent_ready_tasks_all_returned(self):
        """AC-4: all ready tasks are returned so they can be dispatched in parallel."""
        t1 = self._task("T1", self.auto_agent.id)
        t2 = self._task("T2", self.auto_agent.id)
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(t1.id, ready)
        self.assertIn(t2.id, ready)


# ---------------------------------------------------------------------------
# AC-1, AC-2, AC-4 (service layer) — run_auto_task state transitions
# ---------------------------------------------------------------------------

class TestRunAutoTask(unittest.TestCase):
    """Tests for run_auto_task — state machine and concurrent-dispatch guard."""

    _VALID_KEY = "super-secret-key"

    def setUp(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        with self.SessionLocal() as db:
            user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
            project = Project(
                id=1, name="P",
                git_repo_url="https://github.com/x/y",
                collaboration_dir="o/1",
                status="executing",
                is_auto=True,
                created_by=1,
            )
            plan = ProjectPlan(id=1, project_id=1, status="final")
            auto_type = AgentTypeConfig(
                id=1, name="gpt-auto",
                sdk_type="claude",
            )
            auto_agent = Agent(
                id=1, name="Auto", slug="auto-1", agent_type="gpt-auto", created_by=1,
                api_base_url="https://api.example.com/v1",
                api_key_encrypted=encrypt_api_key(self._VALID_KEY),
            )
            db.add_all([user, project, plan, auto_type, auto_agent])
            db.commit()

        import services.auto_dispatch as _mod
        self._orig_SessionLocal = _mod.SessionLocal
        _mod.SessionLocal = self.SessionLocal
        # Clean the in-progress guard set before each test
        _mod._running_auto_tasks.clear()
        self.addCleanup(setattr, _mod, "SessionLocal", self._orig_SessionLocal)
        self.addCleanup(_mod._running_auto_tasks.clear)
        self._task_seq = 1

    def _add_task(self, code: str, depends_on: list | None = None) -> int:
        with self.SessionLocal() as db:
            t = Task(
                id=self._task_seq,
                project_id=1, plan_id=1,
                task_code=code, task_name=code,
                status="pending",
                assignee_agent_id=1,
                depends_on_json=json.dumps(depends_on or []),
                expected_output_path=f"o/1/{code}/result.json",
            )
            self._task_seq += 1
            db.add(t)
            db.commit()
            return t.id

    def test_successful_run_without_result_json_does_not_complete(self):
        """AC-1 (sentinel): runner returns but no result.json → task must NOT be completed."""
        task_id = self._add_task("T1")
        _ok_sync = RepoSyncStatus(repo_dir="/tmp/r", remote_ready=True)
        _no_result = TaskResultDetection(found=False, path="o/1/T1/result.json")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock), \
             patch("services.auto_dispatch.git_service.ensure_repo_sync", return_value=_ok_sync), \
             patch("services.auto_dispatch.detect_task_result", return_value=_no_result):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            self.assertEqual(task.status, "needs_attention")
            self.assertIsNone(task.completed_at)
            self.assertIn("result.json not found", task.last_error)

    def test_downstream_not_dispatched_when_result_json_missing(self):
        """AC-1 (sentinel): no result.json → downstream task must NOT be dispatched."""
        t1_id = self._add_task("T1")
        t2_id = self._add_task("T2", depends_on=["T1"])
        _ok_sync = RepoSyncStatus(repo_dir="/tmp/r", remote_ready=True)
        _no_result = TaskResultDetection(found=False, path="o/1/T1/result.json")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock), \
             patch("services.auto_dispatch.git_service.ensure_repo_sync", return_value=_ok_sync), \
             patch("services.auto_dispatch.detect_task_result", return_value=_no_result):
            asyncio.run(run_auto_task(t1_id))
        with self.SessionLocal() as db:
            t2 = db.query(Task).filter(Task.id == t2_id).first()
            self.assertEqual(t2.status, "pending", "T2 must remain pending when T1 has no result.json")

    def test_successful_run_with_result_json_marks_task_completed(self):
        """AC-1 (sentinel): runner returns + valid result.json → task completed."""
        task_id = self._add_task("T1")
        _ok_sync = RepoSyncStatus(repo_dir="/tmp/r", remote_ready=True)
        _found = TaskResultDetection(found=True, path="o/1/T1/result.json")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock), \
             patch("services.auto_dispatch.git_service.ensure_repo_sync", return_value=_ok_sync), \
             patch("services.auto_dispatch.detect_task_result", return_value=_found):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            self.assertEqual(task.status, "completed")
            self.assertIsNotNone(task.completed_at)

    def test_downstream_dispatched_when_result_json_present(self):
        """AC-1 (sentinel): valid result.json present → downstream task is dispatched."""
        t1_id = self._add_task("T1")
        t2_id = self._add_task("T2", depends_on=["T1"])
        _ok_sync = RepoSyncStatus(repo_dir="/tmp/r", remote_ready=True)
        call_order: list[int] = []

        async def _mock_runner(task_id: int, project_id: int) -> None:
            call_order.append(task_id)

        def _mock_detect(project, task):
            return TaskResultDetection(found=True, path=f"o/1/{task.task_code}/result.json")

        with patch("services.auto_dispatch.run_task_for_agent", new=AsyncMock(side_effect=_mock_runner)), \
             patch("services.auto_dispatch.git_service.ensure_repo_sync", return_value=_ok_sync), \
             patch("services.auto_dispatch.detect_task_result", side_effect=_mock_detect):
            asyncio.run(run_auto_task(t1_id))

        self.assertIn(t1_id, call_order)
        self.assertIn(t2_id, call_order)
        with self.SessionLocal() as db:
            t1 = db.query(Task).filter(Task.id == t1_id).first()
            self.assertEqual(t1.status, "completed")

    def test_successful_run_records_started_and_completed_events(self):
        """AC-1: both auto_dispatch_started and auto_dispatch_completed events logged."""
        task_id = self._add_task("T1")
        _ok_sync = RepoSyncStatus(repo_dir="/tmp/r", remote_ready=True)
        _found = TaskResultDetection(found=True, path="o/1/T1/result.json")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock), \
             patch("services.auto_dispatch.git_service.ensure_repo_sync", return_value=_ok_sync), \
             patch("services.auto_dispatch.detect_task_result", return_value=_found):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            events = db.query(TaskEvent).filter(TaskEvent.task_id == task_id).all()
            event_types = {e.event_type for e in events}
            self.assertIn("auto_dispatch_started", event_types)
            self.assertIn("auto_dispatch_completed", event_types)

    def test_event_details_do_not_contain_api_key(self):
        """AC-6: task events must never leak the stored API key."""
        task_id = self._add_task("T1")
        _ok_sync = RepoSyncStatus(repo_dir="/tmp/r", remote_ready=True)
        _found = TaskResultDetection(found=True, path="o/1/T1/result.json")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock), \
             patch("services.auto_dispatch.git_service.ensure_repo_sync", return_value=_ok_sync), \
             patch("services.auto_dispatch.detect_task_result", return_value=_found):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            events = db.query(TaskEvent).filter(TaskEvent.task_id == task_id).all()
            for event in events:
                self.assertNotIn(self._VALID_KEY, event.detail or "")

    def test_runner_exception_marks_task_needs_attention(self):
        """AC-2: runner failure → task enters needs_attention with error info."""
        task_id = self._add_task("T1")
        with patch(
            "services.auto_dispatch.run_task_for_agent",
            new_callable=AsyncMock,
            side_effect=RuntimeError("auth failed: 401 Unauthorized"),
        ):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            self.assertEqual(task.status, "needs_attention")
            self.assertIsNotNone(task.last_error)
            self.assertIn("auth failed", task.last_error)

    def test_runner_exception_records_failed_event(self):
        """AC-2: auto_dispatch_failed event recorded on runner error."""
        task_id = self._add_task("T1")
        with patch(
            "services.auto_dispatch.run_task_for_agent",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection timeout"),
        ):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            events = db.query(TaskEvent).filter(TaskEvent.task_id == task_id).all()
            failed = [e for e in events if e.event_type == "auto_dispatch_failed"]
            self.assertGreater(len(failed), 0)

    def test_project_completed_when_all_tasks_finish(self):
        """AC-1: project transitions to completed once all tasks are done."""
        task_id = self._add_task("T1")
        _ok_sync = RepoSyncStatus(repo_dir="/tmp/r", remote_ready=True)
        _found = TaskResultDetection(found=True, path="o/1/T1/result.json")
        with patch("services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock), \
             patch("services.auto_dispatch.git_service.ensure_repo_sync", return_value=_ok_sync), \
             patch("services.auto_dispatch.detect_task_result", return_value=_found):
            asyncio.run(run_auto_task(task_id))
        with self.SessionLocal() as db:
            project = db.query(Project).filter(Project.id == 1).first()
            self.assertEqual(project.status, "completed")

    def test_running_guard_prevents_duplicate_dispatch(self):
        """AC-4: _running_auto_tasks guard skips re-entrant execution of the same task."""
        import services.auto_dispatch as _mod
        task_id = self._add_task("T1")
        _mod._running_auto_tasks.add(task_id)
        with patch(
            "services.auto_dispatch.run_task_for_agent", new_callable=AsyncMock
        ) as mock_runner:
            asyncio.run(run_auto_task(task_id))
            mock_runner.assert_not_called()

    def test_dag_chain_downstream_task_dispatched_after_upstream_completes(self):
        """AC-1: T2 is automatically dispatched once T1 completes."""
        t1_id = self._add_task("T1")
        t2_id = self._add_task("T2", depends_on=["T1"])
        call_order: list[int] = []

        async def _mock_runner(task_id: int, project_id: int) -> None:
            call_order.append(task_id)

        def _mock_detect(project, task):
            return TaskResultDetection(found=True, path=f"o/1/{task.task_code}/result.json")

        _ok_sync = RepoSyncStatus(repo_dir="/tmp/r", remote_ready=True)
        with patch("services.auto_dispatch.run_task_for_agent", new=AsyncMock(side_effect=_mock_runner)), \
             patch("services.auto_dispatch.git_service.ensure_repo_sync", return_value=_ok_sync), \
             patch("services.auto_dispatch.detect_task_result", side_effect=_mock_detect):
            asyncio.run(run_auto_task(t1_id))

        self.assertIn(t1_id, call_order)
        self.assertIn(t2_id, call_order)
        # T1 must have been dispatched before T2
        self.assertLess(call_order.index(t1_id), call_order.index(t2_id))


# ---------------------------------------------------------------------------
# AC-3 — project/agent mode compatibility via HTTP API
# ---------------------------------------------------------------------------

def _build_app(session_factory):
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(projects_router.router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = override_db
    return app


class TestProjectAgentModeCompatibility(unittest.TestCase):
    """AC-3: adding a mismatched-mode agent to a project must return HTTP 400."""

    def setUp(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.client = TestClient(_build_app(self.SessionLocal))

        with self.SessionLocal() as db:
            user = User(
                username="owner",
                password_hash=hash_password("Owner123"),
                role="user",
                status="active",
            )
            db.add(user)
            db.flush()
            self._user_id = user.id

            auto_type = AgentTypeConfig(
                name="gpt-auto",
                sdk_type="claude",
            )
            manual_type = AgentTypeConfig(name="manual-type")
            db.add_all([auto_type, manual_type])
            db.flush()

            self._auto_agent_id = self._seed_agent(db, user.id, "auto-a1", "gpt-auto")
            self._manual_agent_id = self._seed_agent(db, user.id, "manual-a1", "manual-type")
            _add_global_settings(db)
            db.commit()

    def _seed_agent(self, db, user_id: int, slug: str, agent_type: str) -> int:
        agent = Agent(
            name=slug, slug=slug,
            agent_type=agent_type,
            availability_status="available",
            subscription_expires_at=datetime.utcnow() + timedelta(days=30),
            created_by=user_id,
        )
        db.add(agent)
        db.flush()
        return agent.id

    def _login(self) -> dict:
        r = self.client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "Owner123"},
        )
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def test_auto_project_with_manual_agent_returns_400(self):
        """AC-3: auto project cannot include a manual-mode agent."""
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Test",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": True,
                "agent_ids": [self._manual_agent_id],
            },
            headers=self._login(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("手动模式", r.json()["detail"])

    def test_manual_project_with_auto_agent_returns_400(self):
        """AC-3: manual project cannot include an auto-mode agent."""
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Test",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": False,
                "agent_ids": [self._auto_agent_id],
            },
            headers=self._login(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("自动模式", r.json()["detail"])

    def test_auto_project_with_auto_agent_accepted(self):
        """AC-3: matching auto modes are accepted (positive case)."""
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Auto Project",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": True,
                "agent_ids": [self._auto_agent_id],
            },
            headers=self._login(),
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["is_auto"])

    def test_manual_project_with_manual_agent_accepted(self):
        """AC-3: matching manual modes are accepted (positive case)."""
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Manual Project",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": False,
                "agent_ids": [self._manual_agent_id],
            },
            headers=self._login(),
        )
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.json()["is_auto"])

    def test_update_project_with_mismatched_agent_returns_400(self):
        """AC-3: updating a project to add a mode-mismatched agent returns 400."""
        headers = self._login()
        # Create a valid auto project first
        create_resp = self.client.post(
            "/api/projects",
            json={
                "name": "Auto",
                "git_repo_url": "https://github.com/x/y",
                "is_auto": True,
                "agent_ids": [self._auto_agent_id],
            },
            headers=headers,
        )
        self.assertEqual(create_resp.status_code, 201)
        project_id = create_resp.json()["id"]

        # Try to swap to a manual agent
        r = self.client.put(
            f"/api/projects/{project_id}",
            json={"agent_ids": [self._manual_agent_id]},
            headers=headers,
        )
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# AC-5 — backward compatibility defaults
# ---------------------------------------------------------------------------

class TestBackwardCompatibility(unittest.TestCase):
    """AC-5: all legacy agents and projects default to manual (non-auto) mode."""

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        self.db.add(user)
        self.db.commit()
        self.addCleanup(self.db.close)

    def test_project_defaults_to_manual_mode(self):
        """AC-5: Project.is_auto is False by default."""
        project = Project(
            name="Legacy",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/legacy",
            status="draft",
            created_by=1,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        self.assertFalse(project.is_auto)

    def test_agent_type_without_sdk_type_is_manual(self):
        """AC-5: AgentTypeConfig without sdk_type is treated as manual by is_auto_agent_type."""
        manual_type = AgentTypeConfig(name="legacy-type")
        self.assertFalse(is_auto_agent_type(manual_type))

    def test_agent_type_with_sdk_type_is_auto(self):
        """Positive check: sdk_type present → is_auto_agent_type returns True."""
        auto_type = AgentTypeConfig(name="auto-type", sdk_type="claude")
        self.assertTrue(is_auto_agent_type(auto_type))

    def test_none_agent_type_config_is_not_auto(self):
        """AC-5: None agent type config is treated as manual."""
        self.assertFalse(is_auto_agent_type(None))

    def test_manual_agent_tasks_excluded_from_auto_dispatch(self):
        """AC-5: tasks assigned to legacy manual agents are never auto-dispatched."""
        project = Project(
            id=2, name="Legacy",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/2",
            status="executing",
            created_by=1,
        )
        plan = ProjectPlan(id=2, project_id=2, status="final")
        manual_type = AgentTypeConfig(id=10, name="legacy-manual")   # no sdk_type
        agent = Agent(
            id=10, name="LegacyAgent", slug="legacy-1",
            agent_type="legacy-manual", created_by=1,
        )
        task = Task(
            project_id=2, plan_id=2,
            task_code="T1", task_name="T1",
            status="pending",
            assignee_agent_id=10,
            depends_on_json="[]",
            expected_output_path="o/2/T1/result.json",
        )
        self.db.add_all([project, plan, manual_type, agent, task])
        self.db.commit()
        ready = get_ready_auto_tasks(self.db, project_id=2)
        self.assertEqual(ready, [])


# ---------------------------------------------------------------------------
# AC-6 — API key never exposed in HTTP responses
# ---------------------------------------------------------------------------

class TestApiKeyNotExposed(unittest.TestCase):
    """AC-6: raw API Key must never appear in any API response payload."""

    _SECRET = "ultra-secret-api-key-must-not-leak"

    def setUp(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        app = FastAPI()
        app.include_router(auth_router.router)
        app.include_router(agent_settings_router.router)

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[database.get_db] = override_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            admin = User(
                username="admin",
                password_hash=hash_password("Admin123"),
                role="admin",
                status="active",
            )
            db.add(admin)
            db.commit()

    def _admin_headers(self) -> dict:
        r = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "Admin123"},
        )
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def _create_auto_type(self, headers: dict, name: str = "gpt-auto") -> dict:
        r = self.client.post(
            "/api/agent-settings/types",
            json={
                "name": name,
                "sdk_type": "claude",
            },
            headers=headers,
        )
        self.assertEqual(r.status_code, 201)
        return r.json()

    def test_create_response_does_not_contain_raw_api_key(self):
        """AC-6: POST /api/agent-settings/types response must not expose any key."""
        headers = self._admin_headers()
        data = self._create_auto_type(headers)
        self.assertNotIn(self._SECRET, json.dumps(data))
        self.assertNotIn("api_key_encrypted", data)
        self.assertNotIn("api_key", data)

    def test_list_response_does_not_contain_raw_api_key(self):
        """AC-6: GET /api/agent-settings/types response must not expose the key."""
        headers = self._admin_headers()
        self._create_auto_type(headers)
        r = self.client.get("/api/agent-settings/types", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(self._SECRET, json.dumps(r.json()))

    def test_update_response_does_not_contain_raw_api_key(self):
        """AC-6: PUT /api/agent-settings/types/{id} response must not expose any key."""
        headers = self._admin_headers()
        data = self._create_auto_type(headers)
        type_id = data["id"]
        r = self.client.put(
            f"/api/agent-settings/types/{type_id}",
            json={"description": "updated"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200)
        payload = json.dumps(r.json())
        self.assertNotIn(self._SECRET, payload)
        self.assertNotIn("api_key_encrypted", r.json())

    def test_agent_type_out_schema_exposes_only_has_api_key_flag(self):
        """AC-6: AgentTypeOut has no raw key fields; has_api_key flag lives on AgentResponse."""
        from routers.agent_settings import AgentTypeOut
        type_fields = set(AgentTypeOut.model_fields.keys())
        self.assertNotIn("api_key", type_fields)
        self.assertNotIn("api_key_encrypted", type_fields)
        self.assertNotIn("has_api_key", type_fields)
        # The has_api_key flag is on the agent instance response
        from routers.agents import AgentResponse
        agent_fields = set(AgentResponse.model_fields.keys())
        self.assertNotIn("api_key", agent_fields)
        self.assertNotIn("api_key_encrypted", agent_fields)
        self.assertIn("has_api_key", agent_fields)


# ---------------------------------------------------------------------------
# Regression: is_auto must gate on project.is_auto, not just agent sdk_type
# ---------------------------------------------------------------------------

class TestManualProjectBackwardCompat(unittest.TestCase):
    """Regression: agent type gaining sdk_type must not affect is_auto=False projects."""

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        # Agent type that has sdk_type — simulates admin setting sdk_type after the fact
        auto_type = AgentTypeConfig(id=1, name="newly-auto", sdk_type="claude")
        self.agent = Agent(
            id=1, name="Agent", slug="agent-1",
            agent_type="newly-auto", created_by=1,
        )
        self.manual_project = Project(
            id=1, name="ManualP",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/1",
            status="executing",
            is_auto=False,
            created_by=1,
        )
        self.auto_project = Project(
            id=2, name="AutoP",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/2",
            status="executing",
            is_auto=True,
            created_by=1,
        )
        plan1 = ProjectPlan(id=1, project_id=1, status="final")
        plan2 = ProjectPlan(id=2, project_id=2, status="final")
        self.db.add_all([user, auto_type, self.agent, self.manual_project, self.auto_project, plan1, plan2])
        self.db.commit()
        self.addCleanup(self.db.close)
        self._seq = 1

    def _task(self, project_id: int, plan_id: int, code: str) -> Task:
        t = Task(
            id=self._seq,
            project_id=project_id, plan_id=plan_id,
            task_code=code, task_name=code,
            status="pending",
            assignee_agent_id=self.agent.id,
            depends_on_json="[]",
            expected_output_path=f"o/{project_id}/{code}/result.json",
        )
        self._seq += 1
        self.db.add(t)
        self.db.commit()
        return t

    def test_is_auto_task_false_for_manual_project(self):
        """Even when agent type has sdk_type, tasks in manual projects are not auto tasks."""
        task = self._task(1, 1, "T1")
        self.assertFalse(is_auto_task(self.db, task))

    def test_is_auto_task_true_for_auto_project(self):
        """Control: same agent type in an auto project → is_auto_task returns True."""
        task = self._task(2, 2, "T1")
        self.assertTrue(is_auto_task(self.db, task))

    def test_get_ready_auto_tasks_skips_manual_project(self):
        """get_ready_auto_tasks must not include tasks from is_auto=False projects."""
        manual_task = self._task(1, 1, "T1")
        ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertNotIn(manual_task.id, ready)


# ---------------------------------------------------------------------------
# Regression: update_agent_type fail-fast when manual project tasks exist
# ---------------------------------------------------------------------------

class TestAgentTypeSdkTypeManualProjectGuard(unittest.TestCase):
    """update_agent_type must block setting sdk_type when manual project tasks exist."""

    def setUp(self):
        engine = _make_engine()
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        app = FastAPI()
        app.include_router(auth_router.router)
        app.include_router(agent_settings_router.router)

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[database.get_db] = override_db
        self.client = TestClient(app)

        with self.SessionLocal() as db:
            db.add(User(
                username="admin",
                password_hash=hash_password("Admin123"),
                role="admin",
                status="active",
            ))
            db.commit()

    def _admin_headers(self) -> dict:
        r = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "Admin123"},
        )
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def test_setting_sdk_type_blocked_when_manual_project_tasks_exist(self):
        """update_agent_type raises 400 when manual project has active tasks of this agent type."""
        headers = self._admin_headers()
        r = self.client.post("/api/agent-settings/types", json={"name": "my-type"}, headers=headers)
        self.assertEqual(r.status_code, 201)
        type_id = r.json()["id"]

        with self.SessionLocal() as db:
            agent = Agent(id=1, name="A", slug="a-1", agent_type="my-type", created_by=1)
            project = Project(
                id=1, name="ManualP",
                git_repo_url="https://github.com/x/y",
                collaboration_dir="o/1",
                status="executing",
                is_auto=False,
                created_by=1,
            )
            plan = ProjectPlan(id=1, project_id=1, status="final")
            task = Task(
                project_id=1, plan_id=1,
                task_code="T1", task_name="T1",
                status="pending",
                assignee_agent_id=1,
                depends_on_json="[]",
                expected_output_path="o/1/T1/result.json",
            )
            db.add_all([agent, project, plan, task])
            db.commit()

        r = self.client.put(
            f"/api/agent-settings/types/{type_id}",
            json={"sdk_type": "claude"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("手动项目", r.json()["detail"])

    def test_setting_sdk_type_allowed_when_no_manual_tasks(self):
        """update_agent_type succeeds when no active tasks exist for this agent type."""
        headers = self._admin_headers()
        r = self.client.post("/api/agent-settings/types", json={"name": "clean-type"}, headers=headers)
        type_id = r.json()["id"]

        r = self.client.put(
            f"/api/agent-settings/types/{type_id}",
            json={"sdk_type": "claude"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sdk_type"], "claude")

    def test_setting_sdk_type_allowed_when_manual_tasks_are_done(self):
        """update_agent_type allows sdk_type when manual project tasks are already completed."""
        headers = self._admin_headers()
        r = self.client.post("/api/agent-settings/types", json={"name": "done-type"}, headers=headers)
        type_id = r.json()["id"]

        with self.SessionLocal() as db:
            agent = Agent(id=2, name="B", slug="b-1", agent_type="done-type", created_by=1)
            project = Project(
                id=2, name="ManualDone",
                git_repo_url="https://github.com/x/y",
                collaboration_dir="o/2",
                status="completed",
                is_auto=False,
                created_by=1,
            )
            plan = ProjectPlan(id=2, project_id=2, status="final")
            task = Task(
                project_id=2, plan_id=2,
                task_code="T1", task_name="T1",
                status="completed",
                assignee_agent_id=2,
                depends_on_json="[]",
                expected_output_path="o/2/T1/result.json",
            )
            db.add_all([agent, project, plan, task])
            db.commit()

        r = self.client.put(
            f"/api/agent-settings/types/{type_id}",
            json={"sdk_type": "claude"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Regression: unready downstream task with missing creds must NOT be failed
# ---------------------------------------------------------------------------

class TestUnreadyTaskWithMissingCredsNotFailed(unittest.TestCase):
    """Regression: T2 depends on T1 (not complete) and has missing API creds.

    Before the fix, get_ready_auto_tasks() checked credentials *before*
    is_task_ready(), so T2 would be prematurely marked 'needs_attention'
    even though it wasn't scheduled to run yet.  After the fix, T2 must
    stay 'pending' until T1 is done.
    """

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        project = Project(
            id=1, name="P",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/1",
            status="executing",
            is_auto=True,
            created_by=1,
        )
        plan = ProjectPlan(id=1, project_id=1, status="final")

        # T1's agent: valid credentials
        self.good_type = AgentTypeConfig(id=1, name="good-type", sdk_type="claude")
        self.good_agent = Agent(
            id=1, name="GoodAgent", slug="good-1", agent_type="good-type", created_by=1,
            api_base_url="https://api.example.com/v1",
            api_key_encrypted=encrypt_api_key("real-key"),
        )
        # T2's agent: missing credentials (no api_base_url, no api_key_encrypted)
        self.bad_type = AgentTypeConfig(id=2, name="bad-type", sdk_type="claude")
        self.bad_agent = Agent(
            id=2, name="BadAgent", slug="bad-1", agent_type="bad-type", created_by=1,
        )

        self.db.add_all([
            user, project, plan,
            self.good_type, self.good_agent,
            self.bad_type, self.bad_agent,
        ])
        self.db.commit()
        self.addCleanup(self.db.close)
        self._seq = 1

    def _task(self, code: str, agent_id: int, depends_on: list | None = None) -> Task:
        t = Task(
            id=self._seq,
            project_id=1, plan_id=1,
            task_code=code, task_name=code,
            status="pending",
            assignee_agent_id=agent_id,
            depends_on_json=json.dumps(depends_on or []),
            expected_output_path=f"o/1/{code}/result.json",
        )
        self._seq += 1
        self.db.add(t)
        self.db.commit()
        return t

    def test_unready_downstream_with_missing_creds_stays_pending(self):
        """T2 (depends on unfinished T1, bad creds) must remain 'pending' after dispatch scan."""
        t1 = self._task("T1", self.good_agent.id)          # no deps, good creds
        t2 = self._task("T2", self.bad_agent.id, depends_on=["T1"])  # blocked, bad creds

        ready = get_ready_auto_tasks(self.db, project_id=1)

        # T1 is ready (no deps, good creds)
        self.assertIn(t1.id, ready)
        # T2 is NOT ready (T1 still pending)
        self.assertNotIn(t2.id, ready)
        # Crucially, T2 must NOT have been prematurely failed
        self.db.refresh(t2)
        self.assertEqual(t2.status, "pending",
                         "Unready downstream task must not be marked needs_attention prematurely")
        self.assertIsNone(t2.last_error)

    def test_ready_downstream_with_missing_creds_gets_needs_attention(self):
        """Once T1 is complete, T2 (ready but bad creds) should become needs_attention."""
        t1 = self._task("T1", self.good_agent.id)
        t1.status = "completed"
        self.db.add(t1)
        self.db.commit()

        t2 = self._task("T2", self.bad_agent.id, depends_on=["T1"])

        ready = get_ready_auto_tasks(self.db, project_id=1)

        self.assertNotIn(t2.id, ready)
        self.db.refresh(t2)
        self.assertEqual(t2.status, "needs_attention",
                         "Ready task with missing creds should still become needs_attention")
        self.assertIsNotNone(t2.last_error)


# ---------------------------------------------------------------------------
# Regression: auto-dispatch must honour the issue review loop business state
# ---------------------------------------------------------------------------

class TestAutoDispatchBusinessStateGate(unittest.TestCase):
    """Auto-dispatch must not run tasks whose business state is 'frozen'.

    The issue-review-loop template only unlocks tasks at specific phases
    (e.g. TASK-003/004 only after TASK-002 publishes its work branch).
    Auto-dispatch must respect the same gate as manual dispatch.
    """

    _VALID_KEY = "super-secret-key"

    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()

        user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        project = Project(
            id=1, name="AutoLoop",
            git_repo_url="https://github.com/x/y",
            collaboration_dir="o/1",
            status="executing",
            is_auto=True,
            created_by=1,
        )
        # A selected plan whose flow_type marks this as an issue_review_loop project
        from services.issue_review_loop import FLOW_TYPE
        plan = ProjectPlan(
            id=1, project_id=1,
            plan_type="final", status="final", is_selected=True,
            plan_json=json.dumps({"flow_type": FLOW_TYPE, "tasks": []}),
        )
        auto_type = AgentTypeConfig(id=1, name="gpt-auto", sdk_type="claude")
        auto_agent = Agent(
            id=1, name="Auto", slug="auto-1", agent_type="gpt-auto", created_by=1,
            api_base_url="https://api.example.com/v1",
            api_key_encrypted=encrypt_api_key(self._VALID_KEY),
        )
        self.db.add_all([user, project, plan, auto_type, auto_agent])
        self.db.commit()
        self.addCleanup(self.db.close)
        self._seq = 1

    def _task(self, code: str, depends_on: list | None = None) -> Task:
        t = Task(
            id=self._seq,
            project_id=1, plan_id=1,
            task_code=code, task_name=code,
            status="pending",
            assignee_agent_id=1,
            depends_on_json=json.dumps(depends_on or []),
            expected_output_path=f"o/1/{code}/result.json",
        )
        self._seq += 1
        self.db.add(t)
        self.db.commit()
        return t

    def test_frozen_task_not_dispatched(self):
        """A DAG-ready task whose business state is 'frozen' must not enter the ready list."""
        t = self._task("TASK-003")
        with patch("services.auto_dispatch.project_uses_issue_review_loop", return_value=True), \
             patch("services.auto_dispatch.get_effective_business_state", return_value="frozen"):
            ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertNotIn(t.id, ready)
        # Must remain pending — frozen is a normal transient state, not an error
        self.db.refresh(t)
        self.assertEqual(t.status, "pending")
        self.assertIsNone(t.last_error)

    def test_unlocked_task_is_dispatched(self):
        """A DAG-ready task whose business state is 'unlocked' must appear in the ready list."""
        t = self._task("TASK-003")
        with patch("services.auto_dispatch.project_uses_issue_review_loop", return_value=True), \
             patch("services.auto_dispatch.get_effective_business_state", return_value="unlocked"):
            ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(t.id, ready)

    def test_needs_fix_task_is_dispatched(self):
        """'needs_fix' is the other dispatchable state (reviewer requested changes)."""
        t = self._task("TASK-002")
        with patch("services.auto_dispatch.project_uses_issue_review_loop", return_value=True), \
             patch("services.auto_dispatch.get_effective_business_state", return_value="needs_fix"):
            ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(t.id, ready)

    def test_non_loop_project_unaffected(self):
        """Projects not using the issue review loop are not subject to the business state gate."""
        t = self._task("TASK-001")
        with patch("services.auto_dispatch.project_uses_issue_review_loop", return_value=False):
            ready = get_ready_auto_tasks(self.db, project_id=1)
        self.assertIn(t.id, ready)

    def test_multiple_tasks_only_unlocked_returned(self):
        """Mixed states: only the unlocked task enters the ready list."""
        t_frozen = self._task("TASK-003")
        t_unlocked = self._task("TASK-004")

        def _biz_state(_db, _project, task_code):
            return "unlocked" if task_code == "TASK-004" else "frozen"

        with patch("services.auto_dispatch.project_uses_issue_review_loop", return_value=True), \
             patch("services.auto_dispatch.get_effective_business_state", side_effect=_biz_state):
            ready = get_ready_auto_tasks(self.db, project_id=1)

        self.assertNotIn(t_frozen.id, ready)
        self.assertIn(t_unlocked.id, ready)


if __name__ == "__main__":
    unittest.main()
