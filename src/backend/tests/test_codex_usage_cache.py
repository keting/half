from email.message import Message
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.codex_usage_cache import (
    CODEX_REDIRECT_URI,
    CodexUsageCache,
    UsageRefreshTooSoonError,
    _parse_codex_headers,
)


def _fake_jwt_payload(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def test_parse_codex_headers_normalizes_windows():
    headers = Message()
    headers["x-codex-primary-used-percent"] = "12.5"
    headers["x-codex-primary-reset-after-seconds"] = "604800"
    headers["x-codex-primary-window-minutes"] = "10080"
    headers["x-codex-secondary-used-percent"] = "42"
    headers["x-codex-secondary-reset-after-seconds"] = "3600"
    headers["x-codex-secondary-window-minutes"] = "300"

    snapshot = _parse_codex_headers(headers)

    assert snapshot["windows"]["seven_day"]["used_percent"] == 12.5
    assert snapshot["windows"]["seven_day"]["remaining_percent"] == 87.5
    assert snapshot["windows"]["five_hour"]["used_percent"] == 42.0
    assert snapshot["windows"]["five_hour"]["remaining_percent"] == 58.0


def test_oauth_session_is_memory_only_and_clearable():
    cache = CodexUsageCache()

    session = cache.start_oauth(CODEX_REDIRECT_URI)

    assert session["auth_url"].startswith("https://auth.openai.com/oauth/authorize?")
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback" in session["auth_url"]
    assert session["session_id"]
    assert cache.status()["authenticated"] is False

    cache.clear()

    assert cache.status()["authenticated"] is False


def test_manual_exchange_accepts_full_callback_url():
    class StubCodexUsageCache(CodexUsageCache):
        def _exchange_code(self, code: str, code_verifier: str, redirect_uri: str):
            assert code == "code-123"
            assert code_verifier
            assert redirect_uri == CODEX_REDIRECT_URI
            return {"access_token": "access-token", "expires_in": 3600}

    cache = StubCodexUsageCache()
    session = cache.start_oauth(CODEX_REDIRECT_URI)
    state = parse_qs(urlparse(session["auth_url"]).query)["state"][0]
    callback_url = f"{CODEX_REDIRECT_URI}?code=code-123&state={state}"

    token = cache.exchange_manual(session["session_id"], callback_url)

    assert token["access_token"] == "access-token"
    assert cache.status()["authenticated"] is True


def test_same_account_login_overwrites_token_and_usage_stays_agent_scoped(monkeypatch):
    class StubCodexUsageCache(CodexUsageCache):
        def _exchange_code(self, code: str, code_verifier: str, redirect_uri: str):
            return {
                "access_token": code,
                "id_token": _fake_jwt_payload({
                    "email": "codex@example.com",
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": "acct-1",
                    },
                }),
                "expires_in": 3600,
            }

    cache = StubCodexUsageCache()

    first = cache.start_oauth(CODEX_REDIRECT_URI, user_id=7, agent_id=101)
    first_state = parse_qs(urlparse(first["auth_url"]).query)["state"][0]
    cache.exchange_manual(first["session_id"], f"{CODEX_REDIRECT_URI}?code=token-a&state={first_state}")

    second = cache.start_oauth(CODEX_REDIRECT_URI, user_id=7, agent_id=202)
    second_state = parse_qs(urlparse(second["auth_url"]).query)["state"][0]
    cache.exchange_manual(second["session_id"], f"{CODEX_REDIRECT_URI}?code=token-b&state={second_state}")

    assert cache.status(7, 101)["authenticated"] is True
    assert cache.status(7, 202)["authenticated"] is True
    assert cache._ensure_access_token(7, 101)["access_token"] == "token-b"

    class FakeResponse:
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size=-1):
            return b""

    FakeResponse.headers["x-codex-primary-used-percent"] = "25"
    FakeResponse.headers["x-codex-primary-reset-after-seconds"] = "3600"
    FakeResponse.headers["x-codex-primary-window-minutes"] = "300"
    FakeResponse.headers["x-codex-secondary-used-percent"] = "50"
    FakeResponse.headers["x-codex-secondary-reset-after-seconds"] = "604800"
    FakeResponse.headers["x-codex-secondary-window-minutes"] = "10080"

    def fake_urlopen(request, timeout):
        assert timeout == 30
        assert request.get_header("Authorization") == "Bearer token-b"
        return FakeResponse()

    monkeypatch.setattr("services.codex_usage_cache.urlopen", fake_urlopen)

    cache.fetch_usage(7, 202)

    assert cache.status(7, 101)["last_usage"] is None
    assert cache.status(7, 202)["last_usage"]["windows"]["five_hour"]["remaining_percent"] == 75.0


