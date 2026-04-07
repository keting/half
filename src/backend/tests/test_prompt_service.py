import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models import Agent, Project, Task
from services.prompt_service import generate_plan_prompt, generate_task_prompt, resolve_selected_agent_models


class PromptServiceTests(unittest.TestCase):
    def test_resolve_selected_agent_models_prefers_explicit_model(self):
        agent = Agent(
            id=1,
            name="Claude 主力",
            slug="claude-main",
            agent_type="claude",
            model_name="claude-opus-4-1",
            models_json='[{"model_name":"claude-opus-4-1","capability":"复杂规划"},{"model_name":"claude-sonnet-4-5","capability":"代码实现"}]',
        )
        resolved = resolve_selected_agent_models("做复杂规划", [agent], {1: "claude-sonnet-4-5"})
        self.assertEqual(resolved[1], "claude-sonnet-4-5")

    def test_generate_plan_prompt_auto_selects_best_matching_model(self):
        project = Project(name="Demo", goal="需要代码实现和任务拆解")
        agent = Agent(
            id=2,
            name="Codex 执行器",
            slug="codex-main",
            agent_type="codex",
            model_name="gpt-5-codex",
            models_json='[{"model_name":"gpt-5-codex","capability":"代码实现、任务拆解"},{"model_name":"codex-mini-latest","capability":"轻量总结"}]',
        )
        prompt, resolved = generate_plan_prompt(project, [agent], "plan-1.json", None, {})
        self.assertEqual(resolved[2], "gpt-5-codex")
        self.assertIn("使用模型：gpt-5-codex", prompt)

    def test_generate_task_prompt_normalizes_output_paths(self):
        project = Project(id=4, name="Demo", collaboration_dir="outputs/proj-4-f9a125")
        task = Task(
            project_id=4,
            task_code="TASK-002",
            task_name="处理数据",
            description="处理 TASK-001 输出",
            depends_on_json='["TASK-001"]',
            expected_output_path="outputs/proj-4-f9a125/TASK-002/result.json，包含 task_code 与处理摘要",
        )
        predecessor = Task(
            project_id=4,
            task_code="TASK-001",
            task_name="生成基础数据",
            expected_output_path="outputs/proj-4-f9a125/TASK-001/result.json，包含 task_code 与 base.json 路径",
        )

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def all(self):
                return [predecessor]

        class FakeSession:
            def query(self, model):
                self.model = model
                return FakeQuery()

        prompt = generate_task_prompt(FakeSession(), project, task)
        self.assertIn("outputs/proj-4-f9a125/TASK-001/result.json", prompt)
        self.assertIn("outputs/proj-4-f9a125/TASK-002/result.json", prompt)
        self.assertNotIn("包含 task_code", prompt)


if __name__ == "__main__":
    unittest.main()
