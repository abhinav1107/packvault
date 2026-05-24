from __future__ import annotations

import re
import urllib.parse

from packvault.utils.errors import BadRequestError

_MAVEN_PATH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_UNSAFE_FRAGMENTS = ("..", "//", "\\", "%2e%2e", "%2f%2f", "./")


def validate_maven_path(path: str, *, max_length: int = 2048) -> str:
    """Validate and normalize a Maven artifact path.

    Returns a normalized relative object key suitable for local filesystem
    storage or S3 object storage.

    This function intentionally rejects:
    - empty paths
    - absolute paths
    - path traversal
    - backslashes
    - URL-encoded traversal
    - empty path segments
    - control characters
    - drive-letter-like paths
    - query strings / fragments
    """

    if not path or not path.strip():
        raise BadRequestError("Empty artifact path")

    if len(path) > max_length:
        raise BadRequestError("Artifact path too long")

    decoded = urllib.parse.unquote(path)

    if len(decoded) > max_length:
        raise BadRequestError("Artifact path too long")

    if decoded != decoded.strip():
        raise BadRequestError("Invalid path")

    if decoded.startswith("/"):
        raise BadRequestError("Invalid path")

    if "\\" in decoded or ":" in decoded or "?" in decoded or "#" in decoded:
        raise BadRequestError("Invalid path")

    if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        raise BadRequestError("Invalid path characters")

    normalized = decoded.strip("/")

    if not normalized:
        raise BadRequestError("Empty artifact path")

    if not _MAVEN_PATH_RE.fullmatch(normalized):
        raise BadRequestError("Path contains disallowed characters")

    segments = normalized.split("/")

    for segment in segments:
        if not segment:
            raise BadRequestError("Invalid path")

        if segment in {".", ".."}:
            raise BadRequestError("Invalid path")

        if ".." in segment:
            raise BadRequestError("Invalid path")

        if not _SAFE_SEGMENT_RE.fullmatch(segment):
            raise BadRequestError("Path contains disallowed characters")

    return normalized
