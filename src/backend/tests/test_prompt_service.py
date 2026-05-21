import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models import Agent, ProcessTemplate, Project, ProjectPlan, Task
from services.issue_review_loop import FLOW_TYPE
from services.prompt_service import generate_plan_prompt, generate_task_prompt, resolve_selected_agent_models
from services.prompt_settings import DEFAULT_PLAN_CO_LOCATION_GUIDANCE


class FakeEmptySession:
    def query(self, model):
        raise AssertionError("blank dependency test should not query predecessors")


class FakeTemplateSession:
    def __init__(self, plan=None, template=None):
        self.plan = plan
        self.template = template
        self.model = None

    def query(self, model):
        self.model = model
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is ProjectPlan:
            return self.plan
        if self.model is ProcessTemplate:
            return self.template
        return None


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

    def test_resolve_selected_agent_models_uses_planning_mode_hints(self):
        agent = Agent(
            id=7,
            name="Codex 双模型",
            slug="codex-dual",
            agent_type="codex",
            models_json='[{"model_name":"gpt-5-codex","capability":"复杂规划、高质量"},{"model_name":"codex-mini-latest","capability":"轻量、低成本、响应快"}]',
        )
        cost_resolved = resolve_selected_agent_models("实现普通页面", [agent], {}, "cost_effective")
        speed_resolved = resolve_selected_agent_models("实现普通页面", [agent], {}, "speed")
        quality_resolved = resolve_selected_agent_models("实现普通页面", [agent], {}, "quality")

        self.assertEqual(cost_resolved[7], "codex-mini-latest")
        self.assertEqual(speed_resolved[7], "codex-mini-latest")
        self.assertEqual(quality_resolved[7], "gpt-5-codex")

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
        self.assertIn(DEFAULT_PLAN_CO_LOCATION_GUIDANCE, prompt)
        self.assertLess(prompt.index("请根据参与 Agent"), prompt.index("## 同服务器分配规则"))
        self.assertLess(prompt.index("## 同服务器分配规则"), prompt.index("## 输出要求"))

    def test_generate_plan_prompt_includes_planning_mode_guidance(self):
        agent = Agent(
            id=2,
            name="Codex 执行器",
            slug="codex-main",
            agent_type="codex",
            model_name="gpt-5-codex",
        )
        cases = [
            ("balanced", "当前模式：均衡模式", "避免不必要的重复任务和评审链路"),
            ("quality", "当前模式：效果优先", "不要让单个 task 同时绑定多个 assignee"),
            ("cost_effective", "当前模式：性价比高", "用户手动指定的模型优先级最高"),
            ("speed", "当前模式：速度优先", "最大化可并行执行的 task 数量"),
        ]
        for mode, heading, expected in cases:
            with self.subTest(mode=mode):
                project = Project(name="Demo", goal="需要规划", planning_mode=mode)
                prompt, _ = generate_plan_prompt(project, [agent], "plan-1.json", None, {})
                self.assertIn(heading, prompt)
                self.assertIn(expected, prompt)
                self.assertLess(prompt.index("## 规划模式策略"), prompt.index("## 同服务器分配规则"))

    def test_generate_plan_prompt_uses_project_co_location_override(self):
        project = Project(
            name="Demo",
            goal="需要部署和复现线上问题",
            agent_ids_json='[{"id":2,"co_located":false}]',
        )
        agent = Agent(
            id=2,
            name="Codex 执行器",
            slug="codex-main",
            agent_type="codex",
            model_name="gpt-5-codex",
            models_json='[{"model_name":"gpt-5-codex","capability":"部署、日志查看、运行时复现"}]',
            co_located=True,
        )
        prompt, _ = generate_plan_prompt(project, [agent], "plan-1.json", None, {})
        self.assertIn("同服务器：否", prompt)

    def test_generate_plan_prompt_accepts_custom_co_location_guidance(self):
        project = Project(name="Demo", goal="需要部署")
        agent = Agent(id=3, name="Agent", slug="agent", agent_type="codex")
        custom_guidance = "## 自定义同机规则\n只用于本次测试。"
        prompt, _ = generate_plan_prompt(project, [agent], "plan-1.json", None, {}, custom_guidance)
        self.assertIn(custom_guidance, prompt)
        self.assertNotIn("必须分配给同服务器 Agent 的任务", prompt)

    def test_generate_plan_prompt_falls_back_when_guidance_is_blank(self):
        project = Project(name="Demo", goal="需要部署")
        agent = Agent(id=3, name="Agent", slug="agent", agent_type="codex")
        prompt, _ = generate_plan_prompt(project, [agent], "plan-1.json", None, {}, "   ")
        self.assertIn(DEFAULT_PLAN_CO_LOCATION_GUIDANCE, prompt)

    def test_generate_plan_prompt_distinguishes_project_and_collaboration_repos(self):
        project = Project(
            name="Demo",
            goal="需要规划",
            git_repo_url="https://github.com/org/collaboration",
            project_repo_url="https://github.com/org/code",
            collaboration_dir="outputs/proj-1",
        )
        agent = Agent(id=3, name="Agent", slug="agent", agent_type="codex")

        prompt, _ = generate_plan_prompt(project, [agent], "outputs/proj-1/plan-1.json", None, {})

        self.assertIn("项目代码仓库地址：https://github.com/org/code", prompt)
        self.assertIn("HALF 协作仓库地址：https://github.com/org/collaboration", prompt)
        self.assertIn("HALF 只轮询该协作仓库", prompt)
        self.assertIn("将计划写入 HALF 协作仓库中的 outputs/proj-1/plan-1.json 文件", prompt)

    def test_generate_task_prompt_uses_fixed_task_directories(self):
        project = Project(
            id=4,
            name="Demo",
            git_repo_url="https://github.com/org/collaboration",
            project_repo_url="https://github.com/org/code",
            collaboration_dir="outputs/proj-4-f9a125",
        )
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
        self.assertIn("outputs/proj-4-f9a125/TASK-001/", prompt)
        self.assertIn("outputs/proj-4-f9a125/TASK-002/", prompt)
        self.assertIn("项目代码仓库地址：https://github.com/org/code", prompt)
        self.assertIn("HALF 协作仓库地址：https://github.com/org/collaboration", prompt)
        self.assertIn("HALF 只轮询该协作仓库", prompt)
        self.assertIn("result.json.tmp", prompt)
        self.assertIn("原子重命名为 `result.json`", prompt)
        self.assertIn("task_code`、`summary`、`artifacts`", prompt)
        self.assertIn("仓库根相对路径字符串数组", prompt)
        self.assertIn("只有项目代码仓库的代码修改已经提交并 push 成功后，才允许生成 `result.json`", prompt)
        self.assertIn("no_code_changes: true", prompt)

    def test_generate_task_prompt_includes_project_goal_section(self):
        project = Project(
            id=4,
            name="Demo",
            goal="  修复模板路径，让任务介绍进入执行 Prompt。\n验收：模板 apply 后任务能读到项目背景。  ",
            collaboration_dir="outputs/proj-4-f9a125",
        )
        task = Task(
            project_id=4,
            task_code="TASK-001",
            task_name="实现修复",
            description="修改模板路径",
            depends_on_json="[]",
        )

        prompt = generate_task_prompt(FakeEmptySession(), project, task)

        self.assertIn("## 项目任务介绍\n修复模板路径，让任务介绍进入执行 Prompt。\n验收：模板 apply 后任务能读到项目背景。", prompt)
        self.assertLess(prompt.index("你是项目 [Demo] 的执行 Agent。"), prompt.index("## 项目任务介绍"))
        self.assertLess(prompt.index("## 项目任务介绍"), prompt.index("## 执行前置步骤"))

    def test_generate_task_prompt_omits_blank_project_goal_section(self):
        task = Task(
            project_id=4,
            task_code="TASK-001",
            task_name="实现修复",
            description="修改模板路径",
            depends_on_json="[]",
        )

        for goal in (None, "", "   \n  "):
            with self.subTest(goal=goal):
                project = Project(id=4, name="Demo", goal=goal, collaboration_dir="outputs/proj-4-f9a125")
                prompt = generate_task_prompt(FakeEmptySession(), project, task)

                self.assertNotIn("## 项目任务介绍", prompt)
                self.assertIn("你是项目 [Demo] 的执行 Agent。\n\n## 仓库约定", prompt)
                self.assertIn("## 仓库约定", prompt)
                self.assertIn("## 执行前置步骤", prompt)
                self.assertLess(prompt.index("## 仓库约定"), prompt.index("## 执行前置步骤"))
                self.assertNotIn("\n\n\n## 执行前置步骤", prompt)

    def test_generate_task_prompt_includes_template_inputs_for_template_plan(self):
        project = Project(
            id=4,
            name="Demo",
            goal="执行系统测试",
            collaboration_dir="outputs/proj-4-f9a125",
            template_inputs_json='{"login_password":" secret ","extra":"ignore","test_url":"https://example.test"}',
        )
        task = Task(
            project_id=4,
            plan_id=21,
            task_code="TASK-001",
            task_name="执行测试",
            description="访问系统并输出报告",
            depends_on_json="[]",
        )
        plan = ProjectPlan(id=21, source_path="template:7")
        template = ProcessTemplate(
            id=7,
            required_inputs_json=(
                '[{"key":"test_url","label":"测试系统 URL","required":true,"sensitive":false},'
                '{"key":"login_password","label":"登录密码","required":true,"sensitive":true},'
                '{"key":"report_path","label":"报告输出路径","required":false,"sensitive":false}]'
            ),
        )

        prompt = generate_task_prompt(FakeTemplateSession(plan, template), project, task)

        self.assertIn("## 模版所需信息\n- 测试系统 URL: https://example.test\n- 登录密码: secret", prompt)
        self.assertNotIn("extra", prompt)
        self.assertNotIn("报告输出路径", prompt)
        self.assertLess(prompt.index("## 项目任务介绍"), prompt.index("## 模版所需信息"))
        self.assertLess(prompt.index("## 模版所需信息"), prompt.index("## 执行前置步骤"))

    def test_generate_task_prompt_omits_template_inputs_without_template_source(self):
        project = Project(
            id=4,
            name="Demo",
            collaboration_dir="outputs/proj-4-f9a125",
            template_inputs_json='{"test_url":"https://example.test"}',
        )
        task = Task(
            project_id=4,
            plan_id=21,
            task_code="TASK-001",
            task_name="执行测试",
            description="访问系统并输出报告",
            depends_on_json="[]",
        )
        for source_path in (None, "", "prompt:21", "template:not-a-number"):
            with self.subTest(source_path=source_path):
                plan = ProjectPlan(id=21, source_path=source_path)
                template = ProcessTemplate(
                    id=7,
                    required_inputs_json='[{"key":"test_url","label":"测试系统 URL","required":true,"sensitive":false}]',
                )
                prompt = generate_task_prompt(FakeTemplateSession(plan, template), project, task)
                self.assertNotIn("## 模版所需信息", prompt)

    def test_issue_review_task_001_prompt_uses_backend_flow_state_contract(self):
        project = Project(id=4, name="Loop", collaboration_dir="outputs/proj-4", template_inputs_json='{"max_review_rounds":"5"}')
        task = Task(
            project_id=4,
            plan_id=21,
            task_code="TASK-001",
            task_name="初始化",
            description="初始化评审循环",
            depends_on_json="[]",
        )
        plan = ProjectPlan(id=21, plan_json=f'{{"flow_type":"{FLOW_TYPE}"}}')

        prompt = generate_task_prompt(FakeTemplateSession(plan), project, task)

        self.assertIn('"flow_type": "issue_code_review_loop"', prompt)
        self.assertIn('"schema_version": 1', prompt)
        self.assertIn('"round_id": "round-001"', prompt)
        self.assertIn('"phase": "coding"', prompt)
        self.assertIn('"task_states": {', prompt)
        self.assertIn('"TASK-001": "completed"', prompt)
        self.assertIn('"TASK-002": "unlocked"', prompt)
        self.assertIn('"TASK-005": "frozen"', prompt)
        self.assertIn("不要写旧格式 `tasks.*.status`", prompt)
        self.assertIn("`max_review_rounds` 的数字值", prompt)

    def test_issue_review_task_002_prompt_updates_top_level_task_states(self):
        project = Project(id=4, name="Loop", collaboration_dir="outputs/proj-4")
        task = Task(
            project_id=4,
            plan_id=21,
            task_code="TASK-002",
            task_name="编码",
            description="编码并推送",
            depends_on_json="[]",
        )
        plan = ProjectPlan(id=21, plan_json=f'{{"flow_type":"{FLOW_TYPE}"}}')

        prompt = generate_task_prompt(FakeTemplateSession(plan), project, task)

        self.assertIn("协作分支固定为 `main`", prompt)
        self.assertIn("项目代码分支与协作分支必须分开处理", prompt)
        self.assertIn("即使两个仓库地址相同，也不能把协作产物提交到项目工作分支", prompt)
        self.assertIn("固定以项目仓库 `main` 分支作为基准分支", prompt)
        self.assertIn("工作分支名由你根据 issue 编号和时间自动生成", prompt)
        self.assertIn("把项目代码 commit 并 push 到项目仓库工作分支", prompt)
        self.assertIn("切换到 HALF 协作仓库 `main` 分支", prompt)
        self.assertIn("push 到 HALF 协作仓库 `origin/main`", prompt)
        self.assertIn("不得把 `outputs/proj-4/flow-state.json` 或 `TASK-002/rounds/` 只提交到项目工作分支", prompt)
        self.assertIn("`base_branch` 必须为 `main`", prompt)
        self.assertNotIn("`base_branch` 创建或更新工作分支", prompt)
        self.assertNotIn("`work_branch_name`", prompt)
        self.assertIn("更新 `outputs/proj-4/flow-state.json` 顶层字段", prompt)
        self.assertIn("在顶层 `task_states` 中将 `TASK-002` 置为 `waiting_review`", prompt)
        self.assertIn("`TASK-003` / `TASK-004` 置为 `unlocked`", prompt)
        self.assertIn("`phase` 置为 `awaiting_review`", prompt)

    def test_issue_review_task_003_prompt_pushes_review_to_collaboration_main(self):
        project = Project(id=4, name="Loop", collaboration_dir="outputs/proj-4")
        task = Task(
            project_id=4,
            plan_id=21,
            task_code="TASK-003",
            task_name="评审 A",
            description="评审",
            depends_on_json="[]",
        )
        plan = ProjectPlan(id=21, plan_json=f'{{"flow_type":"{FLOW_TYPE}"}}')

        prompt = generate_task_prompt(FakeTemplateSession(plan), project, task)

        self.assertIn("只在 HALF 协作仓库 `main` 分支写入 `TASK-003/reviews/round-XXX/review.json`", prompt)
        self.assertIn("push 到 `origin/main`", prompt)
        self.assertIn("评审 Agent 不得修改 `outputs/proj-4/flow-state.json`", prompt)

    def test_issue_review_task_005_prompt_updates_top_level_task_states(self):
        project = Project(id=4, name="Loop", collaboration_dir="outputs/proj-4")
        task = Task(
            project_id=4,
            plan_id=21,
            task_code="TASK-005",
            task_name="决策",
            description="评审决策",
            depends_on_json="[]",
        )
        plan = ProjectPlan(id=21, plan_json=f'{{"flow_type":"{FLOW_TYPE}"}}')

        prompt = generate_task_prompt(FakeTemplateSession(plan), project, task)

        self.assertIn("HALF 派发本任务代表后端已根据 review 文件派生 `TASK-005 = unlocked`", prompt)
        self.assertIn("原始 `flow-state.json.task_states.TASK-005` 可能仍是 `frozen`，不要因此停止", prompt)
        self.assertIn("两份 review 都必须包含布尔 `approve_merge`", prompt)
        self.assertIn("`round`、`round_id`、`work_branch`、`head_commit` 必须与当前 `outputs/proj-4/flow-state.json` 一致", prompt)
        self.assertIn("更新 `outputs/proj-4/flow-state.json` 顶层 `task_states`", prompt)
        self.assertIn("`TASK-002` 为 `needs_fix`", prompt)
        self.assertIn("必须写入本轮 `decision.json` / `decision.md` 人工处理报告", prompt)
        self.assertIn("HALF 后端会据此将 `TASK-005` 派生为已完成并提示人工介入", prompt)
        self.assertIn("在顶层 `task_states` 把 `TASK-002` 标记为 `approved`", prompt)
        self.assertIn("以 `main` 作为目标分支提交 PR", prompt)
        self.assertIn("将决策、PR 记录、`flow-state.json` 和最终 `result.json` commit 并 push 到 HALF 协作仓库 `origin/main`", prompt)


if __name__ == "__main__":
    unittest.main()
