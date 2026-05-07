import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from models import Project, ProjectPlan
from services.git_service import RepoSyncStatus
from services.polling_service import poll_project


@pytest.fixture
def session_local():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def seed_timed_out_plan(session_local):
    db = session_local()
    try:
        project = Project(
            id=52,
            name="Manual Refresh Recovery",
            git_repo_url="git@github.com:example-org/example-repo.git",
            collaboration_dir="outputs/proj-52-plan",
            status="planning",
        )
        plan = ProjectPlan(
            id=53,
            project_id=52,
            status="needs_attention",
            dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=31),
            last_error="Plan JSON not found at outputs/proj-52-plan/plan.json after 31.0 minutes",
        )
        db.add_all([project, plan])
        db.commit()
        return project.id, plan.id
    finally:
        db.close()


def test_manual_poll_recovers_needs_attention_plan_when_plan_json_appears(session_local):
    project_id, plan_id = seed_timed_out_plan(session_local)
    plan_data = {
        "tasks": [
            {
                "task_code": "TASK-001",
                "task_name": "需求梳理",
            }
        ]
    }

    db = session_local()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()

        with patch(
            "services.polling_service.git_service.ensure_repo_sync",
            return_value=RepoSyncStatus(repo_dir="/tmp/repo", fetched=True, pulled=True, remote_ready=True),
        ), patch(
            "services.polling_service.git_service.read_json",
            return_value=plan_data,
        ):
            poll_project(db, project)
    finally:
        db.close()

    verify_db = session_local()
    try:
        refreshed = verify_db.query(ProjectPlan).filter(ProjectPlan.id == plan_id).first()
        assert refreshed.status == "completed"
        assert refreshed.plan_json == json.dumps(plan_data, ensure_ascii=False, indent=2)
        assert refreshed.last_error is None
        assert refreshed.source_path == "outputs/proj-52-plan/plan.json"
        assert refreshed.detected_at is not None
    finally:
        verify_db.close()