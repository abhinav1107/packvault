from __future__ import annotations

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
    token = continuation_token
    next_cursor: str | None = None
    has_more = False

    for _ in range(_MAX_STORAGE_PAGES):
        page = await store.list_prefix(
            storage_prefix,
            max_keys=_STORAGE_FETCH_SIZE,
            continuation_token=token,
        )

        if not page.keys:
            break

        for key in page.keys:
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
                next_cursor = key
                has_more = (
                    key != page.keys[-1]
                    or page.continuation_token is not None
                )
                return ArtifactListResult(items, next_cursor, has_more)

        token = page.continuation_token
        if token is None:
            break

    return ArtifactListResult(items, None, False)
