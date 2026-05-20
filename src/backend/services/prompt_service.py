import json
import re

from sqlalchemy.orm import Session

from models import Agent, ProcessTemplate, Project, ProjectPlan, Task
from services.issue_review_loop import FLOW_TYPE
from services.project_agents import parse_agent_assignments_json
from services.prompt_settings import normalize_plan_co_location_guidance

PLAN_MODE_GUIDANCE = {
    "balanced": """## 规划模式策略
当前模式：均衡模式。为每个 task 选择效果最好的 agent/模型，同时避免不必要的重复任务和评审链路。分配 task 时必须综合考虑 agent 的能力匹配度，让规划结果在效果、成本和速度之间保持稳健平衡。""",
    "quality": """## 规划模式策略
当前模式：效果优先。分配 task 时只考虑能力最强、效果最好的 agent/模型，不以成本和速度为主要约束。对关键任务可安排多个 agent 分别执行同一目标，但必须拆为多个并行候选 task，再增加评审、对比或合并 task 来优选最佳结果；不要让单个 task 同时绑定多个 assignee。对重要产出可安排独立 agent 进行评审。""",
    "cost_effective": """## 规划模式策略
当前模式：性价比高。用户手动指定的模型优先级最高；对未手动指定模型的 agent，在能力满足要求的前提下，优先选择成本较低或更节省用量的模型来执行 task；仅在任务复杂度高、风险高或能力匹配不足时使用更强模型。分配 task 时优先考虑性价比高的 agent/模型组合。""",
    "speed": """## 规划模式策略
当前模式：速度优先。在确保效果理想的前提下，尽量减少任务间的串行依赖，最大化可并行执行的 task 数量，缩短关键路径。避免引入非必要评审任务。分配 task 时优先选择响应更快、更适合快速完成的 agent/模型；关键路径上的任务尤其如此。""",
}


def get_plan_mode_guidance(planning_mode: str | None) -> str:
    return PLAN_MODE_GUIDANCE.get((planning_mode or "balanced").strip(), PLAN_MODE_GUIDANCE["balanced"])


def _project_repo_url(project: Project) -> str:
    return (getattr(project, "project_repo_url", None) or project.git_repo_url or "").strip()


def _collaboration_repo_url(project: Project) -> str:
    return (project.git_repo_url or "").strip()


def generate_plan_prompt(
    project: Project,
    selected_agents: list[Agent],
    plan_path: str,
    usage_path: str | None = None,  # kept for API compat, no longer used
    selected_agent_models: dict[int, str | None] | None = None,
    co_location_guidance: str | None = None,
) -> tuple[str, dict[int, str | None]]:
    resolved_models = resolve_selected_agent_models(
        project.goal or "",
        selected_agents,
        selected_agent_models or {},
        getattr(project, "planning_mode", None),
    )
    assignment_map = {
        int(item["id"]): bool(item["co_located"])
        for item in parse_agent_assignments_json(project.agent_ids_json)
    }
    selected_lines = "\n".join(
        _format_agent_line(agent, resolved_models.get(agent.id), assignment_map.get(agent.id, bool(agent.co_located)))
        for agent in selected_agents
    ) or "- 未指定参与 Agent"
    co_location_guidance_text = normalize_plan_co_location_guidance(co_location_guidance)
    plan_mode_guidance_text = get_plan_mode_guidance(getattr(project, "planning_mode", None))
    project_repo_url = _project_repo_url(project)
    collaboration_repo_url = _collaboration_repo_url(project)

    prompt = f"""你是项目 [{project.name}] 的执行 Agent。

## 任务目标
{project.goal}

## 协作约定
- 项目代码仓库地址：{project_repo_url or '未提供'}
- HALF 协作仓库地址：{collaboration_repo_url or '未提供'}
- 协作目录：{project.collaboration_dir or '仓库根目录'}
- 代码修改、构建验证和业务文件变更提交到项目代码仓库。
- `plan-*.json`、任务输出、`result.json`、`usage.json` 必须写入 HALF 协作仓库的协作目录；HALF 只轮询该协作仓库。

## 本次参与规划的 Agent
{selected_lines}

请根据参与 Agent 的数量、能力特点和分工边界来拆分子任务，尽量让每个子任务的 assignee 都来自上述列表。

{plan_mode_guidance_text}

{co_location_guidance_text}

## 输出要求
请输出结构化工作计划，格式为 JSON，包含以下字段：
- plan_name: 计划名称
- tasks: 任务列表，每个任务包含 task_code, task_name, description, assignee, depends_on, expected_output

将计划写入 HALF 协作仓库中的 {plan_path} 文件。
完成后在 HALF 协作仓库执行 git add、git commit、git push。"""

    return prompt, resolved_models


