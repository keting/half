import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from database import SessionLocal
from models import Agent, Project, ProjectPlan, Task, TaskEvent
from services import git_service
from services.polling_config_service import (
    get_project_polling_settings,
)
from services import feishu_service
from services.feishu_service import NotificationEvent
from validators.result_json import validate_result_json_content
from services.issue_review_loop import (
    get_issue_review_branch_path,
    get_issue_review_decision_path,
    get_issue_review_flow_state,
    project_uses_issue_review_loop,
)

logger = logging.getLogger("half.poller")

ISSUE_REVIEW_LOOP_INTERMEDIATE_TASK_CODES = {"TASK-002", "TASK-003", "TASK-004", "TASK-005"}

GIT_REPO_ACCESS_ERROR_MESSAGE = (
    "无法访问 Git 仓库。请检查仓库是否存在、仓库地址是否正确，"
    "是否有访问该仓库的权限。HALF 会自动重试。"
)
GIT_REPO_SSH_PUBLICKEY_ERROR_MESSAGE = (
    "无法通过 SSH 访问 Git 仓库：后端运行环境缺少可用 SSH key，"
    "或该 key 没有目标仓库权限。Docker 部署时需要把 deploy key 和 known_hosts "
    "显式挂载到后端容器；如果是 public 仓库，也可以改用 HTTPS 地址。HALF 会自动重试。"
)
GIT_REPO_NOT_FOUND_ERROR_MESSAGE = (
    "无法确认 Git 仓库可访问。请检查仓库地址是否正确、仓库是否存在，"
    "以及后端容器是否具备访问权限。public HTTPS 仓库通常可匿名只读；"
    "private 仓库需要配置 SSH key、token 或 credential helper。"
    "HALF 会自动重试。"
)
GIT_REPO_NETWORK_ERROR_MESSAGE = (
    "无法连接 Git 仓库。请检查后端容器的网络、DNS、代理配置，以及目标 Git 服务是否可达。"
    "HALF 会自动重试。"
)


def format_git_repo_access_error(error: str | None) -> str:
    message = (error or "").lower()
    if "permission denied (publickey" in message or "host key verification failed" in message:
        return GIT_REPO_SSH_PUBLICKEY_ERROR_MESSAGE
    if (
        "repository not found" in message
        or "not found" in message and "repository" in message
        or "authentication failed" in message
        or "could not read username" in message
    ):
        return GIT_REPO_NOT_FOUND_ERROR_MESSAGE
    network_markers = (
        "could not resolve host",
        "connection timed out",
        "operation timed out",
        "network is unreachable",
        "connection reset",
        "connection refused",
        "failed to connect",
        "could not resolve hostname",
        "remote end hung up unexpectedly",
        "tls handshake timeout",
        "temporary failure in name resolution",
    )
    if any(marker in message for marker in network_markers):
        return GIT_REPO_NETWORK_ERROR_MESSAGE
    return GIT_REPO_ACCESS_ERROR_MESSAGE


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


@dataclass(frozen=True)
class TaskResultDetection:
    found: bool
    path: str
    validation_error: str | None = None


def _detect_task_result(project: Project, task: Task) -> TaskResultDetection:
    """Read and validate the fixed result.json sentinel file."""
    base = _normalize_collab_dir(project)
    result_path = f"{base}/{task.task_code}/result.json" if base else f"{task.task_code}/result.json"
    content = git_service.read_file(
        project.id,
        result_path,
        git_repo_url=project.git_repo_url,
        prefer_remote=True,
    )
    if content is None:
        return TaskResultDetection(found=False, path=result_path)

    validation = validate_result_json_content(content, task.task_code)
    if validation.error:
        return TaskResultDetection(
            found=True,
            path=result_path,
            validation_error=f"Invalid result.json at {result_path}: {validation.error}",
        )

    return TaskResultDetection(found=True, path=result_path)


