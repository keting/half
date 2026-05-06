import json
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from access import get_owned_project, load_usable_agents
from auth import get_current_user
from database import get_db
from models import Agent, ProcessTemplate, ProjectPlan, User
from routers.plans import finalize_plan_record
from schemas import UtcDatetimeModel
from services.path_service import ExpectedOutputPathError, normalize_expected_output_path
from services.project_agents import agent_ids_from_assignments_json

router = APIRouter(prefix="/api/process-templates", tags=["process_templates"])

AGENT_SLOT_PATTERN = re.compile(r"^agent-[1-9]\d*$")
REQUIRED_INPUT_KEY_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class ProcessTemplateBase(BaseModel):
    name: str = ""
    description: str = ""
    prompt_source_text: str | None = None
    template_json: str | dict
    agent_roles_description: Optional[dict[str, object]] = None
    required_inputs: Optional[object] = None


class ProcessTemplateCreate(ProcessTemplateBase):
    pass


class ProcessTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt_source_text: Optional[str] = None
    template_json: Optional[str | dict] = None
    agent_roles_description: Optional[dict[str, object]] = None
    required_inputs: Optional[object] = None


class ProcessTemplateResponse(UtcDatetimeModel):
    id: int
    name: str
    description: Optional[str]
    prompt_source_text: Optional[str]
    agent_count: int
    agent_slots: list[str]
    agent_roles_description: dict[str, str]
    required_inputs: list[dict[str, object]]
    template_json: str
    created_by: Optional[int]
    updated_by: Optional[int]
    can_edit: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TemplatePromptRequest(BaseModel):
    scenario: str = ""
    description: str


class TemplatePromptResponse(BaseModel):
    prompt: str


class TemplateApplyRequest(BaseModel):
    slot_agent_ids: dict[str, int] = Field(default_factory=dict)


class TemplateApplyResponse(BaseModel):
    plan_id: int
    tasks_created: int
    project_status: str


def _parse_template_json(value: str | dict) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid template JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Template JSON must be an object")
    return parsed


def _slot_sort_key(slot: str) -> tuple[int, str]:
    try:
        return (int(slot.split("-", 1)[1]), slot)
    except (IndexError, ValueError):
        return (10**9, slot)


