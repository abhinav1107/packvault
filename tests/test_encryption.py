from __future__ import annotations

import pytest

from packvault.secrets.encryption import (
    DecryptionError,
    EncryptionContext,
    decrypt_secret,
    encrypt_secret,
    key_fingerprint,
    load_encryption_key_from_environment,
    normalize_master_key,
)
from packvault.secrets.protector import SecretProtector


def test_encrypt_decrypt_round_trip() -> None:
    key = b"test-master-key-material"
    plaintext = "sha256:abc123deadbeef"

    stored = encrypt_secret(key, plaintext)
    assert stored != plaintext
    assert decrypt_secret(key, stored) == plaintext


def test_key_fingerprint_is_stable() -> None:
    key = b"same-key"
    assert key_fingerprint(normalize_master_key(key)) == key_fingerprint(normalize_master_key(key))


def test_decrypt_with_wrong_key_fails() -> None:
    stored = encrypt_secret(b"key-one", "secret-value")
    with pytest.raises(DecryptionError):
        decrypt_secret(b"key-two", stored)


def test_secret_protector_plaintext_mode() -> None:
    protector = SecretProtector(EncryptionContext(enabled=False, key=None, fingerprint=None))
    protected = protector.protect("sha256:abc")
    assert protected.stored == "sha256:abc"
    assert protected.secret_status is None
    assert protector.reveal(protected.stored) == "sha256:abc"


def test_secret_protector_decrypt_failed_status() -> None:
    protector = SecretProtector(EncryptionContext(enabled=False, key=None, fingerprint=None))
    with pytest.raises(DecryptionError):
        protector.reveal("value", secret_status="decrypt_failed")


def test_secret_protector_reveal_or_failed() -> None:
    key = b"protector-key"
    encryption = EncryptionContext(
        enabled=True,
        key=key,
        fingerprint=key_fingerprint(normalize_master_key(key)),
    )
    protector = SecretProtector(encryption)
    protected = protector.protect("sha256:tokenhash")
    wrong_key_protector = SecretProtector(
        EncryptionContext(
            enabled=True,
            key=b"other-key",
            fingerprint=key_fingerprint(normalize_master_key(b"other-key")),
        )
    )
    result = wrong_key_protector.reveal_or_failed(protected.stored)
    assert result.secret_status == "decrypt_failed"


def test_load_encryption_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACKVAULT_SECRETS_ENCRYPTION_KEY", "dev-key")
    assert load_encryption_key_from_environment("PACKVAULT_SECRETS_ENCRYPTION_KEY") == b"dev-key"


def test_aws_secrets_manager_config_accepts_endpoint_url() -> None:
    from packvault.config.settings import AwsSecretsManagerKeyConfig

    cfg = AwsSecretsManagerKeyConfig(
        secret_id="packvault/dev/encryption-key",
        endpoint_url="http://localstack:4566",
    )
    assert cfg.endpoint_url == "http://localstack:4566"


def test_load_encryption_key_from_environment_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PACKVAULT_SECRETS_ENCRYPTION_KEY", raising=False)
    from packvault.utils.errors import ServiceUnavailableError

    with pytest.raises(ServiceUnavailableError):
        load_encryption_key_from_environment("PACKVAULT_SECRETS_ENCRYPTION_KEY")
