from __future__ import annotations

_CONTENT_TYPES: dict[str, str] = {
    ".jar": "application/java-archive",
    ".pom": "application/xml",
    ".xml": "application/xml",
    ".sha1": "text/plain",
    ".md5": "text/plain",
    ".sha256": "text/plain",
    ".sha512": "text/plain",
    ".module": "application/json",
    ".war": "application/java-archive",
    ".zip": "application/zip",
}


def guess_content_type(path: str) -> str:
    normalized = path.lower()

    for suffix, content_type in _CONTENT_TYPES.items():
        if normalized.endswith(suffix):
            return content_type

    return "application/octet-stream"
