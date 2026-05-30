from packvault.ui.packages import (
    PackageCoordinates,
    build_package_summaries,
    infer_package_from_path,
    sort_maven_versions,
)


def test_infer_package_from_jar_path() -> None:
    coordinates = infer_package_from_path(
        "releases",
        "com/example/simple-library/0.1.0/simple-library-0.1.0.jar",
    )

    assert coordinates == PackageCoordinates(
        repository="releases",
        group_id="com.example",
        group_path="com/example",
        artifact_id="simple-library",
        version="0.1.0",
    )
    assert coordinates.package_name == "com.example:simple-library"


def test_infer_package_from_pom_path() -> None:
    coordinates = infer_package_from_path(
        "releases",
        "org/acme/my-app/1.2.3/my-app-1.2.3.pom",
    )

    assert coordinates == PackageCoordinates(
        repository="releases",
        group_id="org.acme",
        group_path="org/acme",
        artifact_id="my-app",
        version="1.2.3",
    )
    assert coordinates.package_name == "org.acme:my-app"


def test_infer_package_ignores_checksum_sidecars() -> None:
    ignored_paths = [
        "com/example/simple-library/0.1.0/simple-library-0.1.0.jar.md5",
        "com/example/simple-library/0.1.0/simple-library-0.1.0.jar.sha1",
        "com/example/simple-library/0.1.0/simple-library-0.1.0.jar.sha256",
        "com/example/simple-library/0.1.0/simple-library-0.1.0.jar.sha512",
        "com/example/simple-library/0.1.0/simple-library-0.1.0.jar.asc",
    ]

    for path in ignored_paths:
        assert infer_package_from_path("releases", path) is None


def test_infer_package_ignores_metadata_and_non_artifact_files() -> None:
    ignored_paths = [
        "com/example/simple-library/maven-metadata.xml",
        "com/example/simple-library/maven-metadata.xml.sha1",
        "com/example/simple-library/0.1.0/README.txt",
        "com/example/simple-library/0.1.0/",
        "simple-library-0.1.0.jar",
        "",
    ]

    for path in ignored_paths:
        assert infer_package_from_path("releases", path) is None


def test_build_package_summaries_collapses_multiple_files_for_same_version() -> None:
    summaries = build_package_summaries(
        "releases",
        [
            "com/example/simple-library/0.1.0/simple-library-0.1.0.jar",
            "com/example/simple-library/0.1.0/simple-library-0.1.0.pom",
            "com/example/simple-library/0.1.0/simple-library-0.1.0.jar.sha1",
            "com/example/simple-library/0.2.0/simple-library-0.2.0.jar",
            "com/example/simple-library/0.2.0/simple-library-0.2.0.pom",
        ],
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.repository == "releases"
    assert summary.group_id == "com.example"
    assert summary.group_path == "com/example"
    assert summary.artifact_id == "simple-library"
    assert summary.package_name == "com.example:simple-library"
    assert summary.artifact_path == "com/example/simple-library"
    assert summary.latest_version == "0.2.0"
    assert summary.version_count == 2
    assert summary.versions == ("0.1.0", "0.2.0")


def test_build_package_summaries_returns_multiple_packages_sorted_by_name() -> None:
    summaries = build_package_summaries(
        "snapshots",
        [
            "org/acme/zeta/1.0.0/zeta-1.0.0.jar",
            "com/example/alpha/2.0.0/alpha-2.0.0.jar",
            "com/example/alpha/2.1.0/alpha-2.1.0.jar",
        ],
    )

    assert [summary.package_name for summary in summaries] == [
        "com.example:alpha",
        "org.acme:zeta",
    ]
    assert summaries[0].repository == "snapshots"
    assert summaries[0].latest_version == "2.1.0"
    assert summaries[0].version_count == 2
    assert summaries[1].latest_version == "1.0.0"
    assert summaries[1].version_count == 1


def test_sort_maven_versions_handles_common_numeric_versions() -> None:
    assert sort_maven_versions(["1.10.0", "1.2.0", "1.0.0", "2.0.0"]) == [
        "1.0.0",
        "1.2.0",
        "1.10.0",
        "2.0.0",
    ]


def test_sort_maven_versions_is_deterministic_for_mixed_qualifiers() -> None:
    assert sort_maven_versions(["1.0.0", "1.0.0-SNAPSHOT", "1.0.0-alpha"]) == [
        "1.0.0",
        "1.0.0-alpha",
        "1.0.0-SNAPSHOT",
    ]
