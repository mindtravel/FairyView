"""Describe a source and render a config that matches its real schema.

This module owns no column vocabulary: it asks `fairyview.roles` and
`fairyview.source` and prints what they found. That is the point — `inspect`,
`auto` and the built-in views cannot disagree about what a column is.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

from fairyview import roles
from fairyview.rows import iter_light_rows
from fairyview.source import load_source


def _suggest_kind(info: roles.Classification) -> tuple[str, list[str]]:
    """Pick an adapter from the classified roles. Returns (kind, notes)."""
    notes: list[str] = []
    if info.by_role(roles.CHAT):
        notes.append(f"对话列：{info.by_role(roles.CHAT)[0]}；assistant 部分标为 loss 区间。")
        return "chat_rows", notes
    if info.by_role(roles.PROMPT) and info.by_role(roles.OUTPUTS):
        notes.append("有 prompt 与模型输出列：benchmark_rows 可按模型并排比较。")
        return "benchmark_rows", notes
    if info.by_role(roles.PROMPT) and info.by_role(roles.GOLD):
        notes.append("有 prompt 和参考答案但没有模型输出：benchmark_rows 会跳过全部行，改用 columns_rows。")
        return "columns_rows", notes
    if info.by_role(roles.TEXT):
        notes.append(f"单文本列：{info.by_role(roles.TEXT)[0]}，用 hf_rows。")
        return "hf_rows", notes
    notes.append("没有识别出对话、prompt/gold 或正文列；用 columns_rows，面板取自 schema。")
    return "columns_rows", notes


def _panel_fields(info: roles.Classification, columns) -> list[dict[str, str]]:
    panels: list[dict[str, str]] = []
    for role in (roles.PROMPT, roles.GOLD):
        found = roles.find(columns, role)
        if found:
            label = found if role == roles.PROMPT else f"{found}（参考答案）"
            panels.append({"field": found, "label": label})
    for name in info.attachments:
        if len(panels) < 6:
            panels.append({"field": name, "label": name})
    if not panels:
        panels = [{"field": name, "label": name} for name in list(columns)[:4]]
    return panels


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def render_config(
    *,
    path: str,
    glob: str,
    kind: str,
    info: roles.Classification,
    columns,
    notes: list[str],
    sample_n: int = 200,
) -> str:
    title = path.rstrip("/").rsplit("/", 1)[-1] or "data"
    lines = [
        *[f"# {note}" for note in notes],
        f'title = "{title} 抽样审核"',
        f'data_key = "{title}"',
        f'description = "自动生成：{kind}；已识别 {len(info.roles)} 列。"',
        'panel_layout = "stacked"',
        "max_inline_records = 500",
        f"facets = {_toml(info.facets)}",
        "",
        "caveats = [",
        '  "随机抽样，不是全量统计。",',
        '  "字符级面板，未经 tokenizer。",',
        "]",
        "",
        "[sample]",
        f"n = {sample_n}",
        "seed = 0",
    ]
    if info.facets:
        lines.append(f'stratify = "{info.facets[0]}"')
    lines += ["", "[source]", f'kind = "{kind}"', f'path = "{path}"']
    if not os.path.isfile(path):
        lines.append(f'glob = "{glob}"')

    id_field = info.by_role(roles.ID)
    if id_field:
        lines.append(f'id_field = "{id_field[0]}"')
    if kind == "chat_rows":
        lines.append(f'messages_field = "{info.by_role(roles.CHAT)[0]}"')
    elif kind == "hf_rows":
        lines.append(f'text_field = "{info.by_role(roles.TEXT)[0]}"')
    elif kind == "benchmark_rows":
        lines.append(f'prompt_field = "{info.by_role(roles.PROMPT)[0]}"')
        gold = info.by_role(roles.GOLD)
        if gold:
            lines.append(f'gold_field = "{gold[0]}"')
    elif kind == "columns_rows":
        lines.append("panels = [")
        for panel in _panel_fields(info, columns):
            lines.append(f'  {{ field = "{panel["field"]}", label = "{panel["label"]}" }},')
        lines.append("]")
    return "\n".join(lines) + "\n"


def inspect_source(path: str, glob: str | None = None, *, sample_rows: int = 200) -> dict[str, Any]:
    cfg = {"path": path}
    if glob:
        cfg["glob"] = glob
    source = load_source(cfg)

    # Named columns are enough for most sources. Read rows only when the
    # schema alone gives no facets, and then with a projection that skips the
    # nested conversation/output columns: their names are all we need, not
    # their megabytes.
    provisional = roles.classify(source.columns, low_cardinality=False)
    rows: list[dict] = []
    if not provisional.facets:
        projection = [c for c in source.columns if c not in _bulky_columns()]
        for row in iter_light_rows(source.files[0], projection):
            rows.append(row)
            if len(rows) >= sample_rows:
                break

    info = roles.classify(source.columns, rows)
    kind, notes = _suggest_kind(info)

    if info.facets:
        counts = Counter(r.get(info.facets[0]) for r in rows if r.get(info.facets[0]) is not None)
        if counts:
            notes.append(f"分层建议：按 {info.facets[0]} 分层，样本中见 {len(counts)} 个取值。")
    if info.unassigned:
        notes.append(f"未分配角色的列：{', '.join(info.unassigned)}。")

    return {
        "path": source.path,
        "glob": source.glob,
        "files": len(source.files),
        "rows_in_file": _row_count(source.files),
        "rows_sampled_for_classification": len(rows),
        "columns": [{"name": name, "role": info.role_of(name) or "unassigned"} for name in source.columns],
        "suggestion": {
            "kind": kind,
            "id_field": (info.by_role(roles.ID) or [None])[0],
            "facets": info.facets,
            "panels": _panel_fields(info, source.columns) if kind == "columns_rows" else [],
        },
        "unassigned": info.unassigned,
        "notes": notes,
        "config": render_config(
            path=source.path,
            glob=source.glob,
            kind=kind,
            info=info,
            columns=source.columns,
            notes=notes,
        ),
    }


def _bulky_columns() -> set[str]:
    """Columns whose values are nested or long; skip them when only listing names."""
    from fairyview.rows import iter_rows

    del iter_rows
    return {*roles.CANDIDATES[roles.CHAT], *roles.CANDIDATES[roles.OUTPUTS]}


def _row_count(files) -> int | None:
    from fairyview.rows import PARQUET_SUFFIXES, parquet_row_count

    if not files or not files[0].endswith(PARQUET_SUFFIXES):
        return None
    return sum(parquet_row_count(f) for f in files)
