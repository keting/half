from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from models import Agent, Project, Task

logger = logging.getLogger("half.agent_runner")


@dataclass
class AgentRunContext:
    task: Task
    project: Project
    agent: Agent
    prompt: str


class AgentRunner(ABC):
    """Abstract base class for SDK-backed agent runners.

    Design patterns
    ---------------
    Template Method
        ``run()`` is the public template: it handles logging, timeout, and
        sequencing.  Subclasses supply the SDK-specific hooks
        ``_ensure_ready()`` and ``_dispatch()``.

    Session lifecycle
    -----------------
    Tools and permissions are fixed at construction time.  A runner instance
    maintains a persistent SDK client and session; calling ``run()`` on the
    same object multiple times reuses the existing session — no new client is
    created.
    """

    def __init__(
        self,
        model: str,
    ) -> None:
        self._model = model

    # ------------------------------------------------------------------
    # Template Method — public entrypoint
    # ------------------------------------------------------------------

    async def run(self, ctx: AgentRunContext) -> None:
        """Execute the task prompt.

        On the first call the SDK client and session are initialised lazily.
        Subsequent calls on the *same instance* reuse the existing session,
        preserving conversational context.
        """
        logger.info(
            "%s starting task %s (model=%s)",
            type(self).__name__,
            ctx.task.task_code,
            self._model,
        )
        await self._ensure_ready(ctx)
        await self._dispatch(ctx)
        logger.info("%s finished task %s", type(self).__name__, ctx.task.task_code)

    # ------------------------------------------------------------------
    # Abstract hooks — implemented by each SDK runner
    # ------------------------------------------------------------------

    @abstractmethod
    async def _ensure_ready(self, ctx: AgentRunContext) -> None:
        """Lazily initialise the SDK client and obtain/resume the session.

        Must be idempotent: if the client and session are already live this
        must be a no-op.
        """

    @abstractmethod
    async def _dispatch(self, ctx: AgentRunContext) -> None:
        """Send the task prompt and block until the agent becomes idle."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down the client and session.  Called by the registry when the
        runner is evicted or the process shuts down."""

    # ------------------------------------------------------------------
    # Async context-manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AgentRunner:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
