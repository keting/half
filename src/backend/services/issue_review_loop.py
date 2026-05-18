import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models import ProcessTemplate, Project, ProjectPlan
from services import git_service


FLOW_TYPE = "issue_code_review_loop"
TEMPLATE_NAME = "Issue 编码与双 Agent 评审循环"
TASK_CODES = ["TASK-001", "TASK-002", "TASK-003", "TASK-004", "TASK-005"]
BUSINESS_DISPATCHABLE_STATES = {"unlocked", "needs_fix"}


def issue_review_loop_template_json() -> dict[str, Any]:
    return {
        "plan_name": TEMPLATE_NAME,
        "description": "输入 issue URL 后，由编码 Agent 编码、两个评审 Agent 并行评审，并按评审结论循环修复或提交 PR。",
        "flow_type": FLOW_TYPE,
        "agent_roles": [
            {
                "slot": "agent-1",
                "description": "编码与决策 Agent。负责拉取 issue、实现代码、测试、推送工作分支，根据评审意见修复，并在双评审通过后提交 PR。",
            },
            {
                "slot": "agent-2",
                "description": "评审 Agent A。负责从当前工作分支和 commit 独立评审代码，按结构化格式写入本轮 review.json 与 review.md。",
            },
            {
                "slot": "agent-3",
                "description": "评审 Agent B。负责独立执行第二份代码评审，不依赖评审 A 的结论，只写入自己的本轮评审产物。",
            },
        ],
        "tasks": [
            {
                "task_code": "TASK-001",
                "task_name": "拉取 issue 并初始化评审循环状态",
                "description": "读取 issue URL，理解需求，生成实现计划，初始化 flow-state.json，解锁编码任务。",
                "assignee": "agent-1",
                "depends_on": [],
                "expected_output": "outputs/TASK-001/result.json",
            },
            {
                "task_code": "TASK-002",
                "task_name": "编码、测试并推送工作分支",
                "description": "实现 issue 或修复上一轮合理评审意见，执行测试，推送项目仓库工作分支，并更新 flow-state.json 进入等待评审。",
                "assignee": "agent-1",
                "depends_on": ["TASK-001"],
                "expected_output": "outputs/TASK-002/result.json",
            },
            {
                "task_code": "TASK-003",
                "task_name": "评审 A",
                "description": "读取当前轮次 branch.json 和用户评审提示词，对工作分支进行独立评审，仅写入自己的 review.json / review.md。",
                "assignee": "agent-2",
                "depends_on": ["TASK-002"],
                "expected_output": "outputs/TASK-003/result.json",
            },
            {
                "task_code": "TASK-004",
                "task_name": "评审 B",
                "description": "读取当前轮次 branch.json 和用户评审提示词，对工作分支进行独立评审，仅写入自己的 review.json / review.md。",
                "assignee": "agent-3",
                "depends_on": ["TASK-002"],
                "expected_output": "outputs/TASK-004/result.json",
            },
            {
                "task_code": "TASK-005",
                "task_name": "评审决策与 PR 提交",
                "description": "只读取当前轮次两份评审结果，决定提交 PR 或解锁下一轮修复，并更新 flow-state.json。",
                "assignee": "agent-1",
                "depends_on": ["TASK-003", "TASK-004"],
                "expected_output": "outputs/TASK-005/result.json",
            },
        ],
    }


def issue_review_loop_required_inputs() -> list[dict[str, object]]:
    return [
        {"key": "issue_url", "label": "Issue URL", "required": True, "sensitive": False},
        {"key": "review_prompt", "label": "评审提示词", "required": True, "sensitive": False},
        {"key": "test_command", "label": "测试命令", "required": False, "sensitive": False},
        {"key": "max_review_rounds", "label": "最大评审轮次", "required": True, "sensitive": False},
    ]


