from __future__ import annotations

from dataclasses import dataclass

from packvault.maven.paths import build_storage_key
from packvault.storage.base import ArtifactStore
from packvault.ui.artifacts import (
    build_list_prefix,
    list_keys_under_prefix,
    normalize_search_prefix,
)
from packvault.utils.errors import BadRequestError, NotFoundError


@dataclass(frozen=True)
class DeleteResult:
    deleted_keys: tuple[str, ...]
    prefix: str

    @property
    def deleted_count(self) -> int:
        return len(self.deleted_keys)


async def delete_artifact_file(
    store: ArtifactStore,
    *,
    repository: str,
    artifact_path: str,
) -> DeleteResult:
    normalized_path = normalize_search_prefix(artifact_path)
    if not normalized_path:
        raise BadRequestError("Cannot delete repository root")

    storage_key = build_storage_key(repository, normalized_path)
    await store.delete(storage_key)
    return DeleteResult(deleted_keys=(storage_key,), prefix=normalized_path)


async def delete_artifact_prefix(
    store: ArtifactStore,
    *,
    repository: str,
    path_prefix: str,
) -> DeleteResult:
    normalized_prefix = normalize_search_prefix(path_prefix)
    if not normalized_prefix:
        raise BadRequestError("Cannot delete repository root")

    storage_prefix = build_list_prefix(repository, normalized_prefix)
    keys = tuple(await list_keys_under_prefix(store, storage_prefix))
    if not keys:
        raise NotFoundError("No artifacts found under prefix")

    await store.delete_many(keys)
    return DeleteResult(deleted_keys=keys, prefix=normalized_prefix)


async def delete_artifact_version(
    store: ArtifactStore,
    *,
    repository: str,
    artifact_path: str,
    version: str,
) -> DeleteResult:
    normalized_artifact_path = normalize_search_prefix(artifact_path)
    normalized_version = normalize_search_prefix(version)
    if "/" in normalized_version:
        raise BadRequestError("Invalid package version")

    return await delete_artifact_prefix(
        store,
        repository=repository,
        path_prefix=f"{normalized_artifact_path}/{normalized_version}",
    )


async def delete_artifact_versions(
    store: ArtifactStore,
    *,
    repository: str,
    artifact_path: str,
    versions: list[str],
) -> DeleteResult:
    if not versions:
        raise BadRequestError("Select at least one version to delete")

    deleted_keys: list[str] = []
    normalized_artifact_path = normalize_search_prefix(artifact_path)

    for version in versions:
        try:
            result = await delete_artifact_version(
                store,
                repository=repository,
                artifact_path=normalized_artifact_path,
                version=version,
            )
        except NotFoundError:
            continue
        deleted_keys.extend(result.deleted_keys)

    if not deleted_keys:
        raise NotFoundError("No artifacts found for selected versions")

    return DeleteResult(
        deleted_keys=tuple(deleted_keys),
        prefix=normalized_artifact_path,
    )


async def delete_artifact_package(
    store: ArtifactStore,
    *,
    repository: str,
    artifact_path: str,
) -> DeleteResult:
    return await delete_artifact_prefix(
        store,
        repository=repository,
        path_prefix=artifact_path,
    )