def _detect_cycle(tasks_by_code: dict[str, dict]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(code: str) -> bool:
        if code in visiting:
            return True
        if code in visited:
            return False
        visiting.add(code)
        task = tasks_by_code[code]
        for dep in task.get("depends_on", []):
            if dep in tasks_by_code and visit(dep):
                return True
        visiting.remove(code)
        visited.add(code)
        return False

    return any(visit(code) for code in tasks_by_code)


def validate_template_json(value: str | dict) -> tuple[str, list[str], dict]:
    data = _parse_template_json(value)
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise HTTPException(status_code=400, detail="Template JSON must contain non-empty tasks")

    task_codes: set[str] = set()
    tasks_by_code: dict[str, dict] = {}
    slots: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise HTTPException(status_code=400, detail=f"Task #{index} must be an object")

        for field in ("task_code", "task_name", "description", "assignee", "depends_on"):
            if field not in task:
                raise HTTPException(status_code=400, detail=f"Task #{index} missing required field: {field}")

        task_code = str(task.get("task_code") or "").strip()
        if not task_code:
            raise HTTPException(status_code=400, detail=f"Task #{index} task_code is required")
        if task_code in task_codes:
            raise HTTPException(status_code=400, detail=f"Duplicate task_code: {task_code}")
        task_codes.add(task_code)
        tasks_by_code[task_code] = task

        if not str(task.get("task_name") or "").strip():
            raise HTTPException(status_code=400, detail=f"Task {task_code} task_name is required")
        if not str(task.get("description") or "").strip():
            raise HTTPException(status_code=400, detail=f"Task {task_code} description is required")

        assignee = str(task.get("assignee") or "").strip()
        if not AGENT_SLOT_PATTERN.fullmatch(assignee):
            raise HTTPException(status_code=400, detail=f"Task {task_code} assignee must use agent-N slot format")
        slots.add(assignee)
        task["assignee"] = assignee

        depends_on = task.get("depends_on")
        if not isinstance(depends_on, list) or not all(isinstance(dep, str) and dep.strip() for dep in depends_on):
            raise HTTPException(status_code=400, detail=f"Task {task_code} depends_on must be a list of task_code strings")
        task["depends_on"] = [dep.strip() for dep in depends_on]

        try:
            task["expected_output"] = normalize_expected_output_path(
                task.get("expected_output"),
                default_path=f"outputs/{task_code}/result.json",
                collaboration_dir="",
                strict=True,
            )
        except ExpectedOutputPathError as exc:
            raise HTTPException(status_code=400, detail=f"Task {task_code} has invalid expected_output: {exc}") from exc

    for task_code, task in tasks_by_code.items():
        for dep in task.get("depends_on", []):
            if dep not in task_codes:
                raise HTTPException(status_code=400, detail=f"Task {task_code} depends on unknown task_code: {dep}")

    if _detect_cycle(tasks_by_code):
        raise HTTPException(status_code=400, detail="Template tasks must form a DAG")

    sorted_slots = sorted(slots, key=_slot_sort_key)
    return json.dumps(data, ensure_ascii=False), sorted_slots, data


def _can_edit(template: ProcessTemplate, user: User) -> bool:
    return user.role == "admin" or template.created_by == user.id


def _parse_agent_roles_description(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    roles: dict[str, str] = {}
    for slot, description in parsed.items():
        if isinstance(slot, str) and isinstance(description, str):
            trimmed = description.strip()
            if trimmed:
                roles[slot] = trimmed
    return roles


def _normalize_agent_roles_description(value: dict[str, object] | None, slots: list[str]) -> dict[str, str]:
    if not value:
        return {}
    slot_set = set(slots)
    roles: dict[str, str] = {}
    for slot, description in value.items():
        if slot not in slot_set or not isinstance(description, str):
            continue
        trimmed = description.strip()
        if trimmed:
            roles[slot] = trimmed
    return roles


def validate_required_inputs(value: object | None) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="required_inputs must be an array")
    normalized: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"required_inputs #{index} must be an object")
        key = str(item.get("key") or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail=f"required_inputs #{index} key is required")
        if not REQUIRED_INPUT_KEY_PATTERN.fullmatch(key):
            raise HTTPException(status_code=400, detail=f"required_inputs #{index} key is invalid")
        if key in seen_keys:
            raise HTTPException(status_code=400, detail=f"Duplicate required_inputs key: {key}")
        seen_keys.add(key)

        label = str(item.get("label") or "").strip()
        if not label:
            raise HTTPException(status_code=400, detail=f"required_inputs {key} label is required")

        required = item.get("required")
        sensitive = item.get("sensitive")
        if type(required) is not bool:
            raise HTTPException(status_code=400, detail=f"required_inputs {key} required must be a boolean")
        if type(sensitive) is not bool:
            raise HTTPException(status_code=400, detail=f"required_inputs {key} sensitive must be a boolean")

        normalized.append({
            "key": key,
            "label": label,
            "required": required,
            "sensitive": sensitive,
        })
    return normalized


