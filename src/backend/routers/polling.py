import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Project, Task, TaskEvent, User
from auth import get_current_user
from services.polling_service import poll_project
from services.polling_config_service import get_project_polling_settings

router = APIRouter(prefix="/api/projects", tags=["polling"])


@router.get("/{project_id}/polling-config")
def get_polling_config(project_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """Get the effective polling configuration for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    settings = get_project_polling_settings(db, project)
    return {
        "polling_interval_min": settings["polling_interval_min"],
        "polling_interval_max": settings["polling_interval_max"],
        "polling_start_delay_minutes": settings["polling_start_delay_minutes"],
        "polling_start_delay_seconds": settings["polling_start_delay_seconds"],
    }


@router.post("/{project_id}/poll")
def manual_poll(project_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.git_repo_url:
        raise HTTPException(status_code=400, detail="Project has no git repo URL")
    poll_project(db, project)
    return {"message": "Poll completed", "project_status": project.status}


@router.get("/{project_id}/summary")
def project_summary(project_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    task_ids = [task.id for task in tasks]
    events = []
    if task_ids:
        events = db.query(TaskEvent).filter(TaskEvent.task_id.in_(task_ids)).all()

    task_details = []
    for t in tasks:
        deps = json.loads(t.depends_on_json) if t.depends_on_json else []
        task_details.append({
            "id": t.id,
            "project_id": t.project_id,
            "task_code": t.task_code,
            "task_name": t.task_name,
            "description": t.description,
            "assignee_agent_id": t.assignee_agent_id,
            "status": t.status,
            "depends_on": deps,
            "expected_output_path": t.expected_output_path,
            "result_file_path": t.result_file_path,
            "usage_file_path": t.usage_file_path,
            "last_error": t.last_error,
            "timeout_minutes": t.timeout_minutes,
            "dispatched_at": t.dispatched_at.isoformat() if t.dispatched_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        })

    summary = {
        "project_id": project.id,
        "project_name": project.name,
        "project_status": project.status,
        "total_tasks": len(tasks),
        "completed": sum(1 for t in tasks if t.status == "completed"),
        "running": sum(1 for t in tasks if t.status == "running"),
        "pending": sum(1 for t in tasks if t.status == "pending"),
        "needs_attention": sum(1 for t in tasks if t.status == "needs_attention"),
        "abandoned": sum(1 for t in tasks if t.status == "abandoned"),
        "tasks": task_details,
        "events": [
            {
                "id": event.id,
                "task_id": event.task_id,
                "event_type": event.event_type,
                "detail": event.detail,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }
    return summary
