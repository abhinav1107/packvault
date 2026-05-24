from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

import aiofiles

ChecksumAlgorithm = Literal["md5", "sha1", "sha256", "sha512"]

_CHECKSUM_SUFFIXES: dict[str, ChecksumAlgorithm] = {
    ".md5": "md5",
    ".sha1": "sha1",
    ".sha256": "sha256",
    ".sha512": "sha512",
}

_CHUNK_SIZE = 64 * 1024


def checksum_algorithm_for_path(path: str) -> ChecksumAlgorithm | None:
    normalized = path.lower()

    for suffix, algorithm in _CHECKSUM_SUFFIXES.items():
        if normalized.endswith(suffix):
            return algorithm

    return None


def is_checksum_path(path: str) -> bool:
    return checksum_algorithm_for_path(path) is not None


def artifact_path_for_checksum(path: str) -> str | None:
    normalized = path.lower()

    for suffix in _CHECKSUM_SUFFIXES:
        if normalized.endswith(suffix):
            return path[: -len(suffix)]

    return None


def new_hasher(algorithm: ChecksumAlgorithm):
    return hashlib.new(algorithm)


def compute_checksum_bytes(data: bytes, algorithm: ChecksumAlgorithm) -> str:
    hasher = new_hasher(algorithm)
    hasher.update(data)
    return hasher.hexdigest()


def compute_checksum_file(path: Path, algorithm: ChecksumAlgorithm) -> str:
    hasher = new_hasher(algorithm)

    with path.open("rb") as file:
        while chunk := file.read(_CHUNK_SIZE):
            hasher.update(chunk)

    return hasher.hexdigest()


async def compute_checksum_file_async(path: Path, algorithm: ChecksumAlgorithm) -> str:
    hasher = new_hasher(algorithm)

    async with aiofiles.open(path, "rb") as file:
        while chunk := await file.read(_CHUNK_SIZE):
            hasher.update(chunk)

    return hasher.hexdigest()


async def compute_checksum_stream(
    stream: AsyncIterator[bytes],
    algorithm: ChecksumAlgorithm,
) -> str:
    hasher = new_hasher(algorithm)

    async for chunk in stream:
        hasher.update(chunk)

    return hasher.hexdigest()


def normalize_checksum_text(value: str) -> str:
    """Normalize uploaded checksum file content.

    Maven checksum files are commonly plain hex digests, but some tools may
    include whitespace or filename-style content. For v1, use the first token.
    """

    return value.strip().split()[0].lower() if value.strip() else ""


def is_valid_checksum_text(value: str, algorithm: ChecksumAlgorithm) -> bool:
    normalized = normalize_checksum_text(value)

    expected_lengths: dict[ChecksumAlgorithm, int] = {
        "md5": 32,
        "sha1": 40,
        "sha256": 64,
        "sha512": 128,
    }

    expected_length = expected_lengths[algorithm]

    if len(normalized) != expected_length:
        return False

    return all(char in "0123456789abcdef" for char in normalized)
