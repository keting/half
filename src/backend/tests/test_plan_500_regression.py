"""Pytest regression for the plan polling 500 fix.

The repaired code must keep GET /api/projects/{id}/plans responsive while the
background poller is inside poll_project. Before the fix, the same scenario
would block the event loop and this test would fail with a request timeout.
"""

import asyncio
import socket
import sys
import threading
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database
from auth import create_token, hash_password
from database import Base
from models import Project, User
from routers import auth as auth_router
from routers import plans as plans_router
from services import polling_service


@pytest.fixture
def session_local():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def auth_token(session_local):
    with session_local() as db:
        user = User(
            username="alice",
            password_hash=hash_password("Alice123"),
            role="user",
            status="active",
        )
        db.add(user)
        db.flush()
        project = Project(
            id=2,
            name="Test Project",
            git_repo_url="git@github.com:example-org/repo.git",
            collaboration_dir="outputs/proj-2",
            status="planning",
            created_by=user.id,
        )
        db.add(project)
        db.commit()
        return create_token(user.id, user.username, user.role)


def build_app(session_local, *, start_polling: bool) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not start_polling:
            yield
            return

        async def delayed_poller() -> None:
            await asyncio.sleep(0.05)
            await polling_service.polling_loop(1)

        poller_task = asyncio.create_task(delayed_poller())
        try:
            yield
        finally:
            poller_task.cancel()
            with suppress(asyncio.CancelledError):
                await poller_task

    app = FastAPI(lifespan=lifespan)
    app.include_router(auth_router.router)
    app.include_router(plans_router.router)

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = override_get_db
    return app


def reserve_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_get_plans_returns_200_normally(session_local, auth_token):
    headers = {"Authorization": f"Bearer {auth_token}"}
    with TestClient(build_app(session_local, start_polling=False), raise_server_exceptions=False) as client:
        response = client.get("/api/projects/2/plans", headers=headers)
    assert response.status_code == 200


def test_get_plans_remains_responsive_during_background_polling(
    session_local, auth_token, monkeypatch
):
    import uvicorn

    headers = {"Authorization": f"Bearer {auth_token}"}
    poll_started = threading.Event()
    release_poll = threading.Event()

    def fake_poll_project(db, project):
        poll_started.set()
        release_poll.wait(timeout=5)

    monkeypatch.setattr(polling_service, "SessionLocal", session_local)
    monkeypatch.setattr(polling_service, "poll_project", fake_poll_project)
    monkeypatch.setattr(
        polling_service,
        "_compute_next_poll_time",
        lambda db, project, now: datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    app = build_app(session_local, start_polling=True)
    port = reserve_tcp_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    server_thread = threading.Thread(target=server.run, daemon=True)

    try:
        server_thread.start()

        deadline = time.time() + 5
        while not server.started:
            assert server_thread.is_alive(), "uvicorn exited before the regression scenario could start."
            assert time.time() < deadline, "uvicorn did not finish startup in time."
            time.sleep(0.05)

        assert poll_started.wait(2), "Background polling never entered poll_project; regression setup is invalid."

        request = Request(
            f"http://127.0.0.1:{port}/api/projects/2/plans",
            headers=headers,
        )
        try:
            with urlopen(request, timeout=0.5) as response:
                status_code = response.status
                response.read()
        except (TimeoutError, URLError) as exc:
            pytest.fail(
                "GET /api/projects/2/plans stayed blocked while poll_project was running; "
                f"the fix regressed and event-loop responsiveness was lost: {exc}"
            )

        assert status_code == 200
    finally:
        release_poll.set()
        server.should_exit = True
        server_thread.join(timeout=5)
        assert not server_thread.is_alive(), "uvicorn did not stop cleanly after the regression test."