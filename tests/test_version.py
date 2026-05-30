from __future__ import annotations

import importlib
import re

from packvault.__version__ import __version__ as version_from_module

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_module() -> None:
    assert _SEMVER_RE.fullmatch(version_from_module)


def test_package_exports_version() -> None:
    import packvault

    importlib.reload(packvault)
    assert packvault.__version__ == version_from_module


def test_installed_metadata_matches() -> None:
    from importlib.metadata import version

    assert version("packvault") == version_from_module
