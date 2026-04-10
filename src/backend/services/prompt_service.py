import json
import re

from sqlalchemy.orm import Session

from models import Agent, Project, Task


def generate_plan_prompt(
    project: Project,
    selected_agents: list[Agent],
    plan_path: str,
    usage_path: str | None = None,  # kept for API compat, no longer used
    selected_agent_models: dict[int, str | None] | None = None,
) -> tuple[str, dict[int, str | None]]:
    resolved_models = resolve_selected_agent_models(project.goal or "", selected_agents, selected_agent_models or {})
    selected_lines = "\n".join(
        _format_agent_line(agent, resolved_models.get(agent.id))
        for agent in selected_agents
    ) or "- 未指定参与 Agent"

    prompt = f"""你是项目 [{project.name}] 的执行 Agent。

## 任务目标
{project.goal}

## 协作约定
- 项目仓库地址：{project.git_repo_url or '未提供'}
- 协作目录：{project.collaboration_dir or '仓库根目录'}

## 本次参与规划的 Agent
{selected_lines}

请根据参与 Agent 的数量、能力特点和分工边界来拆分子任务，尽量让每个子任务的 assignee 都来自上述列表。

## 输出要求
请输出结构化工作计划，格式为 JSON，包含以下字段：
- plan_name: 计划名称
- tasks: 任务列表，每个任务包含 task_code, task_name, description, assignee, depends_on, expected_output

将计划写入 {plan_path} 文件。
完成后执行 git add、git commit、git push。"""

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
) -> dict[int, str | None]:
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
                _score_model_fit(requirement_text, model.get("capability")),
                1 if model.get("capability") else 0,
            ),
        )
        resolved[agent.id] = best_model["model_name"]
    return resolved


def _format_agent_line(agent: Agent, selected_model_name: str | None) -> str:
    models = _parse_agent_models(agent)
    chosen = next((model for model in models if model["model_name"] == selected_model_name), None)
    if chosen:
        capability_text = f"，能力：{chosen['capability']}" if chosen.get("capability") else ""
        return f"- {agent.name} ({agent.slug}, {agent.agent_type}, 使用模型：{chosen['model_name']}{capability_text})"
    if models:
        model_names = " / ".join(model["model_name"] for model in models)
        return f"- {agent.name} ({agent.slug}, {agent.agent_type}, 可用模型：{model_names})"
    return f"- {agent.name} ({agent.slug}, {agent.agent_type})"


def generate_task_prompt(
    db: Session,
    project: Project,
    task: Task,
    include_usage: bool = False,  # kept for API compat, no longer used
) -> str:
    collab = (project.collaboration_dir or "").strip("/")
    task_dir = f"{collab}/{task.task_code}" if collab else task.task_code

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

    prompt = f"""你是项目 [{project.name}] 的执行 Agent。

## 执行前置步骤（必须先做）
1. 在开始本任务前，必须先在项目仓库目录执行 `git pull`，确保拿到最新的远端状态，否则可能读不到前序任务输出。
2. 确认上述前序任务目录及其中的 `result.json` 已经存在；若仍缺失，请等待或与项目负责人沟通，不要凭空创作前序内容。

## 任务信息
- 任务码：{task.task_code}
- 任务名称：{task.task_name}
- 任务描述：{task.description}

## 前序任务输出
{predecessor_lines}

## 输出要求
1. 将所有产出文件写入目录：{task_dir}/
2. 所有产出文件写完后，最后生成 `result.json`，它是完成哨兵，不是中间过程文件
3. 先写入临时文件 `result.json.tmp`，确认写完并 flush 后，再原子重命名为 `result.json`
4. `result.json` 至少包含：`task_code`、`summary`、`artifacts`，其中 `task_code` 必须为 `{task.task_code}`
5. 后续任务默认从前序任务目录及其中的 `result.json` 读取成果，不要依赖旧的单文件输出路径约定
6. 完成后执行 git add、git commit、git push"""

    return prompt
