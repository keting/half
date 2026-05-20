"""Runner registry — per-task agent execution with isolated git worktrees."""
from __future__ import annotations

import logging

from database import SessionLocal
from models import Agent, AgentTypeConfig, Project, Task, TaskEvent
from services import git_service
from services.agent_credentials import decrypt_api_key
from services.agent_runner.base import AgentRunner, AgentRunContext
from services.prompt_service import generate_task_prompt

logger = logging.getLogger("half.agent_runner")

_DEFAULT_MODELS: dict[str, str] = {
    "claude": "deepseek-v4-flash",
}


def _create_runner(
    agent: Agent,
    sdk_type: str,
    api_base_url: str | None = None,
    api_key: str | None = None,
) -> AgentRunner:
    """Instantiate the concrete runner for the given sdk_type."""
    from services.agent_runner.claude_runner import ClaudeRunner

    effective_model = (
        (agent.model_name or "").strip()
        or _DEFAULT_MODELS.get(sdk_type, "")
    )

    if sdk_type == "claude":
        return ClaudeRunner(model=effective_model, api_base_url=api_base_url, api_key=api_key)

    raise ValueError(
        f"Unsupported sdk_type {sdk_type!r} for agent {agent.id}. Available: ['claude']"
    )


def _mark_task_error(db, task: Task, message: str) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    task.status = "needs_attention"
    task.last_error = message
    task.updated_at = now
    db.add(TaskEvent(task_id=task.id, event_type="error", detail=message))
    db.commit()


async def run_task_for_agent(task_id: int, project_id: int) -> None:
    """Background coroutine: run a task in an isolated per-task git worktree.

    For each execution:
    1. Sync the collaboration repo (git_repo_url).
    2. Sync the code repo (project_repo_url) if configured.
    3. Create a per-task workspace with a dedicated worktree branch.
    4. Run the agent; clean up workspace and runner regardless of outcome.
    """
    db = SessionLocal()
    task_workspace_dir: str | None = None
    runner: AgentRunner | None = None
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        project = db.query(Project).filter(Project.id == project_id).first()
        if not task or not project:
            logger.error(
                "run_task_for_agent: task %s or project %s not found", task_id, project_id
            )
            return

        agent = (
            db.query(Agent).filter(Agent.id == task.assignee_agent_id).first()
            if task.assignee_agent_id
            else None
        )
        if not agent:
            logger.error(
                "run_task_for_agent: agent not found for task %s", task_id
            )
            return

        # Look up sdk_type from AgentTypeConfig (type-level, not per-instance)
        agent_type_config = db.query(AgentTypeConfig).filter(AgentTypeConfig.name == agent.agent_type).first()
        effective_sdk_type = (agent_type_config.sdk_type or "").strip() if agent_type_config else ""

        if not effective_sdk_type:
            logger.error(
                "run_task_for_agent: sdk_type not configured for agent %s in task %s", agent.id, task_id
            )
            return

        # --- Sync collaboration repo ---
        sync_status = git_service.ensure_repo_sync(project_id, project.git_repo_url)
        if sync_status.error:
            msg = f"Git sync failed before agent execution: {sync_status.error}"
            logger.error("Task %s: %s", task.task_code, msg)
            _mark_task_error(db, task, msg)
            return

        # --- Sync code repo (two-repo mode) ---
        if project.project_repo_url:
            code_sync = git_service.ensure_code_repo_sync(project_id, project.project_repo_url)
            if code_sync.error:
                msg = f"Code repo sync failed before agent execution: {code_sync.error}"
                logger.error("Task %s: %s", task.task_code, msg)
                _mark_task_error(db, task, msg)
                return

        # --- Create per-task workspace with isolated worktree ---
        workspace = None
        try:
            workspace = git_service.create_task_workspace(project_id, task_id)
            task_workspace_dir = workspace.workspace_dir
        except Exception as exc:
            msg = f"Failed to create task workspace: {exc}"
            logger.error("Task %s: %s", task.task_code, msg)
            _mark_task_error(db, task, msg)
            return

        prompt = generate_task_prompt(
            db, project, task,
            task_branch=workspace.task_branch,
            default_branch=workspace.default_branch,
        )
        ctx = AgentRunContext(
            task=task,
            project=project,
            agent=agent,
            prompt=prompt,
        )

        api_base_url = agent_type_config.api_base_url if agent_type_config else None
        api_key = decrypt_api_key(agent_type_config.api_key_encrypted) if agent_type_config else None
        runner = _create_runner(agent, effective_sdk_type, api_base_url=api_base_url, api_key=api_key)

        logger.info(
            "Auto-executing task %s via sdk_type=%s (runner=%s)",
            task.task_code,
            effective_sdk_type,
            type(runner).__name__,
        )
        await runner.run(ctx)
        logger.info("Auto-execution finished for task %s", task.task_code)

    except Exception as exc:
        logger.exception("Auto-execution failed for task %s: %s", task_id, exc)
        try:
            fresh_db = SessionLocal()
            try:
                task = fresh_db.query(Task).filter(Task.id == task_id).first()
                if task and task.status == "running":
                    _mark_task_error(fresh_db, task, f"Agent SDK execution error: {exc}")
            finally:
                fresh_db.close()
        except Exception:
            logger.exception(
                "Failed to update error state for task %s after runner failure", task_id
            )
    finally:
        if runner is not None:
            try:
                await runner.close()
            except Exception:
                logger.debug("Runner close failed for task %s", task_id, exc_info=True)
        if task_workspace_dir is not None:
            git_service.delete_task_workspace(project_id, task_id)
        db.close()

