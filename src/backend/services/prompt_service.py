import json
import re

from sqlalchemy.orm import Session

from models import Agent, ProcessTemplate, Project, ProjectPlan, Task
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
    sections.append(f"""## 执行前置步骤（必须先做）
1. 在开始本任务前，必须先在项目代码仓库目录执行 `git pull`；若 HALF 协作仓库与项目代码仓库不同，也必须在 HALF 协作仓库目录执行 `git pull`，确保拿到最新的远端状态，否则可能读不到前序任务输出。
2. 确认上述前序任务目录及其中的 `result.json` 已经存在；若仍缺失，请等待或与项目负责人沟通，不要凭空创作前序内容。

## 任务信息
- 任务码：{task.task_code}
- 任务名称：{task.task_name}
- 任务描述：{task.description}

## 前序任务输出
{predecessor_lines}

## 输出要求
1. 将所有协作产出文件写入 HALF 协作仓库目录：{task_dir}/
2. 所有产出文件写完后，最后生成 `result.json`，它是完成哨兵，不是中间过程文件
3. 先写入临时文件 `result.json.tmp`，确认写完并 flush 后，再原子重命名为 `result.json`
4. `result.json` 至少包含：`task_code`、`summary`、`artifacts`，其中 `task_code` 必须为 `{task.task_code}`
5. 后续任务默认从前序任务目录及其中的 `result.json` 读取成果，不要依赖旧的单文件输出路径约定
6. 代码修改在项目代码仓库执行 git add、git commit、git push；协作产物在 HALF 协作仓库执行 git add、git commit、git push。

## 完成哨兵约束
- 只有项目代码仓库的代码修改已经提交并 push 成功后，才允许生成 `result.json`。
- 如果本任务没有代码改动，必须在报告和 `result.json` 中明确说明 `no_code_changes: true` 以及验证依据；不得只生成 `result.json` 冒充完成。""")

    return "\n\n".join(sections)
