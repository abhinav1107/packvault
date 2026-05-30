from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packvault.config.settings import S3StorageConfig
from packvault.storage.s3 import S3ArtifactStore


@pytest.mark.asyncio
async def test_s3_list_prefix_uses_start_after_for_mid_page_resume() -> None:
    config = S3StorageConfig(bucket="packvault", region="us-east-1", prefix="repos")
    store = S3ArtifactStore(config)

    client = AsyncMock()
    client.list_objects_v2 = AsyncMock(
        return_value={
            "Contents": [{"Key": "repos/releases/com/example/c.jar"}],
        }
    )

    session = MagicMock()
    session.client.return_value.__aenter__ = AsyncMock(return_value=client)
    session.client.return_value.__aexit__ = AsyncMock(return_value=None)
    store._session = session

    result = await store.list_prefix(
        "releases/com/example",
        max_keys=50,
        start_after="releases/com/example/b.jar",
    )

    assert result.keys == ["releases/com/example/c.jar"]
    client.list_objects_v2.assert_awaited_once_with(
        Bucket="packvault",
        Prefix="repos/releases/com/example",
        MaxKeys=50,
        StartAfter="repos/releases/com/example/b.jar",
    )


@pytest.mark.asyncio
async def test_s3_list_prefix_uses_continuation_token_for_next_page() -> None:
    config = S3StorageConfig(bucket="packvault", region="us-east-1", prefix="repos")
    store = S3ArtifactStore(config)

    client = AsyncMock()
    client.list_objects_v2 = AsyncMock(
        return_value={
            "Contents": [{"Key": "repos/releases/a.jar"}],
            "NextContinuationToken": "token-2",
        }
    )

    session = MagicMock()
    session.client.return_value.__aenter__ = AsyncMock(return_value=client)
    session.client.return_value.__aexit__ = AsyncMock(return_value=None)
    store._session = session

    result = await store.list_prefix(
        "releases",
        continuation_token="token-1",
    )

    assert result.continuation_token == "token-2"
    client.list_objects_v2.assert_awaited_once_with(
        Bucket="packvault",
        Prefix="repos/releases",
        MaxKeys=100,
        ContinuationToken="token-1",
    )
