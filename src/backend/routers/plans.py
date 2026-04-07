import json
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, Project, ProjectPlan, Task, User
from services.path_service import normalize_expected_output_path
from auth import get_current_user
from services.prompt_service import generate_plan_prompt

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
    plan_json: str
    source_agent_id: Optional[int] = None
    plan_type: str = "candidate"


class PlanResponse(BaseModel):
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


def _resolve_assignee_agent_id(db: Session, assignee: Optional[str]) -> Optional[int]:
    normalized = _normalize_assignee_token(assignee)
    if not normalized:
        return None

    agents = db.query(Agent).all()
    exact_slug = next((agent for agent in agents if _normalize_assignee_token(agent.slug) == normalized), None)
    if exact_slug:
        return exact_slug.id

    exact_name = next((agent for agent in agents if _normalize_assignee_token(agent.name) == normalized), None)
    if exact_name:
        return exact_name.id

    exact_type = next((agent for agent in agents if _normalize_assignee_token(agent.agent_type) == normalized), None)
    if exact_type:
        return exact_type.id

    return None


class FinalizeRequest(BaseModel):
    plan_id: int


@router.post("/{project_id}/plans/generate-prompt", response_model=PromptResponse)
def plan_generate_prompt(
    project_id: int,
    body: PlanPromptRequest = PlanPromptRequest(),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    selected_agents = db.query(Agent).filter(Agent.id.in_(body.selected_agent_ids)).all() if body.selected_agent_ids else []
    if len(selected_agents) != len(body.selected_agent_ids):
        raise HTTPException(status_code=400, detail="Some selected agents do not exist")
    if not selected_agents:
        raise HTTPException(status_code=400, detail="At least one participating agent must be selected")
    selected_agent_models = {}
    for agent in selected_agents:
        selected_model = body.selected_agent_models.get(agent.id)
        if selected_model:
            selected_agent_models[agent.id] = selected_model

    now = datetime.now(timezone.utc)
    plan = ProjectPlan(
        project_id=project_id,
        source_agent_id=None,
        plan_type="candidate",
        prompt_text="",
        status="pending",
        source_path="",
        include_usage=body.include_usage,
        selected_agent_ids_json=json.dumps(body.selected_agent_ids),
        selected_agent_models_json=_serialize_selected_agent_models(selected_agent_models),
        is_selected=False,
    )
    db.add(plan)
    db.flush()

    source_path = _plan_file_path(project, plan.id)
    usage_path = _plan_usage_path(project, plan.id) if body.include_usage else None
    prompt, resolved_models = generate_plan_prompt(project, selected_agents, source_path, usage_path, selected_agent_models)
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
    _user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

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
        selected_agents = db.query(Agent).filter(Agent.id.in_(_parse_selected_agent_ids(plan.selected_agent_ids_json))).all()
        plan.source_path = _plan_file_path(project, plan.id)
        plan.prompt_text, resolved_models = generate_plan_prompt(
            project,
            selected_agents,
            plan.source_path,
            _plan_usage_path(project, plan.id) if plan.include_usage else None,
            _parse_selected_agent_models(plan.selected_agent_models_json),
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
def list_plans(project_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    plans = db.query(ProjectPlan).filter(ProjectPlan.project_id == project_id).order_by(ProjectPlan.created_at.asc()).all()
    return [_build_plan_response(plan) for plan in plans]


@router.post("/{project_id}/plans/import", response_model=PlanResponse, status_code=201)
def import_plan(project_id: int, body: PlanImport, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Validate JSON
    try:
        json.loads(body.plan_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in plan_json")

    now = datetime.now(timezone.utc)
    plan = ProjectPlan(
        project_id=project_id,
        source_agent_id=body.source_agent_id,
        plan_type=body.plan_type,
        plan_json=body.plan_json,
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


@router.post("/{project_id}/plans/finalize")
def finalize_plan(project_id: int, body: FinalizeRequest, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    plan = db.query(ProjectPlan).filter(
        ProjectPlan.id == body.plan_id,
        ProjectPlan.project_id == project_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    # Prevent double finalization
    if plan.plan_type == "final" and plan.is_selected:
        raise HTTPException(status_code=400, detail="Plan already finalized")
    if plan.status != "completed" or not plan.plan_json:
        raise HTTPException(status_code=400, detail="Plan is not ready to finalize")

    # Check if project already has tasks (another plan was finalized)
    existing_tasks = db.query(Task).filter(Task.project_id == project_id).count()
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

    # Mark plan as selected/final
    plan.is_selected = True
    plan.plan_type = "final"
    plan.status = "final"
    plan.updated_at = datetime.now(timezone.utc)

    # Create task records
    created_tasks = []
    for t in tasks_data:
        task_code = t.get("task_code")
        if not task_code:
            raise HTTPException(status_code=400, detail="Each task must have a task_code")

        # Resolve assignee
        assignee_agent_id = _resolve_assignee_agent_id(db, t.get("assignee"))

        depends_on = t.get("depends_on", [])
        collab = _normalize_collab_dir(project)
        expected_output = normalize_expected_output_path(
            t.get("expected_output"),
            default_path=f"outputs/{task_code}/result.json",
            collaboration_dir=collab,
        )

        task = Task(
            project_id=project_id,
            plan_id=plan.id,
            task_code=task_code,
            task_name=t.get("task_name", task_code),
            description=t.get("description", ""),
            assignee_agent_id=assignee_agent_id,
            status="pending",
            depends_on_json=json.dumps(depends_on),
            expected_output_path=expected_output,
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
