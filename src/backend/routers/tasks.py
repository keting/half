import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from access import get_owned_project, get_owned_task
from database import get_db
from models import Project, Task, TaskEvent, User
from auth import get_current_user
from schemas import UtcDatetimeModel
from services.path_service import ExpectedOutputPathError, normalize_expected_output_path
from services.prompt_service import generate_task_prompt
from services import git_service

router = APIRouter(tags=["tasks"])


class TaskResponse(UtcDatetimeModel):
    id: int
    project_id: int
    plan_id: int
    task_code: str
    task_name: str
    description: Optional[str]
    assignee_agent_id: Optional[int]
    status: str
    depends_on_json: Optional[str]
    expected_output_path: Optional[str]
    result_file_path: Optional[str]
    usage_file_path: Optional[str]
    last_error: Optional[str]
    timeout_minutes: Optional[int]
    dispatched_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PromptRequest(BaseModel):
    include_usage: bool = False


class PromptResponse(BaseModel):
    prompt: str


class TaskUpdateRequest(BaseModel):
    task_name: str
    description: str = ""
    expected_output_path: str = ""
    timeout_minutes: Optional[int] = None


class TaskDispatchRequest(BaseModel):
    ignore_missing_predecessor_outputs: bool = False


# Project-scoped task list
@router.get("/api/projects/{project_id}/tasks", response_model=list[TaskResponse])
def list_project_tasks(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_owned_project(db, project_id, user)
    return db.query(Task).filter(Task.project_id == project_id).all()


# Single task detail
@router.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = get_owned_task(db, task_id, user)
    return task


@router.put("/api/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    body: TaskUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = get_owned_task(db, task_id, user)

    depends_on: list[str] = []
    try:
        depends_on = json.loads(task.depends_on_json or "[]")
    except json.JSONDecodeError:
        depends_on = []

    if depends_on:
        predecessor_tasks = db.query(Task).filter(
            Task.project_id == task.project_id,
            Task.task_code.in_(depends_on),
        ).all()
        predecessor_map = {predecessor.task_code: predecessor for predecessor in predecessor_tasks}
        blocked_codes = [
            code for code in depends_on
            if code not in predecessor_map or predecessor_map[code].status not in ("completed", "abandoned")
        ]
        if blocked_codes:
            raise HTTPException(status_code=400, detail="Task cannot be edited before predecessors are completed or abandoned")

    if task.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot edit task in status: {task.status}")

    task_name = body.task_name.strip()
    if not task_name:
        raise HTTPException(status_code=400, detail="task_name is required")
    timeout_minutes = body.timeout_minutes if body.timeout_minutes is not None else task.timeout_minutes
    if timeout_minutes is None:
        timeout_minutes = 10
    if timeout_minutes < 1 or timeout_minutes > 120:
        raise HTTPException(status_code=400, detail="timeout_minutes must be 1-120 minutes")

    now = datetime.now(timezone.utc)
    project = db.query(Project).filter(Project.id == task.project_id).first()
    collab = (project.collaboration_dir or "").strip("/") if project else ""
    task.task_name = task_name
    task.description = body.description
    task.timeout_minutes = timeout_minutes
    try:
        task.expected_output_path = normalize_expected_output_path(
            body.expected_output_path,
            default_path=f"outputs/{task.task_code}/result.json",
            collaboration_dir=collab,
            strict=True,
        )
    except ExpectedOutputPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="updated",
        detail="Task content updated from UI",
    ))
    db.commit()
    db.refresh(task)
    return task


class MissingPredecessor(BaseModel):
    task_code: str
    task_name: str
    expected_path: str


class PredecessorStatusResponse(BaseModel):
    task_id: int
    ready: bool
    missing: list[MissingPredecessor]
    refreshed: bool


