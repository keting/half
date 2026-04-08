"""Simple in-memory rate limiter for login endpoints."""

import time
from collections import defaultdict

from fastapi import HTTPException, status


class LoginRateLimiter:
    """Track failed login attempts per IP/username and enforce cooldowns."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300, lockout_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lockouts: dict[str, float] = {}

    def _cleanup(self, key: str) -> None:
        now = time.monotonic()
        self._attempts[key] = [t for t in self._attempts[key] if now - t < self.window_seconds]
        if not self._attempts[key]:
            self._attempts.pop(key, None)

    def check(self, key: str) -> None:
        now = time.monotonic()
        lockout_until = self._lockouts.get(key)
        if lockout_until and now < lockout_until:
            remaining = int(lockout_until - now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed attempts. Try again in {remaining} seconds.",
            )
        if lockout_until and now >= lockout_until:
            self._lockouts.pop(key, None)
            self._attempts.pop(key, None)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._cleanup(key)
        self._attempts[key].append(now)
        if len(self._attempts[key]) >= self.max_attempts:
            self._lockouts[key] = now + self.lockout_seconds
            self._attempts.pop(key, None)

    def record_success(self, key: str) -> None:
        self._attempts.pop(key, None)
        self._lockouts.pop(key, None)


login_limiter = LoginRateLimiter()