def test_same_agent_usage_refresh_is_rate_limited_by_account(monkeypatch):
    class StubCodexUsageCache(CodexUsageCache):
        def _exchange_code(self, code: str, code_verifier: str, redirect_uri: str):
            return {
                "access_token": code,
                "id_token": _fake_jwt_payload({
                    "email": "codex@example.com",
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": "acct-1",
                    },
                }),
                "expires_in": 3600,
            }

    current_now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("services.codex_usage_cache._now", lambda: current_now)

    cache = StubCodexUsageCache()
    session = cache.start_oauth(CODEX_REDIRECT_URI, user_id=7, agent_id=101)
    state = parse_qs(urlparse(session["auth_url"]).query)["state"][0]
    cache.exchange_manual(session["session_id"], f"{CODEX_REDIRECT_URI}?code=token-a&state={state}")

    class FakeResponse:
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size=-1):
            return b""

    FakeResponse.headers["x-codex-primary-used-percent"] = "25"
    FakeResponse.headers["x-codex-primary-reset-after-seconds"] = "3600"
    FakeResponse.headers["x-codex-primary-window-minutes"] = "300"
    FakeResponse.headers["x-codex-secondary-used-percent"] = "50"
    FakeResponse.headers["x-codex-secondary-reset-after-seconds"] = "604800"
    FakeResponse.headers["x-codex-secondary-window-minutes"] = "10080"

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse()

    monkeypatch.setattr("services.codex_usage_cache.urlopen", fake_urlopen)

    cache.fetch_usage(7, 101)

    try:
        cache.fetch_usage(7, 101)
    except UsageRefreshTooSoonError as err:
        assert err.retry_at == datetime(2026, 5, 7, 12, 10, tzinfo=timezone.utc)
        assert "刷新太快" in str(err)
    else:
        raise AssertionError("Expected same-agent usage refresh to be rate limited")

    assert len(calls) == 1


def test_same_account_different_agent_reuses_cached_usage_within_rate_limit(monkeypatch):
    class StubCodexUsageCache(CodexUsageCache):
        def _exchange_code(self, code: str, code_verifier: str, redirect_uri: str):
            return {
                "access_token": code,
                "id_token": _fake_jwt_payload({
                    "email": "codex@example.com",
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": "acct-1",
                    },
                }),
                "expires_in": 3600,
            }

    fixed_now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("services.codex_usage_cache._now", lambda: fixed_now)

    cache = StubCodexUsageCache()
    first = cache.start_oauth(CODEX_REDIRECT_URI, user_id=7, agent_id=101)
    first_state = parse_qs(urlparse(first["auth_url"]).query)["state"][0]
    cache.exchange_manual(first["session_id"], f"{CODEX_REDIRECT_URI}?code=token-a&state={first_state}")

    second = cache.start_oauth(CODEX_REDIRECT_URI, user_id=7, agent_id=202)
    second_state = parse_qs(urlparse(second["auth_url"]).query)["state"][0]
    cache.exchange_manual(second["session_id"], f"{CODEX_REDIRECT_URI}?code=token-b&state={second_state}")

    class FakeResponse:
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size=-1):
            return b""

    FakeResponse.headers["x-codex-primary-used-percent"] = "25"
    FakeResponse.headers["x-codex-primary-reset-after-seconds"] = "3600"
    FakeResponse.headers["x-codex-primary-window-minutes"] = "300"
    FakeResponse.headers["x-codex-secondary-used-percent"] = "50"
    FakeResponse.headers["x-codex-secondary-reset-after-seconds"] = "604800"
    FakeResponse.headers["x-codex-secondary-window-minutes"] = "10080"

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse()

    monkeypatch.setattr("services.codex_usage_cache.urlopen", fake_urlopen)

    first_usage = cache.fetch_usage(7, 101)
    current_now = datetime(2026, 5, 7, 12, 1, tzinfo=timezone.utc)
    second_usage = cache.fetch_usage(7, 202)

    assert second_usage == first_usage
    try:
        cache.fetch_usage(7, 202)
    except UsageRefreshTooSoonError as err:
        assert err.retry_at == datetime(2026, 5, 7, 12, 10, tzinfo=timezone.utc)
        assert "刷新太快" in str(err)
    else:
        raise AssertionError("Expected repeated cached refresh to be rate limited")

    assert len(calls) == 1
    assert cache.status(7, 202)["last_usage"]["windows"]["five_hour"]["remaining_percent"] == 75.0


def test_callback_exchange_exposes_agent_scope_without_fetching_usage():
    class StubCodexUsageCache(CodexUsageCache):
        def _exchange_code(self, code: str, code_verifier: str, redirect_uri: str):
            return {
                "access_token": "access-token",
                "id_token": _fake_jwt_payload({
                    "email": "codex@example.com",
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": "acct-1",
                    },
                }),
                "expires_in": 3600,
            }

    cache = StubCodexUsageCache()
    session = cache.start_oauth(CODEX_REDIRECT_URI, user_id=9, agent_id=303)
    state = parse_qs(urlparse(session["auth_url"]).query)["state"][0]

    token_info = cache.exchange_callback("callback-code", state)

    assert token_info["_auth_user_id"] == 9
    assert token_info["_auth_agent_id"] == 303

    assert cache.status(9, 303)["last_usage"] is None
