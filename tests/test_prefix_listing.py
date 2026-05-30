from __future__ import annotations

from packvault.storage.prefix_listing import (
    merge_directory_page,
    split_immediate_children,
)


def test_split_immediate_children_groups_by_next_segment() -> None:
    keys = [
        "releases/com/example/app/1.0/a.jar",
        "releases/com/example/app/1.0/a.jar.sha1",
        "releases/com/example/app/maven-metadata.xml",
        "releases/com/example/other/2.0/b.jar",
    ]
    directories, files = split_immediate_children(keys, "releases/com/example")
    assert directories == ["app", "other"]
    assert files == []


def test_split_immediate_children_files_at_level() -> None:
    keys = [
        "releases/com/example/app/maven-metadata.xml",
        "releases/com/example/app/1.0/a.jar",
    ]
    directories, files = split_immediate_children(keys, "releases/com/example/app")
    assert directories == ["1.0"]
    assert files == ["releases/com/example/app/maven-metadata.xml"]


def test_merge_directory_page_paginates_combined_list() -> None:
    directories = ["0.1.0", "0.2.0", "0.3.0"]
    files: list[str] = []
    page_dirs, page_files, cursor, has_more = merge_directory_page(
        directories,
        files,
        max_entries=2,
        start_after=None,
    )
    assert page_dirs == ["0.1.0", "0.2.0"]
    assert page_files == []
    assert has_more
    assert cursor == "d:0.2.0"

    page_dirs, page_files, cursor, has_more = merge_directory_page(
        directories,
        files,
        max_entries=2,
        start_after=cursor,
    )
    assert page_dirs == ["0.3.0"]
    assert not has_more
