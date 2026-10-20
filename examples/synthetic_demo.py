"""Synthetic adapter used by configs/synthetic.toml to smoke-test the tool."""

from __future__ import annotations

from collections.abc import Iterator

from fairyview.schema import Panel, ReviewRecord, Score, Span


def make_records(cfg: dict) -> Iterator[ReviewRecord]:
    for index in range(8):
        kept = index % 3 != 0
        prompt = f"<|start_header_id|>user<|end_header_id|>\n\n问题 {index}：求 1+{index}<|eot_id|>\n"
        answer = f"<|start_header_id|>assistant<|end_header_id|>\n\n答案是 {1 + index}<|eot_id|>"
        text = prompt + answer
        spans = [
            Span(0, len(prompt), "prompt"),
            Span(len(prompt), len(text), "loss"),
        ]
        if not kept:
            spans.append(Span(len(prompt), len(prompt) + 12, "warning", "被过滤的片段"))

        yield ReviewRecord(
            id=f"synthetic/{index:03d}",
            facets={"dataset": "synthetic", "split": "train", "kept": kept},
            fields=[["tokens", 12 + index], ["filter_reason", None if kept else "duplicate"]],
            panels=[
                Panel(role="raw", label="原始记录", text=f"question: 1+{index}\nanswer: {1 + index}"),
                Panel(role="rendered", label="渲染后 chat", text=text, spans=spans),
            ],
            scores=[Score(model="demo", value=index / 8, scale="0-1", reason="占位分数")],
            provenance={"file": "synthetic", "row": index},
        )
