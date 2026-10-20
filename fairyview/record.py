"""Assemble a ReviewRecord from a rendered row.

Id, facets and provenance follow the same rules everywhere; views only supply
panels, scores and their own extra fields. Keeping this out of the views is why
the adapters stopped repeating `f"{relative}:{index}"` and the facet dict
comprehension in four places.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from fairyview.schema import Panel, ReviewRecord, Score


@dataclass
class Rendered:
    """What a view produces for one row."""

    panels: list[Panel] = field(default_factory=list)
    scores: list[Score] = field(default_factory=list)
    fields: list[list] = field(default_factory=list)


def make_record(
    *,
    key: tuple[str, int],
    row: dict,
    rendered: Rendered,
    source,
    facets: Iterable[str] = (),
    id_field: str | None = None,
    provenance: dict | None = None,
) -> ReviewRecord | None:
    """Build a record, or None when the row has nothing to show.

    A row that renders no panel is skipped rather than emitted as an empty
    card; that is how `skip_empty` / empty-messages filtering worked before,
    now in one place.
    """
    if not rendered.panels:
        return None
    file_path, index = key[0], key[1]
    relative = source.relative(file_path)

    if id_field and row.get(id_field) is not None:
        record_id = str(row.get(id_field))
    else:
        record_id = f"{relative}:{index}"

    record_fields = [list(item) for item in rendered.fields]
    record_fields.append(["source_file", relative])
    record_fields.append(["row", index])

    return ReviewRecord(
        id=record_id,
        facets={name: row.get(name) for name in facets if name in row},
        fields=record_fields,
        panels=rendered.panels,
        scores=rendered.scores,
        provenance={"file": file_path, "row": index, **(provenance or {})},
    )
