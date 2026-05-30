from __future__ import annotations

from pathlib import Path

from packvault.setup.service import alembic_config


def test_alembic_config_uses_repo_migrations() -> None:
    config = alembic_config()
    script_location = config.get_main_option("script_location")
    assert script_location is not None
    assert Path(script_location).is_dir()
    assert (Path(script_location) / "versions").is_dir()
