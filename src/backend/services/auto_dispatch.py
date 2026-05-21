from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Iterable

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Agent, AgentTypeConfig, Project, Task, TaskEvent
from services.agent_runner.registry import run_task_for_agent

logger = logging.getLogger(__name__)

DISPATCH_MODE_AUTO = "auto"
DISPATCH_MODE_MANUAL = "manual"
_running_auto_tasks: set[int] = set()
_running_auto_tasks_lock = asyncio.Lock()


def _task_dependency_codes(task: Task) -> list[str]:
    try:
        parsed = json.loads(task.depends_on_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def is_task_ready(db: Session, task: Task) -> bool:
    codes = _task_dependency_codes(task)
    if not codes:
        return True
    predecessors = db.query(Task).filter(
        Task.project_id == task.project_id,
        Task.task_code.in_(codes),
    ).all()
    by_code = {item.task_code: item for item in predecessors}
    return all(
        (predecessor := by_code.get(code)) is not None
        and predecessor.status in ("completed", "abandoned")
        for code in codes
    )


def get_agent_type_config(db: Session, agent: Agent | None) -> AgentTypeConfig | None:
    if not agent:
        return None
    return db.query(AgentTypeConfig).filter(AgentTypeConfig.name == agent.agent_type).first()


def is_auto_agent_type(agent_type: AgentTypeConfig | None) -> bool:
    return bool(agent_type and agent_type.sdk_type)


def is_auto_task(db: Session, task: Task) -> bool:
    if not task.assignee_agent_id:
        return False
    project = db.query(Project).filter(Project.id == task.project_id).first()
    if not project or not project.is_auto:
        return False
    agent = db.query(Agent).filter(Agent.id == task.assignee_agent_id).first()
    return is_auto_agent_type(get_agent_type_config(db, agent))


def _event_detail(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def get_ready_auto_tasks(
    db: Session,
    *,
    project_id: int | None = None,
    task_ids: Iterable[int] | None = None,
) -> list[int]:
    """Return IDs of pending auto tasks whose dependencies are satisfied.

    May mark tasks as 'needs_attention' when agent credentials are missing,
    but never marks tasks as 'running' — that is deferred to run_auto_task.
    """
    query = (
        db.query(Task)
        .join(Project, Task.project_id == Project.id)
        .filter(Task.status == "pending", Project.is_auto == True)  # noqa: E712
    )
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
    task_id_list = list(task_ids or [])
    if task_id_list:
        query = query.filter(Task.id.in_(task_id_list))

    tasks = query.all()

    # Bulk-fetch agents and their type configs to avoid N+1 queries
    agent_ids = {t.assignee_agent_id for t in tasks if t.assignee_agent_id}
    agents_by_id: dict[int, Agent] = {}
    agent_types_by_name: dict[str, AgentTypeConfig] = {}
    if agent_ids:
        agents_by_id = {
            a.id: a
            for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
        }
        agent_type_names = {a.agent_type for a in agents_by_id.values() if a.agent_type}
        if agent_type_names:
            agent_types_by_name = {
                atc.name: atc
                for atc in db.query(AgentTypeConfig)
                .filter(AgentTypeConfig.name.in_(agent_type_names))
                .all()
            }

    ready: list[int] = []
    needs_attention_found = False
    now = datetime.now(timezone.utc)
    for task in tasks:
        if not task.assignee_agent_id:
            continue
        agent = agents_by_id.get(task.assignee_agent_id)
        agent_type = agent_types_by_name.get(agent.agent_type) if agent and agent.agent_type else None
        if not is_auto_agent_type(agent_type):
            continue
        if not agent.api_base_url or not agent.api_key_encrypted or not agent_type.sdk_type:
            task.status = "needs_attention"
            task.last_error = "Auto-dispatch agent is missing API credentials"
            task.updated_at = now
            db.add(TaskEvent(
                task_id=task.id,
                event_type="auto_dispatch_failed",
                detail=_event_detail({
                    "sdk_type": agent_type.sdk_type,
                    "status": "failed",
                    "error": task.last_error,
                }),
            ))
            needs_attention_found = True
            continue
        if is_task_ready(db, task):
            ready.append(task.id)

    if needs_attention_found:
        db.commit()
    return ready


def dispatch_auto_tasks(
    background_tasks: BackgroundTasks,
    db: Session,
    *,
    project_id: int | None = None,
    task_ids: Iterable[int] | None = None,
) -> list[int]:
    """Schedule ready auto tasks for parallel execution via BackgroundTasks."""
    ready_ids = get_ready_auto_tasks(db, project_id=project_id, task_ids=task_ids)
    if ready_ids:
        async def _run() -> None:
            await asyncio.gather(*[run_auto_task(tid) for tid in ready_ids])
        background_tasks.add_task(_run)
    return ready_ids


def _mark_task_error(db: Session, task: Task, message: str, agent_type: AgentTypeConfig | None = None) -> None:
    now = datetime.now(timezone.utc)
    task.status = "needs_attention"
    task.last_error = message
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="auto_dispatch_failed",
        detail=_event_detail({
            "sdk_type": agent_type.sdk_type if agent_type else None,
            "status": "failed",
            "error": message,
        }),
    ))
    db.commit()