def _parse_required_inputs(value: str | None) -> list[dict[str, object]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    try:
        return validate_required_inputs(parsed)
    except HTTPException:
        return []


def _build_response(template: ProcessTemplate, user: User) -> ProcessTemplateResponse:
    try:
        slots = json.loads(template.agent_slots_json or "[]")
    except json.JSONDecodeError:
        slots = []
    if not isinstance(slots, list):
        slots = []
    return ProcessTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        prompt_source_text=template.prompt_source_text,
        agent_count=template.agent_count or 0,
        agent_slots=[str(slot) for slot in slots],
        agent_roles_description=_parse_agent_roles_description(template.agent_roles_description_json),
        required_inputs=_parse_required_inputs(template.required_inputs_json),
        template_json=template.template_json,
        created_by=template.created_by,
        updated_by=template.updated_by,
        can_edit=_can_edit(template, user),
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _derive_metadata(body: ProcessTemplateBase | ProcessTemplateUpdate, existing: ProcessTemplate | None = None) -> tuple[str, str, str, list[str]]:
    raw_json = body.template_json if body.template_json is not None else existing.template_json  # type: ignore[union-attr]
    template_json, slots, parsed = validate_template_json(raw_json)
    derived_name = str(parsed.get("plan_name") or "").strip()
    derived_description = str(parsed.get("description") or "").strip()
    name = str(body.name or "").strip() if body.name is not None else ""
    if not name:
        name = derived_name
    description = str(body.description or "").strip() if body.description is not None else ""
    if not description:
        description = derived_description
    name = str(name or "").strip()
    description = str(description or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Template name is required")
    return name, description, template_json, slots


@router.post("/generate-prompt", response_model=TemplatePromptResponse)
def generate_template_prompt(body: TemplatePromptRequest, _user: User = Depends(get_current_user)):
    scenario = body.scenario.strip()
    description = body.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    scenario_section = f"""
## 适用场景 / 流程目标上下文
{scenario}
""" if scenario else ""
    prompt = f"""你是 HALF 的流程模版设计 Agent。请根据用户描述生成一个通用流程模版 JSON。
{scenario_section}
## 详细流程需求
{description}

## 输出 JSON 格式
必须输出一个 JSON 对象，包含：
- plan_name: 模版名称
- description: 适用场景说明
- agent_roles: 角色说明数组，用于说明每个 agent-N 槽位的职责和适合的 Agent 类型
- tasks: 非空数组

agent_roles 中每一项必须包含：
- slot: 对应的抽象角色槽位，例如 agent-1
- description: 一段 60-120 字的自然语言说明，包含该角色承担的关键任务概括，以及适合由什么类型的 Agent 担任

每个 task 必须包含：
- task_code: 唯一任务码
- task_name: 任务名称
- description: 通用任务描述，不要写入具体项目、仓库、目录或具体 agent 信息
- assignee: 抽象角色槽位，只能使用 agent-1、agent-2 等格式
- depends_on: 前置任务 task_code 数组，无依赖时写 []
- expected_output: 仓库相对路径，建议 outputs/<task_code>/result.json

要求：
1. 不要使用具体 agent 名称、slug、类型或模型。
2. 不要使用绝对路径，不要写具体协作目录。
3. 任务依赖必须是 DAG，不能循环依赖。
4. agent_roles 的 slot 必须覆盖 tasks 中实际使用到的每个 assignee；不要为未使用的 slot 写说明。
5. description 面向项目管理者阅读，不要堆砌任务细节，力求一眼看懂。
6. 只输出 JSON，不要输出 markdown 代码块。"""
    return TemplatePromptResponse(prompt=prompt)


@router.get("", response_model=list[ProcessTemplateResponse])
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    templates = db.query(ProcessTemplate).order_by(ProcessTemplate.updated_at.desc(), ProcessTemplate.id.desc()).all()
    return [_build_response(template, user) for template in templates]


@router.post("", response_model=ProcessTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(body: ProcessTemplateCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name, description, template_json, slots = _derive_metadata(body)
    roles_description = _normalize_agent_roles_description(body.agent_roles_description, slots)
    required_inputs = validate_required_inputs(body.required_inputs)
    now = datetime.now(timezone.utc)
    template = ProcessTemplate(
        name=name,
        description=description,
        prompt_source_text=body.prompt_source_text,
        agent_count=len(slots),
        agent_slots_json=json.dumps(slots, ensure_ascii=False),
        agent_roles_description_json=json.dumps(roles_description, ensure_ascii=False) if roles_description else None,
        required_inputs_json=json.dumps(required_inputs, ensure_ascii=False),
        template_json=template_json,
        created_by=user.id,
        updated_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _build_response(template, user)


@router.get("/{template_id}", response_model=ProcessTemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    template = db.query(ProcessTemplate).filter(ProcessTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return _build_response(template, user)


@router.put("/{template_id}", response_model=ProcessTemplateResponse)
def update_template(template_id: int, body: ProcessTemplateUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    template = db.query(ProcessTemplate).filter(ProcessTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not _can_edit(template, user):
        raise HTTPException(status_code=403, detail="Only template creator or admin can edit this template")
    name, description, template_json, slots = _derive_metadata(body, template)
    raw_roles_description = body.agent_roles_description
    if raw_roles_description is None:
        raw_roles_description = _parse_agent_roles_description(template.agent_roles_description_json)
    roles_description = _normalize_agent_roles_description(raw_roles_description, slots)
    required_inputs = (
        validate_required_inputs(body.required_inputs)
        if body.required_inputs is not None
        else _parse_required_inputs(template.required_inputs_json)
    )
    template.name = name
    template.description = description
    if body.prompt_source_text is not None:
        template.prompt_source_text = body.prompt_source_text
    template.template_json = template_json
    template.agent_count = len(slots)
    template.agent_slots_json = json.dumps(slots, ensure_ascii=False)
    template.agent_roles_description_json = json.dumps(roles_description, ensure_ascii=False) if roles_description else None
    template.required_inputs_json = json.dumps(required_inputs, ensure_ascii=False)
    template.updated_by = user.id
    template.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(template)
    return _build_response(template, user)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    template = db.query(ProcessTemplate).filter(ProcessTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not _can_edit(template, user):
        raise HTTPException(status_code=403, detail="Only template creator or admin can delete this template")
    db.delete(template)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{template_id}/apply/{project_id}", response_model=TemplateApplyResponse)
def apply_template(
    template_id: int,
    project_id: int,
    body: TemplateApplyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_owned_project(db, project_id, user)
    if project.status not in ("draft", "planning"):
        raise HTTPException(status_code=400, detail=f"Cannot apply template to project in status: {project.status}")
    template = db.query(ProcessTemplate).filter(ProcessTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template_json, slots, data = validate_template_json(template.template_json)
    _ = template_json
    mapping = body.slot_agent_ids
    expected_slots = set(slots)
    provided_slots = set(mapping.keys())
    if provided_slots != expected_slots:
        missing = sorted(expected_slots - provided_slots, key=_slot_sort_key)
        extra = sorted(provided_slots - expected_slots, key=_slot_sort_key)
        detail = []
        if missing:
            detail.append(f"missing slots: {', '.join(missing)}")
        if extra:
            detail.append(f"unknown slots: {', '.join(extra)}")
        raise HTTPException(status_code=400, detail="Invalid slot mapping: " + "; ".join(detail))
    mapped_agent_ids = list(mapping.values())
    if len(set(mapped_agent_ids)) != len(mapped_agent_ids):
        raise HTTPException(status_code=400, detail="A single agent cannot be mapped to multiple slots")

    project_agent_ids = set(agent_ids_from_assignments_json(project.agent_ids_json))
    inactive_project_agent_ids = {
        row[0]
        for row in db.query(Agent.id)
        .filter(Agent.id.in_(project_agent_ids), Agent.is_active == False)  # noqa: E712
        .all()
    }
    if inactive_project_agent_ids:
        raise HTTPException(status_code=400, detail="Project references inactive agents; remove them before planning")
    if not set(mapped_agent_ids).issubset(project_agent_ids):
        raise HTTPException(status_code=400, detail="Mapped agents must belong to the project")

    agents = load_usable_agents(db, mapped_agent_ids, user) if mapped_agent_ids else []
    agents_by_id = {agent.id: agent for agent in agents}
    slot_to_slug = {slot: agents_by_id[agent_id].slug for slot, agent_id in mapping.items()}

    applied_data = json.loads(json.dumps(data, ensure_ascii=False))
    for task in applied_data["tasks"]:
        task["assignee"] = slot_to_slug[task["assignee"]]

    now = datetime.now(timezone.utc)
    db.query(ProjectPlan).filter(
        ProjectPlan.project_id == project.id,
        ProjectPlan.plan_type == "candidate",
        ProjectPlan.is_selected == False,  # noqa: E712 - SQLAlchemy comparison
    ).delete(synchronize_session=False)
    plan = ProjectPlan(
        project_id=project.id,
        source_agent_id=None,
        plan_type="candidate",
        plan_json=json.dumps(applied_data, ensure_ascii=False),
        prompt_text=None,
        status="completed",
        source_path=f"template:{template.id}",
        selected_agent_ids_json=json.dumps(mapped_agent_ids, ensure_ascii=False),
        selected_agent_models_json="{}",
        detected_at=now,
        is_selected=False,
    )
    db.add(plan)
    db.flush()

    result = finalize_plan_record(db, project, plan, user)
    return TemplateApplyResponse(
        plan_id=plan.id,
        tasks_created=int(result["tasks_created"]),
        project_status=str(result["project_status"]),
    )
