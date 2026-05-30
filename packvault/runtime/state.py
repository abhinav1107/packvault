from __future__ import annotations

from dataclasses import dataclass

from authlib.integrations.starlette_client import OAuth

from packvault.auth.sessions import SessionManager
from packvault.auth.tokens import TokenRegistry
from packvault.config.settings import Settings
from packvault.db.engine import DatabaseManager
from packvault.repositories.policy import RepositoryRegistry
from packvault.secrets.encryption import EncryptionContext
from packvault.secrets.protector import SecretProtector
from packvault.storage.base import ArtifactStore


@dataclass
class AppState:
    settings: Settings
    store: ArtifactStore
    repositories: RepositoryRegistry
    tokens: TokenRegistry
    sessions: SessionManager
    database: DatabaseManager
    encryption: EncryptionContext
    secret_protector: SecretProtector
    google_oauth: OAuth | None = None
    system_initialized: bool = False
    startup_complete: bool = False
    shutting_down: bool = False
