import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Project, Task, TaskEvent, User
from auth import get_current_user
from services.path_service import normalize_expected_output_path
from services.prompt_service import generate_task_prompt

router = APIRouter(tags=["tasks"])


class TaskResponse(BaseModel):
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


# Project-scoped task list
@router.get("/api/projects/{project_id}/tasks", response_model=list[TaskResponse])
def list_project_tasks(project_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return db.query(Task).filter(Task.project_id == project_id).all()


# Single task detail
@router.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/api/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    body: TaskUpdateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

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

    now = datetime.now(timezone.utc)
    project = db.query(Project).filter(Project.id == task.project_id).first()
    collab = (project.collaboration_dir or "").strip("/") if project else ""
    task.task_name = task_name
    task.description = body.description
    task.expected_output_path = normalize_expected_output_path(
        body.expected_output_path,
        default_path=f"outputs/{task.task_code}/result.json",
        collaboration_dir=collab,
    )
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="updated",
        detail="Task content updated from UI",
    ))
    db.commit()
    db.refresh(task)
    return task


# Generate execution prompt
@router.post("/api/tasks/{task_id}/generate-prompt", response_model=PromptResponse)
def task_generate_prompt(task_id: int, body: PromptRequest = PromptRequest(), db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = db.query(Project).filter(Project.id == task.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    prompt = generate_task_prompt(db, project, task, include_usage=body.include_usage)
    return PromptResponse(prompt=prompt)


# Dispatch task
@router.post("/api/tasks/{task_id}/dispatch", response_model=TaskResponse)
def dispatch_task(task_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("pending", "needs_attention"):
        raise HTTPException(status_code=400, detail=f"Cannot dispatch task in status: {task.status}")

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
def mark_complete(task_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("running", "needs_attention"):
        raise HTTPException(status_code=400, detail=f"Cannot mark complete a task in status: {task.status}")

    now = datetime.now(timezone.utc)
    task.status = "completed"
    task.completed_at = now
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="manual_complete",
        detail="Manually marked complete",
    ))

    # Check if all tasks in project are completed
    project = db.query(Project).filter(Project.id == task.project_id).first()
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
def abandon_task(task_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
    project = db.query(Project).filter(Project.id == task.project_id).first()
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
def redispatch_task(task_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("needs_attention", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot redispatch task in status: {task.status}")

    now = datetime.now(timezone.utc)
    task.status = "running"
    task.dispatched_at = now
    task.last_error = None
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="redispatched",
        detail="Task redispatched",
    ))
    db.commit()
    db.refresh(task)
    return task
