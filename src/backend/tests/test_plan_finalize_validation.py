import json
import sys
import unittest
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from auth import hash_password
from models import Project, ProjectPlan, User
from routers.plans import FinalizeRequest, finalize_plan


class PlanFinalizeValidationTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = self.SessionLocal()
        self.user = User(id=1, username="owner", password_hash=hash_password("Owner123"))
        self.db.add(self.user)
        self.db.commit()
        self.addCleanup(self.db.close)

    def _seed_plan(self, expected_output: str) -> tuple[Project, ProjectPlan]:
        project = Project(
            id=20,
            name="Demo",
            collaboration_dir="outputs/proj-20",
            status="planning",
            created_by=self.user.id,
        )
        plan = ProjectPlan(
            id=30,
            project_id=20,
            plan_type="candidate",
            status="completed",
            plan_json=json.dumps({
                "tasks": [
                    {
                        "task_code": "TASK-001",
                        "task_name": "修复",
                        "expected_output": expected_output,
                    }
                ]
            }, ensure_ascii=False),
        )
        self.db.add_all([project, plan])
        self.db.commit()
        return project, plan

    def test_finalize_plan_rejects_action_phrase_expected_output(self):
        _project, plan = self._seed_plan("代码变更提交")
        with self.assertRaises(HTTPException) as ctx:
            finalize_plan(20, FinalizeRequest(plan_id=plan.id), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("invalid expected_output", ctx.exception.detail)
        self.assertIn("action phrase", ctx.exception.detail)

    def test_finalize_plan_accepts_path_with_trailing_human_description(self):
        _project, plan = self._seed_plan("outputs/proj-20/result.json，请按以下格式写入")
        response = finalize_plan(20, FinalizeRequest(plan_id=plan.id), self.db, self.user)
        self.assertEqual(response["tasks_created"], 1)


if __name__ == "__main__":
    unittest.main()
