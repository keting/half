import asyncio
import json
import logging
import random
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from database import SessionLocal
from models import Agent, Project, ProjectPlan, Task, TaskEvent
from services import git_service
from services.polling_config_service import (
    get_project_polling_settings,
)

logger = logging.getLogger("half.poller")

GIT_REPO_ACCESS_ERROR_MESSAGE = (
    "无法访问 Git 仓库。请检查仓库是否存在、仓库地址是否正确，"
    "是否有访问该仓库的权限。HALF 会自动重试。"
)


def _normalize_collab_dir(project: Project) -> str:
    return (project.collaboration_dir or "").strip("/")


def _plan_source_path(project: Project, plan: ProjectPlan) -> str:
    if plan.source_path:
        return plan.source_path.lstrip("/")
    base = _normalize_collab_dir(project)
    if base:
        return f"{base}/plan.json"
    return "plan.json"


def _task_usage_path(project: Project, task: Task) -> str:
    base = _normalize_collab_dir(project)
    if base:
        return f"{base}/{task.task_code}/usage.json"
    return f"{task.task_code}/usage.json"


def _detect_task_result(project: Project, task: Task) -> tuple[bool, str | None]:
    """Detect task completion via a fixed sentinel file."""
    base = _normalize_collab_dir(project)
    result_path = f"{base}/{task.task_code}/result.json" if base else f"{task.task_code}/result.json"
    if git_service.file_exists(
        project.id,
        result_path,
        git_repo_url=project.git_repo_url,
        prefer_remote=True,
    ):
        return True, result_path
    return False, result_path


def get_effective_task_timeout_minutes(db: Session, project: Project, task: Task) -> int:
    if task.timeout_minutes is not None:
        return task.timeout_minutes

    settings = get_project_polling_settings(db, project)
    project_timeout = settings.get("task_timeout_minutes")
    if project_timeout is not None:
        return int(project_timeout)

    return 10


def _set_task_runtime_error(db: Session, task: Task, now: datetime, message: str, *, needs_attention: bool) -> None:
    task.last_error = message
    task.updated_at = now
    if needs_attention:
        task.status = "needs_attention"
    db.add(TaskEvent(
        task_id=task.id,
        event_type="error",
        detail=message,
    ))


def _set_plan_runtime_error(plan: ProjectPlan, now: datetime, message: str, *, needs_attention: bool) -> None:
    plan.last_error = message
    plan.updated_at = now
    if needs_attention:
        plan.status = "needs_attention"