def get_effective_task_timeout_minutes(db: Session, project: Project, task: Task) -> int:
    if task.timeout_minutes is not None:
        return task.timeout_minutes

    settings = get_project_polling_settings(db, project)
    project_timeout = settings.get("task_timeout_minutes")
    if project_timeout is not None:
        return int(project_timeout)

    return 10


def _set_task_runtime_error(db: Session, task: Task, now: datetime, message: str, *, needs_attention: bool) -> None:
    should_record_event = task.last_error != message
    task.last_error = message
    task.updated_at = now
    if needs_attention and task.status != "needs_attention":
        task.status = "needs_attention"
        should_record_event = True
    if should_record_event:
        db.add(TaskEvent(
            task_id=task.id,
            event_type="error",
            detail=message,
        ))


def _mark_task_completed(db: Session, task: Task, now: datetime, result_path: str, detail: str) -> None:
    task.status = "completed"
    task.completed_at = now
    task.result_file_path = result_path
    task.last_error = None
    task.updated_at = now
    db.add(TaskEvent(
        task_id=task.id,
        event_type="completed",
        detail=detail,
    ))


def _set_plan_runtime_error(plan: ProjectPlan, now: datetime, message: str, *, needs_attention: bool) -> None:
    plan.last_error = message
    plan.updated_at = now
    if needs_attention:
        plan.status = "needs_attention"


