"""Text view: one document per row.

`text_field` is resolved through `fairyview.roles`, so this module no longer
carries its own candidate list.
"""

from __future__ import annotations

import json
from typing import Any

from fairyview.record import Rendered
from fairyview.schema import Panel
from fairyview.views import View, register_row


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


class TextView(View):
    name = "hf_rows"

    def column(self) -> str:
        return self.memo("column", lambda: self.source.resolve(self.cfg.get("text_field"), "text", owner=self.name))

    def columns(self) -> list[str]:
        return [self.column()]

    def render(self, row: dict) -> Rendered | None:
        text = as_text(row.get(self.column()))
        if not text:
            return None
        shown = self.cfg.get("fields") or []
        return Rendered(
            panels=[Panel(role="text", label=self.column(), text=text)],
            fields=[[name, row.get(name)] for name in shown if name in row],
        )


@register_row("hf_rows")
def hf_rows(cfg: dict, source) -> TextView:
    return TextView(name="hf_rows", cfg=cfg, source=source)
