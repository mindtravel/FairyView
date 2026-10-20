"""Rule-driven span rendering.

A mask is a list of rules applied to panel text. The same mechanism covers
chat role masking (`loss_roles`) and arbitrary text patterns (think tags,
per-turn markers, diff regions). Spans are character offsets into the text
shown, never HTML.

Config:

    [mask]
    loss_roles = ["assistant"]        # chat: roles whose content is supervised
    prompt_roles = ["user", "system"] # chat: roles that are context only
    max_panel_chars = 20000           # truncation, always announced in the text

    [[mask.rules]]                    # applied to every panel, any kind
    pattern = "<\\\\|start_think\\\\|>.*?<\\\\|end_think\\\\|>"
    kind = "loss"
    label = "think"
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fairyview.schema import Panel, Span

SPAN_KINDS = {"loss", "prompt", "match", "truncated", "warning", "custom"}
DEFAULT_LOSS_ROLES = ("assistant", "gpt", "model")
DEFAULT_PROMPT_ROLES = ("user", "human", "system", "developer", "tool")


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern
    kind: str
    label: str | None = None


def parse_rules(cfg: dict | None) -> list[Rule]:
    """`[[mask.rules]]` entries -> compiled rules. Invalid regex fails loudly."""
    rules: list[Rule] = []
    for index, item in enumerate((cfg or {}).get("rules", []) or []):
        pattern = item.get("pattern")
        if not pattern:
            raise ValueError(f"mask.rules[{index}] needs `pattern`")
        kind = item.get("kind", "match")
        if kind not in SPAN_KINDS:
            raise ValueError(f"mask.rules[{index}].kind {kind!r} not in {sorted(SPAN_KINDS)}")
        try:
            compiled = re.compile(pattern, re.DOTALL)
        except re.error as exc:
            raise ValueError(f"mask.rules[{index}].pattern is not valid regex: {exc}") from exc
        rules.append(Rule(pattern=compiled, kind=kind, label=item.get("label")))
    return rules


def apply_rules(text: str, rules: list[Rule]) -> list[Span]:
    """All non-overlapping matches, in text order.

    Later rules do not override earlier ones: a span that would overlap an
    accepted span is skipped, so rule order is precedence.
    """
    if not rules or not text:
        return []
    accepted: list[Span] = []
    for rule in rules:
        for match in rule.pattern.finditer(text):
            if match.start() == match.end():
                continue
            if any(match.start() < s.end and s.start < match.end() for s in accepted):
                continue
            accepted.append(Span(match.start(), match.end(), rule.kind, rule.label))
    accepted.sort(key=lambda s: (s.start, s.end))
    return accepted


def role_kinds(cfg: dict | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    cfg = cfg or {}
    loss = tuple(cfg.get("loss_roles") or DEFAULT_LOSS_ROLES)
    prompt = tuple(cfg.get("prompt_roles") or DEFAULT_PROMPT_ROLES)
    return loss, prompt


def max_chars(cfg: dict | None) -> int | None:
    value = (cfg or {}).get("max_panel_chars")
    if value in (None, 0):
        return None
    return int(value)


def truncate(text: str, limit: int | None) -> tuple[str, bool, int]:
    """Cut to `limit` and say so in the text itself.

    Silent truncation makes a reviewer believe a document ended where it was
    cut. The marker is part of the panel text so it survives export and search.
    """
    if limit is None or len(text) <= limit:
        return text, False, len(text)
    marker = f"\n… [truncated: showing {limit} of {len(text)} characters]"
    return text[:limit] + marker, True, len(text)


def finalize_panels(panels, mask_cfg: dict | None):
    """Apply truncation then rules to every panel, keeping span offsets valid.

    Order matters: truncation first, then rules run on the truncated text, then
    pre-existing spans are clipped to the new length. A span pointing past the
    cut would otherwise fail `ReviewRecord.validate()`.
    """
    limit = max_chars(mask_cfg)
    rules = parse_rules(mask_cfg)
    out = []
    for panel in panels:
        text, truncated, original_len = truncate(panel.text, limit)
        spans = [s for s in panel.spans if s.start < len(text)]
        for span in spans:
            span.end = min(span.end, len(text))
        if truncated:
            start = len(text) - len(
                f"\n… [truncated: showing {limit} of {original_len} characters]"
            )
            spans.append(Span(start, len(text), "truncated", f"of {original_len} chars"))
        spans.extend(apply_rules(text, rules))
        spans.sort(key=lambda s: (s.start, s.end))
        out.append(Panel(role=panel.role, label=panel.label, text=text, spans=spans))
    return out
