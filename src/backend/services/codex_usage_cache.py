import base64
import hashlib
import html
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_USER_AGENT = "codex_cli_rs/0.125.0"
CODEX_VERSION = "0.125.0"
CODEX_REDIRECT_URI = "http://localhost:1455/auth/callback"
OAUTH_SESSION_TTL_SECONDS = 30 * 60
TOKEN_REFRESH_SKEW_SECONDS = 90
USAGE_REFRESH_COOLDOWN_SECONDS = 10 * 60
CODEX_USAGE_PROBE_MODEL = "gpt-5.4"


class UsageRefreshTooSoonError(RuntimeError):
    def __init__(self, retry_at: datetime):
        self.retry_at = retry_at
        super().__init__(f"刷新太快，请在 {retry_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')} 后再刷新")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return {}


def _extract_account_info(token_response: dict[str, Any]) -> dict[str, str]:
    info: dict[str, str] = {}
    for token_key in ("id_token", "access_token"):
        claims = _decode_jwt_payload(str(token_response.get(token_key) or ""))
        auth_claims = claims.get("https://api.openai.com/auth")
        if not isinstance(auth_claims, dict):
            continue
        mapping = {
            "chatgpt_account_id": "chatgpt_account_id",
            "chatgpt_user_id": "chatgpt_user_id",
            "organization_id": "organization_id",
            "plan_type": "chatgpt_plan_type",
        }
        for target_key, source_key in mapping.items():
            value = auth_claims.get(source_key)
            if isinstance(value, str) and value.strip() and target_key not in info:
                info[target_key] = value.strip()
        email = claims.get("email")
        if isinstance(email, str) and email.strip() and "email" not in info:
            info["email"] = email.strip()
    return info


def _parse_codex_headers(headers) -> dict[str, Any]:
    def get_float(name: str):
        value = headers.get(name)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def get_int(name: str):
        value = headers.get(name)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    primary = {
        "used_percent": get_float("x-codex-primary-used-percent"),
        "reset_after_seconds": get_int("x-codex-primary-reset-after-seconds"),
        "window_minutes": get_int("x-codex-primary-window-minutes"),
    }
    secondary = {
        "used_percent": get_float("x-codex-secondary-used-percent"),
        "reset_after_seconds": get_int("x-codex-secondary-reset-after-seconds"),
        "window_minutes": get_int("x-codex-secondary-window-minutes"),
    }

    if all(value is None for value in [*primary.values(), *secondary.values()]):
        return {}

    updated_at = _now()

    def normalize_window(label: str, data: dict[str, Any]) -> dict[str, Any]:
        used = data.get("used_percent")
        reset_after = data.get("reset_after_seconds")
        reset_at = None
        if reset_after is not None:
            reset_at = (updated_at + timedelta(seconds=max(0, reset_after))).isoformat()
        return {
            "label": label,
            "used_percent": used,
            "remaining_percent": max(0, 100 - used) if used is not None else None,
            "reset_after_seconds": reset_after,
            "reset_at": reset_at,
            "window_minutes": data.get("window_minutes"),
        }

    windows: dict[str, Any] = {}
    primary_window = primary.get("window_minutes")
    secondary_window = secondary.get("window_minutes")
    if primary_window and secondary_window:
        if primary_window <= secondary_window:
            windows["five_hour"] = normalize_window("5h", primary)
            windows["seven_day"] = normalize_window("7d", secondary)
        else:
            windows["five_hour"] = normalize_window("5h", secondary)
            windows["seven_day"] = normalize_window("7d", primary)
    else:
        windows["seven_day"] = normalize_window("7d", primary)
        windows["five_hour"] = normalize_window("5h", secondary)

    return {
        "updated_at": updated_at.isoformat(),
        "primary": primary,
        "secondary": secondary,
        "primary_over_secondary_limit_percent": get_float("x-codex-primary-over-secondary-limit-percent"),
        "windows": windows,
    }


class CodexUsageCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._account_states: dict[str, dict[str, Any]] = {}
        self._agent_accounts: dict[str, str] = {}
        self._agent_usage: dict[str, dict[str, Any]] = {}
        self._agent_usage_errors: dict[str, str] = {}
        self._account_usage: dict[str, dict[str, Any]] = {}
        self._account_usage_refresh_at: dict[str, datetime] = {}
        self._account_usage_refresh_agent: dict[str, str] = {}
        self._account_usage_snapshot_agents: dict[str, set[str]] = {}
        self._legacy_account_key: str | None = None

    def status(self, user_id: int | None = None, agent_id: int | None = None) -> dict[str, Any]:
        agent_ref = self._agent_ref(user_id, agent_id)
        with self._lock:
            account_key = self._legacy_account_key if agent_ref is None else self._agent_accounts.get(agent_ref)
            token = dict(self._account_states.get(account_key or "", {}))
            usage = dict(self._agent_usage.get(agent_ref or "__global__", {}))
            usage_error = self._agent_usage_errors.get(agent_ref or "__global__")
        return {
            "authenticated": bool(token.get("access_token")),
            "email": token.get("email"),
            "plan_type": token.get("plan_type"),
            "chatgpt_account_id": token.get("chatgpt_account_id"),
            "expires_at": token.get("expires_at"),
            "account_key": token.get("account_identity"),
            "last_usage": usage or None,
            "last_usage_error": usage_error,
        }

    def status_many(self, user_id: int, agent_ids: list[int]) -> list[dict[str, Any]]:
        return [
            {"agent_id": agent_id, **self.status(user_id, agent_id)}
            for agent_id in agent_ids
        ]

    def start_oauth(
        self,
        redirect_uri: str,
        user_id: int | None = None,
        agent_id: int | None = None,
        return_url: str | None = None,
    ) -> dict[str, str]:
        state = secrets.token_hex(32)
        code_verifier = secrets.token_hex(64)
        code_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
        session_id = secrets.token_hex(16)
        created_at = _now()

        params = {
            "response_type": "code",
            "client_id": OPENAI_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email offline_access",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
        }
        auth_url = f"{OPENAI_AUTHORIZE_URL}?{urlencode(params)}"

        with self._lock:
            self._sessions[session_id] = {
                "state": state,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "auth_url": auth_url,
                "created_at": created_at,
                "user_id": user_id,
                "agent_id": agent_id,
                "return_url": return_url,
            }
            self._prune_sessions_locked()

        return {
            "session_id": session_id,
            "auth_url": auth_url,
            "redirect_uri": redirect_uri,
        }

    def exchange_callback(self, code: str, state: str) -> dict[str, Any]:
        session_id = None
        session = None
        with self._lock:
            self._prune_sessions_locked()
            for candidate_id, candidate in self._sessions.items():
                if secrets.compare_digest(candidate["state"], state):
                    session_id = candidate_id
                    session = candidate
                    break

        if session is None or session_id is None:
            raise ValueError("OAuth session not found or expired")

        token_response = self._exchange_code(
            code=code,
            code_verifier=session["code_verifier"],
            redirect_uri=session["redirect_uri"],
        )
        token_info = self._build_token_info(token_response)
        with self._lock:
            self._sessions.pop(session_id, None)
            stored = self._store_token_locked(session, token_info)
        return stored

    def get_return_url_for_state(self, state: str) -> str | None:
        with self._lock:
            for candidate in self._sessions.values():
                if secrets.compare_digest(candidate["state"], state):
                    return candidate.get("return_url")
        return None

    def exchange_manual(self, session_id: str, code_or_callback_url: str, state: str | None = None) -> dict[str, Any]:
        code, callback_state = self._parse_manual_code(code_or_callback_url)
        if not code:
            raise ValueError("OAuth code is required")
        if callback_state:
            state = callback_state
        if not state:
            raise ValueError("OAuth state is required")

        with self._lock:
            self._prune_sessions_locked()
            session = self._sessions.get(session_id)

        if session is None:
            raise ValueError("OAuth session not found or expired")
        if not secrets.compare_digest(session["state"], state):
            raise ValueError("Invalid OAuth state")

        token_response = self._exchange_code(
            code=code,
            code_verifier=session["code_verifier"],
            redirect_uri=session["redirect_uri"],
        )
        token_info = self._build_token_info(token_response)
        with self._lock:
            self._sessions.pop(session_id, None)
            stored = self._store_token_locked(session, token_info)
        return stored

    def _parse_manual_code(self, code_or_callback_url: str) -> tuple[str, str | None]:
        value = code_or_callback_url.strip()
        if not value:
            return "", None
        parsed = urlparse(value)
        query = parsed.query
        if not query and value.startswith("?"):
            query = value[1:]
        if query:
            params = parse_qs(query)
            code = (params.get("code") or [""])[0].strip()
            state = (params.get("state") or [""])[0].strip()
            return code, state or None
        return value, None

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._account_states.clear()
            self._agent_accounts.clear()
            self._agent_usage.clear()
            self._agent_usage_errors.clear()
            self._account_usage.clear()
            self._account_usage_refresh_at.clear()
            self._account_usage_refresh_agent.clear()
            self._account_usage_snapshot_agents.clear()
            self._legacy_account_key = None

    def fetch_usage(self, user_id: int | None = None, agent_id: int | None = None) -> dict[str, Any]:
        agent_ref = self._agent_ref(user_id, agent_id)
        token_info = self._ensure_access_token(user_id, agent_id)
        account_key = token_info.get("account_key")
        if account_key:
            with self._lock:
                last_refresh_at = self._account_usage_refresh_at.get(account_key)
                last_refresh_agent = self._account_usage_refresh_agent.get(account_key)
                account_usage = dict(self._account_usage.get(account_key, {}))
                snapshot_agents = set(self._account_usage_snapshot_agents.get(account_key, set()))
            if last_refresh_at:
                retry_at = last_refresh_at + timedelta(seconds=USAGE_REFRESH_COOLDOWN_SECONDS)
                if _now() < retry_at:
                    usage_key = agent_ref or "__global__"
                    if last_refresh_agent == usage_key:
                        raise UsageRefreshTooSoonError(retry_at)
                    if account_usage and usage_key not in snapshot_agents:
                        with self._lock:
                            self._agent_usage[usage_key] = account_usage
                            self._agent_usage_errors.pop(usage_key, None)
                            self._account_usage_snapshot_agents.setdefault(account_key, set()).add(usage_key)
                        return account_usage
                    raise UsageRefreshTooSoonError(retry_at)

        headers = {
            "Authorization": f"Bearer {token_info['access_token']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "OpenAI-Beta": "responses=experimental",
            "Originator": "codex_cli_rs",
            "Version": CODEX_VERSION,
            "User-Agent": CODEX_USER_AGENT,
        }
        if token_info.get("chatgpt_account_id"):
            headers["chatgpt-account-id"] = token_info["chatgpt_account_id"]

        body = json.dumps({
            # Lightweight probe model used to trigger Codex quota headers.
            "model": CODEX_USAGE_PROBE_MODEL,
            "input": [{
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            }],
            "stream": True,
            "store": False,
            "instructions": "You are Codex, a coding agent.",
        }).encode("utf-8")

        request = Request(CODEX_RESPONSES_URL, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                snapshot = _parse_codex_headers(response.headers)
                response.read(4096)
        except HTTPError as err:
            snapshot = _parse_codex_headers(err.headers)
            if not snapshot:
                detail = err.read(2048).decode("utf-8", errors="replace")
                raise RuntimeError(f"Codex usage probe failed with status {err.code}: {detail}") from err
        except URLError as err:
            raise RuntimeError(f"Codex usage probe request failed: {err.reason}") from err

        if not snapshot:
            raise RuntimeError("Codex usage headers were not present in the response")
        with self._lock:
            usage_key = agent_ref or "__global__"
            self._agent_usage[usage_key] = snapshot
            self._agent_usage_errors.pop(usage_key, None)
            if account_key:
                self._account_usage[account_key] = snapshot
                self._account_usage_refresh_at[account_key] = _now()
                self._account_usage_refresh_agent[account_key] = usage_key
                self._account_usage_snapshot_agents[account_key] = {usage_key}
        return snapshot

    def _ensure_access_token(self, user_id: int | None = None, agent_id: int | None = None) -> dict[str, Any]:
        agent_ref = self._agent_ref(user_id, agent_id)
        with self._lock:
            account_key = self._legacy_account_key if agent_ref is None else self._agent_accounts.get(agent_ref)
            token_info = dict(self._account_states.get(account_key or "", {}))
        if not token_info.get("access_token"):
            raise ValueError("OpenAI OAuth token is not available")

        expires_at = token_info.get("expires_at")
        if expires_at:
            try:
                expires_dt = datetime.fromisoformat(str(expires_at))
            except ValueError:
                expires_dt = None
            if expires_dt and expires_dt - _now() > timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS):
                return token_info
        else:
            return token_info

        refresh_token = token_info.get("refresh_token")
        if not refresh_token:
            return token_info

        refreshed = self._refresh_token(refresh_token)
        next_info = self._build_token_info(refreshed, previous=token_info)
        with self._lock:
            self._account_states[token_info["account_key"]] = next_info
        return next_info

    def _exchange_code(self, code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]:
        data = urlencode({
            "grant_type": "authorization_code",
            "client_id": OPENAI_CLIENT_ID,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }).encode("utf-8")
        return self._post_token(data)

    def _refresh_token(self, refresh_token: str) -> dict[str, Any]:
        data = urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OPENAI_CLIENT_ID,
            "scope": "openid profile email",
        }).encode("utf-8")
        return self._post_token(data)

    def _post_token(self, data: bytes) -> dict[str, Any]:
        request = Request(
            OPENAI_TOKEN_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "codex-cli/0.91.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as err:
            detail = err.read(2048).decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI OAuth token request failed with status {err.code}: {detail}") from err
        except (URLError, json.JSONDecodeError) as err:
            raise RuntimeError(f"OpenAI OAuth token request failed: {err}") from err

    def _build_token_info(self, token_response: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
        previous = previous or {}
        expires_in = int(token_response.get("expires_in") or 0)
        expires_at = _now() + timedelta(seconds=expires_in) if expires_in > 0 else None
        token_info = dict(previous)
        token_info.update({
            "access_token": token_response.get("access_token") or previous.get("access_token"),
            "refresh_token": token_response.get("refresh_token") or previous.get("refresh_token"),
            "id_token": token_response.get("id_token") or previous.get("id_token"),
            "expires_at": expires_at.isoformat() if expires_at else previous.get("expires_at"),
            "created_at": _now().isoformat(),
        })
        token_info.update({k: v for k, v in _extract_account_info(token_response).items() if v})
        return token_info

    def _store_token_locked(self, session: dict[str, Any], token_info: dict[str, Any]) -> dict[str, Any]:
        account_identity = self._account_identity(token_info)
        user_id = session.get("user_id")
        account_key = f"user:{user_id}:account:{account_identity}" if user_id is not None else f"global:{account_identity}"
        stored = dict(token_info)
        stored["account_identity"] = account_identity
        stored["account_key"] = account_key
        stored["_auth_user_id"] = user_id
        stored["_auth_agent_id"] = session.get("agent_id")
        self._account_states[account_key] = stored

        agent_ref = self._agent_ref(user_id, session.get("agent_id"))
        if agent_ref is None:
            self._legacy_account_key = account_key
        else:
            self._agent_accounts[agent_ref] = account_key
        return stored

    def _agent_ref(self, user_id: int | None, agent_id: int | None) -> str | None:
        if user_id is None or agent_id is None:
            return None
        return f"{user_id}:{agent_id}"

    def _account_identity(self, token_info: dict[str, Any]) -> str:
        for key in ("chatgpt_account_id", "chatgpt_user_id", "email"):
            value = str(token_info.get(key) or "").strip()
            if value:
                return value.lower()
        token = str(token_info.get("access_token") or "")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16] if token else secrets.token_hex(8)
        return f"unknown:{digest}"

    def _prune_sessions_locked(self) -> None:
        cutoff = _now() - timedelta(seconds=OAUTH_SESSION_TTL_SECONDS)
        expired = [
            session_id for session_id, session in self._sessions.items()
            if session["created_at"] < cutoff
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)


codex_usage_cache = CodexUsageCache()


class CodexOAuthCallbackServer:
    def __init__(self, cache: CodexUsageCache):
        self._cache = cache
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._server is not None and self._thread is not None and self._thread.is_alive():
                return

            cache = self._cache

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, format, *args):
                    return

                def do_GET(self):
                    parsed = urlparse(self.path)
                    params = parse_qs(parsed.query)
                    if parsed.path != "/auth/callback":
                        self._send_html(callback_html(False, "Unknown OAuth callback path."), 404)
                        return

                    error = params.get("error", [""])[0]
                    code = params.get("code", [""])[0]
                    state = params.get("state", [""])[0]
                    if error:
                        self._send_html(
                            callback_html(False, f"OpenAI OAuth returned an error: {error}"),
                            400,
                        )
                        return
                    if not code or not state:
                        self._send_html(callback_html(False, "Missing OAuth code or state."), 400)
                        return

                    return_url = cache.get_return_url_for_state(state)
                    try:
                        token_info = cache.exchange_callback(code, state)
                    except (ValueError, RuntimeError) as err:
                        self._send_html(callback_html(False, str(err)), 400)
                        return

                    account = token_info.get("email") or token_info.get("chatgpt_account_id") or "OpenAI account"
                    self._send_html(
                        callback_html(True, f"{account} 已登录。正在返回 HALF 智能体页面。", return_url),
                        200,
                    )

                def _send_html(self, body: str, status_code: int) -> None:
                    payload = body.encode("utf-8")
                    self.send_response(status_code)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

            self._server = ThreadingHTTPServer(("0.0.0.0", 1455), Handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()


codex_oauth_callback_server = CodexOAuthCallbackServer(codex_usage_cache)


def callback_html(success: bool, message: str, return_url: str | None = None) -> str:
    title = "Codex OAuth 登录完成" if success else "Codex OAuth 登录失败"
    safe_message = html.escape(message)
    safe_return_url = json.dumps(return_url or "").replace("<", "\\u003c")
    redirect_script = (
        f"<script>window.setTimeout(function() {{ window.location.href = {safe_return_url}; }}, 800);</script>"
        if success and return_url
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>
      body {{ font-family: system-ui, sans-serif; margin: 48px; color: #1e293b; }}
      .box {{ max-width: 560px; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px; }}
      h1 {{ font-size: 22px; margin-bottom: 12px; }}
      p {{ color: #64748b; }}
    </style>
  </head>
  <body>
    <div class="box">
      <h1>{title}</h1>
      <p>{safe_message}</p>
    </div>
    {redirect_script}
  </body>
</html>"""
