from __future__ import annotations

from packvault.config.settings import Settings
from packvault.repositories.policy import RepositoryPolicy, RepositoryRegistry


def build_registry(settings: Settings) -> RepositoryRegistry:
    policies = {
        r.name: RepositoryPolicy(name=r.name, allow_overwrite=r.allow_overwrite)
        for r in settings.repositories
    }
    return RepositoryRegistry(policies)
