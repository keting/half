import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from access import get_visible_agent, list_visible_agents
from auth import get_current_user, require_admin
from config import settings
from database import get_db
from models import User
from services.codex_usage_cache import (
    CODEX_REDIRECT_URI,
    UsageRefreshTooSoonError,
    callback_html,
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
    callback_url: str | None = None
    callback_server_base_url: str | None = None


def _require_codex_agent(agent):
    if (agent.agent_type or "").strip().lower() != CODEX_LOGIN_AGENT_TYPE:
        raise HTTPException(status_code=400, detail="当前 Agent 类型未适配")


@router.get("/status")
async def get_status(_user=Depends(get_current_user)):
    return codex_usage_cache.status()


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
    request: Request,
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
        login_forward_url=settings.CODEX_OAUTH_FORWARD_URL,
        login_forward_param=settings.CODEX_OAUTH_FORWARD_PARAM,
        callback_url=(body.callback_url if body and body.callback_url else str(request.url_for("codex_oauth_callback"))),
        callback_server_base_url=body.callback_server_base_url if body else None,
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

    usage = await asyncio.to_thread(codex_usage_cache.try_fetch_usage, user.id, agent_id)
    return {
        "authenticated": True,
        "email": token_info.get("email"),
        "plan_type": token_info.get("plan_type"),
        "chatgpt_account_id": token_info.get("chatgpt_account_id"),
        "expires_at": token_info.get("expires_at"),
        "last_usage": usage,
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


@router.post("/oauth/manual/start")
async def start_manual_oauth(_user=Depends(require_admin)):
    session = codex_usage_cache.start_oauth(CODEX_REDIRECT_URI)
    try:
        codex_oauth_callback_server.start()
    except OSError as err:
        raise HTTPException(status_code=503, detail=str(err))
    return session


@router.post("/oauth/manual/exchange")
async def exchange_manual_oauth(body: ManualOAuthExchangeRequest, _user=Depends(require_admin)):
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


@router.get("/oauth/callback", name="codex_oauth_callback")
async def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse(callback_html(False, f"OpenAI OAuth returned an error: {error}"), status_code=400)
    if not code or not state:
        return HTMLResponse(callback_html(False, "Missing OAuth code or state."), status_code=400)
    try:
        token_info = await asyncio.to_thread(codex_usage_cache.exchange_callback, code, state)
    except (ValueError, RuntimeError) as err:
        return HTMLResponse(callback_html(False, str(err)), status_code=400)

    await asyncio.to_thread(
        codex_usage_cache.try_fetch_usage,
        token_info.get("_auth_user_id"),
        token_info.get("_auth_agent_id"),
    )
    account = token_info.get("email") or token_info.get("chatgpt_account_id") or "OpenAI account"
    return HTMLResponse(callback_html(True, f"{account} 已登录。可以回到 HALF 智能体页面刷新额度。"))


@router.post("/usage")
async def fetch_usage(_user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(codex_usage_cache.fetch_usage)
    except UsageRefreshTooSoonError as err:
        raise HTTPException(status_code=429, detail=str(err))
    except ValueError as err:
        raise HTTPException(status_code=401, detail=str(err))
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err))


@router.delete("/session")
async def clear_session(_user=Depends(require_admin)):
    codex_usage_cache.clear()
    return {"message": "Codex OAuth cache cleared"}
