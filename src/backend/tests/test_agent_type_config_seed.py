import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import seed_agent_type_configs
from models import AgentTypeConfig, AgentTypeModelMap, Base, ModelDefinition


class AgentTypeConfigSeedTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)

    def test_seed_uses_current_demo_agent_catalog(self):
        with patch("main.SessionLocal", self.SessionLocal):
            seed_agent_type_configs()

        db = self.SessionLocal()
        try:
            type_names = {
                agent_type.name
                for agent_type in db.query(AgentTypeConfig).order_by(AgentTypeConfig.display_order).all()
            }
            self.assertEqual(type_names, {"claude-max", "chatgpt-pro", "copilot-pro"})
            self.assertNotIn("claude", type_names)
            self.assertNotIn("codex", type_names)
            self.assertNotIn("cursor", type_names)
            self.assertNotIn("windsurf", type_names)

            models_by_name = {model.name: model for model in db.query(ModelDefinition).all()}
            self.assertEqual(
                set(models_by_name),
                {"Opus 4.7", "Sonnet 4.6", "gpt-5.5", "gpt-5.4", "Opus 4.6"},
            )
            self.assertTrue(models_by_name["gpt-5.5"].capability)

            self.assertEqual(db.query(AgentTypeModelMap).count(), 8)
        finally:
            db.close()

    def test_seed_keeps_existing_catalog_untouched(self):
        db = self.SessionLocal()
        try:
            db.add(AgentTypeConfig(name="custom-agent"))
            db.commit()
        finally:
            db.close()

        with patch("main.SessionLocal", self.SessionLocal):
            seed_agent_type_configs()

        db = self.SessionLocal()
        try:
            type_names = {agent_type.name for agent_type in db.query(AgentTypeConfig).all()}
            self.assertEqual(type_names, {"custom-agent"})
            self.assertEqual(db.query(ModelDefinition).count(), 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
