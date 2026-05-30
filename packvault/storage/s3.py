from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

import aioboto3
import aiofiles
from botocore.config import Config
from botocore.exceptions import ClientError

from packvault.config.settings import S3StorageConfig
from packvault.storage.base import (
    ArtifactStore,
    ListDirectoryResult,
    ListPrefixResult,
    ObjectMeta,
)
from packvault.storage.prefix_listing import directory_boundary_prefix
from packvault.utils.errors import ConflictError, NotFoundError, ServiceUnavailableError

_CHUNK_SIZE = 64 * 1024


class S3ArtifactStore(ArtifactStore):
    def __init__(self, config: S3StorageConfig) -> None:
        self._config = config
        self._session = aioboto3.Session()
        self._prefix = config.prefix.strip("/")

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")

        if self._prefix:
            return f"{self._prefix}/{key}"

        return key

    def _logical_key(self, full_key: str) -> str:
        if not self._prefix:
            return full_key

        prefix = f"{self._prefix}/"

        if full_key.startswith(prefix):
            return full_key[len(prefix):]

        return full_key

    def _client_kwargs(self) -> dict:
        kwargs: dict = {
            "region_name": self._config.region,
        }

        if self._config.endpoint_url:
            kwargs["endpoint_url"] = self._config.endpoint_url

        if self._config.path_style:
            kwargs["config"] = Config(s3={"addressing_style": "path"})

        return kwargs

    @staticmethod
    def _error_code(exc: ClientError) -> str:
        return exc.response.get("Error", {}).get("Code", "")

    @staticmethod
    def _is_not_found(exc: ClientError) -> bool:
        return S3ArtifactStore._error_code(exc) in {"404", "NoSuchKey", "NotFound"}

    @staticmethod
    def _is_precondition_failed(exc: ClientError) -> bool:
        return S3ArtifactStore._error_code(exc) in {
            "412",
            "PreconditionFailed",
            "Precondition Failed",
        }

    async def head(self, key: str) -> ObjectMeta | None:
        full_key = self._full_key(key)

        async with self._session.client("s3", **self._client_kwargs()) as client:
            try:
                response = await client.head_object(
                    Bucket=self._config.bucket,
                    Key=full_key,
                )
            except ClientError as exc:
                if self._is_not_found(exc):
                    return None

                raise ServiceUnavailableError(f"S3 error: {exc}") from exc

        return ObjectMeta(
            key=key,
            size=response.get("ContentLength", 0),
            etag=response.get("ETag"),
            content_type=response.get("ContentType"),
        )

    async def get(self, key: str) -> AsyncIterator[bytes]:
        full_key = self._full_key(key)

        async def iter_object() -> AsyncIterator[bytes]:
            async with self._session.client("s3", **self._client_kwargs()) as client:
                try:
                    response = await client.get_object(
                        Bucket=self._config.bucket,
                        Key=full_key,
                    )
                    stream = response["Body"]

                    while chunk := await stream.read(_CHUNK_SIZE):
                        yield chunk

                except ClientError as exc:
                    if self._is_not_found(exc):
                        raise NotFoundError("Artifact not found") from exc

                    raise ServiceUnavailableError(f"S3 error: {exc}") from exc

        return iter_object()

    async def put(
        self,
        key: str,
        body: AsyncIterator[bytes] | BinaryIO,
        *,
        content_type: str | None = None,
        if_none_match: bool = False,
    ) -> None:
        full_key = self._full_key(key)
        temp_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(prefix="packvault-s3-upload-", delete=False) as temp:
                temp_path = Path(temp.name)

            async with aiofiles.open(temp_path, "wb") as file:
                if hasattr(body, "read"):
                    while chunk := body.read(_CHUNK_SIZE):  # type: ignore[union-attr]
                        if isinstance(chunk, str):
                            chunk = chunk.encode()
                        await file.write(chunk)
                else:
                    async for chunk in body:  # type: ignore[union-attr]
                        await file.write(chunk)

            put_kwargs: dict = {
                "Bucket": self._config.bucket,
                "Key": full_key,
            }

            if content_type:
                put_kwargs["ContentType"] = content_type

            if if_none_match:
                put_kwargs["IfNoneMatch"] = "*"

            async with self._session.client("s3", **self._client_kwargs()) as client:
                try:
                    with temp_path.open("rb") as file:
                        await client.put_object(
                            Body=file,
                            **put_kwargs,
                        )
                except ClientError as exc:
                    if if_none_match and self._is_precondition_failed(exc):
                        raise ConflictError("Artifact already exists") from exc

                    raise ServiceUnavailableError(f"S3 upload failed: {exc}") from exc

        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    async def check_health(self) -> None:
        async with self._session.client("s3", **self._client_kwargs()) as client:
            try:
                await client.head_bucket(Bucket=self._config.bucket)
            except ClientError as exc:
                raise ServiceUnavailableError(f"S3 bucket unreachable: {exc}") from exc

    async def list_prefix(
        self,
        prefix: str,
        *,
        max_keys: int = 100,
        continuation_token: str | None = None,
        start_after: str | None = None,
    ) -> ListPrefixResult:
        full_prefix = self._full_key(prefix)
        list_kwargs: dict = {
            "Bucket": self._config.bucket,
            "Prefix": full_prefix,
            "MaxKeys": max_keys,
        }

        if continuation_token:
            list_kwargs["ContinuationToken"] = continuation_token
        elif start_after:
            list_kwargs["StartAfter"] = self._full_key(start_after)

        async with self._session.client("s3", **self._client_kwargs()) as client:
            try:
                response = await client.list_objects_v2(**list_kwargs)
            except ClientError as exc:
                raise ServiceUnavailableError(f"S3 list failed: {exc}") from exc

        return ListPrefixResult(
            keys=[
                self._logical_key(obj["Key"])
                for obj in response.get("Contents", [])
            ],
            continuation_token=response.get("NextContinuationToken"),
        )

    async def list_prefix_level(
        self,
        prefix: str,
        *,
        max_entries: int = 100,
        continuation_token: str | None = None,
    ) -> ListDirectoryResult:
        if await self.head(prefix) is not None:
            if continuation_token is not None:
                return ListDirectoryResult([], [], None, False)
            return ListDirectoryResult([], [prefix], None, False)

        full_prefix = self._full_key(prefix)
        list_prefix = directory_boundary_prefix(full_prefix) or full_prefix
        list_kwargs: dict = {
            "Bucket": self._config.bucket,
            "Prefix": list_prefix,
            "Delimiter": "/",
            "MaxKeys": max_entries,
        }
        if continuation_token:
            list_kwargs["ContinuationToken"] = continuation_token

        async with self._session.client("s3", **self._client_kwargs()) as client:
            try:
                response = await client.list_objects_v2(**list_kwargs)
            except ClientError as exc:
                raise ServiceUnavailableError(f"S3 list failed: {exc}") from exc

        directories: list[str] = []
        for common_prefix in response.get("CommonPrefixes", []):
            logical_path = self._logical_key(common_prefix["Prefix"].rstrip("/"))
            directories.append(logical_path.rsplit("/", 1)[-1])

        files = [
            self._logical_key(obj["Key"])
            for obj in response.get("Contents", [])
            if obj["Key"] != list_prefix
        ]
        next_token = response.get("NextContinuationToken")
        has_more = next_token is not None
        return ListDirectoryResult(directories, files, next_token, has_more)

    async def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return

        batch_size = 1000
        async with self._session.client("s3", **self._client_kwargs()) as client:
            for offset in range(0, len(keys), batch_size):
                batch = keys[offset : offset + batch_size]
                delete_payload = {
                    "Objects": [{"Key": self._full_key(key)} for key in batch],
                    "Quiet": True,
                }
                try:
                    response = await client.delete_objects(
                        Bucket=self._config.bucket,
                        Delete=delete_payload,
                    )
                except ClientError as exc:
                    raise ServiceUnavailableError(f"S3 bulk delete failed: {exc}") from exc

                errors = response.get("Errors", [])
                if errors:
                    raise ServiceUnavailableError(
                        f"S3 bulk delete failed: {errors[0].get('Message', 'unknown error')}"
                    )

    async def delete(self, key: str) -> None:
        if await self.head(key) is None:
            raise NotFoundError("Artifact not found")

        full_key = self._full_key(key)

        async with self._session.client("s3", **self._client_kwargs()) as client:
            try:
                await client.delete_object(
                    Bucket=self._config.bucket,
                    Key=full_key,
                )
            except ClientError as exc:
                raise ServiceUnavailableError(f"S3 delete failed: {exc}") from exc