import json
import os
import subprocess
import configparser
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from json_repair import repair_json

from config import settings


def _repo_dir(project_id: int) -> str:
    return os.path.join(settings.REPOS_DIR, str(project_id))


def clone_repo(project_id: int, git_repo_url: str) -> str:
    repo_dir = _repo_dir(project_id)
    if os.path.exists(repo_dir):
        return repo_dir
    os.makedirs(settings.REPOS_DIR, exist_ok=True)
    subprocess.run(
        ["git", "clone", git_repo_url, repo_dir],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return repo_dir


def pull_repo(project_id: int) -> str:
    repo_dir = _repo_dir(project_id)
    if not os.path.exists(repo_dir):
        raise FileNotFoundError(f"Repo directory not found: {repo_dir}")
    subprocess.run(
        ["git", "-C", repo_dir, "pull", "--ff-only"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return repo_dir


def fetch_repo(project_id: int) -> str:
    repo_dir = _repo_dir(project_id)
    if not os.path.exists(repo_dir):
        raise FileNotFoundError(f"Repo directory not found: {repo_dir}")
    subprocess.run(
        ["git", "-C", repo_dir, "fetch", "origin"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return repo_dir


def ensure_repo(project_id: int, git_repo_url: str) -> str:
    repo_dir = _repo_dir(project_id)
    if os.path.exists(repo_dir):
        try:
            fetch_repo(project_id)
        except Exception:
            # Keep polling against the existing local checkout when fetch fails.
            pass
        try:
            pull_repo(project_id)
        except Exception:
            # Keep polling against the existing local checkout when pull fails.
            # Remote-tracking refs may still be available after fetch.
            pass
    else:
        clone_repo(project_id, git_repo_url)
    return repo_dir


def _normalize_relative(relative_path: str) -> str:
    """Strip any leading slashes so os.path.join treats the path as relative.

    Without this, a path like "/v2/plan.json" would be interpreted as an
    absolute filesystem path by os.path.join, completely discarding the
    repo_dir prefix.
    """
    return (relative_path or "").lstrip("/")


def _normalize_repo_identity(repo_url: str | None) -> str | None:
    if not repo_url:
        return None

    value = repo_url.strip()
    if not value:
        return None

    # SSH format: git@github.com:org/repo.git -> github.com/org/repo
    if value.startswith("git@") and ":" in value:
        # Split at the first colon to get user@host and path parts
        user_host_part, path_part = value.split(":", 1)
        # Extract host from "git@github.com" by splitting at @
        if "@" in user_host_part:
            host = user_host_part.split("@", 1)[1].lower()
        else:
            host = user_host_part.lower()
        path = path_part
        if path.endswith(".git"):
            path = path[:-4]
        return f"{host}/{path.strip('/')}"

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path[:-4] if parsed.path.endswith(".git") else parsed.path
        return f"{parsed.netloc.lower()}/{path.strip('/')}"

    normalized = value[:-4] if value.endswith(".git") else value
    return normalized.strip("/") or None


@lru_cache(maxsize=1)
def _workspace_repo_identity() -> str | None:
    workspace_root = settings.WORKSPACE_ROOT
    if not workspace_root or not os.path.isdir(workspace_root):
        return None

    git_config_path = os.path.join(workspace_root, ".git", "config")
    if os.path.isfile(git_config_path):
        parser = configparser.ConfigParser()
        try:
            parser.read(git_config_path, encoding="utf-8")
            remote_url = parser.get('remote "origin"', "url", fallback=None)
        except Exception:
            remote_url = None
        normalized = _normalize_repo_identity(remote_url)
        if normalized:
            return normalized

    try:
        result = subprocess.run(
            ["git", "-C", workspace_root, "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None

    return _normalize_repo_identity(result.stdout)


def _workspace_path(relative_path: str, git_repo_url: str | None) -> str | None:
    workspace_root = settings.WORKSPACE_ROOT
    if not workspace_root or not os.path.isdir(workspace_root):
        return None

    if _workspace_repo_identity() != _normalize_repo_identity(git_repo_url):
        return None

    return os.path.join(workspace_root, _normalize_relative(relative_path))


def _remote_head_ref(project_id: int) -> str | None:
    repo_dir = _repo_dir(project_id)
    if not os.path.isdir(repo_dir):
        return None

    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "symbolic-ref", "refs/remotes/origin/HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return "refs/remotes/origin/main"

    ref = result.stdout.strip()
    return ref or "refs/remotes/origin/main"


def _read_remote_file(project_id: int, relative_path: str) -> str | None:
    repo_dir = _repo_dir(project_id)
    if not os.path.isdir(repo_dir):
        return None

    ref = _remote_head_ref(project_id)
    if not ref:
        return None

    object_spec = f"{ref}:{_normalize_relative(relative_path)}"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "show", object_spec],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return None

    return result.stdout


def read_file(project_id: int, relative_path: str, git_repo_url: str | None = None) -> str | None:
    repo_dir = _repo_dir(project_id)
    file_path = os.path.join(repo_dir, _normalize_relative(relative_path))
    if os.path.isfile(file_path):
        return Path(file_path).read_text(encoding="utf-8")

    workspace_file_path = _workspace_path(relative_path, git_repo_url)
    if workspace_file_path and os.path.isfile(workspace_file_path):
        return Path(workspace_file_path).read_text(encoding="utf-8")

    return _read_remote_file(project_id, relative_path)


def read_json(project_id: int, relative_path: str, git_repo_url: str | None = None) -> dict | None:
    content = read_file(project_id, relative_path, git_repo_url=git_repo_url)
    if content is None:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        try:
            repaired = repair_json(content)
            return json.loads(repaired)
        except Exception:
            return None


def file_exists(project_id: int, relative_path: str, git_repo_url: str | None = None) -> bool:
    repo_dir = _repo_dir(project_id)
    if os.path.isfile(os.path.join(repo_dir, _normalize_relative(relative_path))):
        return True

    workspace_file_path = _workspace_path(relative_path, git_repo_url)
    if workspace_file_path and os.path.isfile(workspace_file_path):
        return True

    return _read_remote_file(project_id, relative_path) is not None
