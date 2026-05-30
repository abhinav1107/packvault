from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from packvault.config.settings import EncryptionKeyConfig, SecretsConfig
from packvault.utils.errors import PackVaultError, ServiceUnavailableError


class EncryptionError(PackVaultError):
    code = "encryption_error"


class DecryptionError(EncryptionError):
    pass


def key_fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()


def normalize_master_key(raw: bytes) -> bytes:
    return hashlib.sha256(raw).digest()


def encrypt_secret(key: bytes, plaintext: str) -> str:
    aesgcm = AESGCM(normalize_master_key(key))
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(key: bytes, stored: str) -> str:
    try:
        data = base64.b64decode(stored)
        if len(data) < 13:
            raise DecryptionError("ciphertext too short")
        nonce, ciphertext = data[:12], data[12:]
        plaintext = AESGCM(normalize_master_key(key)).decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except DecryptionError:
        raise
    except Exception as exc:
        raise DecryptionError("failed to decrypt secret field") from exc


def load_encryption_key_from_environment(variable: str) -> bytes:
    value = os.environ.get(variable, "").strip()
    if not value:
        raise ServiceUnavailableError(
            f"Encryption is enabled but {variable} is not set. "
            "Provide the master key or disable secrets.encrypt_at_rest."
        )
    return value.encode("utf-8")


async def load_encryption_key_from_aws(config: EncryptionKeyConfig) -> bytes:
    aws = config.aws_secrets_manager
    if not aws.secret_id:
        raise ServiceUnavailableError(
            "Encryption is enabled but secrets.encryption_key.aws_secrets_manager.secret_id "
            "is not configured."
        )

    import aioboto3

    kwargs: dict[str, str] = {"SecretId": aws.secret_id}
    if aws.version_id:
        kwargs["VersionId"] = aws.version_id
    if aws.version_stage:
        kwargs["VersionStage"] = aws.version_stage

    client_kwargs: dict[str, str] = {"region_name": aws.region}
    if aws.endpoint_url:
        client_kwargs["endpoint_url"] = aws.endpoint_url

    session = aioboto3.Session()
    async with session.client("secretsmanager", **client_kwargs) as client:
        response = await client.get_secret_value(**kwargs)

    secret = response.get("SecretString")
    if not secret:
        raise ServiceUnavailableError(
            f"AWS Secrets Manager secret {aws.secret_id!r} has no SecretString value."
        )

    return secret.encode("utf-8")


@dataclass(frozen=True)
class EncryptionContext:
    enabled: bool
    key: bytes | None
    fingerprint: str | None
    provider: str | None = None

    @classmethod
    async def from_config(cls, secrets: SecretsConfig) -> EncryptionContext:
        if not secrets.encrypt_at_rest:
            return cls(enabled=False, key=None, fingerprint=None)

        key_config = secrets.encryption_key
        if key_config.provider == "environment":
            key = load_encryption_key_from_environment(
                key_config.environment.variable,
            )
            return cls(
                enabled=True,
                key=key,
                fingerprint=key_fingerprint(normalize_master_key(key)),
                provider="environment",
            )

        if key_config.provider == "aws_secrets_manager":
            key = await load_encryption_key_from_aws(key_config)
            return cls(
                enabled=True,
                key=key,
                fingerprint=key_fingerprint(normalize_master_key(key)),
                provider="aws_secrets_manager",
            )

        raise ServiceUnavailableError(
            f"Unsupported encryption key provider: {key_config.provider!r}"
        )
