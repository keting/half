import os


class Settings:
    SECRET_KEY: str = os.getenv("HALF_SECRET_KEY", "example-insecure-secret-placeholder")
    ADMIN_PASSWORD: str = os.getenv("HALF_ADMIN_PASSWORD", "example-insecure-password-placeholder")
    DATABASE_URL: str = os.getenv(
        "HALF_DATABASE_URL",
        "sqlite:///" + os.getenv("HALF_DB_PATH", os.path.join(os.getcwd(), "half.db")),
    )
    REPOS_DIR: str = os.getenv("HALF_REPOS_DIR", os.path.join(os.getcwd(), "repos"))
    WORKSPACE_ROOT: str | None = os.getenv("HALF_WORKSPACE_ROOT")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    POLL_INTERVAL_SECONDS: int = 45


settings = Settings()
