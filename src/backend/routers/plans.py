import json
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from access import agent_visibility_filter, get_agent_owner_roles, get_owned_project, is_agent_public, load_usable_agents
from database import get_db
from models import Agent, Project, ProjectPlan, Task, User
from services.path_service import ExpectedOutputPathError, normalize_expected_output_path
from auth import get_current_user
from services.prompt_service import generate_plan_prompt
from services.polling_config_service import get_project_polling_settings
from services.prompt_settings import get_plan_co_location_guidance
from schemas import UtcDatetimeModel
from services.project_agents import agent_ids_from_assignments_json

router = APIRouter(prefix="/api/projects", tags=["plans"])


def _try_repair_json(raw: str) -> dict | None:
    """Attempt limited auto-repair of common JSON format issues."""
    text = raw.strip()
    # Strip markdown code fences (```json ... ```)
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Try parsing after repairs
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    return None


class PlanPromptRequest(BaseModel):
    include_usage: bool = False
    selected_agent_ids: list[int] = Field(default_factory=list)
    selected_agent_models: dict[int, Optional[str]] = Field(default_factory=dict)


class PlanImport(BaseModel):
    plan_json: str | dict
    source_agent_id: Optional[int] = None
    plan_type: str = "candidate"


class PlanResponse(UtcDatetimeModel):
    id: int
    project_id: int
    source_agent_id: Optional[int]
    plan_type: str
    plan_json: Optional[str]
    prompt_text: Optional[str]
    status: str
    source_path: Optional[str]
    include_usage: bool
    selected_agent_ids: list[int]
    selected_agent_models: dict[int, Optional[str]]
    dispatched_at: Optional[datetime]
    detected_at: Optional[datetime]
    last_error: Optional[str]
    is_selected: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PromptResponse(BaseModel):
    prompt: str
    plan_id: int
    source_path: str


