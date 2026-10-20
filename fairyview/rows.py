"""Cheap row readers shared by every adapter.

Reading is kept separate from rendering so sampling can happen in between.

Parquet rows are yielded as `LazyRow`: the Arrow batch stays in Arrow memory and
individual values are converted to Python only when asked for. Sampling touches
a low-cardinality facet column; the expensive nested `messages` column is
decoded only for the rows that survive. On a 1.1M-row chat export that is the
difference between ~48s and a few seconds.
"""

from __future__ import annotations

import glob as globmod
import json
import os
from collections.abc import Iterator
from typing import Any

PARQUET_SUFFIXES = (".parquet", ".pq")


class LazyRow:
    """A row backed by one Arrow batch; values decode on access."""

    __slots__ = ("_batch", "_row", "_position")

    def __init__(self, batch, row: int, position: dict[str, int]) -> None:
        self._batch = batch
        self._row = row
        self._position = position

    def __contains__(self, name: str) -> bool:
        return name in self._position

    def __getitem__(self, name: str) -> Any:
        return self.get(name)

    def get(self, name: str, default: Any = None) -> Any:
        index = self._position.get(name)
        if index is None:
            return default
        return self._batch.column(index)[self._row].as_py()

    def keys(self):
        return self._position.keys()

    def as_dict(self) -> dict[str, Any]:
        return {name: self.get(name) for name in self._position}


def iter_files(path: str, pattern: str = "**/*.parquet") -> list[str]:
    if os.path.isfile(path):
        return [path]
    files = sorted(globmod.glob(os.path.join(path, pattern), recursive=True))
    if not files:
        raise FileNotFoundError(f"no files matched {path!r} / {pattern!r}")
    return files


def parquet_columns(file_path: str) -> list[str]:
    """Column names from the file footer only (no data pages read)."""
    if not file_path.endswith(PARQUET_SUFFIXES):
        return []
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return []
    return list(pq.ParquetFile(file_path).schema_arrow.names)


def available_columns(files: list[str]) -> set[str]:
    for file_path in files:
        columns = parquet_columns(file_path)
        if columns:
            return set(columns)
    return set()


