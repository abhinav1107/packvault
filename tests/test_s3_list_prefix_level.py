from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from packvault.config.settings import S3StorageConfig
from packvault.storage.s3 import S3ArtifactStore


@pytest.mark.asyncio
async def test_s3_list_prefix_level_uses_delimiter() -> None:
    config = S3StorageConfig(bucket="packvault", region="us-east-1", prefix="repos")
    store = S3ArtifactStore(config)

    client = AsyncMock()
    client.list_objects_v2 = AsyncMock(
        return_value={
            "CommonPrefixes": [{"Prefix": "repos/releases/com/"}],
            "Contents": [],
        }
    )

    session = MagicMock()
    session.client.return_value.__aenter__ = AsyncMock(return_value=client)
    session.client.return_value.__aexit__ = AsyncMock(return_value=None)
    store._session = session
    store.head = AsyncMock(return_value=None)  # type: ignore[method-assign]

    result = await store.list_prefix_level("releases", max_entries=50)

    assert result.directories == ["com"]
    client.list_objects_v2.assert_awaited_once()
    call_kwargs = client.list_objects_v2.await_args.kwargs
    assert call_kwargs["Delimiter"] == "/"
    assert call_kwargs["Prefix"] == "repos/releases/"
