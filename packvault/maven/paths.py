from __future__ import annotations

import re
from dataclasses import dataclass

from packvault.security.path_validation import validate_maven_path
from packvault.utils.errors import BadRequestError, NotFoundError

_REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class MavenRequest:
    repository: str
    artifact_path: str
    storage_key: str


def validate_repository_name(repository: str) -> str:
    if not repository or not _REPOSITORY_NAME_RE.fullmatch(repository):
        raise BadRequestError("Invalid repository name")

    return repository


def build_storage_key(repository: str, artifact_path: str) -> str:
    return f"{repository}/{artifact_path}"


def parse_maven_request(
    repository: str,
    artifact_path: str,
    *,
    known_repositories: set[str],
) -> MavenRequest:
    validated_repository = validate_repository_name(repository)

    if validated_repository not in known_repositories:
        raise NotFoundError(f"Repository '{validated_repository}' not found")

    validated_artifact_path = validate_maven_path(artifact_path)
    storage_key = build_storage_key(validated_repository, validated_artifact_path)

    return MavenRequest(
        repository=validated_repository,
        artifact_path=validated_artifact_path,
        storage_key=storage_key,
    )
