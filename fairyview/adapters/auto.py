"""Auto view: classify the schema with `fairyview.roles`, then delegate.

This module no longer holds its own column lists. It asks the single role
vocabulary and hands the row to the matching view, so `auto`, `inspect` and the
built-ins cannot disagree about what a column is.
"""

from __future__ import annotations

from fairyview import roles
from fairyview.record import Rendered
from fairyview.views import View, load_adapter, register_row

# `provenance["mode"]` was "chat"/"pair"/"text" before `auto` delegated to named
# views. Keep those values: downstream filters and saved records use them.
MODE_BY_VIEW = {
    "chat_rows": "chat",
    "hf_rows": "text",
    "benchmark_rows": "benchmark",
    "inference_rows": "inference",
    "columns_rows": "columns",
}


def choose_view(columns) -> str:
    info = roles.classify(columns)
    has = info.by_role
    if has(roles.CHAT):
        return "chat_rows"
    if has(roles.PROMPT) and has(roles.OUTPUTS):
        return "benchmark_rows"
    if has(roles.PROMPT) and has(roles.GOLD):
        return "columns_rows"
    if has(roles.TEXT):
        return "hf_rows"
    return "columns_rows"


class AutoView(View):
    name = "auto"

    def __init__(self, cfg, source):
        super().__init__(name="auto", cfg=cfg, source=source)
        self._inner: View | None = None
        self._chosen: str | None = None

    def _delegate(self) -> View:
        if self._inner is None:
            chosen = choose_view(self.source.columns)
            self._chosen = chosen
            # Reuse the registry entry's factory so auto cannot construct a view
            # the driver would not.
            self._inner = load_adapter(chosen)._factory(self.cfg, self.source)  # type: ignore[attr-defined]
        return self._inner

    def columns(self) -> list[str]:
        return self._delegate().columns()

    def render(self, row: dict) -> Rendered | None:
        return self._delegate().render(row)

    def provenance(self) -> dict:
        self._delegate()
        return {"mode": MODE_BY_VIEW.get(self._chosen, self._chosen), **super().provenance()}


@register_row("auto")
def auto(cfg: dict, source) -> AutoView:
    return AutoView(cfg=cfg, source=source)
