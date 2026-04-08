"""Git URL validation to prevent SSRF and RCE via malicious repository URLs."""

import ipaddress
import re
from urllib.parse import urlparse


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "javascript"}

# git@ SSH format: git@host:org/repo.git
_SSH_PATTERN = re.compile(r"^git@[\w.\-]+:[\w.\-/]+(?:\.git)?$")


def _is_private_ip(hostname: str) -> bool:
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


def _is_private_hostname(hostname: str) -> bool:
    lower = hostname.lower()
    if lower in ("localhost", "localhost.localdomain"):
        return True
    if _is_private_ip(hostname):
        return True
    return False


def validate_git_url(url: str | None) -> str | None:
    """Validate and sanitize a git repository URL.

    Returns the URL if valid, raises ValueError if dangerous.
    Returns None if url is None or empty.
    """
    if not url:
        return None

    stripped = url.strip()
    if not stripped:
        return None

    # Block ext:: protocol (git remote helper attack vector)
    if stripped.startswith("ext::"):
        raise ValueError("ext:: protocol is not allowed in git URLs")

    # Allow SSH format: git@github.com:org/repo.git
    if stripped.startswith("git@"):
        if not _SSH_PATTERN.match(stripped):
            raise ValueError("Invalid SSH git URL format")
        # Extract hostname from git@host:path
        host = stripped.split("@", 1)[1].split(":", 1)[0]
        if _is_private_hostname(host):
            raise ValueError("Git URLs pointing to private/local networks are not allowed")
        return stripped

    # Parse as URL
    parsed = urlparse(stripped)

    if parsed.scheme.lower() in _BLOCKED_SCHEMES:
        raise ValueError(f"URL scheme '{parsed.scheme}' is not allowed for git repositories")

    if not parsed.scheme:
        raise ValueError("Git URL must have an explicit scheme (https://, ssh://, git@)")

    if parsed.scheme.lower() not in ("https", "http", "ssh", "git"):
        raise ValueError(f"URL scheme '{parsed.scheme}' is not supported for git repositories")

    hostname = parsed.hostname or ""
    if _is_private_hostname(hostname):
        raise ValueError("Git URLs pointing to private/local networks are not allowed")

    return stripped
