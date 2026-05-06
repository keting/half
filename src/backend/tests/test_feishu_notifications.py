import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from models import GlobalSetting, Project, ProjectPlan, Task
import routers.settings as settings_router
import services.polling_service as polling_service
from services.feishu_service import (
    DEFAULT_NOTIFY_EVENTS,
    FEISHU_NOTIFY_EVENTS_KEY,
    FEISHU_WEBHOOK_URL_KEY,
    NotificationEvent,
    get_feishu_settings,
)
from services.git_service import RepoSyncStatus
from services.polling_service import poll_project


@pytest.fixture
def session_local():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db(session_local):
    session = session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded_project(session_local):
    session = session_local()
    try:
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
            status="running",
            expected_output_path="outputs/proj-7-7b145d/TASK-001/result.json",
            dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=11),
            timeout_minutes=10,
        )
        session.add_all([project, plan, task])
        session.commit()
        session.refresh(project)
        session.refresh(task)
        yield project, task
    finally:
        session.close()


def test_get_feishu_settings_falls_back_to_defaults_for_missing_or_invalid_values(db):
    assert get_feishu_settings(db) == {
        "webhook_url": "",
        "notify_events": DEFAULT_NOTIFY_EVENTS,
    }

    for raw_value in ['{"unexpected": true}', '"completed"', '{bad json']:
        db.query(GlobalSetting).delete()
        db.add(GlobalSetting(key=FEISHU_NOTIFY_EVENTS_KEY, value=raw_value))
        db.commit()

        settings = get_feishu_settings(db)

        assert settings["webhook_url"] == ""
        assert settings["notify_events"] == DEFAULT_NOTIFY_EVENTS


def test_update_feishu_notification_settings_round_trips_to_global_settings(db):
    payload = {
        "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/demo_token-123",
        "notify_events": ["completed", "project_completed"],
    }

    saved = asyncio.run(
        settings_router.update_feishu_notification_settings(payload, db=db, _user=object())
    )

    assert saved == payload
    stored = {
        row.key: row.value
        for row in db.query(GlobalSetting).filter(
            GlobalSetting.key.in_([FEISHU_WEBHOOK_URL_KEY, FEISHU_NOTIFY_EVENTS_KEY])
        ).all()
    }
    assert stored[FEISHU_WEBHOOK_URL_KEY] == payload["webhook_url"]
    assert json.loads(stored[FEISHU_NOTIFY_EVENTS_KEY]) == payload["notify_events"]
    assert get_feishu_settings(db) == payload


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"webhook_url": "https://example.com/webhook", "notify_events": ["completed"]},
            "webhook_url must match",
        ),
        (
            {"webhook_url": 123, "notify_events": ["completed"]},
            "webhook_url must be a string",
        ),
        (
            {"webhook_url": "", "notify_events": "completed"},
            "notify_events must be a list",
        ),
        (
            {"webhook_url": "", "notify_events": ["completed", "unknown"]},
            "Invalid event types",
        ),
    ],
)
def test_update_feishu_notification_settings_rejects_invalid_payloads(session_local, payload, expected):
    session = session_local()
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                settings_router.update_feishu_notification_settings(payload, db=session, _user=object())
            )
        assert expected in str(exc_info.value.detail)
    finally:
        session.close()


def test_poll_project_returns_completed_notification_event(session_local, seeded_project, monkeypatch):
    project, _task = seeded_project

    monkeypatch.setattr(
        "services.polling_service.git_service.ensure_repo_sync",
        lambda *args, **kwargs: RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
    )
    monkeypatch.setattr(
        "services.polling_service.git_service.file_exists",
        lambda project_id, relative_path, git_repo_url=None, prefer_remote=False: relative_path == "outputs/proj-7-7b145d/TASK-001/result.json",
    )

    notifications = poll_project(session_local(), project)

    assert [event.event_type for event in notifications] == ["completed", "project_completed"]
    assert notifications[0].project_name == "Demo"
    assert notifications[0].task_name == "需求梳理与功能清单"
    assert notifications[1].project_name == "Demo"
    assert notifications[1].task_name is None


def test_poll_project_returns_timeout_notification_event(session_local, seeded_project, monkeypatch):
    project, _task = seeded_project

    monkeypatch.setattr(
        "services.polling_service.git_service.ensure_repo_sync",
        lambda *args, **kwargs: RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
    )
    monkeypatch.setattr(
        "services.polling_service.git_service.file_exists",
        lambda *args, **kwargs: False,
    )

    notifications = poll_project(session_local(), project)

    assert len(notifications) == 1
    assert notifications[0].event_type == "timeout"
    assert notifications[0].project_name == "Demo"
    assert notifications[0].task_name == "需求梳理与功能清单"
    assert "超时" in notifications[0].detail


def test_polling_loop_only_dispatches_enabled_feishu_events(session_local, seeded_project, monkeypatch):
    project, _task = seeded_project
    scheduled_tasks = []
    sent_events = []
    original_create_task = asyncio.create_task

    async def fake_send(webhook_url: str, event: NotificationEvent) -> None:
        sent_events.append((webhook_url, event.event_type, event.project_name, event.task_name))

    def capture_task(coro):
        task = original_create_task(coro)
        scheduled_tasks.append(task)
        return task

    async def stop_sleep(_seconds: int) -> None:
        raise asyncio.CancelledError()

    async def exercise() -> None:
        monkeypatch.setattr(polling_service, "SessionLocal", session_local)
        monkeypatch.setattr(
            polling_service,
            "poll_project",
            lambda db, current_project: [
                NotificationEvent(event_type="completed", project_name=current_project.name, task_name="完成任务"),
                NotificationEvent(event_type="timeout", project_name=current_project.name, task_name="超时任务"),
            ],
        )
        monkeypatch.setattr(
            polling_service.feishu_service,
            "get_feishu_settings",
            lambda db: {
                "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/demo_token-123",
                "notify_events": ["timeout"],
            },
        )
        monkeypatch.setattr(polling_service.feishu_service, "send_feishu_notification", fake_send)
        monkeypatch.setattr(polling_service, "_compute_next_poll_time", lambda db, project_obj, now: now)
        monkeypatch.setattr(polling_service.asyncio, "create_task", capture_task)
        monkeypatch.setattr(polling_service.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await polling_service.polling_loop(5)

        if scheduled_tasks:
            await asyncio.gather(*scheduled_tasks)

    asyncio.run(exercise())

    assert sent_events == [
        ("https://open.feishu.cn/open-apis/bot/v2/hook/demo_token-123", "timeout", "Demo", "超时任务")
    ]
