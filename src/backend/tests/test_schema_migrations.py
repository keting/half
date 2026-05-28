import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main


class SchemaMigrationTests(unittest.TestCase):
    def test_task_code_unique_migration_preserves_dispatch_mode_column(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY
                )
            """))
            conn.execute(text("""
                CREATE TABLE project_plans (
                    id INTEGER PRIMARY KEY
                )
            """))
            conn.execute(text("""
                CREATE TABLE agents (
                    id INTEGER PRIMARY KEY
                )
            """))
            conn.execute(text("""
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    plan_id INTEGER NOT NULL REFERENCES project_plans(id),
                    task_code TEXT NOT NULL,
                    task_name TEXT NOT NULL,
                    description TEXT,
                    assignee_agent_id INTEGER REFERENCES agents(id),
                    model_name TEXT,
                    status TEXT DEFAULT 'pending',
                    depends_on_json TEXT DEFAULT '[]',
                    expected_output_path TEXT,
                    result_file_path TEXT,
                    usage_file_path TEXT,
                    last_error TEXT,
                    timeout_minutes INTEGER DEFAULT 10,
                    dispatch_mode TEXT,
                    dispatched_at DATETIME,
                    completed_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE(task_code)
                )
            """))
            conn.execute(text("INSERT INTO projects (id) VALUES (1)"))
            conn.execute(text("INSERT INTO project_plans (id) VALUES (1)"))
            conn.execute(text("""
                INSERT INTO tasks (
                    id,
                    project_id,
                    plan_id,
                    task_code,
                    task_name,
                    model_name,
                    dispatch_mode
                )
                VALUES (1, 1, 1, 'T1', 'Task 1', 'claude-opus', 'auto')
            """))

        with patch.object(main, "engine", engine):
            main.migrate_task_code_unique_constraint()

        columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
        self.assertIn("model_name", columns)
        self.assertIn("dispatch_mode", columns)
        with engine.connect() as conn:
            model_name, dispatch_mode = conn.execute(
                text("SELECT model_name, dispatch_mode FROM tasks WHERE id = 1")
            ).one()
        self.assertEqual(model_name, "claude-opus")
        self.assertEqual(dispatch_mode, "auto")


if __name__ == "__main__":
    unittest.main()