def _parse_agent_models(agent: Agent) -> list[dict[str, str | None]]:
    if agent.models_json:
        try:
            parsed = json.loads(agent.models_json)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            models = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                model_name = str(item.get("model_name") or "").strip()
                if not model_name:
                    continue
                capability = item.get("capability")
                models.append({
                    "model_name": model_name,
                    "capability": str(capability).strip() if capability else None,
                })
            if models:
                return models
    if agent.model_name:
        return [{"model_name": agent.model_name, "capability": agent.capability}]
    return []


def _tokenize_text(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[\s,，。；;、/\\()\[\]{}:+\-]+", value.lower())
    return [part for part in parts if len(part) >= 2]


def _score_model_fit(requirement_text: str, capability: str | None) -> int:
    if not capability:
        return 0
    requirement_lower = requirement_text.lower()
    score = 0
    for token in _tokenize_text(capability):
        if token in requirement_lower:
            score += max(2, len(token))
    return score


def resolve_selected_agent_models(
    requirement_text: str,
    selected_agents: list[Agent],
    preferred_models: dict[int, str | None],
    planning_mode: str | None = None,
) -> dict[int, str | None]:
    mode_requirement_hints = {
        "quality": " 效果最好 能力最强 复杂规划 深度分析 高质量",
        "cost_effective": " 性价比 低成本 成本较低 节省用量 轻量",
        "speed": " 速度快 快速 响应快 高并发",
    }
    effective_requirement_text = requirement_text + mode_requirement_hints.get((planning_mode or "balanced").strip(), "")
    resolved: dict[int, str | None] = {}
    for agent in selected_agents:
        models = _parse_agent_models(agent)
        if not models:
            resolved[agent.id] = None
            continue
        preferred_model = (preferred_models.get(agent.id) or "").strip()
        if preferred_model:
            matched = next((model for model in models if model["model_name"] == preferred_model), None)
            if matched:
                resolved[agent.id] = matched["model_name"]
                continue
        best_model = max(
            models,
            key=lambda model: (
                _score_model_fit(effective_requirement_text, model.get("capability")),
                1 if model.get("capability") else 0,
            ),
        )
        resolved[agent.id] = best_model["model_name"]
    return resolved


def _format_agent_line(agent: Agent, selected_model_name: str | None, co_located: bool = False) -> str:
    co_located_text = "同服务器：是" if co_located else "同服务器：否"
    models = _parse_agent_models(agent)
    chosen = next((model for model in models if model["model_name"] == selected_model_name), None)
    if chosen:
        capability_text = f"，能力：{chosen['capability']}" if chosen.get("capability") else ""
        return f"- {agent.name} ({agent.slug}, {agent.agent_type}, 使用模型：{chosen['model_name']}{capability_text}，{co_located_text})"
    if models:
        model_names = " / ".join(model["model_name"] for model in models)
        return f"- {agent.name} ({agent.slug}, {agent.agent_type}, 可用模型：{model_names}，{co_located_text})"
    return f"- {agent.name} ({agent.slug}, {agent.agent_type}, {co_located_text})"


def _parse_json_object(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_required_inputs(value: str | None) -> list[dict[str, object]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    normalized: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for item in parsed:
        if not isinstance(item, dict):
            return []
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        if not key or not label or key in seen_keys:
            return []
        if type(item.get("required")) is not bool or type(item.get("sensitive")) is not bool:
            return []
        seen_keys.add(key)
        normalized.append({
            "key": key,
            "label": label,
            "required": bool(item["required"]),
            "sensitive": bool(item["sensitive"]),
        })
    return normalized


def _template_id_from_source_path(source_path: str | None) -> int | None:
    value = (source_path or "").strip()
    if not value.startswith("template:"):
        return None
    raw_id = value.split(":", 1)[1].strip()
    if not raw_id.isdigit():
        return None
    return int(raw_id)


def _build_template_inputs_section(db: Session, project: Project, task: Task) -> str:
    template_inputs = _parse_json_object(getattr(project, "template_inputs_json", None))
    if not template_inputs:
        return ""

    plan = db.query(ProjectPlan).filter(ProjectPlan.id == task.plan_id).first()
    template_id = _template_id_from_source_path(getattr(plan, "source_path", None) if plan else None)
    if template_id is None:
        return ""
    template = db.query(ProcessTemplate).filter(ProcessTemplate.id == template_id).first()
    if not template:
        return ""
    required_inputs = _parse_required_inputs(getattr(template, "required_inputs_json", None))
    if not required_inputs:
        return ""

    lines: list[str] = []
    for item in required_inputs:
        key = str(item["key"])
        value = str(template_inputs.get(key) or "").strip()
        if value:
            lines.append(f"- {item['label']}: {value}")
    if not lines:
        return ""
    return "## 模版所需信息\n" + "\n".join(lines)


def _task_uses_issue_review_loop(db: Session, task: Task) -> bool:
    if not getattr(task, "plan_id", None):
        return False
    plan = db.query(ProjectPlan).filter(ProjectPlan.id == task.plan_id).first()
    data = _parse_json_object(getattr(plan, "plan_json", None) if plan else None)
    return data.get("flow_type") == FLOW_TYPE


def _issue_review_loop_task_section(project: Project, task: Task) -> str:
    collab = (project.collaboration_dir or "").strip("/")
    flow_state_path = f"{collab}/flow-state.json" if collab else "flow-state.json"
    project_repo_url = _project_repo_url(project) or "未提供"
    collaboration_repo_url = _collaboration_repo_url(project) or "未提供"
    common = f"""## Issue 编码与双 Agent 评审循环规则
- 本流程固定使用 `TASK-001` 到 `TASK-005` 作为角色槽位，真实轮次记录在 `{flow_state_path}` 和各 Task 的轮次目录中。
- HALF 协作仓库地址：{collaboration_repo_url}
- 项目代码仓库地址：{project_repo_url}
- 协作分支固定为 `main`：所有协作产物、`flow-state.json`、`branch.json`、`review.json`、`decision.json` 都必须提交并 push 到 HALF 协作仓库的 `main` 分支。
- 项目代码分支与协作分支必须分开处理：代码改动 push 到项目工作分支；协作产物 push 到协作仓库 `main`。即使两个仓库地址相同，也不能把协作产物提交到项目工作分支。
- 后端和前端只按当前轮次目录派生业务状态；不要扫描历史轮次目录寻找“最新”评审。
- 轮次目录使用 `round-XXX` 三位补零格式，例如 `round-001`。
- 不要把密钥、令牌、私有凭据写入协作产物。"""

    task_code = task.task_code
    if task_code == "TASK-001":
        specific = f"""## 本任务职责
1. 从 `issue_url` 获取 issue 内容，写入 `TASK-001/issue-summary.md`。
2. 生成实现计划，写入 `TASK-001/implementation-plan.md`。
3. 初始化 `{flow_state_path}`，必须使用 HALF 后端可识别的顶层字段；不要写旧格式 `tasks.*.status`。
4. `flow-state.json` 初始结构必须包含：
```json
{{
  "schema_version": 1,
  "flow_type": "{FLOW_TYPE}",
  "current_round": 1,
  "round_id": "round-001",
  "phase": "coding",
  "work_branch": null,
  "head_commit": null,
  "max_review_rounds": 3,
  "task_states": {{
    "TASK-001": "completed",
    "TASK-002": "unlocked",
    "TASK-003": "frozen",
    "TASK-004": "frozen",
    "TASK-005": "frozen"
  }}
}}
```
其中 `max_review_rounds` 必须使用模板输入 `max_review_rounds` 的数字值。
5. 最后生成 `TASK-001/result.json` 作为计划初始化完成哨兵。"""
    elif task_code == "TASK-002":
        specific = f"""## 本任务职责
1. 开始前读取 `{flow_state_path}`；只有 `TASK-002` 的业务状态为 `unlocked` 或 `needs_fix` 时才继续。
2. 固定以项目仓库 `main` 分支作为基准分支创建或更新工作分支；工作分支名由你根据 issue 编号和时间自动生成，不要要求用户提供分支名。
3. 若是修复轮次，只读取当前轮次两份 review，并逐条回应合理性；拒绝采纳的意见必须说明理由。
4. 完成代码修改和必要测试后，把项目代码 commit 并 push 到项目仓库工作分支，不要把代码改动直接提交到 `main`。
5. 代码分支 push 成功后，切换到 HALF 协作仓库 `main` 分支并拉取最新状态；如果项目代码仓库和 HALF 协作仓库是同一个仓库，也必须先切回 `main` 再写协作产物。
6. 在协作仓库 `main` 写入 `TASK-002/rounds/round-XXX/branch.json`、实现或修复摘要、测试报告；`branch.json` 中的 `base_branch` 必须为 `main`。
7. 在协作仓库 `main` 更新 `{flow_state_path}` 顶层字段：设置最新 `current_round`、`round_id`、`work_branch`、`head_commit`，在顶层 `task_states` 中将 `TASK-002` 置为 `waiting_review`，`TASK-003` / `TASK-004` 置为 `unlocked`，`TASK-005` 置为 `frozen`，`phase` 置为 `awaiting_review`。
8. 将上述协作产物 commit 并 push 到 HALF 协作仓库 `origin/main`；不得把 `{flow_state_path}` 或 `TASK-002/rounds/` 只提交到项目工作分支。
9. 不得在两个评审都同意合并前提交 PR；中间轮次不要用 `result.json` 结束整个角色槽位。"""
    elif task_code in ("TASK-003", "TASK-004"):
        specific = f"""## 本任务职责
1. 开始前读取 `{flow_state_path}`；只有 `{task_code}` 的业务状态为 `unlocked` 时才继续。
2. 读取当前轮次的 `TASK-002/rounds/round-XXX/branch.json`，并用其中 `round`、`round_id`、`work_branch`、`head_commit` 作为评审锚点。
3. 基于用户填写的 `review_prompt` 独立评审代码正确性、测试覆盖、回归风险、可维护性和需求匹配度。
4. 只在 HALF 协作仓库 `main` 分支写入 `{task_code}/reviews/round-XXX/review.json` 和 `{task_code}/reviews/round-XXX/review.md`，并 push 到 `origin/main`。
5. `review.json` 必须包含布尔字段 `approve_merge`，并且 `round`、`round_id`、`work_branch`、`head_commit` 必须与当前 flow-state 一致。
6. 评审 Agent 不得修改 `{flow_state_path}`，不得依赖另一名评审 Agent 的结论。"""
    elif task_code == "TASK-005":
        specific = f"""## 本任务职责
1. 开始前读取 `{flow_state_path}` 和当前轮次两份 review；HALF 派发本任务代表后端已根据 review 文件派生 `TASK-005 = unlocked`，原始 `flow-state.json.task_states.TASK-005` 可能仍是 `frozen`，不要因此停止。
2. 只读取当前轮次 `TASK-003/reviews/round-XXX/review.json` 和 `TASK-004/reviews/round-XXX/review.json`；任一文件缺失、非法或锚点不匹配时必须停止并说明原因。
3. 两份 review 都必须包含布尔 `approve_merge`，并且 `round`、`round_id`、`work_branch`、`head_commit` 必须与当前 `{flow_state_path}` 一致。
4. 在 HALF 协作仓库 `main` 分支写入 `TASK-005/decisions/round-XXX/decision.json` 和 `decision.md`。
5. 若任一评审不同意合并，更新 `{flow_state_path}` 顶层 `task_states`：`TASK-002` 为 `needs_fix`，`TASK-003` / `TASK-004` / `TASK-005` 为 `frozen`，并更新 `phase`。
6. 若达到 `max_review_rounds` 且仍未通过，必须写入本轮 `decision.json` / `decision.md` 人工处理报告，并将流程 `phase` 标记为 `needs_attention`；HALF 后端会据此将 `TASK-005` 派生为已完成并提示人工介入。
7. 只有两份评审都同意合并时，先在顶层 `task_states` 把 `TASK-002` 标记为 `approved`，再以 `main` 作为目标分支提交 PR，写入 `TASK-005/pr.json` / `pr.md`，最后将流程标记为 `completed` 并生成最终 `result.json`。
8. 将决策、PR 记录、`flow-state.json` 和最终 `result.json` commit 并 push 到 HALF 协作仓库 `origin/main`。"""
    else:
        specific = ""
    return common + "\n\n" + specific


def generate_task_prompt(
    db: Session,
    project: Project,
    task: Task,
    include_usage: bool = False,  # kept for API compat, no longer used
) -> str:
    collab = (project.collaboration_dir or "").strip("/")
    task_dir = f"{collab}/{task.task_code}" if collab else task.task_code
    goal_text = (project.goal or "").strip()
    template_inputs_section = _build_template_inputs_section(db, project, task)
    issue_review_loop_task = _task_uses_issue_review_loop(db, task)
    project_repo_url = _project_repo_url(project)
    collaboration_repo_url = _collaboration_repo_url(project)

    depends_on = json.loads(task.depends_on_json) if task.depends_on_json else []
    predecessor_lines = ""
    if depends_on:
        predecessors = db.query(Task).filter(
            Task.project_id == project.id,
            Task.task_code.in_(depends_on),
        ).all()
        paths = []
        for p in predecessors:
            if p.status == "abandoned":
                continue
            pred_dir = f"{collab}/{p.task_code}" if collab else p.task_code
            paths.append(f"- {p.task_code}: {pred_dir}/")
        if paths:
            predecessor_lines = "\n".join(paths)
        else:
            predecessor_lines = "无前序任务输出"
    else:
        predecessor_lines = "无前序任务输出"

    sections = [f"你是项目 [{project.name}] 的执行 Agent。"]
    if goal_text:
        sections.append(f"## 项目任务介绍\n{goal_text}")
    sections.append(f"""## 仓库约定
- 项目代码仓库地址：{project_repo_url or '未提供'}
- HALF 协作仓库地址：{collaboration_repo_url or '未提供'}
- 协作目录：{project.collaboration_dir or '仓库根目录'}
- 代码修改、构建验证和业务文件变更提交到项目代码仓库。
- 任务产出、`result.json`、`usage.json` 写入 HALF 协作仓库的协作目录；HALF 只轮询该协作仓库。""")
    if template_inputs_section:
        sections.append(template_inputs_section)
    if issue_review_loop_task:
        sections.append(_issue_review_loop_task_section(project, task))

    sentinel_rules = """2. 本流程的中间轮次状态由 `flow-state.json`、`branch.json`、`review.json`、`decision.json` 表达；不要为了让 HALF 结束角色槽位而提前生成 `result.json`
3. 只有 `TASK-001` 初始化完成、`TASK-005` 提交 PR 成功或流程进入终止状态时，才生成对应任务的 `result.json`
4. 需要生成 `result.json` 时，先写入临时文件 `result.json.tmp`，确认写完并 flush 后，再原子重命名为 `result.json`
5. `result.json` 必须是合法 JSON 对象，包含 `task_code`、`summary`、`artifacts`；`task_code` 必须为 `{task_code}`，`summary` 必须为非空字符串，`artifacts` 必须是仓库根相对路径字符串数组，不得使用绝对路径、反斜杠或 `..` 越界路径
6. 代码修改在项目代码仓库工作分支执行 git add、git commit、git push；协作产物在 HALF 协作仓库 `main` 分支执行 git add、git commit、git push origin main。""".format(task_code=task.task_code) if issue_review_loop_task else """2. 所有产出文件写完后，最后生成 `result.json`，它是完成哨兵，不是中间过程文件
3. 先写入临时文件 `result.json.tmp`，确认写完并 flush 后，再原子重命名为 `result.json`
4. `result.json` 必须是合法 JSON 对象，包含 `task_code`、`summary`、`artifacts`；`task_code` 必须为 `{task_code}`，`summary` 必须为非空字符串，`artifacts` 必须是仓库根相对路径字符串数组，不得使用绝对路径、反斜杠或 `..` 越界路径
5. 后续任务默认从前序任务目录及其中的 `result.json` 读取成果，不要依赖旧的单文件输出路径约定
6. 代码修改在项目代码仓库执行 git add、git commit、git push；协作产物在 HALF 协作仓库执行 git add、git commit、git push。""".format(task_code=task.task_code)
    predecessor_check = (
        "2. 按本流程规则读取前序任务目录、`flow-state.json` 和当前轮次产物；不要要求中间轮次一定存在前序 `result.json`。"
        if issue_review_loop_task
        else "2. 确认上述前序任务目录及其中的 `result.json` 已经存在；若仍缺失，请等待或与项目负责人沟通，不要凭空创作前序内容。"
    )
    completion_sentinel = (
        """## 完成哨兵约束
- 本流程的中间任务不要提前生成 `result.json`；按上方专用规则在允许的阶段生成。
- 如果生成 `result.json` 时没有代码改动，必须在报告和 `result.json` 中明确说明 `no_code_changes: true` 以及验证依据。"""
        if issue_review_loop_task
        else """## 完成哨兵约束
- 只有项目代码仓库的代码修改已经提交并 push 成功后，才允许生成 `result.json`。
- 如果本任务没有代码改动，必须在报告和 `result.json` 中明确说明 `no_code_changes: true` 以及验证依据；不得只生成 `result.json` 冒充完成。"""
    )
    sections.append(f"""## 执行前置步骤（必须先做）
1. 在开始本任务前，必须先在项目代码仓库目录执行 `git pull`；若 HALF 协作仓库与项目代码仓库不同，也必须在 HALF 协作仓库目录执行 `git pull`，确保拿到最新的远端状态，否则可能读不到前序任务输出。
{predecessor_check}

## 任务信息
- 任务码：{task.task_code}
- 任务名称：{task.task_name}
- 任务描述：{task.description}

## 前序任务输出
{predecessor_lines}

## 输出要求
1. 将所有协作产出文件写入 HALF 协作仓库目录：{task_dir}/
{sentinel_rules}

{completion_sentinel}""")

    return "\n\n".join(sections)
