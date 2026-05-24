from __future__ import annotations

from dataclasses import dataclass

from authlib.integrations.starlette_client import OAuth

from packvault.auth.sessions import SessionManager
from packvault.auth.tokens import TokenRegistry
from packvault.config.settings import Settings
from packvault.repositories.policy import RepositoryRegistry
from packvault.storage.base import ArtifactStore


@dataclass
class AppState:
    settings: Settings
    store: ArtifactStore
    repositories: RepositoryRegistry
    tokens: TokenRegistry
    sessions: SessionManager
    google_oauth: OAuth | None = None
    startup_complete: bool = False
    shutting_down: bool = False