def _compute_predecessor_status(db: Session, task: Task, refresh: bool) -> PredecessorStatusResponse:
    project = db.query(Project).filter(Project.id == task.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Server-side git fetch/pull is intentionally NOT triggered here. Pulling on
    # the deploy host is meaningless for dispatch — the executing Agent runs on
    # its own machine and is responsible for `git pull` before reading
    # predecessor outputs (the generated prompt enforces this). This endpoint is
    # now kept only for compatibility/diagnostic purposes and does not
    # participate in the normal page-side dispatch flow.
    refreshed = False

    try:
        depends_on = json.loads(task.depends_on_json or "[]")
    except json.JSONDecodeError:
        depends_on = []

    missing: list[MissingPredecessor] = []
    if depends_on:
        collab = (project.collaboration_dir or "").strip("/")
        predecessors = db.query(Task).filter(
            Task.project_id == project.id,
            Task.task_code.in_(depends_on),
        ).all()
        pmap = {p.task_code: p for p in predecessors}
        for code in depends_on:
            p = pmap.get(code)
            if not p:
                missing.append(MissingPredecessor(task_code=code, task_name="(未知)", expected_path=""))
                continue
            if p.status == "abandoned":
                continue
            if p.status != "completed":
                missing.append(
                    MissingPredecessor(
                        task_code=p.task_code,
                        task_name=p.task_name,
                        expected_path=p.result_file_path or p.expected_output_path or "",
                    )
                )
                continue
            try:
                path = p.result_file_path or normalize_expected_output_path(
                    p.expected_output_path,
                    default_path=f"outputs/{p.task_code}/result.json",
                    collaboration_dir=collab,
                    strict=True,
                )
            except ExpectedOutputPathError:
                missing.append(MissingPredecessor(task_code=p.task_code, task_name=p.task_name, expected_path="(invalid expected_output_path)"))
                continue
            exists = git_service.file_exists(project.id, path, git_repo_url=project.git_repo_url)
            if not exists:
                missing.append(MissingPredecessor(task_code=p.task_code, task_name=p.task_name, expected_path=path))

    return PredecessorStatusResponse(
        task_id=task.id,
        ready=len(missing) == 0,
        missing=missing,
        refreshed=refreshed,
    )


@router.get("/api/tasks/{task_id}/predecessor-status", response_model=PredecessorStatusResponse)
def get_predecessor_status(task_id: int, refresh: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = get_owned_task(db, task_id, user)
    return _compute_predecessor_status(db, task, refresh=refresh)


@router.get("/api/projects/{project_id}/predecessor-status", response_model=list[PredecessorStatusResponse])
def list_project_predecessor_status(project_id: int, refresh: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_owned_project(db, project_id, user)

    # Server-side git fetch/pull is intentionally NOT triggered here. See the
    # rationale in `_compute_predecessor_status`.
    _ = refresh
    tasks = db.query(Task).filter(Task.project_id == project_id).all()

    # The project detail page uses this batch endpoint to split pending tasks
    # into ready vs blocked queues. For that UI decision, dependency status is
    # authoritative: completed/abandoned predecessors unblock the task, while
    # missing or unfinished predecessors keep it blocked. We intentionally do
    # not check Git file existence here because demo and diagnostic projects may
    # carry result_file_path metadata without requiring a public committed file.
    collab = (project.collaboration_dir or "").strip("/")
    code_to_task: dict[str, Task] = {t.task_code: t for t in tasks if t.task_code}

    results: list[PredecessorStatusResponse] = []
    for task in tasks:
        try:
            depends_on = json.loads(task.depends_on_json or "[]")
        except json.JSONDecodeError:
            depends_on = []

        missing: list[MissingPredecessor] = []
        for code in depends_on:
            p = code_to_task.get(code)
            if not p:
                missing.append(MissingPredecessor(task_code=code, task_name="(未知)", expected_path=""))
                continue
            if p.status == "abandoned":
                continue
            if p.status != "completed":
                missing.append(
                    MissingPredecessor(
                        task_code=p.task_code,
                        task_name=p.task_name,
                        expected_path=p.result_file_path or p.expected_output_path or "",
                    )
                )
                continue
            try:
                normalize_expected_output_path(
                    p.result_file_path or p.expected_output_path,
                    default_path=f"outputs/{p.task_code}/result.json",
                    collaboration_dir=collab,
                    strict=True,
                )
            except ExpectedOutputPathError:
                missing.append(
                    MissingPredecessor(task_code=p.task_code, task_name=p.task_name, expected_path="(invalid expected_output_path)")
                )

        results.append(
            PredecessorStatusResponse(
                task_id=task.id,
                ready=len(missing) == 0,
                missing=missing,
                refreshed=False,
            )
        )
    return results


# Generate execution prompt
@router.post("/api/tasks/{task_id}/generate-prompt", response_model=PromptResponse)
def task_generate_prompt(task_id: int, body: PromptRequest = PromptRequest(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = get_owned_task(db, task_id, user)
    project = get_owned_project(db, task.project_id, user)
    prompt = generate_task_prompt(db, project, task, include_usage=body.include_usage)
    return PromptResponse(prompt=prompt)


# Dispatch task
def _validate_dispatch_predecessors(
    db: Session,
    task: Task,
    *,
    ignore_missing_predecessor_outputs: bool,
) -> None:
    depends_on: list[str] = []
    try:
        depends_on = json.loads(task.depends_on_json or "[]")
    except json.JSONDecodeError:
        depends_on = []

    if depends_on:
        predecessor_tasks = db.query(Task).filter(
            Task.project_id == task.project_id,
            Task.task_code.in_(depends_on),
        ).all()
        predecessor_map = {predecessor.task_code: predecessor for predecessor in predecessor_tasks}
        blocked_codes = [
            code for code in depends_on
            if code not in predecessor_map or predecessor_map[code].status not in ("completed", "abandoned")
        ]
        if blocked_codes:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot dispatch task before predecessors are completed or abandoned: {', '.join(blocked_codes)}",
            )

    # NOTE: Predecessor output file presence is no longer enforced on the
    # server. The deploy host should not git fetch/pull on demand — that
    # operation is only meaningful on the Agent's own machine, and the
    # generated prompt instructs the Agent to `git pull` before reading
    # predecessor outputs. We trust predecessor task statuses (above) and
    # leave file-level verification to the Agent. The
    # `ignore_missing_predecessor_outputs` flag is kept on the request for
    # API compatibility but is now a no-op.
    _ = ignore_missing_predecessor_outputs


@router.post("/api/tasks/{task_id}/dispatch", response_model=TaskResponse)
def dispatch_task(
    task_id: int,
    body: TaskDispatchRequest = TaskDispatchRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = get_owned_task(db, task_id, user)
    if task.status not in ("pending", "needs_attention"):
        raise HTTPException(status_code=400, detail=f"Cannot dispatch task in status: {task.status}")

    _validate_dispatch_predecessors(
        db,
        task,
        ignore_missing_predecessor_outputs=body.ignore_missing_predecessor_outputs,
    )

    now = datetime.now(timezone.utc)
    task.status = "running"
    task.dispatched_at = now
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="dispatched",
        detail="Task dispatched, timer started",
    ))
    db.commit()
    db.refresh(task)
    return task


# Mark complete
@router.post("/api/tasks/{task_id}/mark-complete", response_model=TaskResponse)
def mark_complete(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = get_owned_task(db, task_id, user)
    if task.status not in ("running", "needs_attention"):
        raise HTTPException(status_code=400, detail=f"Cannot mark complete a task in status: {task.status}")

    now = datetime.now(timezone.utc)
    task.status = "completed"
    task.completed_at = now
    task.last_error = None
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="manual_complete",
        detail="Manually marked complete",
    ))

    # Check if all tasks in project are completed
    project = get_owned_project(db, task.project_id, user)
    if project and project.status == "executing":
        all_tasks = db.query(Task).filter(Task.project_id == project.id).all()
        if all(t.status in ("completed", "abandoned") or t.id == task.id for t in all_tasks):
            project.status = "completed"
            project.updated_at = now

    db.commit()
    db.refresh(task)
    return task


# Abandon task
@router.post("/api/tasks/{task_id}/abandon", response_model=TaskResponse)
def abandon_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = get_owned_task(db, task_id, user)
    if task.status in ("completed", "abandoned"):
        raise HTTPException(status_code=400, detail=f"Cannot abandon a task in status: {task.status}")

    now = datetime.now(timezone.utc)
    task.status = "abandoned"
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="abandoned",
        detail="Task abandoned",
    ))

    # Check if all tasks in project are completed or abandoned
    project = get_owned_project(db, task.project_id, user)
    if project and project.status == "executing":
        all_tasks = db.query(Task).filter(Task.project_id == project.id).all()
        if all(t.status in ("completed", "abandoned") or t.id == task.id for t in all_tasks):
            project.status = "completed"
            project.updated_at = now

    db.commit()
    db.refresh(task)
    return task


