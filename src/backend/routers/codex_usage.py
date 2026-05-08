import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from access import get_visible_agent, list_visible_agents
from auth import get_current_user
from database import get_db
from models import User
from services.codex_usage_cache import (
    CODEX_REDIRECT_URI,
    UsageRefreshTooSoonError,
    codex_oauth_callback_server,
    codex_usage_cache,
)

router = APIRouter(prefix="/api/codex-usage", tags=["codex-usage"])
CODEX_LOGIN_AGENT_TYPE = "chatgpt-pro"


class ManualOAuthExchangeRequest(BaseModel):
    session_id: str
    code: str
    state: str | None = None


class AgentOAuthStartRequest(BaseModel):
    return_url: str | None = None


def _require_codex_agent(agent):
    if (agent.agent_type or "").strip().lower() != CODEX_LOGIN_AGENT_TYPE:
        raise HTTPException(status_code=400, detail="当前 Agent 类型未适配")


@router.get("/agents/status")
async def get_agent_statuses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agents = list_visible_agents(db, user)
    codex_agent_ids = [
        agent.id
        for agent in agents
        if (agent.agent_type or "").strip().lower() == CODEX_LOGIN_AGENT_TYPE
    ]
    return codex_usage_cache.status_many(user.id, codex_agent_ids)


@router.get("/agents/{agent_id}/status")
async def get_agent_status(agent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_visible_agent(db, agent_id, user)
    _require_codex_agent(agent)
    return codex_usage_cache.status(user.id, agent_id)


@router.post("/agents/{agent_id}/oauth/start")
async def start_agent_oauth(
    agent_id: int,
    body: AgentOAuthStartRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = get_visible_agent(db, agent_id, user)
    _require_codex_agent(agent)
    session = codex_usage_cache.start_oauth(
        CODEX_REDIRECT_URI,
        user_id=user.id,
        agent_id=agent_id,
        return_url=body.return_url if body else None,
    )
    try:
        codex_oauth_callback_server.start()
    except OSError as err:
        raise HTTPException(status_code=503, detail=str(err))
    return session


@router.post("/agents/{agent_id}/oauth/exchange")
async def exchange_agent_oauth(
    agent_id: int,
    body: ManualOAuthExchangeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = get_visible_agent(db, agent_id, user)
    _require_codex_agent(agent)
    try:
        token_info = await asyncio.to_thread(
            codex_usage_cache.exchange_manual,
            body.session_id,
            body.code,
            body.state,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err))

    return {
        "authenticated": True,
        "email": token_info.get("email"),
        "plan_type": token_info.get("plan_type"),
        "chatgpt_account_id": token_info.get("chatgpt_account_id"),
        "expires_at": token_info.get("expires_at"),
    }


@router.post("/agents/{agent_id}/usage")
async def fetch_agent_usage(agent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_visible_agent(db, agent_id, user)
    _require_codex_agent(agent)
    try:
        return await asyncio.to_thread(codex_usage_cache.fetch_usage, user.id, agent_id)
    except UsageRefreshTooSoonError as err:
        raise HTTPException(status_code=429, detail=str(err))
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err))
