import json
import os
import shutil
import subprocess
import configparser
import time
import threading

_sleep = time.sleep
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

# Per-project TTL for ensure_repo. Successive calls within this window reuse the
# previous fetch/pull instead of hitting the remote again. Keeps "frontend
# pre-checks then immediately dispatches" from doing two back-to-back git fetches.
_ENSURE_REPO_TTL_SECONDS = 3.0
_ensure_repo_last_run: dict[int, float] = {}
_ensure_repo_locks: dict[int, threading.Lock] = {}
_ensure_code_repo_locks: dict[int, threading.Lock] = {}

import logging

from json_repair import repair_json

from config import settings
from validators.git_url import validate_git_url as _validate_git_repo_url

logger = logging.getLogger("half.git")

GIT_REPO_URL_REQUIRED_ERROR = "Git 仓库地址不能为空。"


_RETRYABLE_GIT_ERROR_MARKERS = (
    "could not resolve host",
    "connection timed out",
    "operation timed out",
    "network is unreachable",
    "connection reset",
    "connection refused",
    "remote end hung up unexpectedly",
    "tls handshake timeout",
    "failed to connect",
    "temporary failure in name resolution",
)


@dataclass(frozen=True)
class TaskWorkspace:
    workspace_dir: str
    task_branch: str
    default_branch: str | None


@dataclass(frozen=True)
class RepoSyncStatus:
    repo_dir: str | None
    used_cache: bool = False
    fetched: bool = False
    pulled: bool = False
    remote_ready: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def validate_git_url(url: str) -> str:
    """Validate a Git repository clone URL for project remotes."""
    if not isinstance(url, str):
        raise ValueError(GIT_REPO_URL_REQUIRED_ERROR)
    value = _validate_git_repo_url(url)
    if not value:
        raise ValueError(GIT_REPO_URL_REQUIRED_ERROR)
    return value


def _project_dir(project_id: int) -> str:
    """Root workspace directory for a project: {REPOS_DIR}/{project_id}/"""
    return os.path.join(settings.REPOS_DIR, str(project_id))


def _collab_dir(project_id: int) -> str:
    """Collaboration repo checkout: {REPOS_DIR}/{project_id}/collab/"""
    return os.path.join(settings.REPOS_DIR, str(project_id), "collab")


def _code_dir(project_id: int) -> str:
    """Code repo checkout (two-repo mode): {REPOS_DIR}/{project_id}/code/"""
    return os.path.join(settings.REPOS_DIR, str(project_id), "code")


def _task_workspace_dir(project_id: int, task_id: int) -> str:
    """Per-task isolated workspace (auto mode): {REPOS_DIR}/{project_id}/tasks/{task_id}/"""
    return os.path.join(settings.REPOS_DIR, str(project_id), "tasks", str(task_id))


def _project_lock(project_id: int) -> threading.Lock:
    lock = _ensure_repo_locks.get(project_id)
    if lock is None:
        lock = threading.Lock()
        _ensure_repo_locks[project_id] = lock
    return lock


def _code_lock(project_id: int) -> threading.Lock:
    lock = _ensure_code_repo_locks.get(project_id)
    if lock is None:
        lock = threading.Lock()
        _ensure_code_repo_locks[project_id] = lock
    return lock


def _safe_join(base: str, relative_path: str) -> str:
    """Join a relative path to base and reject any traversal outside base."""
    base_real = os.path.realpath(base)
    candidate = os.path.realpath(os.path.join(base_real, _normalize_relative(relative_path)))
    if candidate != base_real and not candidate.startswith(base_real + os.sep):
        raise PermissionError(f"path escapes repo root: {relative_path}")
    return candidate


def _migrate_legacy_repo(project_id: int) -> None:
    """Move a legacy repo from {project_id}/ directly to {project_id}/collab/ if needed."""
    project = _project_dir(project_id)
    collab = _collab_dir(project_id)
    if os.path.isdir(collab):
        return  # already migrated or freshly created
    if not os.path.isdir(os.path.join(project, ".git")):
        return  # no legacy repo present
    tmp = collab + ".migrating"
    os.makedirs(tmp, exist_ok=True)
    for item in os.listdir(project):
        if item in ("collab", "collab.migrating", "code", "tasks"):
            continue
        os.rename(os.path.join(project, item), os.path.join(tmp, item))
    os.rename(tmp, collab)
    logger.info("Migrated legacy repo for project %s to %s", project_id, collab)


