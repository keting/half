import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.path_service import extract_json_path, normalize_expected_output_path


class PathServiceTests(unittest.TestCase):
    def test_extract_json_path_ignores_trailing_human_description(self):
        value = "outputs/proj-4-f9a125/TASK-001/result.json，包含 task_code 与 base.json 路径"
        self.assertEqual(extract_json_path(value), "outputs/proj-4-f9a125/TASK-001/result.json")

    def test_normalize_expected_output_path_adds_collaboration_dir_once(self):
        normalized = normalize_expected_output_path(
            "outputs/TASK-001/result.json，包含 task_code",
            default_path="outputs/TASK-001/result.json",
            collaboration_dir="outputs/proj-4-f9a125",
        )
        self.assertEqual(normalized, "outputs/proj-4-f9a125/TASK-001/result.json")

    def test_normalize_expected_output_path_preserves_prefixed_path(self):
        normalized = normalize_expected_output_path(
            "outputs/proj-4-f9a125/TASK-001/result.json，包含 task_code",
            default_path="outputs/TASK-001/result.json",
            collaboration_dir="outputs/proj-4-f9a125",
        )
        self.assertEqual(normalized, "outputs/proj-4-f9a125/TASK-001/result.json")


if __name__ == "__main__":
    unittest.main()
