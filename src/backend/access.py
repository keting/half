from fastapi import HTTPException
from sqlalchemy import and_, or_
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


def _admin_user_ids_query(db: Session):
    return db.query(User.id).filter(User.role == "admin")


def agent_visibility_filter(db: Session, user: User):
    admin_owner_ids = _admin_user_ids_query(db)
    if user.role == "admin":
        return or_(
            Agent.created_by == user.id,
            Agent.created_by.in_(admin_owner_ids),
        )
    return or_(
        Agent.created_by == user.id,
        and_(Agent.created_by.in_(admin_owner_ids), Agent.is_active == True),  # noqa: E712
    )


def list_visible_agents(db: Session, user: User) -> list[Agent]:
    return (
        db.query(Agent)
        .filter(agent_visibility_filter(db, user))
        .order_by(Agent.is_active.desc(), Agent.display_order, Agent.id)
        .all()
    )


def get_visible_agent(db: Session, agent_id: int, user: User) -> Agent:
    agent = db.query(Agent).filter(Agent.id == agent_id, agent_visibility_filter(db, user)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def get_mutable_agent(db: Session, agent_id: int, user: User) -> Agent:
    agent = get_visible_agent(db, agent_id, user)
    if agent.created_by != user.id:
        raise HTTPException(status_code=403, detail="公共 Agent 仅创建者可维护")
    return agent


def get_agent_owner_roles(db: Session, agents: list[Agent]) -> dict[int, str | None]:
    owner_ids = {agent.created_by for agent in agents if agent.created_by is not None}
    if not owner_ids:
        return {}
    return {
        user.id: user.role
        for user in db.query(User).filter(User.id.in_(owner_ids)).all()
    }


def is_agent_public(owner_roles: dict[int, str | None], agent: Agent) -> bool:
    return bool(agent.created_by is not None and owner_roles.get(agent.created_by) == "admin")


def load_usable_agents(db: Session, agent_ids: list[int], user: User) -> list[Agent]:
    if not agent_ids:
        raise HTTPException(status_code=400, detail="At least one agent must be selected")
    if len(set(agent_ids)) != len(agent_ids):
        raise HTTPException(status_code=400, detail="Some agent_ids are duplicated")

    agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    if len(agents) != len(agent_ids):
        raise HTTPException(status_code=400, detail="Some agent_ids are invalid")

    owner_roles = get_agent_owner_roles(db, agents)
    visible_agent_ids = {
        row[0]
        for row in db.query(Agent.id).filter(Agent.id.in_(agent_ids), agent_visibility_filter(db, user)).all()
    }
    invalid_ids: list[int] = []
    inactive_ids: list[int] = []
    for agent in agents:
        if not agent.is_active and (
            agent.id in visible_agent_ids or agent.created_by == user.id or is_agent_public(owner_roles, agent)
        ):
            inactive_ids.append(agent.id)
            continue
        if agent.id not in visible_agent_ids:
            invalid_ids.append(agent.id)
    if invalid_ids:
        raise HTTPException(status_code=400, detail="Some agent_ids are invalid")
    if inactive_ids:
        raise HTTPException(status_code=400, detail="Some agent_ids are inactive")

    agents_by_id = {agent.id: agent for agent in agents}
    return [agents_by_id[agent_id] for agent_id in agent_ids]


def get_owned_task(db: Session, task_id: int, user: User) -> Task:
    task = db.query(Task).join(Project, Task.project_id == Project.id).filter(
        Task.id == task_id,
        Project.created_by == user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