def clone_repo(project_id: int, git_repo_url: str) -> str:
    repo_dir = _collab_dir(project_id)
    if os.path.exists(repo_dir):
        return repo_dir
    os.makedirs(os.path.dirname(repo_dir), exist_ok=True)
    subprocess.run(
        ["git", "clone", git_repo_url, repo_dir],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return repo_dir


def _run_git(repo_dir: str, args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo_dir, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def pull_repo(project_id: int) -> str:
    repo_dir = _collab_dir(project_id)
    if not os.path.exists(repo_dir):
        raise FileNotFoundError(f"Repo directory not found: {repo_dir}")
    _run_git(repo_dir, ["pull", "--ff-only"])
    return repo_dir


def fetch_repo(project_id: int) -> str:
    repo_dir = _collab_dir(project_id)
    if not os.path.exists(repo_dir):
        raise FileNotFoundError(f"Repo directory not found: {repo_dir}")
    _run_git(repo_dir, ["fetch", "--prune", "origin"])
    return repo_dir


def _git_exception_detail(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        details: list[str] = []
        for stream_value in (exc.stderr, exc.stdout):
            if isinstance(stream_value, str) and stream_value.strip():
                details.append(stream_value.strip())
        if details:
            return " | ".join(details)
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"command timed out after {exc.timeout} seconds"
    return str(exc)


def _is_retryable_git_error(exc: Exception) -> bool:
    message = _git_exception_detail(exc).lower()
    if isinstance(exc, subprocess.TimeoutExpired):
        return True
    return any(marker in message for marker in _RETRYABLE_GIT_ERROR_MARKERS)


def _retry_git_operation(label: str, fn, *, retries: int = 3) -> tuple[bool, str | None]:
    last_error: str | None = None
    for attempt in range(1, retries + 1):
        try:
            fn()
            return True, None
        except Exception as exc:
            last_error = _git_exception_detail(exc)
            if attempt >= retries or not _is_retryable_git_error(exc):
                return False, f"{label} failed: {last_error}"
            delay = 0.5 * (2 ** (attempt - 1))
            logger.warning("%s attempt %s/%s failed: %s; retrying in %.1fs", label, attempt, retries, last_error, delay)
            _sleep(delay)
    return False, f"{label} failed"


def _is_shallow_repo(repo_dir: str) -> bool:
    try:
        result = _run_git(repo_dir, ["rev-parse", "--is-shallow-repository"], timeout=10)
    except Exception:
        return False
    return result.stdout.strip().lower() == "true"


def _unshallow_repo(project_id: int) -> tuple[bool, str | None]:
    repo_dir = _collab_dir(project_id)
    if not _is_shallow_repo(repo_dir):
        return True, None
    return _retry_git_operation(
        "git fetch --unshallow",
        lambda: _run_git(repo_dir, ["fetch", "--unshallow", "origin"]),
    )


def ensure_repo_sync(project_id: int, git_repo_url: str) -> RepoSyncStatus:
    _migrate_legacy_repo(project_id)
    repo_dir = _collab_dir(project_id)
    now = time.monotonic()
    lock = _project_lock(project_id)
    with lock:
        last = _ensure_repo_last_run.get(project_id)
        if last is not None and (now - last) < _ENSURE_REPO_TTL_SECONDS and os.path.exists(repo_dir):
            return RepoSyncStatus(
                repo_dir=repo_dir,
                used_cache=True,
                remote_ready=True,
            )

        warnings: list[str] = []
        if os.path.exists(repo_dir):
            fetched, fetch_error = _retry_git_operation(
                "git fetch origin",
                lambda: fetch_repo(project_id),
            )
            if fetched:
                remote_ready = True
                shallow_ok, shallow_error = _unshallow_repo(project_id)
                if not shallow_ok and shallow_error:
                    warnings.append(shallow_error)
                pulled, pull_error = _retry_git_operation(
                    "git pull --ff-only",
                    lambda: pull_repo(project_id),
                )
                if pull_error:
                    warnings.append(pull_error)
                _ensure_repo_last_run[project_id] = time.monotonic()
                return RepoSyncStatus(
                    repo_dir=repo_dir,
                    fetched=True,
                    pulled=pulled,
                    remote_ready=remote_ready,
                    warnings=warnings,
                )
            return RepoSyncStatus(
                repo_dir=repo_dir,
                fetched=False,
                pulled=False,
                remote_ready=False,
                warnings=warnings,
                error=fetch_error,
            )

        cloned, clone_error = _retry_git_operation(
            "git clone",
            lambda: clone_repo(project_id, git_repo_url),
        )
        if not cloned:
            return RepoSyncStatus(repo_dir=None, remote_ready=False, error=clone_error)

        _ensure_repo_last_run[project_id] = time.monotonic()
        shallow_ok, shallow_error = _unshallow_repo(project_id)
        if not shallow_ok and shallow_error:
            warnings.append(shallow_error)
        return RepoSyncStatus(
            repo_dir=repo_dir,
            fetched=True,
            pulled=True,
            remote_ready=True,
            warnings=warnings,
        )


def ensure_repo(project_id: int, git_repo_url: str) -> str:
    status = ensure_repo_sync(project_id, git_repo_url)
    if status.error:
        raise RuntimeError(status.error)
    if not status.repo_dir:
        raise RuntimeError(f"Repo sync did not produce a checkout for project {project_id}")
    return status.repo_dir


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
    repo_dir = _collab_dir(project_id)
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
    repo_dir = _collab_dir(project_id)
    if not os.path.isdir(repo_dir):
        return None

    ref = _remote_head_ref(project_id)
    if not ref:
        return None

    object_spec = f"{ref}:{_normalize_relative(relative_path)}"
    try:
        result = _run_git(repo_dir, ["show", object_spec], timeout=20)
    except Exception:
        return None

    return result.stdout


def _list_remote_dir(project_id: int, relative_path: str) -> list[str]:
    repo_dir = _collab_dir(project_id)
    if not os.path.isdir(repo_dir):
        return []
    ref = _remote_head_ref(project_id)
    if not ref:
        return []
    object_spec = f"{ref}:{_normalize_relative(relative_path)}"
    try:
        result = _run_git(repo_dir, ["ls-tree", "--name-only", object_spec], timeout=20)
    except Exception:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _remote_dir_has_content(project_id: int, relative_path: str) -> bool:
    repo_dir = _collab_dir(project_id)
    if not os.path.isdir(repo_dir):
        return False
    ref = _remote_head_ref(project_id)
    if not ref:
        return False
    path = _normalize_relative(relative_path)
    try:
        result = _run_git(repo_dir, ["ls-tree", "-r", "--name-only", ref, path], timeout=20)
    except Exception:
        return False
    return any(line.strip() for line in result.stdout.splitlines())


def read_file(
    project_id: int,
    relative_path: str,
    git_repo_url: str | None = None,
    *,
    prefer_remote: bool = False,
) -> str | None:
    repo_dir = _collab_dir(project_id)
    if prefer_remote:
        remote_content = _read_remote_file(project_id, relative_path)
        if remote_content is not None:
            return remote_content
    try:
        file_path = _safe_join(repo_dir, relative_path)
    except PermissionError:
        return None
    if os.path.isfile(file_path):
        return Path(file_path).read_text(encoding="utf-8")

    workspace_file_path = _workspace_path(relative_path, git_repo_url)
    if workspace_file_path and os.path.isfile(workspace_file_path):
        return Path(workspace_file_path).read_text(encoding="utf-8")

    return _read_remote_file(project_id, relative_path)


def read_json(
    project_id: int,
    relative_path: str,
    git_repo_url: str | None = None,
    *,
    prefer_remote: bool = False,
) -> dict | None:
    content = read_file(
        project_id,
        relative_path,
        git_repo_url=git_repo_url,
        prefer_remote=prefer_remote,
    )
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


def list_dir(
    project_id: int,
    relative_path: str,
    git_repo_url: str | None = None,
    *,
    prefer_remote: bool = False,
) -> list[str]:
    """List immediate entries in a repo subdirectory. Returns [] if not a dir."""
    repo_dir = _collab_dir(project_id)
    if prefer_remote:
        remote_entries = _list_remote_dir(project_id, relative_path)
        if remote_entries:
            return remote_entries
    try:
        candidate = _safe_join(repo_dir, relative_path)
    except PermissionError:
        return []
    if os.path.isdir(candidate):
        try:
            return sorted(os.listdir(candidate))
        except OSError:
            return []

    workspace_dir = _workspace_path(relative_path, git_repo_url)
    if workspace_dir and os.path.isdir(workspace_dir):
        try:
            return sorted(os.listdir(workspace_dir))
        except OSError:
            return []
    return _list_remote_dir(project_id, relative_path)


def dir_has_content(
    project_id: int,
    relative_path: str,
    git_repo_url: str | None = None,
    *,
    prefer_remote: bool = False,
) -> bool:
    """True if relative_path is a directory containing at least one non-empty file."""
    repo_dir = _collab_dir(project_id)
    if prefer_remote and _remote_dir_has_content(project_id, relative_path):
        return True
    candidates: list[str] = []
    try:
        candidates.append(_safe_join(repo_dir, relative_path))
    except PermissionError:
        pass
    workspace_dir = _workspace_path(relative_path, git_repo_url)
    if workspace_dir:
        candidates.append(workspace_dir)
    for path in candidates:
        if not os.path.isdir(path):
            continue
        for root, _dirs, files in os.walk(path):
            for name in files:
                full = os.path.join(root, name)
                try:
                    if os.path.getsize(full) > 0:
                        return True
                except OSError:
                    continue
    return _remote_dir_has_content(project_id, relative_path)


def file_exists(
    project_id: int,
    relative_path: str,
    git_repo_url: str | None = None,
    *,
    prefer_remote: bool = False,
) -> bool:
    repo_dir = _collab_dir(project_id)
    if prefer_remote and _read_remote_file(project_id, relative_path) is not None:
        return True
    try:
        candidate = _safe_join(repo_dir, relative_path)
    except PermissionError:
        return False
    if os.path.isfile(candidate):
        return True

    workspace_file_path = _workspace_path(relative_path, git_repo_url)
    if workspace_file_path and os.path.isfile(workspace_file_path):
        return True

    return _read_remote_file(project_id, relative_path) is not None


# ---------------------------------------------------------------------------
# Code repo (project_repo_url) — auto mode only
# ---------------------------------------------------------------------------

def ensure_code_repo_sync(project_id: int, code_repo_url: str) -> RepoSyncStatus:
    """Ensure the code repository (project_repo_url) is cloned and up-to-date."""
    repo_dir = _code_dir(project_id)
    lock = _code_lock(project_id)
    with lock:
        if os.path.exists(repo_dir):
            fetched, fetch_error = _retry_git_operation(
                "git fetch origin (code repo)",
                lambda: _run_git(repo_dir, ["fetch", "--prune", "origin"]),
            )
            if not fetched:
                return RepoSyncStatus(repo_dir=repo_dir, fetched=False, remote_ready=False, error=fetch_error)
            warnings: list[str] = []
            pulled, pull_error = _retry_git_operation(
                "git pull --ff-only (code repo)",
                lambda: _run_git(repo_dir, ["pull", "--ff-only"]),
            )
            if pull_error:
                warnings.append(pull_error)
            return RepoSyncStatus(repo_dir=repo_dir, fetched=True, pulled=pulled, remote_ready=True, warnings=warnings)

        os.makedirs(os.path.dirname(repo_dir), exist_ok=True)
        cloned, clone_error = _retry_git_operation(
            "git clone (code repo)",
            lambda: subprocess.run(
                ["git", "clone", code_repo_url, repo_dir],
                check=True, capture_output=True, text=True, timeout=120,
            ),
        )
        if not cloned:
            return RepoSyncStatus(repo_dir=None, remote_ready=False, error=clone_error)
        return RepoSyncStatus(repo_dir=repo_dir, fetched=True, pulled=True, remote_ready=True)


# ---------------------------------------------------------------------------
# Per-task workspace — auto mode
# ---------------------------------------------------------------------------

def _get_default_branch(repo_dir: str) -> str | None:
    """Return the remote default branch name (e.g. 'main' or 'master').

    Uses the local tracking ref ``origin/HEAD`` which is set during
    ``git clone`` — no network access required.
    Returns *None* when the ref is absent or unparseable.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        ref = result.stdout.strip()  # e.g. "origin/main"
        if ref and "/" in ref:
            return ref.split("/", 1)[1]
        return ref or None
    except Exception:
        logger.debug("Could not determine default branch for %s", repo_dir, exc_info=True)
        return None


def create_task_workspace(project_id: int, task_id: int) -> TaskWorkspace:
    """Create an isolated workspace for auto-mode task execution.

    Structure::

        {project_dir}/tasks/{task_id}/
            code/   <- git worktree of the code repo (or collab repo in single-repo mode)
            collab  -> symlink ../../collab

    Returns the task workspace directory path.
    """
    task_ws = _task_workspace_dir(project_id, task_id)
    code_wt = os.path.join(task_ws, "code")
    collab_link = os.path.join(task_ws, "collab")

    # Use code repo if present (two-repo mode), else collab repo (single-repo mode)
    code = _code_dir(project_id)
    base_repo = code if os.path.isdir(os.path.join(code, ".git")) else _collab_dir(project_id)

    os.makedirs(task_ws, exist_ok=True)
    branch = f"task-{task_id}"
    # Use -B (force-reset) so that a stale branch from a previous failed run
    # does not block re-dispatch of the same task.
    _run_git(base_repo, ["worktree", "add", "-B", branch, code_wt])
    logger.info("Created worktree for task %s at %s (branch=%s)", task_id, code_wt, branch)

    default_branch = _get_default_branch(base_repo)

    # Symlink collab repo into task workspace so agent sees both dirs
    collab_target = os.path.relpath(_collab_dir(project_id), task_ws)
    os.symlink(collab_target, collab_link)

    return TaskWorkspace(
        workspace_dir=task_ws,
        task_branch=branch,
        default_branch=default_branch,
    )


def delete_task_workspace(project_id: int, task_id: int) -> None:
    """Remove the task worktree and workspace directory."""
    task_ws = _task_workspace_dir(project_id, task_id)
    code_wt = os.path.join(task_ws, "code")

    code = _code_dir(project_id)
    base_repo = code if os.path.isdir(os.path.join(code, ".git")) else _collab_dir(project_id)

    try:
        _run_git(base_repo, ["worktree", "remove", "--force", code_wt])
    except Exception:
        logger.warning("Failed to remove worktree at %s", code_wt, exc_info=True)

    try:
        _run_git(base_repo, ["worktree", "prune"])
    except Exception:
        pass

    # Delete the task branch so that a subsequent re-dispatch can recreate it
    # without hitting "branch already exists" errors.
    branch = f"task-{task_id}"
    try:
        _run_git(base_repo, ["branch", "-D", branch])
        logger.info("Deleted branch %s for task %s", branch, task_id)
    except Exception:
        logger.debug("Branch %s not found or could not be deleted (may already be gone)", branch)

    try:
        shutil.rmtree(task_ws, ignore_errors=True)
    except Exception:
        logger.warning("Failed to remove task workspace at %s", task_ws, exc_info=True)


def delete_project_repo(project_id: int) -> None:
    """Remove all on-disk git checkouts for a project.

    Cleans up {REPOS_DIR}/{project_id}/ entirely so that a future project
    with the same ID cannot accidentally inherit a stale checkout.
    """
    project_dir = _project_dir(project_id)
    if not os.path.exists(project_dir):
        return
    try:
        shutil.rmtree(project_dir)
        logger.info("Deleted repo directory for project %s: %s", project_id, project_dir)
    except Exception:
        logger.warning("Failed to delete repo directory for project %s at %s", project_id, project_dir, exc_info=True)
