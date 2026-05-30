from __future__ import annotations


def directory_boundary_prefix(storage_prefix: str) -> str:
    """Return the prefix used to match immediate children in object keys."""
    if not storage_prefix:
        return ""
    if storage_prefix.endswith("/"):
        return storage_prefix
    return f"{storage_prefix}/"


def split_immediate_children(
    keys: list[str],
    storage_prefix: str,
) -> tuple[list[str], list[str]]:
    """Split flat object keys into child directory names and files at one level."""
    boundary = directory_boundary_prefix(storage_prefix)
    directories: set[str] = set()
    files: list[str] = []

    for key in keys:
        if boundary:
            if not key.startswith(boundary):
                if key == storage_prefix.rstrip("/"):
                    files.append(key)
                continue
            remainder = key[len(boundary) :]
        else:
            remainder = key

        if not remainder:
            continue

        segment, _, rest = remainder.partition("/")
        if rest:
            directories.add(segment)
        else:
            files.append(key)

    return sorted(directories), sorted(files)


def merge_directory_page(
    directories: list[str],
    files: list[str],
    *,
    max_entries: int,
    start_after: str | None,
) -> tuple[list[str], list[str], str | None, bool]:
    """Paginate a combined directories-then-files listing."""
    entries: list[tuple[str, str]] = [("d", name) for name in directories]
    entries.extend(("f", key) for key in files)

    if start_after:
        start_index = 0
        for index, (kind, value) in enumerate(entries):
            token = f"{kind}:{value}"
            if token > start_after:
                start_index = index
                break
        else:
            return [], [], None, False
        entries = entries[start_index:]

    page = entries[:max_entries]
    has_more = len(entries) > max_entries

    page_dirs: list[str] = []
    page_files: list[str] = []
    for kind, value in page:
        if kind == "d":
            page_dirs.append(value)
        else:
            page_files.append(value)

    next_cursor = None
    if has_more and page:
        last_kind, last_value = page[-1]
        next_cursor = f"{last_kind}:{last_value}"

    return page_dirs, page_files, next_cursor, has_more