def _mark_task_completed(db: Session, task: Task, agent_type: AgentTypeConfig | None = None) -> None:
    now = datetime.now(timezone.utc)
    task.status = "completed"
    task.completed_at = now
    task.last_error = None
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="auto_dispatch_completed",
        detail=_event_detail({
            "sdk_type": agent_type.sdk_type if agent_type else None,
            "status": "succeeded",
        }),
    ))
    db.commit()


def _complete_project_if_done(db: Session, project_id: int) -> None:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or project.status != "executing":
        return
    all_tasks = db.query(Task).filter(Task.project_id == project.id).all()
    if all_tasks and all(task.status in ("completed", "abandoned") for task in all_tasks):
        project.status = "completed"
        project.updated_at = datetime.now(timezone.utc)
        db.commit()


async def run_auto_task(task_id: int) -> None:
    async with _running_auto_tasks_lock:
        if task_id in _running_auto_tasks:
            return
        _running_auto_tasks.add(task_id)
    db = SessionLocal()
    agent_type: AgentTypeConfig | None = None
    project_id: int | None = None
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error("Auto-dispatch task %s not found", task_id)
            return
        project_id = task.project_id
        if task.status != "pending":
            return
        project = db.query(Project).filter(Project.id == task.project_id).first()
        agent = (
            db.query(Agent).filter(Agent.id == task.assignee_agent_id).first()
            if task.assignee_agent_id
            else None
        )
        agent_type = get_agent_type_config(db, agent)
        if not project or not agent or not is_auto_agent_type(agent_type):
            _mark_task_error(db, task, "Auto-dispatch task is missing project or auto agent config", agent_type)
            return

        # Mark running immediately before handing off to the agent runner
        now = datetime.now(timezone.utc)
        task.status = "running"
        task.dispatch_mode = DISPATCH_MODE_AUTO
        task.dispatched_at = now
        task.last_error = None
        task.updated_at = now
        db.add(TaskEvent(
            task_id=task.id,
            event_type="auto_dispatch_started",
            detail=_event_detail({
                "sdk_type": agent_type.sdk_type,
                "status": "started",
            }),
        ))
        db.commit()

        await run_task_for_agent(task_id, project_id)
        # run_task_for_agent uses its own DB session; re-fetch to see outcome
        db.expire_all()
        task = db.query(Task).filter(Task.id == task_id).first()
        if task and task.status == "running":
            _mark_task_completed(db, task, agent_type)
        if project_id is not None:
            next_ids = get_ready_auto_tasks(db, project_id=project_id)
            _complete_project_if_done(db, project_id)
            if next_ids:
                # Run all newly-unlocked tasks concurrently. Each branch will
                # independently chain its own downstream tasks as they complete,
                # so converging nodes are dispatched as soon as all deps finish.
                await asyncio.gather(*[run_auto_task(tid) for tid in next_ids])
    except Exception as exc:
        logger.exception("Auto-dispatch failed for task %s: %s", task_id, exc)
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                _mark_task_error(db, task, str(exc), agent_type)
        except Exception:
            logger.exception("Failed to record auto-dispatch error for task %s", task_id)
    finally:
        async with _running_auto_tasks_lock:
            _running_auto_tasks.discard(task_id)
        db.close()
