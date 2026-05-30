from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from packvault.maven.checksums import is_checksum_path
from packvault.maven.paths import build_storage_key, validate_repository_name
from packvault.security.path_validation import validate_maven_path
from packvault.storage.base import ArtifactStore
from packvault.utils.errors import BadRequestError

UI_PAGE_SIZE = 50
_STORAGE_FETCH_SIZE = 100
_MAX_STORAGE_PAGES = 20


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


def encode_ui_list_cursor(
    *,
    storage_token: str | None,
    start_after: str | None,
) -> str:
    payload = {"s": storage_token, "a": start_after}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_ui_list_cursor(cursor: str) -> tuple[str | None, str | None]:
    """Decode a UI list cursor into storage pagination parameters.

    Legacy cursors were bare object keys (local-only). They are treated as
    ``start_after`` so existing local bookmarks keep working.
    """
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


async def list_artifacts_for_ui(
    store: ArtifactStore,
    *,
    repository: str,
    path_prefix: str = "",
    show_all: bool = False,
    continuation_token: str | None = None,
    page_size: int = UI_PAGE_SIZE,
) -> ArtifactListResult:
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
