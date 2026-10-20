"""Columns view: name the columns, get panels.

The long tail adapter. Field paths support `a.b` and `a[0].b`; lists and dicts
render as JSON. When `panels` is omitted, the driver-visible schema decides —
via `fairyview.roles`, not a private candidate list.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fairyview import roles
from fairyview.record import Rendered
from fairyview.schema import Panel, Score
from fairyview.views import View, register_row

_PATH = re.compile(r"([^.[\]]+)|\[(\d+)\]")


def resolve_path(row: Any, path: str) -> Any:
    current = row
    for name, index in _PATH.findall(path):
        if index:
            try:
                current = current[int(index)]
            except (IndexError, KeyError, TypeError):
                return None
        elif isinstance(current, dict):
            current = current.get(name)
        else:
            return None
        if current is None:
            return None
    return current


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


class ColumnsView(View):
    name = "columns_rows"

    def _panels(self) -> list[dict]:
        def compute() -> list[dict]:
            configured = self.cfg.get("panels") or []
            if configured:
                return list(configured)
            skip = set(self.facets)
            if self.id_field:
                skip.add(self.id_field)
            # Classifying the schema once, not once per rendered row.
            return roles.default_panels(
                self.source.columns, skip=skip, limit=int(self.cfg.get("auto_panels", 4))
            )

        return self.memo("panels", compute)

    def _scores(self) -> list[dict]:
        return self.memo("scores", lambda: list(self.cfg.get("scores") or []))

    def columns(self) -> list[str]:
        names: list[str] = []
        for item in [*self._panels(), *self._scores()]:
            field = item["field"] if isinstance(item, dict) else item
            top = _PATH.match(field)
            if top:
                names.append(top.group(1))
        return names

    def render(self, row: dict) -> Rendered | None:
        skip_empty = bool(self.cfg.get("skip_empty", True))
        panels: list[Panel] = []
        for item in self._panels():
            field = item["field"]
            text = as_text(resolve_path(row, field))
            if not text and skip_empty:
                continue
            panels.append(Panel(role=item.get("role", field), label=item.get("label", field), text=text))
        if not panels:
            return None

        scores = []
        for item in self._scores():
            value = resolve_path(row, item["field"])
            if value is None:
                continue
            scores.append(
                Score(
                    model=item.get("model", item["field"]),
                    value=value if isinstance(value, (int, float, str)) else as_text(value),
                    scale=item.get("scale", "0-1"),
                    reason=item.get("reason"),
                )
            )
        return Rendered(panels=panels, scores=scores)


@register_row("columns_rows")
def columns_rows(cfg: dict, source) -> ColumnsView:
    return ColumnsView(name="columns_rows", cfg=cfg, source=source)
