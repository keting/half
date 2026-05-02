import json
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from access import get_owned_project
from database import get_db
from models import Agent, Project, ProjectPlan, Task, TaskEvent, User
from auth import get_current_user
from schemas import UtcDatetimeModel
from services.polling_config_service import get_global_polling_settings
from services.git_service import validate_git_url
from services.project_agents import (
    agent_ids_from_assignments_json,
    parse_agent_assignments_json,
    serialize_agent_assignments,
)
from services.agents import derive_agent_status

router = APIRouter(prefix="/api/projects", tags=["projects"])

DEFAULT_PLANNING_MODE = "balanced"
VALID_PLANNING_MODES = {"balanced", "quality", "cost_effective", "speed"}
UNAVAILABLE_AGENT_DETAIL = "Some selected agents are unavailable"
GIT_REPO_URL_REQUIRED_DETAIL = "Git 仓库地址不能为空。"


def _normalize_planning_mode(value: Optional[str]) -> str:
    normalized = (value or DEFAULT_PLANNING_MODE).strip()
    if normalized not in VALID_PLANNING_MODES:
        raise HTTPException(status_code=400, detail="Invalid planning_mode")
    return normalized


def _validate_required_git_repo_url(value: Optional[str]) -> str:
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail=GIT_REPO_URL_REQUIRED_DETAIL)
    try:
        normalized = validate_git_url(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not normalized:
        raise HTTPException(status_code=400, detail=GIT_REPO_URL_REQUIRED_DETAIL)
    return normalized


class AgentAssignment(BaseModel):
    id: int
    co_located: bool = False


class ProjectCreate(BaseModel):
    name: str
    goal: Optional[str] = None
    git_repo_url: Optional[str] = None
    collaboration_dir: Optional[str] = None
    agent_ids: list[int] = Field(default_factory=list)
    agent_assignments: Optional[list[AgentAssignment]] = None
    polling_interval_min: Optional[int] = None  # seconds, None = use global default
    polling_interval_max: Optional[int] = None  # seconds, None = use global default
    polling_start_delay_minutes: Optional[int] = None  # None = use global default
    polling_start_delay_seconds: Optional[int] = None  # None = use global default
    task_timeout_minutes: Optional[int] = None
    planning_mode: str = DEFAULT_PLANNING_MODE
    template_inputs: Optional[object] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    git_repo_url: Optional[str] = None
    collaboration_dir: Optional[str] = None
    status: Optional[str] = None
    agent_ids: Optional[list[int]] = None
    agent_assignments: Optional[list[AgentAssignment]] = None
    polling_interval_min: Optional[int] = None
    polling_interval_max: Optional[int] = None
    polling_start_delay_minutes: Optional[int] = None
    polling_start_delay_seconds: Optional[int] = None
    task_timeout_minutes: Optional[int] = None
    planning_mode: Optional[str] = None
    template_inputs: Optional[object] = None


class ProjectResponse(UtcDatetimeModel):
    id: int
    name: str
    goal: Optional[str]
    git_repo_url: Optional[str]
    collaboration_dir: Optional[str]
    status: str
    created_by: Optional[int]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    agent_ids: list[int]
    polling_interval_min: Optional[int]
    polling_interval_max: Optional[int]
    polling_start_delay_minutes: Optional[int]
    polling_start_delay_seconds: Optional[int]
    task_timeout_minutes: Optional[int]
    planning_mode: str
    template_inputs: dict[str, str]
    agent_assignments: list[AgentAssignment]

    class Config:
        from_attributes = True


class ProjectDetailResponse(ProjectResponse):
    next_step: str
    task_summary: dict



def _project_agent_ids(project: Project) -> list[int]:
    return agent_ids_from_assignments_json(project.agent_ids_json)


def _project_agent_assignments(project: Project) -> list[AgentAssignment]:
    return [AgentAssignment(**item) for item in parse_agent_assignments_json(project.agent_ids_json)]


def _normalize_template_inputs(value: object | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="template_inputs must be an object")
    normalized: dict[str, str] = {}
    for key, raw_value in value.items():
        if not isinstance(key, str) or not key.strip():
            raise HTTPException(status_code=400, detail="template_inputs keys must be non-empty strings")
        if isinstance(raw_value, (dict, list)):
            raise HTTPException(status_code=400, detail="template_inputs values must be scalar")
        normalized[key.strip()] = "" if raw_value is None else str(raw_value)
    return normalized


def _parse_template_inputs_json(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    try:
        return _normalize_template_inputs(parsed)
    except HTTPException:
        return {}



def _build_project_response(project: Project, next_step: Optional[str] = None, task_summary: Optional[dict] = None) -> ProjectResponse | ProjectDetailResponse:
    payload = {
        'id': project.id,
        'name': project.name,
        'goal': project.goal,
        'git_repo_url': project.git_repo_url,
        'collaboration_dir': project.collaboration_dir,
        'status': project.status,
        'created_by': project.created_by,
        'created_at': project.created_at,
        'updated_at': project.updated_at,
        'agent_ids': _project_agent_ids(project),
        'agent_assignments': _project_agent_assignments(project),
        'polling_interval_min': project.polling_interval_min,
        'polling_interval_max': project.polling_interval_max,
        'polling_start_delay_minutes': project.polling_start_delay_minutes,
        'polling_start_delay_seconds': project.polling_start_delay_seconds,
        'task_timeout_minutes': project.task_timeout_minutes,
        'planning_mode': _normalize_planning_mode(getattr(project, 'planning_mode', None)),
        'template_inputs': _parse_template_inputs_json(getattr(project, 'template_inputs_json', None)),
    }
    if next_step is not None and task_summary is not None:
        return ProjectDetailResponse(next_step=next_step, task_summary=task_summary, **payload)
    return ProjectResponse(**payload)


def _raise_unavailable_agent_error(agent_ids: list[int]) -> None:
    raise HTTPException(
        status_code=400,
        detail={
            "message": UNAVAILABLE_AGENT_DETAIL,
            "unavailable_agent_ids": agent_ids,
        },
    )


def _load_owned_agents(db: Session, agent_ids: list[int], user: User) -> list[Agent]:
    if not agent_ids:
        raise HTTPException(status_code=400, detail='At least one agent must be selected')
    if len(set(agent_ids)) != len(agent_ids):
        raise HTTPException(status_code=400, detail='Some agent_ids are duplicated')
    agents = db.query(Agent).filter(
        Agent.id.in_(agent_ids),
        Agent.created_by == user.id,
    ).all()
    if len(agents) != len(agent_ids):
        raise HTTPException(status_code=400, detail='Some agent_ids are invalid')
    agents_by_id = {agent.id: agent for agent in agents}
    return [agents_by_id[agent_id] for agent_id in agent_ids]


def _validate_owned_agent_assignments(
    db: Session,
    assignments: list[dict],
    user: User,
    allow_keep_ids: set[int] | None = None,
) -> list[dict[str, int | bool]]:
    agent_ids = [int(item.get("id")) for item in assignments]
    owned_agents = _load_owned_agents(db, agent_ids, user)
    keep_ids = allow_keep_ids or set()
    unavailable_agent_ids = [
        agent.id
        for agent in owned_agents
        if derive_agent_status(agent) == "unavailable" and agent.id not in keep_ids
    ]
    if unavailable_agent_ids:
        _raise_unavailable_agent_error(unavailable_agent_ids)
    return [
        {"id": int(item.get("id")), "co_located": bool(item.get("co_located", False))}
        for item in assignments
    ]


def _agent_assignments_from_ids(
    db: Session,
    agent_ids: list[int],
    user: User,
    allow_keep_ids: set[int] | None = None,
) -> list[dict[str, int | bool]]:
    agents = _load_owned_agents(db, agent_ids, user)
    keep_ids = allow_keep_ids or set()
    unavailable_agent_ids = [
        agent.id
        for agent in agents
        if derive_agent_status(agent) == "unavailable" and agent.id not in keep_ids
    ]
    if unavailable_agent_ids:
        _raise_unavailable_agent_error(unavailable_agent_ids)
    agents_by_id = {agent.id: agent for agent in agents}
    return [
        {"id": agent_id, "co_located": bool(agents_by_id[agent_id].co_located)}
        for agent_id in agent_ids
    ]


def _project_assignments_from_body(
    db: Session,
    body: ProjectCreate | ProjectUpdate,
    user: User,
    allow_keep_ids: set[int] | None = None,
) -> list[dict[str, int | bool]]:
    if body.agent_assignments is not None:
        return _validate_owned_agent_assignments(
            db,
            [item.model_dump() for item in body.agent_assignments],
            user,
            allow_keep_ids=allow_keep_ids,
        )
    return _agent_assignments_from_ids(db, body.agent_ids or [], user, allow_keep_ids=allow_keep_ids)



def compute_next_step(db: Session, project: Project) -> tuple[str, dict]:
    tasks = db.query(Task).filter(Task.project_id == project.id).all()
    plans = db.query(ProjectPlan).filter(ProjectPlan.project_id == project.id).all()
    summary = {
        'total': len(tasks),
        'pending': sum(1 for t in tasks if t.status == 'pending'),
        'running': sum(1 for t in tasks if t.status == 'running'),
        'completed': sum(1 for t in tasks if t.status == 'completed'),
        'needs_attention': sum(1 for t in tasks if t.status == 'needs_attention'),
        'abandoned': sum(1 for t in tasks if t.status == 'abandoned'),
    }

    if project.status == 'draft':
        return 'Create project plan', summary

    if project.status == 'planning':
        running_plans = sum(1 for plan in plans if plan.status == 'running')
        completed_plans = sum(1 for plan in plans if plan.status in ('completed', 'final') and plan.plan_json)
        if running_plans > 0:
            return 'Waiting for plan generation', summary
        if completed_plans > 0:
            return 'Review and finalize plan', summary
        return 'Create project plan', summary

    if project.status == 'executing':
        if tasks and all(t.status in ('completed', 'abandoned') for t in tasks):
            return 'View execution summary', summary

        completed_codes = {t.task_code for t in tasks if t.status in ('completed', 'abandoned')}
        for t in tasks:
            if t.status == 'pending':
                deps = json.loads(t.depends_on_json) if t.depends_on_json else []
                if all(d in completed_codes for d in deps):
                    return f'Dispatch task: {t.task_code} - {t.task_name}', summary

        if any(t.status == 'running' for t in tasks):
            return 'Waiting for running tasks to complete', summary
        if any(t.status == 'needs_attention' for t in tasks):
            return 'Handle tasks that need attention', summary
        return 'View execution summary', summary

    if project.status == 'completed':
        return 'View execution summary', summary

    return 'No action available', summary


@router.get('', response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    projects = db.query(Project).filter(Project.created_by == user.id).all()
    return [_build_project_response(project) for project in projects]


def _normalize_collab_dir_input(value: Optional[str]) -> Optional[str]:
    """Strip leading/trailing slashes so the value is a clean repo-relative path.
    Required because os.path.join treats absolute-looking paths as absolute and
    discards the repo prefix."""
    if value is None:
        return None
    cleaned = value.strip().strip("/")
    return cleaned or None


def _generate_default_collab_dir(db: Session, project_id: int) -> str:
    # Keep numeric project_id for stable routing, and add a short random suffix
    # so default collaboration_dir stays unique even if ids are reused in edge cases.
    for _ in range(10):
        suffix = secrets.token_hex(3)
        candidate = f"outputs/proj-{project_id}-{suffix}"
        exists = db.query(Project).filter(Project.collaboration_dir == candidate).first()
        if not exists:
            return candidate
    return f"outputs/proj-{project_id}-{secrets.token_hex(5)}"


def _validate_polling_params(
    interval_min: Optional[int],
    interval_max: Optional[int],
    delay_minutes: Optional[int],
    delay_seconds: Optional[int],
    task_timeout_minutes: Optional[int] = None,
) -> None:
    """Validate polling configuration values. Raises HTTPException on invalid input."""
    if interval_min is not None:
        if interval_min < 1 or interval_min > 600:
            raise HTTPException(status_code=400, detail="polling_interval_min must be 1-600 seconds")
    if interval_max is not None:
        if interval_max < 1 or interval_max > 600:
            raise HTTPException(status_code=400, detail="polling_interval_max must be 1-600 seconds")
    if interval_min is not None and interval_max is not None:
        if interval_min > interval_max:
            raise HTTPException(
                status_code=400,
                detail="polling_interval_min must be <= polling_interval_max",
            )
    if delay_minutes is not None:
        if delay_minutes < 0 or delay_minutes > 60:
            raise HTTPException(status_code=400, detail="polling_start_delay_minutes must be 0-60")
    if delay_seconds is not None:
        if delay_seconds < 0 or delay_seconds > 59:
            raise HTTPException(status_code=400, detail="polling_start_delay_seconds must be 0-59")
    if task_timeout_minutes is not None:
        if task_timeout_minutes < 1 or task_timeout_minutes > 120:
            raise HTTPException(status_code=400, detail="task_timeout_minutes must be 1-120 minutes")


def _resolve_polling_snapshot(
    db: Session,
    interval_min: Optional[int],
    interval_max: Optional[int],
    delay_minutes: Optional[int],
    delay_seconds: Optional[int],
    task_timeout_minutes: Optional[int],
) -> dict:
    """Resolve project-level polling values, snapshotting global defaults for any
    field the user did not explicitly provide. This guarantees that subsequent
    changes to the global settings do NOT silently shift behavior of existing
    projects: each project carries its own immutable snapshot at creation time."""
    global_defaults = get_global_polling_settings(db)
    return {
        "polling_interval_min": (
            interval_min if interval_min is not None else global_defaults["polling_interval_min"]
        ),
        "polling_interval_max": (
            interval_max if interval_max is not None else global_defaults["polling_interval_max"]
        ),
        "polling_start_delay_minutes": (
            delay_minutes if delay_minutes is not None else global_defaults["polling_start_delay_minutes"]
        ),
        "polling_start_delay_seconds": (
            delay_seconds if delay_seconds is not None else global_defaults["polling_start_delay_seconds"]
        ),
        "task_timeout_minutes": (
            task_timeout_minutes if task_timeout_minutes is not None else global_defaults["task_timeout_minutes"]
        ),
    }


@router.post('', response_model=ProjectResponse, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    body.git_repo_url = _validate_required_git_repo_url(body.git_repo_url)
    agent_assignments = _project_assignments_from_body(db, body, user, allow_keep_ids=set())
    _validate_polling_params(
        body.polling_interval_min,
        body.polling_interval_max,
        body.polling_start_delay_minutes,
        body.polling_start_delay_seconds,
        body.task_timeout_minutes,
    )
    user_collab = _normalize_collab_dir_input(body.collaboration_dir)
    # Snapshot global defaults into project-level fields. After this, the
    # project carries its own concrete values and is unaffected by later
    # changes to the global settings.
    polling_snapshot = _resolve_polling_snapshot(
        db,
        body.polling_interval_min,
        body.polling_interval_max,
        body.polling_start_delay_minutes,
        body.polling_start_delay_seconds,
        body.task_timeout_minutes,
    )
    project = Project(
        name=body.name,
        goal=body.goal,
        git_repo_url=body.git_repo_url,
        collaboration_dir=user_collab,  # may be None, will be defaulted after flush
        created_by=user.id,
        agent_ids_json=serialize_agent_assignments(agent_assignments),
        polling_interval_min=polling_snapshot["polling_interval_min"],
        polling_interval_max=polling_snapshot["polling_interval_max"],
        polling_start_delay_minutes=polling_snapshot["polling_start_delay_minutes"],
        polling_start_delay_seconds=polling_snapshot["polling_start_delay_seconds"],
        task_timeout_minutes=polling_snapshot["task_timeout_minutes"],
        planning_mode=_normalize_planning_mode(body.planning_mode),
        template_inputs_json=json.dumps(_normalize_template_inputs(body.template_inputs), ensure_ascii=False),
    )
    if project.created_by is None:
        raise HTTPException(status_code=500, detail="created_by must not be None")
    db.add(project)
    # Flush to get the auto-generated id, then default the collaboration_dir
    # to outputs/proj-<id>-<random> if user didn't provide one. This guarantees
    # each project has a collision-resistant output directory.
    db.flush()
    if not user_collab:
        project.collaboration_dir = _generate_default_collab_dir(db, project.id)
    db.commit()
    db.refresh(project)
    return _build_project_response(project)


@router.get('/{project_id}', response_model=ProjectDetailResponse)
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_owned_project(db, project_id, user)
    next_step, task_summary = compute_next_step(db, project)
    return _build_project_response(project, next_step=next_step, task_summary=task_summary)


@router.put('/{project_id}', response_model=ProjectResponse)
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_owned_project(db, project_id, user)
    update_data = body.model_dump(exclude_unset=True)
    allow_keep_ids = set(_project_agent_ids(project))
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    if 'git_repo_url' in update_data:
        update_data['git_repo_url'] = _validate_required_git_repo_url(update_data['git_repo_url'])
    elif not project.git_repo_url or not project.git_repo_url.strip():
        raise HTTPException(status_code=400, detail=GIT_REPO_URL_REQUIRED_DETAIL)
    if 'agent_assignments' in update_data:
        update_data.pop('agent_ids', None)
        update_data['agent_ids_json'] = serialize_agent_assignments(
            _validate_owned_agent_assignments(
                db,
                update_data.pop('agent_assignments'),
                user,
                allow_keep_ids=allow_keep_ids,
            )
        )
    elif 'agent_ids' in update_data:
        update_data['agent_ids_json'] = serialize_agent_assignments(
            _agent_assignments_from_ids(
                db,
                update_data.pop('agent_ids'),
                user,
                allow_keep_ids=allow_keep_ids,
            )
        )
    if 'collaboration_dir' in update_data:
        update_data['collaboration_dir'] = _normalize_collab_dir_input(update_data['collaboration_dir'])
    if update_data.get('task_timeout_minutes') is None and 'task_timeout_minutes' in update_data:
        update_data['task_timeout_minutes'] = get_global_polling_settings(db)["task_timeout_minutes"]
    if 'planning_mode' in update_data:
        update_data['planning_mode'] = _normalize_planning_mode(update_data['planning_mode'])
    if 'template_inputs' in update_data:
        update_data['template_inputs_json'] = json.dumps(
            _normalize_template_inputs(update_data.pop('template_inputs')),
            ensure_ascii=False,
        )
    # Validate polling fields against the merged final state so cross-field
    # constraints (min <= max) are enforced even when only one is updated.
    merged_min = update_data.get('polling_interval_min', project.polling_interval_min)
    merged_max = update_data.get('polling_interval_max', project.polling_interval_max)
    merged_delay_minutes = update_data.get(
        'polling_start_delay_minutes', project.polling_start_delay_minutes
    )
    merged_delay_seconds = update_data.get(
        'polling_start_delay_seconds', project.polling_start_delay_seconds
    )
    merged_task_timeout = update_data.get('task_timeout_minutes', project.task_timeout_minutes)
    _validate_polling_params(merged_min, merged_max, merged_delay_minutes, merged_delay_seconds, merged_task_timeout)
    for key, value in update_data.items():
        setattr(project, key, value)
    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return _build_project_response(project)


@router.delete('/{project_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_owned_project(db, project_id, user)

    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    task_ids = [task.id for task in tasks]
    if task_ids:
        db.query(TaskEvent).filter(TaskEvent.task_id.in_(task_ids)).delete(synchronize_session=False)
    db.query(Task).filter(Task.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectPlan).filter(ProjectPlan.project_id == project_id).delete(synchronize_session=False)
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
