import json
import posixpath
import re
from dataclasses import dataclass
from typing import Any


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class ResultJsonValidation:
    data: dict[str, Any] | None
    error: str | None

    @property
    def is_valid(self) -> bool:
        return self.error is None


def validate_result_json_content(content: str, expected_task_code: str) -> ResultJsonValidation:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return ResultJsonValidation(
            data=None,
            error=f"malformed JSON at line {exc.lineno} column {exc.colno}: {exc.msg}",
        )

    if not isinstance(parsed, dict):
        return ResultJsonValidation(data=None, error="root value must be a JSON object")

    missing_fields = [
        field for field in ("task_code", "summary", "artifacts")
        if field not in parsed
    ]
    if missing_fields:
        return ResultJsonValidation(
            data=None,
            error=f"missing required fields: {', '.join(missing_fields)}",
        )

    task_code = parsed.get("task_code")
    if not isinstance(task_code, str) or not task_code.strip():
        return ResultJsonValidation(data=None, error="task_code must be a non-empty string")
    if task_code != expected_task_code:
        return ResultJsonValidation(
            data=None,
            error=f"task_code must equal {expected_task_code}, got {task_code}",
        )

    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return ResultJsonValidation(data=None, error="summary must be a non-empty string")

    artifacts = parsed.get("artifacts")
    if not isinstance(artifacts, list):
        return ResultJsonValidation(
            data=None,
            error="artifacts must be an array of repository-root relative path strings",
        )

    for index, artifact_path in enumerate(artifacts):
        path_error = _validate_repo_relative_path(artifact_path)
        if path_error:
            return ResultJsonValidation(data=None, error=f"artifacts[{index}] {path_error}")

    return ResultJsonValidation(data=parsed, error=None)


def _validate_repo_relative_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return "must be a string path"

    path = value.strip()
    if not path:
        return "must be a non-empty path"
    if "\x00" in path:
        return "must not contain NUL bytes"
    if "\\" in path:
        return "must use forward slashes, not backslashes"
    if path.startswith("/") or _WINDOWS_DRIVE_RE.match(path):
        return "must be relative to the repository root, not absolute"

    normalized = posixpath.normpath(path)
    if normalized in (".", "..") or normalized.startswith("../"):
        return "must not escape the repository root"

    return None
