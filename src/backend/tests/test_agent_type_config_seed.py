import json
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
from models import Agent, AgentTypeConfig, AgentTypeModelMap, Base, ModelDefinition
from services.demo_seed import LEGACY_DEMO_MODEL_CAPABILITIES


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
                {
                    "Fable 5",
                    "Opus 5 (1M)",
                    "Sonnet 5",
                    "gpt-5.6-sol",
                    "gpt-5.6-terra",
                    "gpt-5.6-luna",
                    "Gemini 3.6 Flash",
                },
            )
            self.assertTrue(models_by_name["gpt-5.6-sol"].capability)

            self.assertEqual(db.query(AgentTypeModelMap).count(), 9)
        finally:
            db.close()

    def test_seed_preserves_modified_demo_agent_selection(self):
        db = self.SessionLocal()
        try:
            db.add(AgentTypeConfig(name="chatgpt-pro"))
            db.add(Agent(
                name="My Codex",
                slug="codex-pro",
                agent_type="chatgpt-pro",
                model_name="custom-model",
                models_json=json.dumps([
                    {"model_name": "custom-model", "capability": "User choice"},
                ]),
            ))
            db.commit()
        finally:
            db.close()

        with patch("main.SessionLocal", self.SessionLocal):
            seed_agent_type_configs()

        db = self.SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.slug == "codex-pro").one()
            self.assertEqual(agent.model_name, "custom-model")
            self.assertEqual(
                [item["model_name"] for item in json.loads(agent.models_json)],
                ["custom-model"],
            )
        finally:
            db.close()

    def test_seed_preserves_modified_legacy_demo_capabilities(self):
        db = self.SessionLocal()
        try:
            db.add(AgentTypeConfig(name="chatgpt-pro"))
            db.add(Agent(
                name="Codex Pro",
                slug="codex-pro",
                agent_type="chatgpt-pro",
                model_name="gpt-5.5",
                models_json=json.dumps([
                    {"model_name": "gpt-5.5", "capability": "User-edited capability"},
                    {
                        "model_name": "gpt-5.4",
                        "capability": LEGACY_DEMO_MODEL_CAPABILITIES["gpt-5.4"],
                    },
                ]),
                capability="User-edited capability",
            ))
            db.commit()
        finally:
            db.close()

        with patch("main.SessionLocal", self.SessionLocal):
            seed_agent_type_configs()

        db = self.SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.slug == "codex-pro").one()
            self.assertEqual(agent.model_name, "gpt-5.5")
            self.assertEqual(
                json.loads(agent.models_json)[0]["capability"],
                "User-edited capability",
            )
        finally:
            db.close()

    def test_seed_refreshes_legacy_defaults_without_removing_old_models(self):
        db = self.SessionLocal()
        try:
            agent_type = AgentTypeConfig(name="chatgpt-pro", description="User description")
            db.add(agent_type)
            db.flush()
            for index, model_name in enumerate(["gpt-5.5", "gpt-5.4"]):
                model = ModelDefinition(
                    name=model_name,
                    capability=LEGACY_DEMO_MODEL_CAPABILITIES[model_name],
                )
                db.add(model)
                db.flush()
                db.add(AgentTypeModelMap(
                    agent_type_id=agent_type.id,
                    model_definition_id=model.id,
                    display_order=index,
                ))
            db.add(Agent(
                name="Codex Pro",
                slug="codex-pro",
                agent_type="chatgpt-pro",
                model_name="gpt-5.5",
                models_json=json.dumps([
                    {
                        "model_name": "gpt-5.5",
                        "capability": LEGACY_DEMO_MODEL_CAPABILITIES["gpt-5.5"],
                    },
                    {
                        "model_name": "gpt-5.4",
                        "capability": LEGACY_DEMO_MODEL_CAPABILITIES["gpt-5.4"],
                    },
                ]),
                capability="；".join([
                    LEGACY_DEMO_MODEL_CAPABILITIES["gpt-5.5"],
                    LEGACY_DEMO_MODEL_CAPABILITIES["gpt-5.4"],
                ]),
            ))
            db.commit()
        finally:
            db.close()

        with patch("main.SessionLocal", self.SessionLocal):
            seed_agent_type_configs()

        db = self.SessionLocal()
        try:
            type_names = {agent_type.name for agent_type in db.query(AgentTypeConfig).all()}
            self.assertEqual(type_names, {"chatgpt-pro"})

            agent_type = db.query(AgentTypeConfig).filter(AgentTypeConfig.name == "chatgpt-pro").one()
            mappings = db.query(AgentTypeModelMap).filter(
                AgentTypeModelMap.agent_type_id == agent_type.id
            ).order_by(AgentTypeModelMap.display_order, AgentTypeModelMap.id).all()
            model_names_by_id = {model.id: model.name for model in db.query(ModelDefinition).all()}
            self.assertEqual(
                [model_names_by_id[mapping.model_definition_id] for mapping in mappings],
                ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4"],
            )

            agent = db.query(Agent).filter(Agent.slug == "codex-pro").one()
            self.assertEqual(agent.model_name, "gpt-5.6-sol")
            self.assertEqual(
                [item["model_name"] for item in json.loads(agent.models_json)],
                ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
            )
            self.assertEqual(agent_type.description, "User description")
            self.assertIn("gpt-5.5", model_names_by_id.values())
            self.assertIn("gpt-5.4", model_names_by_id.values())
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
