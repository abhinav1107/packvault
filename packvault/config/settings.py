from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from packvault.config.env_subst import substitute_env_vars

RepositoryAction = Literal["read", "write"]
AuthProvider = Literal["local", "google", "oidc"]
StorageBackend = Literal["local", "s3"]
LogFormat = Literal["json", "standard"]


class LocalStorageConfig(BaseModel):
    root: Path = Path("/data")


class S3StorageConfig(BaseModel):
    bucket: str = Field(min_length=1)
    region: str = "us-east-1"
    prefix: str = "repositories"
    endpoint_url: str = ""
    path_style: bool = False


class CacheConfig(BaseModel):
    path: Path = Path("/data")
    metadata_ttl_seconds: int = Field(default=60, ge=0)
    snapshot_ttl_seconds: int = Field(default=300, ge=0)


class StorageConfig(BaseModel):
    backend: Literal["local", "s3"] = "local"
    local: LocalStorageConfig = Field(default_factory=LocalStorageConfig)
    s3: S3StorageConfig | None = None
    cache: CacheConfig = Field(default_factory=CacheConfig)

    @model_validator(mode="after")
    def s3_required_when_backend_s3(self) -> StorageConfig:
        if self.backend == "s3" and self.s3 is None:
            raise ValueError("storage.s3 is required when storage.backend is s3")
        return self


class LocalAuthConfig(BaseModel):
    username: str = Field(default="admin", min_length=1)
    password_hash: str = ""


class GoogleAuthConfig(BaseModel):
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    redirect_uri: str = ""


class OidcAuthConfig(BaseModel):
    issuer: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    redirect_uri: str = ""
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])


class TokenPermission(BaseModel):
    repository: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    actions: set[RepositoryAction]


class TokenConfig(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    token_hash: str = Field(min_length=1)
    expires_at: datetime | None = None
    permissions: list[TokenPermission] = Field(default_factory=list)


class AuthConfig(BaseModel):
    providers: list[AuthProvider] = Field(default_factory=lambda: ["local"])
    local: LocalAuthConfig = Field(default_factory=LocalAuthConfig)
    google: GoogleAuthConfig | None = None
    oidc: OidcAuthConfig | None = None
    tokens: list[TokenConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_provider_config(self) -> AuthConfig:
        if "local" in self.providers and not self.local.password_hash:
            raise ValueError("auth.local.password_hash is required when auth.providers is local")

        if "google" in self.providers and self.google is None:
            raise ValueError("auth.google is required when google auth provider is enabled")

        if "oidc" in self.providers and self.oidc is None:
            raise ValueError("auth.oidc is required when oidc auth provider is enabled")

        return self


class RepositoryConfig(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    allow_overwrite: bool = False


class SecurityConfig(BaseModel):
    anonymous_read: bool = False


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    public_url: str | None = None
    session_secret: str = Field(min_length=1)
    max_upload_bytes: int = Field(default=524_288_000, gt=0)
    request_timeout_seconds: int = Field(default=300, gt=0)
    ping_rate_limit_per_minute: int = Field(
        default=10,
        ge=1,
        le=10_000,
        description="Combined /ping requests allowed per minute across all clients",
    )
    operations_port: int = Field(default=9090, ge=1, le=65535)

    @model_validator(mode="after")
    def set_default_public_url(self):
        if not self.public_url:
            self.public_url = f"http://localhost:{self.port}"
        return self


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: LogFormat = "json"


EncryptionKeyProvider = Literal["environment", "aws_secrets_manager"]


class EnvironmentKeyConfig(BaseModel):
    variable: str = "PACKVAULT_SECRETS_ENCRYPTION_KEY"


class AwsSecretsManagerKeyConfig(BaseModel):
    secret_id: str = ""
    region: str = "us-east-1"
    endpoint_url: str = ""
    version_id: str = ""
    version_stage: str = ""


class EncryptionKeyConfig(BaseModel):
    provider: EncryptionKeyProvider = "environment"
    environment: EnvironmentKeyConfig = Field(default_factory=EnvironmentKeyConfig)
    aws_secrets_manager: AwsSecretsManagerKeyConfig = Field(
        default_factory=AwsSecretsManagerKeyConfig
    )


class SecretsConfig(BaseModel):
    encrypt_at_rest: bool = False
    encryption_key: EncryptionKeyConfig = Field(default_factory=EncryptionKeyConfig)


class DatabaseConfig(BaseModel):
    url: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PACKVAULT_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    storage: StorageConfig = Field(default_factory=StorageConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    repositories: list[RepositoryConfig] = Field(
        default_factory=lambda: [
            RepositoryConfig(name="releases", allow_overwrite=False),
            RepositoryConfig(name="snapshots", allow_overwrite=True),
        ]
    )
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)

    config_path: Path | None = None

    @property
    def database_enabled(self) -> bool:
        return bool(self.database.url.strip())

    @model_validator(mode="after")
    def validate_repository_references(self) -> Settings:
        repository_names = {repo.name for repo in self.repositories}

        if len(repository_names) != len(self.repositories):
            raise ValueError("repository names must be unique")

        for token in self.auth.tokens:
            for permission in token.permissions:
                if permission.repository not in repository_names:
                    raise ValueError(
                        f"token {token.name!r} references unknown repository "
                        f"{permission.repository!r}"
                    )

        return self


def _merge_yaml_into_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize YAML keys (camelCase) to snake_case for nested models."""

    def to_snake(s: str) -> str:
        result: list[str] = []

        for i, c in enumerate(s):
            if c.isupper() and i > 0:
                result.append("_")
            result.append(c.lower())

        return "".join(result)

    def convert(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {to_snake(k): convert(v) for k, v in obj.items()}

        if isinstance(obj, list):
            return [convert(i) for i in obj]

        return obj

    return convert(data)


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or os.environ.get("PACKVAULT_CONFIG")

    if path:
        config_file = Path(path)

        if not config_file.is_file():
            raise ValueError(f"PackVault config file not found: {config_file}")

        with config_file.open() as f:
            raw = yaml.safe_load(f) or {}

        raw = substitute_env_vars(raw)
        normalized = _merge_yaml_into_settings(raw)

        settings = Settings(**normalized)
        settings.config_path = config_file

        return settings

    return Settings()


@lru_cache
def get_settings() -> Settings:
    return load_settings()
