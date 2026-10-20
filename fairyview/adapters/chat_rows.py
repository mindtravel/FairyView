"""Chat view: a conversation column, rendered with assistant spans marked.

Reads one column (`messages`, `conversations`, ...). The only interesting
decision left here is how a source's conversation representation becomes
`messages`: nested list, JSON string, or Python-literal string.
"""

from __future__ import annotations

import ast
import json
from typing import Any

from fairyview import mask
from fairyview.record import Rendered
from fairyview.schema import Panel, Span
from fairyview.views import View, register_row

HEADER = "<|start_header_id|>{role}<|end_header_id|>\n\n"
TURN_END = "<|eot_id|>\n"
DEFAULT_LOSS_ROLES = ("assistant", "gpt", "model")
DEFAULT_PROMPT_ROLES = ("user", "human", "system", "developer", "tool")
DEFAULT_FIELDS = ("messages", "conversations", "conversation", "chat", "dialogue", "turns")


def coerce_messages(value: Any) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return []
    if isinstance(value, (list, tuple)):
        return [m for m in value if isinstance(m, dict)]
    return []


def _content(message: dict) -> str:
    content = message.get("content", message.get("value"))
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)


def _role(message: dict) -> str:
    return str(message.get("role") or message.get("from") or "unknown")


def render_messages(
    messages: list[dict],
    *,
    loss_roles: tuple[str, ...] = DEFAULT_LOSS_ROLES,
    prompt_roles: tuple[str, ...] = DEFAULT_PROMPT_ROLES,
) -> tuple[str, list[Span]]:
    parts: list[str] = []
    spans: list[Span] = []
    cursor = 0
    for message in messages:
        role = _role(message)
        content = _content(message)
        header = HEADER.format(role=role)
        parts.append(header)
        cursor += len(header)
        if role in loss_roles:
            kind = "loss"
        elif role in prompt_roles:
            kind = "prompt"
        else:
            # An unclassified role is neither supervised nor context. Say so
            # instead of guessing it into one bucket.
            kind = "warning"
        spans.append(Span(cursor, cursor + len(content), kind))
        parts.append(content)
        cursor += len(content)
        parts.append(TURN_END)
        cursor += len(TURN_END)
    return "".join(parts), spans


class ChatView(View):
    name = "chat_rows"

    def column(self) -> str:
        return self.memo("column", lambda: self.source.resolve(self.cfg.get("messages_field"), "chat", owner=self.name))

    def system_column(self) -> str | None:
        def compute() -> str | None:
            configured = self.cfg.get("system_field")
            if configured:
                self.source.require([configured], owner=self.name)
                return configured
            return "system" if self.source.has("system") else None

        return self.memo("system", compute)

    def columns(self) -> list[str]:
        system = self.system_column()
        return [c for c in (self.column(), system) if c]

    def render(self, row: dict) -> Rendered | None:
        messages = coerce_messages(row.get(self.column()))
        if not messages:
            return None
        loss_roles, prompt_roles = mask.role_kinds(self.cfg.get("mask"))
        text, spans = render_messages(
            messages, loss_roles=loss_roles, prompt_roles=prompt_roles
        )
        assistant_chars = sum(span.end - span.start for span in spans if span.kind == "loss")
        panels = []
        system = self.system_column()
        if system and row.get(system):
            # The system prompt is prompt-side text; it is not part of the
            # rendered conversation, and hiding it made template review useless.
            panels.append(Panel(role="system", label="system prompt", text=str(row[system])))
        panels.append(Panel(role="chat", label="对话（蓝色为 assistant，将参与 loss）", text=text, spans=spans))
        return Rendered(
            panels=panels,
            fields=[
                ["turns", len(messages)],
                ["rendered chars", len(text)],
                ["assistant chars", assistant_chars],
            ],
            # assistant_chars is what proves the mask covers the reply, not the prompt.
        )


@register_row("chat_rows")
def chat_rows(cfg: dict, source) -> ChatView:
    return ChatView(name="chat_rows", cfg=cfg, source=source)
