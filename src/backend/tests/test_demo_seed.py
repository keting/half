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

from auth import hash_password
from models import Agent, AgentTypeConfig, AgentTypeModelMap, Base, ModelDefinition, ProcessTemplate, Project, ProjectPlan, Task, TaskEvent, User
from services.demo_seed import DEMO_PROJECT_NAME, DEMO_TEMPLATE_NAME, seed_demo_project


class DemoSeedTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = self.SessionLocal()
        self.admin = User(username="admin", password_hash=hash_password("Admin123"), role="admin", status="active")
        self.db.add(self.admin)
        self.db.commit()
        self.db.refresh(self.admin)
        self.addCleanup(self.db.close)

    def test_seed_creates_browsable_demo_project(self):
        created = seed_demo_project(self.db, self.admin)

        self.assertTrue(created)
        project = self.db.query(Project).filter(Project.name == DEMO_PROJECT_NAME).one()
        self.assertEqual(project.git_repo_url, "https://github.com/keting/half.git")
        self.assertEqual(project.collaboration_dir, "demo/half-demo-collaboration")
        self.assertEqual(project.status, "executing")

        template = self.db.query(ProcessTemplate).filter(ProcessTemplate.name == DEMO_TEMPLATE_NAME).one()
        self.assertEqual(template.agent_count, 3)

        plan = self.db.query(ProjectPlan).filter(ProjectPlan.project_id == project.id).one()
        self.assertEqual(plan.status, "final")
        self.assertTrue(plan.is_selected)
        self.assertEqual(plan.source_path, f"template:{template.id}")
        plan_data = json.loads(plan.plan_json)
        self.assertEqual(len(plan_data["tasks"]), 5)
        self.assertEqual(plan_data["tasks"][0]["assignee"], "codex-pro")

        tasks = {
            task.task_code: task
            for task in self.db.query(Task).filter(Task.project_id == project.id).all()
        }
        self.assertEqual(set(tasks), {"T1_DEV", "T2_TEST", "T3_REVIEW", "T4_EVAL", "T5_SYNC"})
        self.assertEqual(tasks["T1_DEV"].status, "completed")
        self.assertEqual(tasks["T1_DEV"].result_file_path, "demo/half-demo-collaboration/outputs/T1_DEV/result.json")
        self.assertEqual(json.loads(tasks["T2_TEST"].depends_on_json), ["T1_DEV"])
        self.assertEqual(json.loads(tasks["T3_REVIEW"].depends_on_json), ["T1_DEV"])
        self.assertEqual(json.loads(tasks["T4_EVAL"].depends_on_json), ["T2_TEST", "T3_REVIEW"])
        self.assertEqual(json.loads(tasks["T5_SYNC"].depends_on_json), ["T4_EVAL"])

        completed_event = (
            self.db.query(TaskEvent)
            .filter(TaskEvent.task_id == tasks["T1_DEV"].id, TaskEvent.event_type == "completed")
            .one()
        )
        self.assertIn("Demo task completed", completed_event.detail)

        agents = {agent.slug: agent for agent in self.db.query(Agent).all()}
        self.assertEqual(set(agents), {"claude-max", "codex-pro", "copilot-pro"})
        self.assertEqual(agents["codex-pro"].model_name, "gpt-5.5")

        agent_types = {
            agent_type.name: agent_type
            for agent_type in self.db.query(AgentTypeConfig)
            .filter(AgentTypeConfig.name.in_(["claude-max", "chatgpt-pro", "copilot-pro"]))
            .all()
        }
        self.assertEqual(set(agent_types), {"claude-max", "chatgpt-pro", "copilot-pro"})
        models_by_id = {model.id: model.name for model in self.db.query(ModelDefinition).all()}

        def type_models(type_name: str) -> list[str]:
            maps = self.db.query(AgentTypeModelMap).filter(
                AgentTypeModelMap.agent_type_id == agent_types[type_name].id,
            ).order_by(AgentTypeModelMap.display_order, AgentTypeModelMap.id).all()
            return [models_by_id[mapping.model_definition_id] for mapping in maps]

        self.assertEqual(type_models("claude-max"), ["Opus 4.7", "Sonnet 4.6"])
        self.assertEqual(type_models("chatgpt-pro"), ["gpt-5.5", "gpt-5.4"])
        self.assertEqual(type_models("copilot-pro"), ["Opus 4.6", "gpt-5.4", "Sonnet 4.6", "Opus 4.7"])

    def test_seed_prunes_unused_legacy_default_agent_types_from_demo_catalog(self):
        self.db.add_all([
            AgentTypeConfig(name="claude"),
            AgentTypeConfig(name="codex"),
            AgentTypeConfig(name="cursor"),
            AgentTypeConfig(name="windsurf"),
            AgentTypeConfig(name="custom-reviewer"),
        ])
        self.db.commit()

        seed_demo_project(self.db, self.admin)

        type_names = {agent_type.name for agent_type in self.db.query(AgentTypeConfig).all()}
        self.assertNotIn("claude", type_names)
        self.assertNotIn("codex", type_names)
        self.assertNotIn("cursor", type_names)
        self.assertNotIn("windsurf", type_names)
        self.assertIn("custom-reviewer", type_names)
        self.assertIn("claude-max", type_names)
        self.assertIn("chatgpt-pro", type_names)
        self.assertIn("copilot-pro", type_names)

    def test_seed_keeps_legacy_default_agent_type_if_existing_agent_uses_it(self):
        self.db.add(AgentTypeConfig(name="claude"))
        self.db.add(Agent(
            name="Existing Claude",
            slug="existing-claude",
            agent_type="claude",
            created_by=self.admin.id,
        ))
        self.db.commit()

        seed_demo_project(self.db, self.admin)

        type_names = {agent_type.name for agent_type in self.db.query(AgentTypeConfig).all()}
        self.assertIn("claude", type_names)
        self.assertIn("claude-max", type_names)

    def test_seed_is_idempotent(self):
        self.assertTrue(seed_demo_project(self.db, self.admin))
        self.assertFalse(seed_demo_project(self.db, self.admin))

        self.assertEqual(self.db.query(Project).filter(Project.name == DEMO_PROJECT_NAME).count(), 1)
        project = self.db.query(Project).filter(Project.name == DEMO_PROJECT_NAME).one()
        self.assertEqual(self.db.query(ProjectPlan).filter(ProjectPlan.project_id == project.id).count(), 1)
        self.assertEqual(self.db.query(Task).filter(Task.project_id == project.id).count(), 5)
        self.assertEqual(self.db.query(Agent).count(), 3)


if __name__ == "__main__":
    unittest.main()