def _parse_selected_agent_ids(value: Optional[str]) -> list[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [int(item) for item in parsed if isinstance(item, int)]


def _build_plan_response(plan: ProjectPlan) -> PlanResponse:
    return PlanResponse(
        id=plan.id,
        project_id=plan.project_id,
        source_agent_id=plan.source_agent_id,
        plan_type=plan.plan_type,
        plan_json=plan.plan_json,
        prompt_text=plan.prompt_text,
        status=plan.status,
        source_path=plan.source_path,
        include_usage=plan.include_usage,
        selected_agent_ids=_parse_selected_agent_ids(plan.selected_agent_ids_json),
        selected_agent_models=_parse_selected_agent_models(plan.selected_agent_models_json),
        dispatched_at=plan.dispatched_at,
        detected_at=plan.detected_at,
        last_error=plan.last_error,
        is_selected=plan.is_selected,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _normalize_collab_dir(project: Project) -> str:
    """Return collaboration_dir without leading or trailing slashes.
    Repo-relative paths must not start with '/', otherwise os.path.join
    will treat them as absolute and discard the repo prefix."""
    return (project.collaboration_dir or "").strip("/")


def _plan_file_path(project: Project, plan_id: int) -> str:
    base_dir = _normalize_collab_dir(project)
    filename = f"plan-{plan_id}.json"
    return f"{base_dir}/{filename}" if base_dir else filename


def _plan_usage_path(project: Project, plan_id: int) -> str:
    base_dir = _normalize_collab_dir(project)
    filename = f"plan-{plan_id}-usage.json"
    return f"{base_dir}/{filename}" if base_dir else filename


def _parse_selected_agent_models(value: Optional[str]) -> dict[int, Optional[str]]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[int, Optional[str]] = {}
    for key, model_name in parsed.items():
        try:
            agent_id = int(key)
        except (TypeError, ValueError):
            continue
        normalized = str(model_name).strip() if model_name else None
        result[agent_id] = normalized or None
    return result


def _serialize_selected_agent_models(value: dict[int, Optional[str]]) -> str:
    return json.dumps({str(agent_id): model_name for agent_id, model_name in value.items()}, ensure_ascii=False)


def _normalize_assignee_token(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().casefold()


def _match_assignee_agent(agents: list[Agent], normalized: str) -> Optional[Agent]:
    exact_slug = next((agent for agent in agents if _normalize_assignee_token(agent.slug) == normalized), None)
    if exact_slug:
        return exact_slug

    exact_name = next((agent for agent in agents if _normalize_assignee_token(agent.name) == normalized), None)
    if exact_name:
        return exact_name

    exact_type = next((agent for agent in agents if _normalize_assignee_token(agent.agent_type) == normalized), None)
    if exact_type:
        return exact_type

    return None


def _resolve_assignee_agent_id(db: Session, assignee: Optional[str], project: Project, owner: User) -> Optional[int]:
    normalized = _normalize_assignee_token(assignee)
    if not normalized:
        return None

    project_agent_ids = agent_ids_from_assignments_json(project.agent_ids_json)
    project_agents = (
        db.query(Agent).filter(Agent.id.in_(project_agent_ids), Agent.is_active == True).all()  # noqa: E712
        if project_agent_ids
        else []
    )
    project_agents_by_id = {agent.id: agent for agent in project_agents}
    ordered_project_agents = [project_agents_by_id[agent_id] for agent_id in project_agent_ids if agent_id in project_agents_by_id]
    project_match = _match_assignee_agent(ordered_project_agents, normalized)
    if project_match:
        return project_match.id

    agents = db.query(Agent).filter(agent_visibility_filter(db, owner)).all()
    owner_roles = get_agent_owner_roles(db, agents)
    private_agents = [agent for agent in agents if agent.created_by == owner.id and not is_agent_public(owner_roles, agent)]
    public_agents = [agent for agent in agents if is_agent_public(owner_roles, agent) and agent.is_active]
    fallback_match = _match_assignee_agent(private_agents + public_agents, normalized)
    return fallback_match.id if fallback_match else None


def _load_project_plan_agents(db: Session, project: Project, user: User, selected_agent_ids: list[int]) -> list[Agent]:
    project_agent_ids = agent_ids_from_assignments_json(project.agent_ids_json)
    inactive_project_agent_ids = {
        row[0]
        for row in db.query(Agent.id)
        .filter(Agent.id.in_(project_agent_ids), Agent.is_active == False)  # noqa: E712
        .all()
    }
    if inactive_project_agent_ids:
        raise HTTPException(status_code=400, detail="Project references inactive agents; remove them before planning")
    if not selected_agent_ids:
        raise HTTPException(status_code=400, detail="At least one participating agent must be selected")
    if any(agent_id not in project_agent_ids for agent_id in selected_agent_ids):
        raise HTTPException(status_code=400, detail="Some selected agents are not assigned to this project")
    return load_usable_agents(db, selected_agent_ids, user)


def _normalize_task_fields(tasks_data: list[dict]) -> list[dict]:
    """Normalize legacy field names to canonical ones for backward compatibility.

    Handles:
      - predecessors -> depends_on
      - title -> task_name
      - agent_id -> assignee
    """
    normalized = []
    for t in tasks_data:
        if not isinstance(t, dict):
            continue
        task = dict(t)
        # predecessors -> depends_on
        if "depends_on" not in task and "predecessors" in task:
            task["depends_on"] = task.pop("predecessors")
        # title -> task_name
        if "task_name" not in task and "title" in task:
            task["task_name"] = task.pop("title")
        # agent_id -> assignee (convert int agent_id to string for resolution)
        if "assignee" not in task and "agent_id" in task:
            agent_id_val = task.pop("agent_id")
            task["assignee"] = str(agent_id_val) if agent_id_val is not None else None
        normalized.append(task)
    return normalized


class FinalizeRequest(BaseModel):
    plan_id: int


@router.post("/{project_id}/plans/generate-prompt", response_model=PromptResponse)
def plan_generate_prompt(
    project_id: int,
    body: PlanPromptRequest = PlanPromptRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_owned_project(db, project_id, user)
    selected_agents = _load_project_plan_agents(db, project, user, body.selected_agent_ids)
    selected_agent_models = {}
    for agent in selected_agents:
        selected_model = body.selected_agent_models.get(agent.id)
        if selected_model:
            selected_agent_models[agent.id] = selected_model

    now = datetime.now(timezone.utc)
    selected_agent_ids_json = json.dumps(body.selected_agent_ids)
    selected_agent_models_json = _serialize_selected_agent_models(selected_agent_models)
    plan = (
        db.query(ProjectPlan)
        .filter(
            ProjectPlan.project_id == project_id,
            ProjectPlan.plan_type == "candidate",
            ProjectPlan.status == "pending",
            ProjectPlan.dispatched_at.is_(None),
            ProjectPlan.detected_at.is_(None),
            ProjectPlan.plan_json.is_(None),
            ProjectPlan.is_selected == False,  # noqa: E712 - SQLAlchemy comparison
        )
        .order_by(ProjectPlan.id.desc())
        .first()
    )
    if plan is None:
        plan = ProjectPlan(
            project_id=project_id,
            source_agent_id=None,
            plan_type="candidate",
            prompt_text="",
            status="pending",
            source_path="",
            include_usage=body.include_usage,
            selected_agent_ids_json=selected_agent_ids_json,
            selected_agent_models_json=selected_agent_models_json,
            is_selected=False,
        )
        db.add(plan)
        db.flush()
    else:
        plan.include_usage = body.include_usage
        plan.selected_agent_ids_json = selected_agent_ids_json
        plan.selected_agent_models_json = selected_agent_models_json
        plan.last_error = None
        plan.updated_at = now

    source_path = plan.source_path or _plan_file_path(project, plan.id)
    usage_path = _plan_usage_path(project, plan.id) if body.include_usage else None
    prompt, resolved_models = generate_plan_prompt(
        project,
        selected_agents,
        source_path,
        usage_path,
        selected_agent_models,
        get_plan_co_location_guidance(db),
    )
    plan.prompt_text = prompt
    plan.source_path = source_path
    plan.selected_agent_models_json = _serialize_selected_agent_models(resolved_models)

    # Update project status to planning
    if project.status == "draft":
        project.status = "planning"
    project.updated_at = now
    db.commit()
    db.refresh(plan)
    return PromptResponse(prompt=prompt, plan_id=plan.id, source_path=source_path)


@router.post("/{project_id}/plans/{plan_id}/dispatch", response_model=PlanResponse)
def dispatch_plan(
    project_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_owned_project(db, project_id, user)

    plan = db.query(ProjectPlan).filter(
        ProjectPlan.id == plan_id,
        ProjectPlan.project_id == project_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if not plan.prompt_text:
        raise HTTPException(status_code=400, detail="Plan has no generated prompt")

    now = datetime.now(timezone.utc)

    if plan.status == "running":
        return _build_plan_response(plan)

    if plan.status in ("completed", "final"):
        plan = ProjectPlan(
            project_id=project_id,
            source_agent_id=plan.source_agent_id,
            plan_type="candidate",
            prompt_text=plan.prompt_text,
            status="running",
            source_path="",
            include_usage=plan.include_usage,
            selected_agent_ids_json=plan.selected_agent_ids_json,
            selected_agent_models_json=plan.selected_agent_models_json,
            dispatched_at=now,
            is_selected=False,
        )
        db.add(plan)
        db.flush()
        selected_agents = _load_project_plan_agents(db, project, user, _parse_selected_agent_ids(plan.selected_agent_ids_json))
        plan.source_path = _plan_file_path(project, plan.id)
        plan.prompt_text, resolved_models = generate_plan_prompt(
            project,
            selected_agents,
            plan.source_path,
            _plan_usage_path(project, plan.id) if plan.include_usage else None,
            _parse_selected_agent_models(plan.selected_agent_models_json),
            get_plan_co_location_guidance(db),
        )
        plan.selected_agent_models_json = _serialize_selected_agent_models(resolved_models)
    else:
        plan.status = "running"
        plan.dispatched_at = now
        plan.detected_at = None
        plan.last_error = None
        plan.updated_at = now

    if project.status == "draft":
        project.status = "planning"
    project.updated_at = now
    db.commit()
    db.refresh(plan)
    return _build_plan_response(plan)


@router.get("/{project_id}/plans", response_model=list[PlanResponse])
async def list_plans(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_owned_project(db, project_id, user)
    plans = db.query(ProjectPlan).filter(ProjectPlan.project_id == project_id).order_by(ProjectPlan.created_at.asc()).all()
    return [_build_plan_response(plan) for plan in plans]


@router.post("/{project_id}/plans/import", response_model=PlanResponse, status_code=201)
def import_plan(project_id: int, body: PlanImport, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_owned_project(db, project_id, user)
    # Accept both JSON string and dict object
    if isinstance(body.plan_json, dict):
        plan_json_str = json.dumps(body.plan_json, ensure_ascii=False)
    else:
        try:
            json.loads(body.plan_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in plan_json")
        plan_json_str = body.plan_json

    now = datetime.now(timezone.utc)
    plan = ProjectPlan(
        project_id=project_id,
        source_agent_id=body.source_agent_id,
        plan_type=body.plan_type,
        plan_json=plan_json_str,
        status="completed",
        source_path=f"{_normalize_collab_dir(project)}/plan.json" if _normalize_collab_dir(project) else "plan.json",
        selected_agent_ids_json="[]",
        selected_agent_models_json="{}",
        detected_at=now,
        is_selected=False,
    )
    db.add(plan)
    if project.status == "draft":
        project.status = "planning"
    project.updated_at = now
    db.commit()
    db.refresh(plan)
    return _build_plan_response(plan)


def finalize_plan_record(
    db: Session,
    project: Project,
    plan: ProjectPlan,
    user: User,
) -> dict:
    # Prevent double finalization
    if plan.plan_type == "final" and plan.is_selected:
        raise HTTPException(status_code=400, detail="Plan already finalized")
    if plan.status != "completed" or not plan.plan_json:
        raise HTTPException(status_code=400, detail="Plan is not ready to finalize")

    # Check if project already has tasks (another plan was finalized)
    existing_tasks = db.query(Task).filter(Task.project_id == project.id).count()
    if existing_tasks > 0:
        raise HTTPException(status_code=400, detail="Project already has tasks from a finalized plan")

    # Parse plan JSON with limited auto-repair
    raw_json = plan.plan_json
    try:
        plan_data = json.loads(raw_json)
    except json.JSONDecodeError:
        repaired = _try_repair_json(raw_json)
        if repaired is None:
            raise HTTPException(status_code=400, detail="Invalid plan JSON")
        plan_data = repaired

    tasks_data = plan_data.get("tasks", [])
    if not tasks_data:
        raise HTTPException(status_code=400, detail="Plan contains no tasks")

    # Normalize task fields for backward compatibility
    tasks_data = _normalize_task_fields(tasks_data)

    # Mark plan as selected/final
    plan.is_selected = True
    plan.plan_type = "final"
    plan.status = "final"
    plan.updated_at = datetime.now(timezone.utc)
    task_timeout_minutes = get_project_polling_settings(db, project)["task_timeout_minutes"]

    # Create task records
    created_tasks = []
    for t in tasks_data:
        # Compatibility aliases for legacy / external plan schemas (T1-ANALYZE F-P0-06, F-P1-03/04)
        if isinstance(t, dict):
            if "depends_on" not in t and "predecessors" in t:
                t["depends_on"] = t.get("predecessors")
            if "task_name" not in t and "title" in t:
                t["task_name"] = t.get("title")
            if "assignee" not in t and "agent_id" in t:
                t["assignee"] = t.get("agent_id")
        task_code = t.get("task_code")
        if not task_code:
            raise HTTPException(status_code=400, detail="Each task must have a task_code")

        # Resolve assignee
        assignee_agent_id = _resolve_assignee_agent_id(db, t.get("assignee"), project, user)

        depends_on = t.get("depends_on", [])
        collab = _normalize_collab_dir(project)
        try:
            expected_output = normalize_expected_output_path(
                t.get("expected_output"),
                default_path=f"outputs/{task_code}/result.json",
                collaboration_dir=collab,
                strict=True,
            )
        except ExpectedOutputPathError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Task {task_code} has invalid expected_output: {exc}",
            ) from exc

        task = Task(
            project_id=project.id,
            plan_id=plan.id,
            task_code=task_code,
            task_name=t.get("task_name", task_code),
            description=t.get("description", ""),
            assignee_agent_id=assignee_agent_id,
            status="pending",
            depends_on_json=json.dumps(depends_on),
            expected_output_path=expected_output,
            timeout_minutes=task_timeout_minutes,
        )
        db.add(task)
        created_tasks.append(task)

    # Update project status
    project.status = "executing"
    project.updated_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "message": "Plan finalized",
        "tasks_created": len(created_tasks),
        "project_status": project.status,
    }


@router.post("/{project_id}/plans/finalize")
def finalize_plan(project_id: int, body: FinalizeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_owned_project(db, project_id, user)

    plan = db.query(ProjectPlan).filter(
        ProjectPlan.id == body.plan_id,
        ProjectPlan.project_id == project_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    return finalize_plan_record(db, project, plan, user)