def poll_project(db: Session, project: Project) -> list[NotificationEvent]:
    """Poll a project for task/plan updates. Returns notification events to dispatch."""
    pending_notifications: list[NotificationEvent] = []

    if not project.git_repo_url:
        return pending_notifications

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
        ProjectPlan.status.in_(("running", "needs_attention")),
    ).all()
    sync_status = git_service.ensure_repo_sync(project.id, project.git_repo_url)
    if sync_status.error:
        user_sync_message = format_git_repo_access_error(sync_status.error)
        technical_sync_message = (
            f"Git sync failed while polling project {project.id}: {sync_status.error}. "
            f"User-facing message: {user_sync_message} "
            "HALF will retry automatically; this is not treated as 'result not found'."
        )
        logger.error(technical_sync_message)
        for plan in running_plans:
            if _delay_satisfied(plan.dispatched_at):
                _set_plan_runtime_error(plan, now, user_sync_message, needs_attention=False)
        for task in running_tasks:
            if _delay_satisfied(task.dispatched_at):
                _set_task_runtime_error(db, task, now, user_sync_message, needs_attention=False)
        db.commit()
        return pending_notifications

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

    issue_review_loop_enabled = project_uses_issue_review_loop(db, project)
    issue_review_flow_state = (
        get_issue_review_flow_state(db, project)
        if issue_review_loop_enabled
        else None
    )

    for task in running_tasks:
        # Skip polling this task if start delay has not elapsed yet
        if not _delay_satisfied(task.dispatched_at):
            logger.debug(
                "Project %s task %s polling delayed (waiting %ss after dispatch)",
                project.id, task.task_code, delay_seconds,
            )
            continue
        result = _detect_task_result(project, task)
        result_path = result.path

        if result.found and result.validation_error:
            _set_task_runtime_error(db, task, now, result.validation_error, needs_attention=True)
        elif result.found:
            _mark_task_completed(db, task, now, result_path, f"Result validated at {result_path}")
            pending_notifications.append(NotificationEvent(
                event_type="completed",
                project_name=project.name,
                task_name=task.task_name,
            ))
        elif issue_review_loop_enabled and task.task_code in ISSUE_REVIEW_LOOP_INTERMEDIATE_TASK_CODES:
            task_states = (
                issue_review_flow_state.get("task_states", {})
                if isinstance(issue_review_flow_state, dict)
                else {}
            )
            effective_task_states = (
                issue_review_flow_state.get("effective_task_states", {})
                if isinstance(issue_review_flow_state, dict)
                else {}
            )
            reviews = (
                issue_review_flow_state.get("reviews", {})
                if isinstance(issue_review_flow_state, dict)
                else {}
            )
            decision = (
                issue_review_flow_state.get("decision", {})
                if isinstance(issue_review_flow_state, dict)
                else {}
            )
            flow_result_path = ""
            if task.task_code == "TASK-002" and task_states.get("TASK-002") in ("waiting_review", "approved"):
                current_round = (
                    issue_review_flow_state.get("current_round")
                    if isinstance(issue_review_flow_state, dict)
                    else None
                )
                if isinstance(current_round, int):
                    branch_path = get_issue_review_branch_path(project, current_round)
                    if git_service.read_file(
                        project.id,
                        branch_path,
                        git_repo_url=project.git_repo_url,
                        prefer_remote=True,
                    ) is not None:
                        flow_result_path = branch_path
                if not flow_result_path:
                    base = _normalize_collab_dir(project)
                    flow_state_path = f"{base}/flow-state.json" if base else "flow-state.json"
                    if git_service.read_file(
                        project.id,
                        flow_state_path,
                        git_repo_url=project.git_repo_url,
                        prefer_remote=True,
                    ) is not None:
                        flow_result_path = flow_state_path
            elif task.task_code in ("TASK-003", "TASK-004"):
                review_state = reviews.get(task.task_code)
                if isinstance(review_state, dict) and review_state.get("status") == "submitted":
                    flow_result_path = str(review_state.get("review_path") or result_path)
            elif task.task_code == "TASK-005":
                current_round = (
                    issue_review_flow_state.get("current_round")
                    if isinstance(issue_review_flow_state, dict)
                    else None
                )
                terminal_phase = (
                    issue_review_flow_state.get("derived_phase") or issue_review_flow_state.get("phase")
                    if isinstance(issue_review_flow_state, dict)
                    else None
                )
                if (
                    isinstance(current_round, int)
                    and isinstance(decision, dict)
                    and decision.get("status") == "submitted"
                    and (
                        terminal_phase in {"needs_fix", "approved", "completed", "needs_attention"}
                        or effective_task_states.get("TASK-005") in {"completed", "needs_attention"}
                    )
                ):
                    flow_result_path = str(decision.get("decision_path") or get_issue_review_decision_path(project, current_round))

            if flow_result_path:
                _mark_task_completed(
                    db,
                    task,
                    now,
                    flow_result_path,
                    f"Issue review loop state advanced at {flow_result_path}",
                )
                pending_notifications.append(NotificationEvent(
                    event_type="completed",
                    project_name=project.name,
                    task_name=task.task_name,
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
                pending_notifications.append(NotificationEvent(
                    event_type="timeout",
                    project_name=project.name,
                    task_name=task.task_name,
                    detail=f"超时 {elapsed_minutes:.1f} 分钟",
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
            pending_notifications.append(NotificationEvent(
                event_type="project_completed",
                project_name=project.name,
            ))
    elif project.status == "planning":
        if any(plan.status in ("completed", "final") for plan in db.query(ProjectPlan).filter(ProjectPlan.project_id == project.id).all()):
            project.updated_at = now

    db.commit()
    return pending_notifications


def _poll_project_in_worker(project_id: int) -> list[NotificationEvent]:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            return []
        return poll_project(db, project)
    finally:
        db.close()


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
                    project_id = project.id
                    try:
                        notifications = await asyncio.get_running_loop().run_in_executor(
                            None, _poll_project_in_worker, project_id
                        )
                    except Exception as e:
                        logger.error(f"Error polling project {project.id}: {e}")
                        notifications = []
                    await feishu_service.dispatch_notifications(db, project.created_by, notifications)
                    # Re-fetch settings each time so live config changes take effect
                    db.expire_all()
                    refreshed_project = db.query(Project).filter(Project.id == project_id).first()
                    if refreshed_project is None:
                        next_poll_at.pop(project_id, None)
                        continue
                    next_poll_at[project_id] = _compute_next_poll_time(db, refreshed_project, now)
                    logger.debug(
                        "Project %s next poll at %s",
                        project_id, next_poll_at[project_id].isoformat(),
                    )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Polling loop error: {e}")
        # Short tick so we can honor per-project random intervals as low as a few seconds.
        await asyncio.sleep(2)
