"""Helpers for presenting Maven artifacts as package summaries in the UI.

The storage layer exposes Maven artifacts as object paths, for example:

    com/example/simple-library/0.1.0/simple-library-0.1.0.jar

The UI should not force users to browse those raw paths. This module converts
Maven object paths into package-oriented summaries such as:

    com.example:simple-library latest=0.1.0 versions=1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cmp_to_key
from pathlib import PurePosixPath
from typing import Iterable


VISIBLE_ARTIFACT_SUFFIXES = (".jar", ".pom")
IGNORED_FILENAMES = {"maven-metadata.xml"}
IGNORED_SUFFIXES = (
    ".asc",
    ".md5",
    ".sha1",
    ".sha256",
    ".sha512",
)


@dataclass(frozen=True)
class PackageCoordinates:
    """Maven package coordinates inferred from a storage object path."""

    repository: str
    group_id: str
    group_path: str
    artifact_id: str
    version: str

    @property
    def package_name(self) -> str:
        """Return the Maven package name in groupId:artifactId format."""
        return f"{self.group_id}:{self.artifact_id}"



@dataclass(frozen=True)
class PackageSummary:
    """Human-friendly summary for one Maven package in one repository."""

    repository: str
    group_id: str
    group_path: str
    artifact_id: str
    latest_version: str
    version_count: int
    versions: tuple[str, ...] = field(default_factory=tuple)
    updated_label: str = "unknown"

    @property
    def package_name(self) -> str:
        """Return the Maven package name in groupId:artifactId format."""
        return f"{self.group_id}:{self.artifact_id}"

    @property
    def artifact_path(self) -> str:
        """Return the storage prefix containing all versions of this artifact."""
        return f"{self.group_path}/{self.artifact_id}"



@dataclass(frozen=True)
class PackageVersionSummary:
    """Human-friendly summary for one version of a Maven package."""

    version: str
    path: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class PackageDetail:
    """Human-friendly detail view for one Maven package."""

    repository: str
    group_id: str
    group_path: str
    artifact_id: str
    latest_version: str
    versions: tuple[PackageVersionSummary, ...]

    @property
    def package_name(self) -> str:
        """Return the Maven package name in groupId:artifactId format."""
        return f"{self.group_id}:{self.artifact_id}"

    @property
    def artifact_path(self) -> str:
        """Return the storage prefix containing all versions of this artifact."""
        return f"{self.group_path}/{self.artifact_id}"

    @property
    def version_count(self) -> int:
        """Return the number of versions available for this package."""
        return len(self.versions)

    @property
    def maven_dependency(self) -> str:
        """Return a Maven dependency snippet for the latest version."""
        return (
            "<dependency>\n"
            f"  <groupId>{self.group_id}</groupId>\n"
            f"  <artifactId>{self.artifact_id}</artifactId>\n"
            f"  <version>{self.latest_version}</version>\n"
            "</dependency>"
        )

    @property
    def gradle_dependency(self) -> str:
        """Return a Gradle dependency snippet for the latest version."""
        return f'implementation("{self.group_id}:{self.artifact_id}:{self.latest_version}")'


def infer_package_from_path(repository: str, path: str) -> PackageCoordinates | None:
    """Infer Maven package coordinates from a storage object path.

    Returns None when the path does not look like a primary Maven artifact file.
    Checksum sidecars, signatures, metadata files, directories, and malformed
    paths are intentionally ignored.
    """
    normalized_path = path.strip("/")
    if not normalized_path:
        return None

    object_path = PurePosixPath(normalized_path)
    filename = object_path.name

    if filename in IGNORED_FILENAMES:
        return None

    if filename.endswith(IGNORED_SUFFIXES):
        return None

    if not filename.endswith(VISIBLE_ARTIFACT_SUFFIXES):
        return None

    parts = object_path.parts
    if len(parts) < 4:
        return None

    version = parts[-2]
    artifact_id = parts[-3]
    group_parts = parts[:-3]

    if not version or not artifact_id or not group_parts:
        return None

    group_path = "/".join(group_parts)
    group_id = ".".join(group_parts)

    return PackageCoordinates(
        repository=repository,
        group_id=group_id,
        group_path=group_path,
        artifact_id=artifact_id,
        version=version,
    )


def build_package_summaries(repository: str, paths: Iterable[str]) -> list[PackageSummary]:
    """Build package summaries from Maven storage object paths.

    Multiple files belonging to the same package version, for example a JAR and
    a POM, are collapsed into one package/version entry.
    """
    versions_by_package: dict[tuple[str, str], set[str]] = {}
    group_path_by_package: dict[tuple[str, str], str] = {}

    for path in paths:
        coordinates = infer_package_from_path(repository, path)
        if coordinates is None:
            continue

        package_key = (coordinates.group_id, coordinates.artifact_id)
        versions_by_package.setdefault(package_key, set()).add(coordinates.version)
        group_path_by_package[package_key] = coordinates.group_path

    summaries: list[PackageSummary] = []
    for (group_id, artifact_id), versions in versions_by_package.items():
        sorted_versions = sort_maven_versions(versions)
        latest_version = sorted_versions[-1]

        summaries.append(
            PackageSummary(
                repository=repository,
                group_id=group_id,
                group_path=group_path_by_package[(group_id, artifact_id)],
                artifact_id=artifact_id,
                latest_version=latest_version,
                version_count=len(sorted_versions),
                versions=tuple(sorted_versions),
            )
        )

    return sorted(summaries, key=lambda package: package.package_name)


def build_package_detail(
    repository: str,
    artifact_path: str,
    paths: Iterable[str],
) -> PackageDetail | None:
    """Build package detail from Maven storage object paths under one artifact.

    The artifact_path is the Maven path without the version, for example:

        com/example/simple-library

    Returns None when no primary Maven artifact files are found for that package.
    """
    normalized_artifact_path = artifact_path.strip("/")
    artifact_parts = PurePosixPath(normalized_artifact_path).parts
    if len(artifact_parts) < 2:
        return None

    artifact_id = artifact_parts[-1]
    group_parts = artifact_parts[:-1]
    group_path = "/".join(group_parts)
    group_id = ".".join(group_parts)

    version_files: dict[str, set[str]] = {}

    for path in paths:
        coordinates = infer_package_from_path(repository, path)
        if coordinates is None:
            continue
        if coordinates.group_path != group_path:
            continue
        if coordinates.artifact_id != artifact_id:
            continue

        filename = PurePosixPath(path).name
        version_files.setdefault(coordinates.version, set()).add(filename)

    if not version_files:
        return None

    sorted_versions = sort_maven_versions(version_files)
    version_summaries = tuple(
        PackageVersionSummary(
            version=version,
            path=f"{normalized_artifact_path}/{version}",
            files=tuple(sorted(version_files[version])),
        )
        for version in reversed(sorted_versions)
    )

    return PackageDetail(
        repository=repository,
        group_id=group_id,
        group_path=group_path,
        artifact_id=artifact_id,
        latest_version=sorted_versions[-1],
        versions=version_summaries,
    )


def sort_maven_versions(versions: Iterable[str]) -> list[str]:
    """Sort Maven-like version strings in ascending order.

    This is intentionally lightweight. It handles common numeric versions well
    enough for the package list UI, while keeping unknown/custom version formats
    deterministic. Full Maven ComparableVersion compatibility can be added later
    if PackVault needs exact Maven ordering semantics.
    """
    return sorted(set(versions), key=cmp_to_key(_compare_versions))


def _compare_versions(left: str, right: str) -> int:
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)

    for left_part, right_part in zip(left_parts, right_parts):
        if left_part == right_part:
            continue

        if isinstance(left_part, int) and isinstance(right_part, int):
            return -1 if left_part < right_part else 1

        left_text = str(left_part)
        right_text = str(right_part)
        if left_text == right_text:
            continue
        return -1 if left_text < right_text else 1

    if len(left_parts) == len(right_parts):
        return 0

    return -1 if len(left_parts) < len(right_parts) else 1


def _version_parts(version: str) -> tuple[int | str, ...]:
    separators = version.replace("-", ".").replace("_", ".")
    parts: list[int | str] = []

    for part in separators.split("."):
        if not part:
            continue
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part.lower())

    return tuple(parts) or (version,)
