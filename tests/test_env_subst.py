from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from packvault.auth.passwords import hash_password
from packvault.config.env_subst import EnvSubstitutionError, substitute_env_vars
from packvault.config.settings import load_settings


def test_substitute_whole_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SECRET", "hunter2")
    raw = {"auth": {"local": {"passwordHash": "${env.MY_SECRET}"}}}
    assert substitute_env_vars(raw)["auth"]["local"]["passwordHash"] == "hunter2"


def test_substitute_embedded_in_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "packvault.example")
    raw = {"server": {"publicUrl": "https://${env.HOST}"}}
    assert substitute_env_vars(raw)["server"]["publicUrl"] == "https://packvault.example"


def test_substitute_in_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_HASH", "sha256:abc")
    raw = {"auth": {"tokens": [{"tokenHash": "${env.TOKEN_HASH}"}]}}
    result = substitute_env_vars(raw)
    assert result["auth"]["tokens"][0]["tokenHash"] == "sha256:abc"


def test_missing_env_strict() -> None:
    os.environ.pop("DEFINITELY_NOT_SET_XYZ", None)
    with pytest.raises(EnvSubstitutionError, match="DEFINITELY_NOT_SET_XYZ"):
        substitute_env_vars({"x": "${env.DEFINITELY_NOT_SET_XYZ}"})


def test_load_settings_from_yaml_with_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PACKVAULT_SESSION_SECRET", "from-env-secret")

    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.dump(
            {
                "server": {
                    "sessionSecret": "${env.PACKVAULT_SESSION_SECRET}",
                },
                "storage": {
                    "backend": "local",
                    "local": {
                        "root": "/tmp/maven",
                    },
                },
                "auth": {
                    "providers": ["local"],
                    "local": {
                        "username": "admin",
                        "passwordHash": hash_password("admin"),
                    },
                },
            }
        )
    )

    settings = load_settings(config)

    assert settings.server.session_secret == "from-env-secret"
    assert settings.auth.local.username == "admin"
    assert settings.auth.local.password_hash