def iter_rows(file_path: str, columns: list[str] | None = None) -> Iterator[Any]:
    """Yield rows. Parquet rows are `LazyRow`; JSONL rows are plain dicts.

    `columns` limits the parquet read to those columns before any decoding.
    """
    if file_path.endswith(PARQUET_SUFFIXES):
        try:
            import pyarrow.parquet as pq
        except ImportError:
            import pandas as pd

            frame = pd.read_parquet(file_path, columns=columns) if columns else pd.read_parquet(file_path)
            for row in frame.to_dict(orient="records"):
                yield row
            return

        parquet = pq.ParquetFile(file_path)
        names = parquet.schema_arrow.names
        selected = [c for c in (columns or []) if c in names] or None
        positions = None
        for batch in parquet.iter_batches(batch_size=4096, columns=selected):
            if positions is None:
                positions = {name: index for index, name in enumerate(batch.schema.names)}
            for row in range(batch.num_rows):
                yield LazyRow(batch, row, positions)
        return

    if file_path.endswith(".json"):
        # Either a JSON array of records or JSONL that happens to be named .json
        # (BFCL ships the latter). Try the whole-file parse first.
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            yield from (item for item in payload if isinstance(item, dict))
            return
        if isinstance(payload, dict):
            # A single object, or {"rows": [...]}-style wrappers.
            for value in payload.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    yield from value
                    return
            yield payload
            return
        # Fall through to line-by-line parsing.

    with open(file_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


# ---------- two-pass helpers: sample on cheap columns, decode only survivors ----------


def parquet_row_count(file_path: str) -> int:
    import pyarrow.parquet as pq

    return pq.ParquetFile(file_path).metadata.num_rows


def parquet_row_groups(file_path: str) -> list[tuple[int, int, int]]:
    """(row_group_index, start_row, num_rows) from the footer only."""
    import pyarrow.parquet as pq

    metadata = pq.ParquetFile(file_path).metadata
    out, start = [], 0
    for index in range(metadata.num_row_groups):
        rows = metadata.row_group(index).num_rows
        out.append((index, start, rows))
        start += rows
    return out


def iter_column(file_path: str, column: str) -> Iterator[Any]:
    """Yield one column's values in row order without building row objects."""
    if file_path.endswith(PARQUET_SUFFIXES):
        import pyarrow.parquet as pq

        for batch in pq.ParquetFile(file_path).iter_batches(batch_size=8192, columns=[column]):
            if batch.num_columns != 1:
                raise KeyError(f"column {column!r} not in {file_path}")
            yield from batch.column(0).to_pylist()
        return
    for row in iter_rows(file_path):
        yield row[column]


def read_rows_at(file_path: str, indices: set[int], columns: list[str]) -> dict[int, dict[str, Any]]:
    """Decode only the requested row indices, reading only their row groups."""
    if not indices:
        return {}
    if not file_path.endswith(PARQUET_SUFFIXES):
        wanted = set(indices)
        out = {}
        for index, row in enumerate(iter_rows(file_path)):
            if index in wanted:
                out[index] = row
                if len(out) == len(wanted):
                    break
        return out

    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(file_path)
    names = parquet.schema_arrow.names
    selected = [c for c in columns if c in names] or None
    out: dict[int, dict[str, Any]] = {}
    for row_group, start, rows in parquet_row_groups(file_path):
        local = sorted(i - start for i in indices if start <= i < start + rows)
        if not local:
            continue
        table = parquet.read_row_group(row_group, columns=selected)
        for offset in local:
            out[start + offset] = {
                name: table.column(name)[offset].as_py() for name in (selected or names)
            }
    return out


def iter_light_rows(file_path: str, columns: list[str]) -> Iterator[dict[str, Any]]:
    """Yield dicts containing only `columns`.

    Cheap by construction: parquet decodes just those column chunks, so this is
    suitable for scanning a facet column over millions of rows.
    """
    if not columns:
        raise ValueError("iter_light_rows needs at least one column")
    if file_path.endswith(PARQUET_SUFFIXES):
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(file_path)
        names = parquet.schema_arrow.names
        selected = [c for c in columns if c in names]
        if not selected:
            return
        for batch in parquet.iter_batches(batch_size=16384, columns=selected):
            yield from batch.to_pylist()
        return
    for row in iter_rows(file_path):
        yield {name: row[name] for name in columns if name in row}


# ---------- JSONL by byte offset: scan once, seek to survivors ----------

CHUNK_BYTES = 64 << 20


def is_seekable_jsonl(file_path: str) -> bool:
    return file_path.endswith(".jsonl")


def _chunk_bounds(file_path: str, size: int | None = None) -> list[tuple[int, int]]:
    """Byte ranges that start at a line start and end after a newline."""
    size = size or CHUNK_BYTES
    total = os.path.getsize(file_path)
    bounds, start = [], 0
    with open(file_path, "rb") as handle:
        while start < total:
            end = min(start + size, total)
            if end < total:
                handle.seek(end)
                handle.readline()
                end = handle.tell()
            bounds.append((start, end))
            start = end
    return bounds


def _scan_chunk(args) -> list[tuple[int, dict[str, Any]]]:
    file_path, start, end, columns = args
    out = []
    with open(file_path, "rb") as handle:
        handle.seek(start)
        offset = start
        while offset < end:
            line = handle.readline()
            if not line:
                break
            if line.strip():
                if columns:
                    row = json.loads(line)
                    out.append((offset, {name: row[name] for name in columns if name in row}))
                else:
                    out.append((offset, {}))
            offset += len(line)
    return out


def scan_jsonl(file_path: str, columns: list[str]) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield (byte offset, light row) for every non-empty line, in file order.

    Without columns no line is parsed. With columns, chunks are parsed in
    parallel: `json.loads` is the whole cost of a JSONL scan (IO for 1.5 GB is
    ~0.3 s, parsing ~4 s), and it splits cleanly at line boundaries.
    """
    bounds = _chunk_bounds(file_path)
    jobs = [(file_path, start, end, list(columns)) for start, end in bounds]
    if not columns or len(jobs) == 1:
        for job in jobs:
            yield from _scan_chunk(job)
        return
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    # spawn, not fork: forking a process that holds threads (pyarrow) can
    # deadlock a child.
    workers = min(len(jobs), os.cpu_count() or 1, 32)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        for part in pool.map(_scan_chunk, jobs):
            yield from part


def read_jsonl_at(file_path: str, offsets) -> dict[int, dict[str, Any]]:
    out = {}
    with open(file_path, "rb") as handle:
        for offset in sorted(set(offsets)):
            handle.seek(offset)
            out[offset] = json.loads(handle.readline())
    return out
