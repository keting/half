"""Git remote URL validation to reject unsafe or non-clone URLs."""

import ipaddress
import re
from urllib.parse import unquote, urlparse


_KNOWN_GIT_WEB_HOSTS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "codeberg.org",
    "gitee.com",
}
_BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "javascript"}
_PAGE_PATH_SEGMENTS = {
    "actions",
    "blob",
    "branches",
    "commit",
    "commits",
    "compare",
    "issues",
    "merge_requests",
    "network",
    "pull",
    "pulls",
    "releases",
    "security",
    "settings",
    "tree",
    "wiki",
}
_SCP_GIT_PATTERN = re.compile(r"^git@(?P<host>[^:/\s]+):(?P<path>[^\s]+)$", re.IGNORECASE)
_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
_PATH_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._~+-]+$")
_SSH_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]*$")
_GIT_REPO_URL_ERROR = (
    "git_repo_url must be a Git repository clone URL, for example "
    "https://github.com/org/repo, https://github.com/org/repo.git, "
    "ssh://git@github.com/org/repo.git, or git@github.com:org/repo.git. "
    "Use the repository root or clone URL, not an issues/pull/tree/blob page URL."
)


def _raise_invalid() -> None:
    raise ValueError(_GIT_REPO_URL_ERROR)


def _normalize_host(hostname: str | None) -> str:
    host = (hostname or "").strip().lower()
    if not host or host.endswith("."):
        _raise_invalid()
    return host


def _ip_address_literal(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    ip_literal = hostname.strip("[]")
    try:
        return ipaddress.ip_address(ip_literal)
    except ValueError:
        return None


def _is_valid_dns_hostname(hostname: str) -> bool:
    if ":" in hostname:
        return False
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    return bool(_HOSTNAME_PATTERN.fullmatch(ascii_hostname))


def _is_private_or_local_host(hostname: str) -> bool:
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        return True

    ip = _ip_address_literal(hostname)
    if ip is None:
        return False
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _validate_host(hostname: str | None) -> str:
    host = _normalize_host(hostname)
    if _is_private_or_local_host(host):
        raise ValueError("Git repository URLs pointing to private or local networks are not allowed")
    if _ip_address_literal(host) is None and not _is_valid_dns_hostname(host):
        _raise_invalid()
    return host


def _repo_path_segments(path: str) -> list[str]:
    if not path or path.startswith("-") or "\\" in path:
        _raise_invalid()

    normalized = path.strip("/")
    if not normalized:
        _raise_invalid()

    segments = [unquote(segment) for segment in normalized.split("/")]
    if len(segments) < 2:
        _raise_invalid()

    for segment in segments:
        if segment in {"", ".", ".."} or segment.startswith("-") or not _PATH_SEGMENT_PATTERN.fullmatch(segment):
            _raise_invalid()

    return segments


def _looks_like_web_page_path(segments: list[str]) -> bool:
    return any(segment in _PAGE_PATH_SEGMENTS for segment in segments[2:])


def _validate_ssh_username(username: str | None) -> None:
    if not username or not _SSH_USERNAME_PATTERN.fullmatch(username):
        _raise_invalid()


def _validate_repo_path(hostname: str, path: str) -> None:
    segments = _repo_path_segments(path)
    if _looks_like_web_page_path(segments):
        _raise_invalid()

    repo_name = segments[-1]
    if repo_name in {".git", "..git"}:
        _raise_invalid()

    if not repo_name.endswith(".git") and hostname not in _KNOWN_GIT_WEB_HOSTS:
        _raise_invalid()


def validate_git_url(url: str | None) -> str | None:
    """Validate and sanitize a Git repository clone URL.

    Returns the URL if valid, raises ValueError if invalid.
    Returns None if url is None or empty.
    """
    if not url:
        return None

    stripped = url.strip()
    if not stripped:
        return None

    lowered = stripped.lower()
    if lowered.startswith("-") or lowered.startswith("ext::"):
        _raise_invalid()

    scp_match = _SCP_GIT_PATTERN.fullmatch(stripped)
    if scp_match:
        host = _validate_host(scp_match.group("host"))
        _validate_repo_path(host, scp_match.group("path"))
        return stripped

    parsed = urlparse(stripped)
    scheme = parsed.scheme.lower()

    if scheme in _BLOCKED_SCHEMES or scheme not in ("https", "ssh"):
        _raise_invalid()
    host = _validate_host(parsed.hostname)
    if parsed.params or parsed.query or parsed.fragment:
        _raise_invalid()
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(_GIT_REPO_URL_ERROR) from exc

    if parsed.password:
        _raise_invalid()
    if scheme == "https" and parsed.username:
        _raise_invalid()
    if scheme == "ssh":
        _validate_ssh_username(parsed.username)

    _validate_repo_path(host, parsed.path)

    return stripped
