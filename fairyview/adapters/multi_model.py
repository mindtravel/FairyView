"""Benchmark / inference view: one prompt, a gold answer, several outputs.

Recognized row shapes (all optional except the outputs):

    {"question": ..., "gold": ..., "model_outputs": {"m1": "...", "m2": "..."}}
    {"prompt": ...,  "answer": ..., "outputs": {...}, "scores": {...}}
    {"problem":..., "solution":..., "model_a": "...", "model_b": "..."}

Column names come from `fairyview.roles`; this module only decides the layout.
"""

from __future__ import annotations

import json
from typing import Any

from fairyview import roles
from fairyview.record import Rendered
from fairyview.schema import Panel, Score
from fairyview.views import View, register_row


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, indent=2)


RESERVED_MODEL_COLUMNS = ("model_outputs", "model_scores", "model_answers")


def collect_outputs(row: dict, outputs_column: str | None) -> dict[str, str]:
    """Model outputs, however the export stores them.

    - `{"m1": "...", "m2": "..."}`
    - `[{"response_model": "m1", "response": "..."}, ...]` (natural_reasoning)
    - `[{"model": ..., "output": ...}]`, or a plain string
    """
    outputs: dict[str, str] = {}
    if outputs_column and outputs_column in row:
        value = row[outputs_column]
        if isinstance(value, dict):
            outputs.update({str(k): as_text(v) for k, v in value.items()})
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    name = _response_name(item) or f"output{index + 1}"
                    text = _response_text(item)
                    outputs[name] = as_text(text)
                elif item is not None:
                    outputs[f"output{index + 1}"] = as_text(item)
        elif value is not None:
            outputs["output"] = as_text(value)
    for key, val in row.items():
        if key.startswith("model_") and key not in RESERVED_MODEL_COLUMNS:
            outputs[key[len("model_") :]] = as_text(val)
    return outputs


_RESPONSE_NAME_KEYS = ("response_model", "model", "name", "model_name")
_RESPONSE_TEXT_KEYS = ("response", "output", "text", "content", "answer", "completion")


def _response_name(item: dict) -> str | None:
    for key in _RESPONSE_NAME_KEYS:
        if isinstance(item.get(key), str) and item[key]:
            return item[key]
    return None


def _response_text(item: dict) -> Any:
    for key in _RESPONSE_TEXT_KEYS:
        if key in item:
            return item[key]
    return item


class BenchmarkView(View):
    name = "benchmark_rows"
    with_gold = True
    with_scoring = True

    def _prompt(self) -> str:
        return self.memo("prompt", lambda: self.source.resolve(self.cfg.get("prompt_field"), "prompt", owner=self.name))

    def _gold(self) -> str | None:
        def compute() -> str | None:
            if not self.with_gold:
                return None
            configured = self.cfg.get("gold_field")
            if configured == "__none__":
                return None
            if configured:
                self.source.require([configured], owner=self.name)
                return configured
            return roles.find(self.source.columns, "gold")

        return self.memo("gold", compute)

    def _outputs(self) -> str | None:
        def compute() -> str | None:
            configured = self.cfg.get("outputs_field")
            if configured:
                self.source.require([configured], owner=self.name)
                return configured
            return roles.find(self.source.columns, "outputs")

        return self.memo("outputs", compute)

    def _scoring(self) -> bool:
        return self.memo("scoring", lambda: bool(self.cfg.get("scoring", self.with_scoring)))

    def _score_field(self) -> str | None:
        def compute() -> str | None:
            configured = self.cfg.get("score_field")
            if configured:
                return configured
            return roles.find(self.source.columns, "score")

        return self.memo("score_field", compute)

    def columns(self) -> list[str]:
        # Every `model_*` column is an output. `collect_outputs` discovers them by
        # prefix at render time, so they must be in the projection or the row
        # arrives without them and every record is skipped.
        models = [c for c in self.source.columns if c.startswith("model_") and c not in RESERVED_MODEL_COLUMNS]
        named = [c for c in (self._prompt(), self._gold(), self._outputs(), self._score_field()) if c]
        return list(dict.fromkeys([*named, *models]))

    def render(self, row: dict) -> Rendered | None:
        outputs = collect_outputs(row, self._outputs())
        if not outputs:
            return None
        prompt = self._prompt()
        gold = self._gold()

        panels = [Panel(role="prompt", label="题目", text=as_text(row.get(prompt)))]
        if gold:
            panels.append(Panel(role="gold", label="参考答案", text=as_text(row.get(gold))))

        score_field = self._score_field()
        score_map: dict[str, Any] = {}
        if self._scoring() and score_field and isinstance(row.get(score_field), dict):
            score_map = row[score_field]

        for model, answer in outputs.items():
            verdict = row.get("verdict")
            label = f"{model} 的回答"
            if isinstance(verdict, (bool, int, str)) and len(outputs) == 1:
                label += f"（{verdict}）"
            panels.append(Panel(role=f"model:{model}", label=label, text=answer))

        scores = [
            Score(model=model, value=value if isinstance(value, (int, float)) else as_text(value))
            for model, value in score_map.items()
        ]
        return Rendered(
            panels=panels,
            scores=scores,
            fields=[["models", ", ".join(outputs)], ["prompt_col", prompt], ["gold_col", gold]],
        )


class InferenceView(BenchmarkView):
    name = "inference_rows"
    with_gold = False
    with_scoring = False


@register_row("benchmark_rows")
def benchmark_rows(cfg: dict, source) -> BenchmarkView:
    return BenchmarkView(name="benchmark_rows", cfg=cfg, source=source)


@register_row("inference_rows")
def inference_rows(cfg: dict, source) -> InferenceView:
    return InferenceView(name="inference_rows", cfg=cfg, source=source)