def ensure_issue_review_loop_template(db: Session, admin) -> None:
    existing = db.query(ProcessTemplate).filter(ProcessTemplate.name == TEMPLATE_NAME).first()
    now = datetime.now(timezone.utc)
    agent_slots_json = json.dumps(["agent-1", "agent-2", "agent-3"], ensure_ascii=False)
    agent_roles_description_json = json.dumps(
        {
            "agent-1": "编码与决策 Agent，负责实现、测试、修复、推送工作分支和最终提交 PR。",
            "agent-2": "评审 Agent A，负责独立代码评审并写入结构化评审结果。",
            "agent-3": "评审 Agent B，负责独立代码评审并写入结构化评审结果。",
        },
        ensure_ascii=False,
    )
    required_inputs_json = json.dumps(issue_review_loop_required_inputs(), ensure_ascii=False)
    template_json = json.dumps(issue_review_loop_template_json(), ensure_ascii=False)
    if existing is not None:
        existing.description = "输入 issue URL 后，固定使用编码、双评审、决策 5 个 Task 完成编码评审闭环。"
        existing.prompt_source_text = "MVP 内置模板：固定 5 个 Task，运行状态由协作仓库 flow-state.json 与当前轮次产物派生。"
        existing.agent_count = 3
        existing.agent_slots_json = agent_slots_json
        existing.agent_roles_description_json = agent_roles_description_json
        existing.required_inputs_json = required_inputs_json
        existing.template_json = template_json
        existing.updated_by = admin.id
        existing.updated_at = now
        db.commit()
        return

    template = ProcessTemplate(
        name=TEMPLATE_NAME,
        description="输入 issue URL 后，固定使用编码、双评审、决策 5 个 Task 完成编码评审闭环。",
        prompt_source_text="MVP 内置模板：固定 5 个 Task，运行状态由协作仓库 flow-state.json 与当前轮次产物派生。",
        agent_count=3,
        agent_slots_json=agent_slots_json,
        agent_roles_description_json=agent_roles_description_json,
        required_inputs_json=required_inputs_json,
        template_json=template_json,
        created_by=admin.id,
        updated_by=admin.id,
        created_at=now,
        updated_at=now,
    )
    db.add(template)
    db.commit()


def _parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_issue_review_loop_plan(plan: ProjectPlan | None) -> bool:
    if not plan:
        return False
    data = _parse_json_object(plan.plan_json)
    return data.get("flow_type") == FLOW_TYPE


def get_issue_review_loop_plan(db: Session, project: Project) -> ProjectPlan | None:
    plans = (
        db.query(ProjectPlan)
        .filter(ProjectPlan.project_id == project.id, ProjectPlan.is_selected == True)  # noqa: E712
        .order_by(ProjectPlan.id.desc())
        .all()
    )
    for plan in plans:
        if is_issue_review_loop_plan(plan):
            return plan
    return None


def project_uses_issue_review_loop(db: Session, project: Project) -> bool:
    return get_issue_review_loop_plan(db, project) is not None


def _collab_dir(project: Project) -> str:
    return (project.collaboration_dir or "").strip("/")


def _flow_state_path(project: Project) -> str:
    base = _collab_dir(project)
    return f"{base}/flow-state.json" if base else "flow-state.json"


def _round_dir(current_round: int) -> str:
    return f"round-{current_round:03d}"


def _review_path(project: Project, task_code: str, current_round: int) -> str:
    base = _collab_dir(project)
    path = f"{task_code}/reviews/{_round_dir(current_round)}/review.json"
    return f"{base}/{path}" if base else path


def _empty_response(enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "exists": False,
        "valid": False,
        "flow_type": None,
        "phase": None,
        "derived_phase": None,
        "current_round": None,
        "round_id": None,
        "work_branch": None,
        "head_commit": None,
        "max_review_rounds": None,
        "task_states": {},
        "effective_task_states": {},
        "reviews": {},
        "decision": {},
        "pr": {},
        "errors": [],
    }


