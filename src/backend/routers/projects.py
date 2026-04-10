import json
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from access import get_owned_project
from database import get_db
from models import Agent, Project, ProjectPlan, Task, TaskEvent, User
from auth import get_current_user
from services.polling_config_service import get_global_polling_settings
from services.git_service import validate_git_url

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    goal: Optional[str] = None
    git_repo_url: Optional[str] = None
    collaboration_dir: Optional[str] = None
    agent_ids: list[int] = []
    polling_interval_min: Optional[int] = None  # seconds, None = use global default
    polling_interval_max: Optional[int] = None  # seconds, None = use global default
    polling_start_delay_minutes: Optional[int] = None  # None = use global default
    polling_start_delay_seconds: Optional[int] = None  # None = use global default


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    git_repo_url: Optional[str] = None
    collaboration_dir: Optional[str] = None
    status: Optional[str] = None
    agent_ids: Optional[list[int]] = None
    polling_interval_min: Optional[int] = None
    polling_interval_max: Optional[int] = None
    polling_start_delay_minutes: Optional[int] = None
    polling_start_delay_seconds: Optional[int] = None


class ProjectResponse(BaseModel):
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

    class Config:
        from_attributes = True


class ProjectDetailResponse(ProjectResponse):
    next_step: str
    task_summary: dict



def _project_agent_ids(project: Project) -> list[int]:
    if not project.agent_ids_json:
        return []
    try:
        return json.loads(project.agent_ids_json)
    except json.JSONDecodeError:
        return []



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
        'polling_interval_min': project.polling_interval_min,
        'polling_interval_max': project.polling_interval_max,
        'polling_start_delay_minutes': project.polling_start_delay_minutes,
        'polling_start_delay_seconds': project.polling_start_delay_seconds,
    }
    if next_step is not None and task_summary is not None:
        return ProjectDetailResponse(next_step=next_step, task_summary=task_summary, **payload)
    return ProjectResponse(**payload)

def _validate_owned_agent_ids(db: Session, agent_ids: list[int], user: User) -> list[int]:
    if not agent_ids:
        raise HTTPException(status_code=400, detail='At least one agent must be selected')
    agents = db.query(Agent).filter(
        Agent.id.in_(agent_ids),
        Agent.created_by == user.id,
    ).all()
    if len(agents) != len(agent_ids):
        raise HTTPException(status_code=400, detail='Some agent_ids are invalid')
    return agent_ids



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


def _resolve_polling_snapshot(
    db: Session,
    interval_min: Optional[int],
    interval_max: Optional[int],
    delay_minutes: Optional[int],
    delay_seconds: Optional[int],
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
    }


@router.post('', response_model=ProjectResponse, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.git_repo_url:
        try:
            body.git_repo_url = validate_git_url(body.git_repo_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    agent_ids = _validate_owned_agent_ids(db, body.agent_ids, user)
    _validate_polling_params(
        body.polling_interval_min,
        body.polling_interval_max,
        body.polling_start_delay_minutes,
        body.polling_start_delay_seconds,
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
    )
    project = Project(
        name=body.name,
        goal=body.goal,
        git_repo_url=body.git_repo_url,
        collaboration_dir=user_collab,  # may be None, will be defaulted after flush
        created_by=user.id,
        agent_ids_json=json.dumps(agent_ids),
        polling_interval_min=polling_snapshot["polling_interval_min"],
        polling_interval_max=polling_snapshot["polling_interval_max"],
        polling_start_delay_minutes=polling_snapshot["polling_start_delay_minutes"],
        polling_start_delay_seconds=polling_snapshot["polling_start_delay_seconds"],
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
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    if 'git_repo_url' in update_data and update_data['git_repo_url']:
        try:
            update_data['git_repo_url'] = validate_git_url(update_data['git_repo_url'])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if 'agent_ids' in update_data:
        update_data['agent_ids_json'] = json.dumps(_validate_owned_agent_ids(db, update_data.pop('agent_ids'), user))
    if 'collaboration_dir' in update_data:
        update_data['collaboration_dir'] = _normalize_collab_dir_input(update_data['collaboration_dir'])
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
    _validate_polling_params(merged_min, merged_max, merged_delay_minutes, merged_delay_seconds)
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