def poll_project(db: Session, project: Project) -> None:
    if not project.git_repo_url:
        return

    all_tasks = db.query(Task).filter(Task.project_id == project.id).all()
    running_tasks = [task for task in all_tasks if task.status in ("running", "needs_attention")]

    now = datetime.now(timezone.utc)

    # Get effective polling delay for this project (project-level overrides global)
    polling_settings = get_project_polling_settings(db, project)
    delay_seconds = (
        polling_settings["polling_start_delay_minutes"] * 60
        + polling_settings["polling_start_delay_seconds"]
    )
    delay_threshold = timedelta(seconds=delay_seconds)

    def _delay_satisfied(dispatched_at) -> bool:
        """Return True if enough time has passed since dispatch to start polling."""
        if dispatched_at is None or delay_seconds <= 0:
            return True
        elapsed = now - dispatched_at.replace(tzinfo=timezone.utc)
        return elapsed >= delay_threshold

    running_plans = db.query(ProjectPlan).filter(
        ProjectPlan.project_id == project.id,
        ProjectPlan.status == "running",
    ).all()
    sync_status = git_service.ensure_repo_sync(project.id, project.git_repo_url)
    if sync_status.error:
        technical_sync_message = (
            f"Git sync failed while polling project {project.id}: {sync_status.error}. "
            "HALF will retry automatically; this is not treated as 'result not found'."
        )
        logger.error(technical_sync_message)
        for plan in running_plans:
            if _delay_satisfied(plan.dispatched_at):
                _set_plan_runtime_error(plan, now, GIT_REPO_ACCESS_ERROR_MESSAGE, needs_attention=False)
        for task in running_tasks:
            if _delay_satisfied(task.dispatched_at):
                _set_task_runtime_error(db, task, now, GIT_REPO_ACCESS_ERROR_MESSAGE, needs_attention=False)
        db.commit()
        return

    sync_warning = None
    if sync_status.warnings:
        sync_warning = (
            "Git sync warning: "
            + " | ".join(sync_status.warnings)
            + ". HALF used the latest reachable remote snapshot for detection."
        )
        logger.warning("Project %s polling sync warning: %s", project.id, sync_warning)

    for plan in running_plans:
        # Skip polling this plan if start delay has not elapsed yet
        if not _delay_satisfied(plan.dispatched_at):
            logger.debug(
                "Project %s plan %s polling delayed (waiting %ss after dispatch)",
                project.id, plan.id, delay_seconds,
            )
            continue
        source_path = _plan_source_path(project, plan)
        if source_path.startswith("template:"):
            logger.warning(
                "Skipping non-file template plan source while polling project %s plan %s: %s",
                project.id,
                plan.id,
                source_path,
            )
            continue
        plan_data = git_service.read_json(
            project.id,
            source_path,
            git_repo_url=project.git_repo_url,
            prefer_remote=True,
        )

        if isinstance(plan_data, dict) and isinstance(plan_data.get("tasks"), list) and plan_data.get("tasks"):
            plan.plan_json = json.dumps(plan_data, ensure_ascii=False, indent=2)
            plan.status = "completed"
            plan.detected_at = now
            plan.last_error = None
            plan.source_path = source_path
            plan.updated_at = now
        elif plan.dispatched_at:
            elapsed_minutes = (now - plan.dispatched_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
            if elapsed_minutes > 30:
                plan.status = "needs_attention"
                plan.last_error = f"Plan JSON not found at {source_path} after {elapsed_minutes:.1f} minutes"
                plan.updated_at = now

    for task in running_tasks:
        # Skip polling this task if start delay has not elapsed yet
        if not _delay_satisfied(task.dispatched_at):
            logger.debug(
                "Project %s task %s polling delayed (waiting %ss after dispatch)",
                project.id, task.task_code, delay_seconds,
            )
            continue
        result_detected, result_path = _detect_task_result(project, task)

        if result_detected:
            task.status = "completed"
            task.completed_at = now
            task.result_file_path = result_path
            task.last_error = None
            task.updated_at = now
            db.add(TaskEvent(
                task_id=task.id,
                event_type="completed",
                detail=f"Result detected at {result_path}",
            ))
        elif task.dispatched_at:
            elapsed_minutes = (now - task.dispatched_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
            timeout_limit = get_effective_task_timeout_minutes(db, project, task)
            if elapsed_minutes > timeout_limit and task.status != "needs_attention":
                task.status = "needs_attention"
                task.last_error = f"Timeout: result not found at {result_path} after {elapsed_minutes:.1f} minutes"
                task.updated_at = now
                db.add(TaskEvent(
                    task_id=task.id,
                    event_type="timeout",
                    detail=f"Timeout after {elapsed_minutes:.1f} minutes",
                ))

        # Check usage.json
        usage_path = _task_usage_path(project, task)
        if usage_path and git_service.file_exists(
            project.id,
            usage_path,
            git_repo_url=project.git_repo_url,
            prefer_remote=True,
        ):
            task.usage_file_path = usage_path
            if task.assignee_agent_id:
                agent = db.query(Agent).filter(Agent.id == task.assignee_agent_id).first()
                if agent:
                    agent.last_usage_update_at = now
                    agent.updated_at = now

    # Check if all tasks in executing project are completed
    if project.status == "executing":
        if all_tasks and all(t.status in ("completed", "abandoned") for t in all_tasks):
            project.status = "completed"
            project.updated_at = now
    elif project.status == "planning":
        if any(plan.status in ("completed", "final") for plan in db.query(ProjectPlan).filter(ProjectPlan.project_id == project.id).all()):
            project.updated_at = now

    db.commit()


def _compute_next_poll_time(db: Session, project: Project, now: datetime) -> datetime:
    """Compute the next polling time for a project based on its random interval config."""
    settings = get_project_polling_settings(db, project)
    min_interval = max(1, settings["polling_interval_min"])
    max_interval = max(min_interval, settings["polling_interval_max"])
    interval_seconds = random.randint(min_interval, max_interval)
    return now + timedelta(seconds=interval_seconds)


async def polling_loop(interval_seconds: int) -> None:
    """Per-project polling scheduler.

    Each project schedules its own next poll based on its (random) interval
    configured at project level, falling back to global defaults. The main
    loop wakes up frequently (every 2 seconds) and dispatches polling for any
    project whose next_poll_at has been reached.

    The legacy ``interval_seconds`` parameter is kept only for backward
    compatibility with the startup signature; it is no longer used as the
    actual interval, since each project now has its own random interval.
    """
    logger.info(
        "Per-project polling loop started (legacy interval_seconds=%s ignored; "
        "each project now uses its own random interval)",
        interval_seconds,
    )
    # Map project_id -> datetime when this project should be polled next.
    # Newly-discovered projects are polled immediately on the first tick.
    next_poll_at: dict[int, datetime] = {}

    while True:
        try:
            now = datetime.now(timezone.utc)
            db = SessionLocal()
            try:
                projects = db.query(Project).filter(
                    Project.status.in_(("planning", "executing"))
                ).all()
                active_ids = {p.id for p in projects}
                # Drop schedule entries for projects no longer active
                for stale_id in list(next_poll_at.keys()):
                    if stale_id not in active_ids:
                        next_poll_at.pop(stale_id, None)

                for project in projects:
                    scheduled = next_poll_at.get(project.id)
                    if scheduled is not None and scheduled > now:
                        continue  # Not yet time for this project
                    try:
                        poll_project(db, project)
                    except Exception as e:
                        logger.error(f"Error polling project {project.id}: {e}")
                    # Re-fetch settings each time so live config changes take effect
                    next_poll_at[project.id] = _compute_next_poll_time(db, project, now)
                    logger.debug(
                        "Project %s next poll at %s",
                        project.id, next_poll_at[project.id].isoformat(),
                    )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Polling loop error: {e}")
        # Short tick so we can honor per-project random intervals as low as a few seconds.
        await asyncio.sleep(2)
