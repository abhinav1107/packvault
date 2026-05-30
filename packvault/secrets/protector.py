from __future__ import annotations

from dataclasses import dataclass

from packvault.db.models import SECRET_STATUS_DECRYPT_FAILED
from packvault.secrets.encryption import (
    DecryptionError,
    EncryptionContext,
    decrypt_secret,
    encrypt_secret,
)


@dataclass(frozen=True)
class SecretValue:
    stored: str
    secret_status: str | None = None


class SecretProtector:
    def __init__(self, encryption: EncryptionContext) -> None:
        self._encryption = encryption

    @property
    def encryption_enabled(self) -> bool:
        return self._encryption.enabled

    @property
    def key_fingerprint(self) -> str | None:
        return self._encryption.fingerprint

    def protect(self, plaintext: str) -> SecretValue:
        if not self._encryption.enabled:
            return SecretValue(stored=plaintext)

        if self._encryption.key is None:
            raise RuntimeError("encryption enabled but master key is missing")

        return SecretValue(stored=encrypt_secret(self._encryption.key, plaintext))

    def reveal(self, stored: str, *, secret_status: str | None = None) -> str:
        if secret_status == SECRET_STATUS_DECRYPT_FAILED:
            raise DecryptionError("secret field marked decrypt_failed")

        if not self._encryption.enabled:
            return stored

        if self._encryption.key is None:
            raise RuntimeError("encryption enabled but master key is missing")

        return decrypt_secret(self._encryption.key, stored)

    def reveal_or_failed(self, stored: str, *, secret_status: str | None = None) -> SecretValue:
        try:
            return SecretValue(stored=self.reveal(stored, secret_status=secret_status))
        except DecryptionError:
            return SecretValue(stored=stored, secret_status=SECRET_STATUS_DECRYPT_FAILED)
