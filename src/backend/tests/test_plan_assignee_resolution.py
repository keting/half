import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routers.plans import _resolve_assignee_agent_id


class PlanAssigneeResolutionTests(unittest.TestCase):
    def setUp(self):
        self.agents = [
            SimpleNamespace(id=1, slug="codex-plus", name="Codex Plus", agent_type="chatgpt-plus"),
            SimpleNamespace(id=2, slug="claude-max", name="Claude Max", agent_type="claude-max"),
        ]
        self.db = MagicMock()
        self.db.query.return_value.filter.return_value.all.return_value = self.agents

    def test_resolves_assignee_by_slug(self):
        self.assertEqual(_resolve_assignee_agent_id(self.db, "codex-plus", owner_user_id=1), 1)

    def test_resolves_assignee_by_display_name(self):
        self.assertEqual(_resolve_assignee_agent_id(self.db, "Claude Max", owner_user_id=1), 2)

    def test_resolves_assignee_by_agent_type(self):
        self.assertEqual(_resolve_assignee_agent_id(self.db, "chatgpt-plus", owner_user_id=1), 1)

    def test_returns_none_when_unmatched(self):
        self.assertIsNone(_resolve_assignee_agent_id(self.db, "unknown-agent", owner_user_id=1))


if __name__ == "__main__":
    unittest.main()
