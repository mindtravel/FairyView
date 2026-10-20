"""Source resolution: which files, which columns, and what is missing.

Adapters no longer locate files or decide projections. They ask a `Source` for
the rows they need and name the columns they intend to read; the Source checks
those names against the real schema and fails with the available columns.

That check exists because the previous per-adapter behaviour was inconsistent:
`chat_rows` silently produced an empty page when its default facet column was
absent, while `hf_rows` raised. One place, one answer.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple

from fairyview.rows import (
    PARQUET_SUFFIXES,
    iter_files,
    iter_light_rows,
    iter_rows,
    parquet_columns,
    parquet_row_count,
    read_jsonl_at,
    read_rows_at,
    scan_jsonl,
    is_seekable_jsonl,
)


class Key(NamedTuple):
    """Row address. `offset` is the byte offset for plain JSONL, else None."""

    file: str
    index: int
    offset: int | None = None


@dataclass(frozen=True)
class Source:
    path: str
    glob: str
    files: tuple[str, ...]
    columns: tuple[str, ...]
    root: str
    # (size, mtime_ns) per file at load time. Row keys carry byte offsets, so a
    # file rewritten between scan and read would return the wrong rows.
    stamps: tuple[tuple[int, int], ...] = ()

    @property
    def is_parquet(self) -> bool:
        return bool(self.files) and self.files[0].endswith(PARQUET_SUFFIXES)

    def relative(self, file_path: str) -> str:
        return os.path.relpath(file_path, self.root) if os.path.isdir(self.root) else os.path.basename(file_path)

    def has(self, column: str) -> bool:
        return column in self.columns

    def missing(self, wanted) -> list[str]:
        return [c for c in wanted if c and c not in self.columns]

    def require(self, wanted, *, owner: str) -> None:
        missing = self.missing(wanted)
        if missing:
            raise ValueError(
                f"{owner}: columns {missing} not found in {self.path!r}; available: {list(self.columns)}"
            )

    def resolve(self, column: str | None, role: str, *, owner: str) -> str:
        """Configured column, else the role's first match; else fail."""
        from fairyview import roles

        if column:
            self.require([column], owner=owner)
            return column
        found = roles.find(self.columns, role)
        if not found:
            raise ValueError(
                f"{owner}: no {role} column found; available: {list(self.columns)}. "
                f"Set the matching field in [source] explicitly."
            )
        return found

    def iter_index(self, projection, *, owner: str) -> Iterator[tuple[Key, dict]]:
        """Stream (file, index) keys with only the projected columns decoded.

        A generator, not a list: sampling consumes the stream and keeps `n`
        items, so a 1M-row file costs one rolling window rather than a
        1M-entry list.
        """
        projection = [c for c in projection if c]
        if projection:
            self.require(projection, owner=owner)
        for file_path in self.files:
            if is_seekable_jsonl(file_path):
                for index, (offset, row) in enumerate(scan_jsonl(file_path, projection)):
                    yield Key(file_path, index, offset), row
            elif projection:
                for index, row in enumerate(iter_light_rows(file_path, projection)):
                    yield Key(file_path, index), row
            elif file_path.endswith(PARQUET_SUFFIXES):
                for index in range(parquet_row_count(file_path)):
                    yield Key(file_path, index), {}
            else:
                for index, _ in enumerate(iter_rows(file_path)):
                    yield Key(file_path, index), {}

    def check_unchanged(self) -> None:
        for file_path, stamp in zip(self.files, self.stamps):
            if _stamp(file_path) != stamp:
                raise RuntimeError(f"{file_path} changed while it was being read; rerun the build")

    def read(self, keys, projection) -> dict[Key, dict]:
        self.check_unchanged()
        by_file: dict[str, list[Key]] = {}
        for key in keys:
            by_file.setdefault(key.file, []).append(key)
        columns = [c for c in projection if c]
        decoded: dict[Key, dict] = {}
        for file_path, file_keys in by_file.items():
            if all(key.offset is not None for key in file_keys):
                rows = read_jsonl_at(file_path, [key.offset for key in file_keys])
                for key in file_keys:
                    decoded[key] = rows[key.offset]
                continue
            rows = read_rows_at(file_path, {key.index for key in file_keys}, columns)
            for key in file_keys:
                if key.index in rows:
                    decoded[key] = rows[key.index]
        return decoded


GLOB_FALLBACKS = ("**/*.parquet", "**/*.jsonl", "**/*.json")
COMPRESSED_SUFFIXES = (".gz", ".bz2", ".xz", ".zst")


def _files_for(path: str, pattern: str | None) -> tuple[list[str], str]:
    """Configured glob, else the first fallback that matches something.

    Datasets arrive as parquet, JSONL, or a single JSON array. Defaulting to
    parquet alone silently excluded the other two. Compressed files are
    rejected in `load_source`: byte offsets need a seekable plain file.
    """
    if pattern:
        return iter_files(path, pattern), pattern
    if os.path.isfile(path):
        return [path], os.path.basename(path)
    errors: list[str] = []
    for candidate in GLOB_FALLBACKS:
        try:
            return iter_files(path, candidate), candidate
        except FileNotFoundError as exc:
            errors.append(str(exc))
    raise FileNotFoundError(f"no data files under {path!r}; tried {list(GLOB_FALLBACKS)}")


def load_source(cfg: dict) -> Source:
    path = os.path.expanduser(cfg["path"])
    files, pattern = _files_for(path, cfg.get("glob"))
    compressed = [f for f in files if f.endswith(COMPRESSED_SUFFIXES)]
    if compressed:
        raise ValueError(
            f"compressed files are not read directly: {compressed[:5]}. "
            f"Decompress first (e.g. `gunzip -k <file>`) and point `glob` at the result."
        )
    columns: list[str] = []
    # Union of every file's schema, not just the first file's. Benchmark
    # directories hold per-split files whose columns differ (BFCL: only some
    # splits carry `ground_truth`).
    for file_path in files:
        for name in _file_columns(file_path):
            if name not in columns:
                columns.append(name)
    if not columns:
        raise ValueError(f"no columns found under {path!r} / {pattern!r}")
    return Source(
        path=path,
        glob=pattern,
        files=tuple(files),
        columns=tuple(columns),
        root=path,
        stamps=tuple(_stamp(f) for f in files),
    )


def _stamp(file_path: str) -> tuple[int, int]:
    stat = os.stat(file_path)
    return stat.st_size, stat.st_mtime_ns


def _file_columns(file_path: str) -> list[str]:
    """Column names of one file: parquet footer, else the first row's keys."""
    footer = parquet_columns(file_path)
    if footer:
        return footer
    from fairyview.rows import iter_rows

    for row in iter_rows(file_path):
        if isinstance(row, dict):
            return list(row)
    return []
