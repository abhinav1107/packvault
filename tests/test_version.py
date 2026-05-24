from __future__ import annotations

import importlib

from packvault.__version__ import __version__ as version_from_module


def test_version_module() -> None:
    assert version_from_module == "0.1.2"


def test_package_exports_version() -> None:
    import packvault

    importlib.reload(packvault)
    assert packvault.__version__ == "0.1.2"


def test_installed_metadata_matches() -> None:
    from importlib.metadata import version

    assert version("packvault") == "0.1.2"