def _validate_review(
    project: Project,
    task_code: str,
    flow_state: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    current_round = flow_state.get("current_round")
    if not isinstance(current_round, int):
        return {"status": "pending", "approve_merge": None, "review_path": None}

    path = _review_path(project, task_code, current_round)
    content = git_service.read_file(
        project.id,
        path,
        git_repo_url=project.git_repo_url,
        prefer_remote=True,
    )
    if content is None:
        return {"status": "pending", "approve_merge": None, "review_path": path}

    try:
        review = json.loads(content)
    except json.JSONDecodeError:
        errors.append(f"{task_code} review.json is not valid JSON: {path}")
        return {"status": "needs_attention", "approve_merge": None, "review_path": path}

    if not isinstance(review, dict):
        errors.append(f"{task_code} review.json must be an object: {path}")
        return {"status": "needs_attention", "approve_merge": None, "review_path": path}

    for key, expected in (
        ("round", flow_state.get("current_round")),
        ("round_id", flow_state.get("round_id")),
        ("work_branch", flow_state.get("work_branch")),
        ("head_commit", flow_state.get("head_commit")),
    ):
        if review.get(key) != expected:
            errors.append(f"{task_code} review.json {key} does not match current flow-state: {path}")
            return {"status": "needs_attention", "approve_merge": None, "review_path": path}

    approve_merge = review.get("approve_merge")
    if type(approve_merge) is not bool:
        errors.append(f"{task_code} review.json approve_merge must be boolean: {path}")
        return {"status": "needs_attention", "approve_merge": None, "review_path": path}

    return {"status": "submitted", "approve_merge": approve_merge, "review_path": path}


def get_issue_review_flow_state(db: Session, project: Project) -> dict[str, Any]:
    if not project_uses_issue_review_loop(db, project):
        return _empty_response(enabled=False)

    path = _flow_state_path(project)
    content = git_service.read_file(
        project.id,
        path,
        git_repo_url=project.git_repo_url,
        prefer_remote=True,
    )
    if content is None:
        response = _empty_response(enabled=True)
        response["effective_task_states"] = {code: ("unlocked" if code == "TASK-001" else "frozen") for code in TASK_CODES}
        response["errors"] = [f"flow-state.json not found: {path}"]
        return response

    response = _empty_response(enabled=True)
    response["exists"] = True
    try:
        flow_state = json.loads(content)
    except json.JSONDecodeError:
        response["errors"] = [f"flow-state.json is not valid JSON: {path}"]
        response["effective_task_states"] = {code: "frozen" for code in TASK_CODES}
        return response

    if not isinstance(flow_state, dict) or flow_state.get("flow_type") != FLOW_TYPE:
        response["errors"] = [f"flow-state.json flow_type must be {FLOW_TYPE}: {path}"]
        response["effective_task_states"] = {code: "frozen" for code in TASK_CODES}
        return response

    required = ("current_round", "round_id", "phase", "task_states")
    missing = [key for key in required if key not in flow_state]
    if missing:
        response["errors"] = [f"flow-state.json missing required fields: {', '.join(missing)}"]
        response["effective_task_states"] = {code: "frozen" for code in TASK_CODES}
        return response

    task_states = flow_state.get("task_states") if isinstance(flow_state.get("task_states"), dict) else {}
    effective = {code: str(task_states.get(code) or "frozen") for code in TASK_CODES}
    errors: list[str] = []
    reviews = {
        "TASK-003": _validate_review(project, "TASK-003", flow_state, errors),
        "TASK-004": _validate_review(project, "TASK-004", flow_state, errors),
    }
    both_reviews_submitted = all(item.get("status") == "submitted" for item in reviews.values())
    derived_phase = str(flow_state.get("phase") or "")

    task_005_state = effective.get("TASK-005")

    if both_reviews_submitted and task_005_state not in {"completed", "approved", "abandoned"}:
        effective["TASK-003"] = "frozen"
        effective["TASK-004"] = "frozen"
        effective["TASK-005"] = "unlocked"
        derived_phase = "awaiting_decision"
    elif errors:
        for task_code, item in reviews.items():
            if item.get("status") == "needs_attention":
                effective[task_code] = "needs_attention"

    response.update({
        "valid": True,
        "flow_type": flow_state.get("flow_type"),
        "phase": flow_state.get("phase"),
        "derived_phase": derived_phase,
        "current_round": flow_state.get("current_round"),
        "round_id": flow_state.get("round_id"),
        "work_branch": flow_state.get("work_branch"),
        "head_commit": flow_state.get("head_commit"),
        "max_review_rounds": flow_state.get("max_review_rounds"),
        "task_states": task_states,
        "effective_task_states": effective,
        "reviews": reviews,
        "decision": flow_state.get("decision") if isinstance(flow_state.get("decision"), dict) else {},
        "pr": flow_state.get("pr") if isinstance(flow_state.get("pr"), dict) else {},
        "errors": errors,
    })
    return response


def get_effective_business_state(db: Session, project: Project, task_code: str) -> str | None:
    state = get_issue_review_flow_state(db, project)
    if not state.get("enabled"):
        return None
    effective = state.get("effective_task_states") if isinstance(state.get("effective_task_states"), dict) else {}
    value = effective.get(task_code)
    return str(value) if value is not None else "frozen"


def is_business_dispatch_allowed(state: str | None) -> bool:
    return state in BUSINESS_DISPATCHABLE_STATES
