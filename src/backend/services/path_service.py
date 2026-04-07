import re


_JSON_PATH_PATTERN = re.compile(r"([A-Za-z0-9._\-/]+\.json)\b")


def extract_json_path(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    match = _JSON_PATH_PATTERN.search(text)
    if match:
        return match.group(1).lstrip("/")

    first_segment = re.split(r"[\s,，;；]+", text, maxsplit=1)[0].strip()
    return first_segment.lstrip("/")


def normalize_expected_output_path(raw_value: str | None, default_path: str, collaboration_dir: str = "") -> str:
    candidate = extract_json_path(raw_value) or default_path.lstrip("/")
    collab = (collaboration_dir or "").strip("/")
    if collab.startswith("outputs/") and candidate.startswith("outputs/") and not candidate.startswith(collab + "/"):
        candidate = candidate[len("outputs/"):]
    if collab and candidate != collab and not candidate.startswith(collab + "/"):
        return f"{collab}/{candidate}"
    return candidate
