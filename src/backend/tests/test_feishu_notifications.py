import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from models import Project, ProjectPlan, Task, User
import routers.polling as polling_router
import routers.settings as settings_router
import services.polling_service as polling_service
from services.feishu_service import (
    DEFAULT_NOTIFY_EVENTS,
    NotificationEvent,
    dispatch_notifications,
    get_feishu_destination_for_user,
    get_feishu_settings,
)
from services.git_service import RepoSyncStatus
from services.polling_service import poll_project


@pytest.fixture
def session_local():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db(session_local):
    session = session_local()
    try:
        yield session
    finally:
        session.close()


def create_user(db, username: str = "alice", **kwargs) -> User:
    user = User(
        username=username,
        password_hash="secret",
        role=kwargs.pop("role", "user"),
        status=kwargs.pop("status", "active"),
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def seeded_project(session_local):
    session = session_local()
    try:
        owner = User(
            id=99,
            username="owner",
            password_hash="secret",
            role="user",
            status="active",
        )
        project = Project(
            id=7,
            name="Demo",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir="outputs/proj-7-7b145d",
            status="executing",
            task_timeout_minutes=20,
            created_by=99,
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
        session.add_all([owner, project, plan, task])
        session.commit()
        session.refresh(project)
        session.refresh(task)
        yield project, task
    finally:
        session.close()


def test_get_feishu_settings_falls_back_to_defaults_for_missing_or_invalid_values(db):
    user = create_user(db)

    assert get_feishu_settings(user) == {
        "webhook_url": "",
        "notify_events": DEFAULT_NOTIFY_EVENTS,
    }

    for raw_value in ['{"unexpected": true}', '"completed"', '{bad json', '["unknown"]']:
        user.feishu_notify_events_json = raw_value
        db.commit()
        db.refresh(user)

        settings = get_feishu_settings(user)

        assert settings["webhook_url"] == ""
        assert settings["notify_events"] == DEFAULT_NOTIFY_EVENTS


def test_update_feishu_notification_settings_round_trips_to_current_user(db):
    user = create_user(db)
    payload = {
        "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/demo_token-123",
        "notify_events": ["completed", "project_completed"],
    }

    saved = asyncio.run(
        settings_router.update_feishu_notification_settings(payload, db=db, user=user)
    )

    assert saved == payload
    db.refresh(user)
    assert user.feishu_webhook_url == payload["webhook_url"]
    assert json.loads(user.feishu_notify_events_json) == payload["notify_events"]
    assert get_feishu_settings(user) == payload


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
        user = create_user(session)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                settings_router.update_feishu_notification_settings(payload, db=session, user=user)
            )
        assert expected in str(exc_info.value.detail)
    finally:
        session.close()


def test_get_feishu_destination_for_user_returns_only_matching_active_user(session_local):
    session = session_local()
    try:
        active_user = create_user(
            session,
            username="alice",
            feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/alice",
            feishu_notify_events_json='["completed", "timeout"]',
        )
        inactive_user = create_user(
            session,
            username="bob",
            status="frozen",
            feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/bob",
            feishu_notify_events_json='["completed", "timeout"]',
        )

        destination = get_feishu_destination_for_user(session, active_user.id)
        inactive_destination = get_feishu_destination_for_user(session, inactive_user.id)

        assert destination is not None
        assert destination.webhook_url == "https://open.feishu.cn/open-apis/bot/v2/hook/alice"
        assert destination.notify_events == frozenset(["completed", "timeout"])
        assert inactive_destination is None
    finally:
        session.close()


def test_dispatch_notifications_delivers_matching_events_only_to_project_owner(session_local, monkeypatch):
    session = session_local()
    try:
        owner = create_user(
            session,
            username="alice",
            feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/alice",
            feishu_notify_events_json='["completed"]',
        )
        create_user(
            session,
            username="bob",
            feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/bob",
            feishu_notify_events_json='["completed", "timeout"]',
        )

        sent_events = []

        async def fake_send(webhook_url: str, event: NotificationEvent) -> None:
            sent_events.append((webhook_url, event.event_type, event.project_name, event.task_name))

        monkeypatch.setattr("services.feishu_service.send_feishu_notification", fake_send)

        delivered = asyncio.run(dispatch_notifications(session, owner.id, [
            NotificationEvent(event_type="completed", project_name="Demo", task_name="完成任务"),
            NotificationEvent(event_type="timeout", project_name="Demo", task_name="超时任务"),
        ]))

        assert delivered == 1
        assert sent_events == [
            ("https://open.feishu.cn/open-apis/bot/v2/hook/alice", "completed", "Demo", "完成任务"),
        ]
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


def test_poll_project_returns_no_notifications_when_git_repo_is_inaccessible(session_local, seeded_project, monkeypatch):
    project, _task = seeded_project

    monkeypatch.setattr(
        "services.polling_service.git_service.ensure_repo_sync",
        lambda *args, **kwargs: RepoSyncStatus(
            repo_dir="/tmp/repo",
            remote_ready=False,
            error="permission denied",
        ),
    )

    db = session_local()
    try:
        fetched_project = db.query(Project).filter(Project.id == project.id).first()
        notifications = poll_project(db, fetched_project)
    finally:
        db.close()

    assert notifications == []


def test_manual_poll_dispatches_generated_notifications(session_local, monkeypatch):
    session = session_local()
    try:
        user = create_user(session, username="owner")
        project = Project(
            id=11,
            name="Manual Poll",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir="outputs/proj-11",
            status="executing",
            created_by=user.id,
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        dispatched: list[tuple[int, list[str]]] = []

        async def fake_dispatch(db, user_id, notifications):
            dispatched.append((user_id, [event.event_type for event in notifications]))
            return len(notifications)

        monkeypatch.setattr(
            "routers.polling.poll_project",
            lambda db, current_project: [
                NotificationEvent(event_type="completed", project_name=current_project.name, task_name="完成任务")
            ],
        )
        monkeypatch.setattr("routers.polling.feishu_service.dispatch_notifications", fake_dispatch)

        response = asyncio.run(polling_router.manual_poll(project.id, db=session, user=user))

        assert response["project_status"] == "executing"
        assert response["notification_events"] == ["completed"]
        assert dispatched == [(project.created_by, ["completed"])]
    finally:
        session.close()


def test_polling_loop_dispatches_notifications_via_shared_helper(session_local, seeded_project, monkeypatch):
    project, _task = seeded_project
    dispatched = []

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

        async def fake_dispatch(db, user_id, notifications):
            dispatched.append((user_id, [event.event_type for event in notifications]))
            return len(notifications)

        monkeypatch.setattr(polling_service.feishu_service, "dispatch_notifications", fake_dispatch)
        monkeypatch.setattr(polling_service, "_compute_next_poll_time", lambda db, project_obj, now: now)
        monkeypatch.setattr(polling_service.asyncio, "sleep", stop_sleep)

        with pytest.raises(asyncio.CancelledError):
            await polling_service.polling_loop(5)

    asyncio.run(exercise())

    assert dispatched == [(project.created_by, ["completed", "timeout"])]


def test_manual_poll_sends_feishu_notification_end_to_end(session_local, monkeypatch):
    """End-to-end: manual_poll → real dispatch_notifications → send_feishu_notification called.

    Only the HTTP layer is mocked; dispatch_notifications runs for real so that
    bugs like a wrong user_id or misconfigured FeishuDestination are caught.
    """
    session = session_local()
    try:
        owner = create_user(
            session,
            username="owner",
            feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/owner-token",
            feishu_notify_events_json='["completed", "timeout"]',
        )
        project = Project(
            id=21,
            name="E2E Project",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir="outputs/proj-21",
            status="executing",
            created_by=owner.id,
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        sent: list[tuple[str, str]] = []

        async def fake_send(webhook_url: str, event: NotificationEvent) -> None:
            sent.append((webhook_url, event.event_type))

        monkeypatch.setattr(
            "routers.polling.poll_project",
            lambda db, current_project: [
                NotificationEvent(event_type="completed", project_name=current_project.name, task_name="完成任务"),
                NotificationEvent(event_type="timeout", project_name=current_project.name, task_name="超时任务"),
            ],
        )
        monkeypatch.setattr("services.feishu_service.send_feishu_notification", fake_send)

        response = asyncio.run(polling_router.manual_poll(project.id, db=session, user=owner))

        assert response["notification_events"] == ["completed", "timeout"]
        # owner subscribed to ["completed", "timeout"], so both are delivered
        assert sent == [
            ("https://open.feishu.cn/open-apis/bot/v2/hook/owner-token", "completed"),
            ("https://open.feishu.cn/open-apis/bot/v2/hook/owner-token", "timeout"),
        ]
    finally:
        session.close()


def test_manual_poll_returns_empty_notification_events_and_sends_nothing_when_poll_is_clean(session_local, monkeypatch):
    """When poll_project produces no events, notification_events is [] and no Feishu call is made."""
    session = session_local()
    try:
        owner = create_user(
            session,
            username="owner",
            feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/owner-token",
            feishu_notify_events_json='["completed"]',
        )
        project = Project(
            id=22,
            name="Quiet Project",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir="outputs/proj-22",
            status="executing",
            created_by=owner.id,
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        sent: list = []

        async def fake_send(webhook_url: str, event: NotificationEvent) -> None:
            sent.append((webhook_url, event.event_type))

        monkeypatch.setattr("routers.polling.poll_project", lambda db, current_project: [])
        monkeypatch.setattr("services.feishu_service.send_feishu_notification", fake_send)

        response = asyncio.run(polling_router.manual_poll(project.id, db=session, user=owner))

        assert response["notification_events"] == []
        assert sent == []
    finally:
        session.close()
