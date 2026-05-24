from __future__ import annotations

import pytest

from packvault.security.path_validation import validate_maven_path
from packvault.utils.errors import BadRequestError


def test_valid_path() -> None:
    assert validate_maven_path("com/acme/foo/1.0.0/foo-1.0.0.jar") == (
        "com/acme/foo/1.0.0/foo-1.0.0.jar"
    )


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../etc/passwd",
        "com//acme",
        "com/acme%2e%2e/foo",
        "com/acme/foo\x00bar",
    ],
)
def test_invalid_paths(path: str) -> None:
    with pytest.raises(BadRequestError):
        validate_maven_path(path)
