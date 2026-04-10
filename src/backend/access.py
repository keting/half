from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Agent, Project, Task, User


def get_owned_project(db: Session, project_id: int, user: User) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.created_by == user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_owned_agent(db: Session, agent_id: int, user: User) -> Agent:
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.created_by == user.id,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def get_owned_task(db: Session, task_id: int, user: User) -> Task:
    task = db.query(Task).join(Project, Task.project_id == Project.id).filter(
        Task.id == task_id,
        Project.created_by == user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def list_owned_agents(db: Session, user: User) -> list[Agent]:
    return db.query(Agent).filter(Agent.created_by == user.id).order_by(Agent.display_order, Agent.id).all()
