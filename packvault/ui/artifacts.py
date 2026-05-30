from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Literal

from packvault.maven.checksums import is_checksum_path
from packvault.maven.paths import build_storage_key, validate_repository_name
from packvault.security.path_validation import validate_maven_path
from packvault.storage.base import ArtifactStore
from packvault.utils.errors import BadRequestError, NotFoundError

_VERSION_DIR_RE = re.compile(r"^[0-9A-Za-z._+-]+$")

UI_PAGE_SIZE = 50
_STORAGE_FETCH_SIZE = 100
_MAX_STORAGE_PAGES = 20
_MAX_DELETE_PAGES = 500

BrowseLevel = Literal["repository", "browse", "artifact", "version"]


@dataclass(frozen=True)
class ArtifactListItem:
    repository: str
    path: str
    storage_key: str


@dataclass(frozen=True)
class ArtifactListResult:
    items: list[ArtifactListItem]
    continuation_token: str | None
    has_more: bool


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    kind: Literal["directory", "file"]
    path: str


@dataclass(frozen=True)
class ArtifactBrowseResult:
    entries: list[DirectoryEntry]
    level: BrowseLevel
    continuation_token: str | None
    has_more: bool
    can_delete_artifact: bool
    can_delete_version: bool
    can_select_versions: bool


@dataclass(frozen=True)
class DeleteUnderPrefixResult:
    deleted_count: int
    prefix: str


def is_hidden_artifact_path(path: str) -> bool:
    """Return true for checksum sidecars and maven-metadata.xml (default UI filter)."""
    basename = path.rsplit("/", 1)[-1].lower()
    if basename == "maven-metadata.xml":
        return True
    if path.lower().endswith(".asc"):
        return True
    return is_checksum_path(path)


def normalize_search_prefix(value: str) -> str:
    normalized = value.strip().strip("/")
    if not normalized:
        return ""
    return validate_maven_path(normalized)


def build_list_prefix(repository: str, path_prefix: str) -> str:
    if path_prefix:
        return build_storage_key(repository, path_prefix)
    return validate_repository_name(repository)


def artifact_path_from_key(key: str, repository: str) -> str:
    prefix = f"{repository}/"
    if not key.startswith(prefix):
        raise BadRequestError("Invalid artifact key")
    return key[len(prefix) :]


def join_artifact_path(prefix: str, segment: str) -> str:
    if prefix:
        return validate_maven_path(f"{prefix}/{segment}")
    return validate_maven_path(segment)


def parent_artifact_prefix(path_prefix: str) -> str:
    if not path_prefix or "/" not in path_prefix:
        return ""
    return path_prefix.rsplit("/", 1)[0]


def breadcrumb_segments(path_prefix: str) -> list[tuple[str, str]]:
    """Return cumulative (label, prefix) pairs for breadcrumbs."""
    if not path_prefix:
        return []

    parts = path_prefix.split("/")
    segments: list[tuple[str, str]] = []
    current = ""
    for part in parts:
        current = join_artifact_path(current, part) if current else part
        segments.append((part, current))
    return segments


def is_version_directory(name: str) -> bool:
    if not _VERSION_DIR_RE.fullmatch(name):
        return False
    return any(char.isdigit() for char in name)


def path_looks_like_version_dir(path_prefix: str) -> bool:
    return is_version_directory(path_prefix.rsplit("/", 1)[-1])


def infer_browse_level(
    path_prefix: str,
    directories: list[str],
    files: list[str],
) -> BrowseLevel:
    if not path_prefix:
        return "repository"

    if files and not directories:
        if path_looks_like_version_dir(path_prefix):
            return "version"
        return "artifact"

    if directories and not files:
        if directories and all(is_version_directory(name) for name in directories):
            return "artifact"
        return "browse"

    if directories and files:
        return "artifact"

    return "browse"


