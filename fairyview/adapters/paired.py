"""Paired view: before/after, raw/rendered, document/matched-eval.

This is the one adapter that cannot be row-at-a-time: it joins two files. It
keeps the record callable protocol and uses `fairyview.record.make_record` for
id/facets/provenance, so those rules still live in one place.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from fairyview.record import Rendered, make_record
from fairyview.rows import iter_files, iter_rows
from fairyview.schema import Panel
from fairyview.source import Source
from fairyview.views import register_source


def _load_side(side: dict) -> list[dict]:
    path = os.path.expanduser(side["path"])
    rows: list[dict] = []
    for file_path in iter_files(path, side.get("glob", "**/*.parquet")):
        for row in iter_rows(file_path):
            rows.append(row.as_dict() if hasattr(row, "as_dict") else dict(row))
    return rows


def _text_field(side: dict, rows: list[dict]) -> str | None:
    configured = side.get("text_field")
    if configured:
        return configured
    from fairyview import roles

    columns = list(rows[0]) if rows else []
    return roles.find(columns, "text")


def _stringify(row: dict, field: str | None) -> str:
    from fairyview.adapters.hf_rows import as_text

    return as_text(row.get(field)) if field else ""


def make_records(cfg: dict) -> Iterator:
    left_cfg, right_cfg = cfg["left"], cfg["right"]
    join_field = cfg.get("join_field")
    facets = cfg.get("facets") or []
    show_fields = cfg.get("fields") or []

    left_rows = _load_side(left_cfg)
    right_rows = _load_side(right_cfg)
    left_text = _text_field(left_cfg, left_rows)
    right_text = _text_field(right_cfg, right_rows)

    if join_field:
        right_index = {str(r.get(join_field)): r for r in right_rows}
        pairs = [(left, right_index.get(str(left.get(join_field)))) for left in left_rows]
    else:
        pairs = list(zip(left_rows, right_rows))

    source = Source(path=left_cfg["path"], glob="", files=(), columns=(), root=left_cfg["path"])
    for index, (left, right) in enumerate(pairs):
        if right is None:
            continue
        panels = [
            Panel(role="before", label=left_cfg.get("label", "before"), text=_stringify(left, left_text)),
            Panel(role="after", label=right_cfg.get("label", "after"), text=_stringify(right, right_text)),
        ]
        if cfg.get("reason_field"):
            panels.append(Panel(role="reason", label="reason", text=_stringify(right, cfg["reason_field"])))

        record = make_record(
            key=(left_cfg["path"], index),
            row=left,
            rendered=Rendered(
                panels=panels,
                fields=[[name, left.get(name)] for name in show_fields if name in left],
            ),
            source=source,
            facets=facets,
            id_field=join_field,
            provenance={"left": left_cfg["path"], "right": right_cfg["path"]},
        )
        if record is not None:
            yield record


@register_source("paired")
def paired(cfg: dict) -> object:
    # A whole-source adapter: returns the record producer, because a join needs
    # both sides at once and cannot be driven row-at-a-time.
    return make_records
