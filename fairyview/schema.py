"""Stable review-record contract shared by every adapter and the renderer.

An adapter turns one source row into exactly one ReviewRecord. The renderer
knows nothing about datasets: it only renders facets, fields, panels, spans
and scores. Keep this module dependency-free so it can run anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


SCHEMA_VERSION = 1


@dataclass
class Span:
    """A character range inside a Panel's text, highlighted by kind."""

    start: int
    end: int
    kind: str  # loss | prompt | match | truncated | warning | custom
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"start": self.start, "end": self.end, "kind": self.kind}
        if self.label:
            d["label"] = self.label
        return d


@dataclass
class Panel:
    """One text view of a record (input, output, match, answer ...)."""

    role: str
    label: str
    text: str
    spans: list[Span] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "label": self.label,
            "text": self.text,
            "spans": [s.to_dict() for s in self.spans],
        }


@dataclass
class Score:
    """A model or human score. `scale` keeps unlike scales from being merged."""

    model: str
    value: float | str
    scale: str = "0-1"
    reason: str | None = None
    comparable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "value": self.value,
            "scale": self.scale,
            "reason": self.reason,
            "comparable": self.comparable,
        }


@dataclass
class ReviewRecord:
    id: str
    facets: dict[str, Any] = field(default_factory=dict)
    fields: list[list[Any]] = field(default_factory=list)  # [[name, value], ...]
    panels: list[Panel] = field(default_factory=list)
    scores: list[Score] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("record id must be non-empty")
        for panel in self.panels:
            for span in panel.spans:
                if not (0 <= span.start <= span.end <= len(panel.text)):
                    raise ValueError(
                        f"{self.id}: span {span.start}:{span.end} outside panel "
                        f"{panel.role!r} of length {len(panel.text)}"
                    )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "facets": self.facets,
            "fields": self.fields,
            "panels": [p.to_dict() for p in self.panels],
            "scores": [s.to_dict() for s in self.scores],
            "provenance": self.provenance,
        }


def validate_all(records: Iterable[ReviewRecord]) -> list[ReviewRecord]:
    out = []
    for record in records:
        record.validate()
        out.append(record)
    return out