# Redispatch task
@router.post("/api/tasks/{task_id}/redispatch", response_model=TaskResponse)
def redispatch_task(
    task_id: int,
    body: TaskDispatchRequest = TaskDispatchRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = get_owned_task(db, task_id, user)
    if task.status not in ("needs_attention", "running", "abandoned"):
        raise HTTPException(status_code=400, detail=f"Cannot redispatch task in status: {task.status}")

    _validate_dispatch_predecessors(
        db,
        task,
        ignore_missing_predecessor_outputs=body.ignore_missing_predecessor_outputs,
    )

    now = datetime.now(timezone.utc)
    prev_status = task.status
    prev_error = task.last_error
    task.status = "running"
    task.dispatched_at = now
    task.last_error = None
    task.updated_at = now
    detail = (
        f"Task redispatched from {prev_status}. Previous error: {prev_error}"
        if prev_error
        else f"Task redispatched from {prev_status}"
    )
    db.add(TaskEvent(
        task_id=task.id,
        event_type="redispatched",
        detail=detail,
    ))

    # If project was completed but we're re-dispatching, set it back to executing
    project = get_owned_project(db, task.project_id, user)
    if project and project.status == "completed":
        project.status = "executing"
        project.updated_at = now

    db.commit()
    db.refresh(task)
    return task
