import json
import unittest
from pathlib import Path

from routers.process_templates import validate_template_json


TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"


class ProcessTemplateExamplesTestCase(unittest.TestCase):
    def test_all_example_templates_match_current_schema(self):
        template_paths = sorted(TEMPLATES_DIR.glob("*.json"))
        self.assertTrue(template_paths, "templates/ must contain at least one JSON example")

        for template_path in template_paths:
            with self.subTest(template=template_path.name):
                data = json.loads(template_path.read_text(encoding="utf-8"))
                normalized_json, slots, normalized_data = validate_template_json(data)

                self.assertEqual(json.loads(normalized_json), normalized_data)
                self.assertTrue(slots)
