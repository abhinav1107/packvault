from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packvault.storage.local import LocalArtifactStore
from packvault.utils.errors import ConflictError


@pytest.mark.asyncio
async def test_local_exclusive_put() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))
        await store.put("releases/a/b.jar", _bytes_iter(b"one"), if_none_match=True)
        with pytest.raises(ConflictError):
            await store.put("releases/a/b.jar", _bytes_iter(b"two"), if_none_match=True)


async def _bytes_iter(data: bytes):
    yield data
