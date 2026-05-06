import json
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main
from models import Agent, Base, Project, ProjectPlan, Task, User


class StartupTaskAssigneeRepairTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.original_session_local = main.SessionLocal
        main.SessionLocal = self.SessionLocal

    def tearDown(self):
        main.SessionLocal = self.original_session_local

    def test_repairs_unassigned_task_from_plan_json_assignee(self):
        with self.SessionLocal() as db:
            owner = User(username="owner", password_hash="x", role="user", status="active")
            db.add(owner)
            db.flush()
            agent = Agent(name="Planner", slug="planner", agent_type="codex", created_by=owner.id)
            db.add(agent)
            db.flush()
            project = Project(
                name="demo",
                goal="x",
                git_repo_url="https://github.com/keting/half",
                created_by=owner.id,
                agent_ids_json=json.dumps([agent.id]),
            )
            db.add(project)
            db.flush()
            plan = ProjectPlan(
                project_id=project.id,
                plan_type="final",
                status="final",
                plan_json=json.dumps({"tasks": [{"task_code": "T1", "assignee": "planner"}]}),
            )
            db.add(plan)
            db.flush()
            task = Task(
                project_id=project.id,
                plan_id=plan.id,
                task_code="T1",
                task_name="Task 1",
                assignee_agent_id=None,
            )
            db.add(task)
            db.commit()
            task_id = task.id
            agent_id = agent.id

        main.repair_unassigned_tasks_from_plan_json()

        with self.SessionLocal() as db:
            repaired_task = db.query(Task).filter(Task.id == task_id).one()
            self.assertEqual(repaired_task.assignee_agent_id, agent_id)


if __name__ == "__main__":
    unittest.main()
