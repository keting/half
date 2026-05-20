from __future__ import annotations

import logging

from services import git_service
from services.agent_runner.base import AgentRunContext, AgentRunner
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

logger = logging.getLogger(__name__)


class ClaudeRunner(AgentRunner):
    def __init__(
        self,
        model: str,
        api_base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model)
        self._api_base_url = api_base_url
        self._api_key = api_key
        self._client: ClaudeSDKClient | None = None

    # ------------------------------------------------------------------
    # Template-Method hooks
    # ------------------------------------------------------------------

    async def _ensure_ready(self, ctx: AgentRunContext) -> None:
        """Start the Claude client once; idempotent on subsequent calls."""
        if self._client is not None:
            return

        env: dict[str, str] = {}
        if self._api_base_url:
            env["ANTHROPIC_BASE_URL"] = self._api_base_url
        if self._api_key:
            env["ANTHROPIC_API_KEY"] = self._api_key

        proj_collab_dir = git_service._collab_dir(ctx.project.id)
        proj_code_dir = git_service._code_dir(ctx.project.id) if ctx.project.project_repo_url else None
        task_workspace_dir = git_service._task_workspace_dir(ctx.project.id, ctx.task.id)

        options = ClaudeAgentOptions(
            model=self._model,
            cwd=task_workspace_dir,
            permission_mode="acceptEdits", # 自动批准工作目录内的文件编辑和常见 FS 操作
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "LS"], # 预批准核心工具
            add_dirs=list({d for d in [ proj_collab_dir, proj_code_dir ] if d}),
            sandbox={
                "enabled": True,
                "autoAllowBashIfSandboxed": True,      # Sandbox 内 Bash 自动批准
                "failIfUnavailable": True,           # 可选：Sandbox 不可用时失败
                "network": {
                    "allowedDomains": [
                        "gitee.com",
                        "*.gitee.com",
                        "github.com",
                        "*.github.com",
                    ]
                },
            },
            env=env,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.__aenter__()
        logger.debug("ClaudeRunner: client started")

    async def _dispatch(self, ctx: AgentRunContext) -> None:
        """Send the prompt and consume the response stream."""
        await self._client.query(ctx.prompt)
        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ThinkingBlock):
                        logger.debug(
                            "ClaudeRunner task %s thinking: %s",
                            ctx.task.task_code,
                            block.thinking,
                        )
                    elif isinstance(block, ToolUseBlock):
                        logger.debug(
                            "ClaudeRunner task %s tool_call: %s(%s)",
                            ctx.task.task_code,
                            block.name,
                            block.input,
                        )
            elif isinstance(message, UserMessage):
                content = message.content if isinstance(message.content, list) else []
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        logger.debug(
                            "ClaudeRunner task %s tool_result: error=%s content=%s",
                            ctx.task.task_code,
                            block.is_error,
                            block.content,
                        )
            if hasattr(message, "result") and message.result:
                logger.debug(
                    "ClaudeRunner task %s result: %s",
                    ctx.task.task_code,
                    message.result,
                )

    # ------------------------------------------------------------------
    # Resource teardown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                logger.debug("ClaudeRunner: client close failed", exc_info=True)
            self._client = None

# ------------ Local Test --------------
async def main():
    from unittest.mock import MagicMock
    from models import Project, Task
    from services.prompt_service import generate_task_prompt

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = None
    fake_db.query.return_value.filter.return_value.all.return_value = []

    project = Project(
        id=2,
        name="测试项目",
        goal="验证 ClaudeRunner 本地执行流程",
        collaboration_dir="outputs/proj-2-9400f8",
        git_repo_url="git@gitee.com:black-pwq/colab.git",
        project_repo_url="git@gitee.com:black-pwq/coding.git",
    )
    task = Task(
        id=7,
        project_id=2,
        plan_id=0,
        task_code="test",
        task_name="本地测试任务",
        description="在项目代码仓库（git@gitee.com:black-pwq/coding.git）中创建文件 a.py，内容为：print('hello a!')。创建后使用 python a.py 验证输出为 hello a!，然后提交并推送到仓库。",
        depends_on_json=None,
        assignee_agent_id=0,
        dispatch_mode="auto",
        status="running",
    )

    prompt = generate_task_prompt(fake_db, project, task)
    runner = ClaudeRunner(model="glm-5")
    await runner.run(AgentRunContext(
        task=task,
        project=project,
        agent=None,
        prompt=prompt,
    ))

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())