def encode_ui_list_cursor(
    *,
    storage_token: str | None,
    start_after: str | None,
) -> str:
    payload = {"s": storage_token, "a": start_after}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_ui_list_cursor(cursor: str) -> tuple[str | None, str | None]:
    """Decode a UI list cursor into storage pagination parameters."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None, cursor

    if not isinstance(payload, dict):
        return None, cursor

    storage_token = payload.get("s")
    start_after = payload.get("a")

    if storage_token is not None and not isinstance(storage_token, str):
        raise BadRequestError("Invalid list cursor")
    if start_after is not None and not isinstance(start_after, str):
        raise BadRequestError("Invalid list cursor")

    return storage_token, start_after


async def list_artifact_directory(
    store: ArtifactStore,
    *,
    repository: str,
    path_prefix: str = "",
    show_all: bool = False,
    continuation_token: str | None = None,
    page_size: int = UI_PAGE_SIZE,
) -> ArtifactBrowseResult:
    storage_prefix = build_list_prefix(repository, path_prefix)
    page = await store.list_prefix_level(
        storage_prefix,
        max_entries=page_size,
        continuation_token=continuation_token,
    )

    entries: list[DirectoryEntry] = []
    for name in page.directories:
        entries.append(
            DirectoryEntry(
                name=name,
                kind="directory",
                path=join_artifact_path(path_prefix, name),
            )
        )

    for storage_key in page.files:
        path = artifact_path_from_key(storage_key, repository)
        if not show_all and is_hidden_artifact_path(path):
            continue
        entries.append(
            DirectoryEntry(
                name=path.rsplit("/", 1)[-1],
                kind="file",
                path=path,
            )
        )

    level = infer_browse_level(path_prefix, page.directories, page.files)
    can_delete_version = level == "version"
    can_delete_artifact = level == "artifact"
    can_select_versions = level == "artifact" and bool(page.directories)

    return ArtifactBrowseResult(
        entries=entries,
        level=level,
        continuation_token=page.continuation_token,
        has_more=page.has_more,
        can_delete_artifact=can_delete_artifact and bool(path_prefix),
        can_delete_version=can_delete_version,
        can_select_versions=can_select_versions,
    )


async def list_keys_under_prefix(
    store: ArtifactStore,
    storage_prefix: str,
) -> list[str]:
    keys: list[str] = []
    storage_token: str | None = None
    start_after: str | None = None

    for _ in range(_MAX_DELETE_PAGES):
        page = await store.list_prefix(
            storage_prefix,
            max_keys=_STORAGE_FETCH_SIZE,
            continuation_token=storage_token,
            start_after=start_after,
        )
        storage_token = None
        start_after = None
        keys.extend(page.keys)

        if page.continuation_token is None:
            break
        storage_token = page.continuation_token

    return keys


async def delete_under_prefix(
    store: ArtifactStore,
    *,
    repository: str,
    path_prefix: str,
) -> DeleteUnderPrefixResult:
    normalized_prefix = normalize_search_prefix(path_prefix)
    if not normalized_prefix:
        raise BadRequestError("Cannot delete repository root")

    storage_prefix = build_list_prefix(repository, normalized_prefix)
    keys = await list_keys_under_prefix(store, storage_prefix)

    if not keys:
        raise NotFoundError("No artifacts found under prefix")

    await store.delete_many(keys)
    return DeleteUnderPrefixResult(
        deleted_count=len(keys),
        prefix=normalized_prefix,
    )


async def list_artifacts_for_ui(
    store: ArtifactStore,
    *,
    repository: str,
    path_prefix: str = "",
    show_all: bool = False,
    continuation_token: str | None = None,
    page_size: int = UI_PAGE_SIZE,
) -> ArtifactListResult:
    """Flat listing retained for tests and internal pagination checks."""
    storage_prefix = build_list_prefix(repository, path_prefix)
    items: list[ArtifactListItem] = []
    storage_token, start_after = (
        decode_ui_list_cursor(continuation_token)
        if continuation_token
        else (None, None)
    )

    for _ in range(_MAX_STORAGE_PAGES):
        page = await store.list_prefix(
            storage_prefix,
            max_keys=_STORAGE_FETCH_SIZE,
            continuation_token=storage_token,
            start_after=start_after,
        )
        storage_token = None
        start_after = None

        if not page.keys:
            break

        for index, key in enumerate(page.keys):
            path = artifact_path_from_key(key, repository)
            if not show_all and is_hidden_artifact_path(path):
                continue

            items.append(
                ArtifactListItem(
                    repository=repository,
                    path=path,
                    storage_key=key,
                )
            )
            if len(items) >= page_size:
                remaining_in_page = index < len(page.keys) - 1
                if remaining_in_page:
                    next_cursor = encode_ui_list_cursor(
                        storage_token=None,
                        start_after=key,
                    )
                elif page.continuation_token:
                    next_cursor = encode_ui_list_cursor(
                        storage_token=page.continuation_token,
                        start_after=None,
                    )
                else:
                    next_cursor = None

                has_more = remaining_in_page or page.continuation_token is not None
                return ArtifactListResult(items, next_cursor, has_more)

        storage_token = page.continuation_token
        if storage_token is None:
            break

    return ArtifactListResult(items, None, False)
