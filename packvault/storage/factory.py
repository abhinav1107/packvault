from __future__ import annotations

from packvault.config.settings import Settings
from packvault.storage.base import ArtifactStore
from packvault.storage.cached import CachedArtifactStore
from packvault.storage.local import LocalArtifactStore
from packvault.storage.s3 import S3ArtifactStore
from packvault.utils.errors import PackVaultError


def create_artifact_store(settings: Settings) -> ArtifactStore:
    if settings.storage.backend == "local":
        return LocalArtifactStore(settings.storage.local.root)

    if settings.storage.backend == "s3":
        if settings.storage.s3 is None:
            raise PackVaultError("S3 storage config missing")

        primary = S3ArtifactStore(settings.storage.s3)

        if settings.storage.cache is None:
            return primary

        return CachedArtifactStore(
            primary,
            cache_root=settings.storage.cache.path,
            metadata_ttl_seconds=settings.storage.cache.metadata_ttl_seconds,
            snapshot_ttl_seconds=settings.storage.cache.snapshot_ttl_seconds,
        )

    raise PackVaultError(f"Unknown storage backend: {settings.storage.backend}")