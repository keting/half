import logging
import os
import re
import sys


logger = logging.getLogger("half.config")


_DEFAULT_INSECURE_SECRETS = {
    "example-insecure-secret-placeholder",
    "changeme",
    "secret",
    "password",
    "12345678",
}
_DEFAULT_INSECURE_PASSWORDS = {"example-insecure-password-placeholder", "admin", "password", "123456"}

_PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    SECRET_KEY: str = os.getenv("HALF_SECRET_KEY", "example-insecure-secret-placeholder")
    ADMIN_PASSWORD: str = os.getenv("HALF_ADMIN_PASSWORD", "example-insecure-password-placeholder")
    ALLOW_REGISTER: bool = _truthy(os.getenv("HALF_ALLOW_REGISTER", "false"))
    DEMO_SEED_ENABLED: bool = _truthy(os.getenv("HALF_DEMO_SEED_ENABLED", "true"))
    DATABASE_URL: str = os.getenv(
        "HALF_DATABASE_URL",
        "sqlite:///" + os.getenv("HALF_DB_PATH", os.path.join(os.getcwd(), "half.db")),
    )
    REPOS_DIR: str = os.getenv("HALF_REPOS_DIR", os.path.join(os.getcwd(), "repos"))
    WORKSPACE_ROOT: str | None = os.getenv("HALF_WORKSPACE_ROOT")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    POLL_INTERVAL_SECONDS: int = 45
    STRICT_SECURITY: bool = _truthy(os.getenv("HALF_STRICT_SECURITY", "true"))
    CORS_ORIGINS: str = os.getenv("HALF_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    ALLOWED_CORS_ORIGINS: list[str] = [
        o.strip()
        for o in CORS_ORIGINS.split(",")
        if o.strip()
    ]


settings = Settings()


def validate_security_config() -> None:
    """Validate critical security configuration at startup.

    In strict mode (HALF_STRICT_SECURITY=true) the process will exit if a
    weak/default secret or admin password is detected. Otherwise a loud
    warning is logged so existing dev environments are not broken, while
    deployers see a clear signal to fix the configuration.
    """
    problems: list[str] = []

    if settings.SECRET_KEY in _DEFAULT_INSECURE_SECRETS or len(settings.SECRET_KEY) < 32:
        problems.append(
            "HALF_SECRET_KEY must be set to a strong value (>=32 chars, not the built-in default). "
            "Generate one: export HALF_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
        )
    try:
        validate_user_password(settings.ADMIN_PASSWORD)
    except ValueError:
        problems.append(
            "HALF_ADMIN_PASSWORD must be set to a strong value (>=8 chars, not a known default). "
            "It should contain uppercase, lowercase, and digits."
        )
    else:
        if settings.ADMIN_PASSWORD in _DEFAULT_INSECURE_PASSWORDS:
            problems.append(
                "HALF_ADMIN_PASSWORD must be set to a strong value (>=8 chars, not a known default). "
                "It should contain uppercase, lowercase, and digits."
            )

    if not problems:
        return

    message = (
        "[HALF security] Insecure configuration detected:\n  - "
        + "\n  - ".join(problems)
        + "\nSet HALF_SECRET_KEY and HALF_ADMIN_PASSWORD via environment before exposing this service."
    )
    if settings.STRICT_SECURITY:
        logger.error(message)
        sys.stderr.write(message + "\n")
        raise SystemExit(1)
    logger.warning(message)


def validate_user_password(password: str) -> str:
    """Validate a user-set password against the project's unified strength rule."""
    if not _PASSWORD_PATTERN.match(password or ""):
        raise ValueError(
            "Password must be at least 8 characters and contain uppercase, "
            "lowercase, and digits."
        )
    return password
