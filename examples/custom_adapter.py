"""A fully commented adapter you can copy as a starting point.

Point a config at it with a relative path — no packaging, no PYTHONPATH:

    [source]
    kind = "./custom_adapter.py:make_records"
    path = "data/my_export"
"""

from __future__ import annotations

from collections.abc import Iterator

from fairyview.schema import Panel, ReviewRecord, Score, Span


def make_records(cfg: dict) -> Iterator[ReviewRecord]:
    """`cfg` is the `[source]` table from the config, verbatim.

    Yield one ReviewRecord per row. Do not sample here: configure `[sample]`
    at the top level of the config and FairyView applies it to whatever you
    yield. Do not build HTML here either; spans are the only styling hook.
    """
    rows = load_rows(cfg["path"])  # your own loader

    for row in rows:
        text = row["response"]
        # A span marks [start, end) inside THIS panel's text.
        # Kinds: loss | prompt | match | truncated | warning | custom.
        highlight = Span(start=0, end=min(120, len(text)), kind="warning", label="first 120 chars")

        yield ReviewRecord(
            id=row["id"],
            # Facets become filters in the page. Keep them low-cardinality.
            facets={"split": row["split"], "lang": row["lang"], "kept": row["kept"]},
            # Fields are shown as key/value chips under the title.
            fields=[["tokens", row["tokens"]], ["source", row["source"]]],
            # Panels are the page body: one or more side-by-side text views.
            panels=[
                Panel(role="prompt", label="prompt", text=row["prompt"]),
                Panel(role="response", label="response", text=text, spans=[highlight]),
            ],
            # Scores with different `scale` values are never merged.
            scores=[
                Score(model="quality-model", value=row["score"], scale="0-1"),
            ],
            # Provenance must let a reader find the row again.
            provenance={"file": cfg["path"], "row": row["row_index"]},
        )


def load_rows(path: str):
    """Replace with your loader (parquet, jsonl, a database, an API ...)."""
    raise NotImplementedError("replace load_rows with your own data loader")
