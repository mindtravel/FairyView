"""Column roles: the single vocabulary for "what is this column?".

Every part of FairyView that needs to guess a column meaning asks here. There is
exactly one candidate list per role, so `inspect`, `auto`, and the built-in
views cannot disagree with each other.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

CHAT = "chat"
PROMPT = "prompt"
GOLD = "gold"
OUTPUTS = "outputs"
TEXT = "text"
ID = "id"
ATTACHMENT = "attachment"
FACET = "facet"
SCORE = "score"

CANDIDATES: dict[str, tuple[str, ...]] = {
    CHAT: ("messages", "conversations", "conversation", "chat", "dialogue", "turns"),
    PROMPT: ("question", "prompt", "problem", "instruction", "input", "query", "task", "query_text"),
    GOLD: (
        "final answer",
        "answer",
        "gold",
        "reference",
        "reference_answer",
        "target",
        "solution",
        "expected",
        "expected_answer",
    ),
    OUTPUTS: ("model_outputs", "outputs", "responses", "answers", "model_answers"),
    TEXT: ("text", "content", "document", "body", "article", "passage"),
    ID: ("id", "task_id", "uid", "sample_id", "problem_id", "doc_id", "_id", "example_id"),
    ATTACHMENT: ("file_name", "file_path", "image", "url", "path", "attachment", "attachment_name"),
    SCORE: ("scores", "model_scores", "verdicts", "verdict", "correct"),
}

FACET_NAMES: tuple[str, ...] = (
    "level",
    "source",
    "subset",
    "category",
    "type",
    "split",
    "difficulty",
    "domain",
    "language",
    "model",
    "task_type",
    "license",
    "dataset",
)

# Order in which a column may claim a role when several candidates exist.
# SCORE sits after OUTPUTS so `model_scores` is not taken as the outputs column.
ROLE_ORDER: tuple[str, ...] = (CHAT, PROMPT, GOLD, OUTPUTS, SCORE, TEXT, ID, ATTACHMENT)


def normalize(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def find(columns, role: str, *, exclude=()) -> str | None:
    """First column matching a role's candidates, skipping `exclude`."""
    by_norm = {normalize(c): c for c in columns}
    for candidate in CANDIDATES[role]:
        found = by_norm.get(normalize(candidate))
        if found and found not in exclude:
            return found
    return None


@dataclass
class Classification:
    roles: dict[str, str] = field(default_factory=dict)          # column -> role
    unassigned: list[str] = field(default_factory=list)

    def by_role(self, role: str) -> list[str]:
        return [name for name, value in self.roles.items() if value == role]

    def role_of(self, column: str) -> str | None:
        return self.roles.get(column)

    @property
    def facets(self) -> list[str]:
        return self.by_role(FACET)

    @property
    def attachments(self) -> list[str]:
        return self.by_role(ATTACHMENT)


def classify(columns, rows=None, *, low_cardinality: bool = True) -> Classification:
    """Assign at most one role per column.

    Named roles win first, in `ROLE_ORDER`. Remaining columns whose names look
    like facets (level, source, ...) are facets. With `rows`, low-cardinality
    scalar columns are also treated as facets so an unnamed split column still
    works as a filter.
    """
    columns = list(columns)
    roles: dict[str, str] = {}
    for role in ROLE_ORDER:
        chosen = find(columns, role, exclude=tuple(roles))
        if chosen:
            roles[chosen] = role

    if "chat" in roles.values():
        # A chat export's prompt/gold names are usually nested inside messages;
        # a top-level "content" column is the message body, not a text corpus.
        for name in columns:
            if roles.get(name) == TEXT:
                del roles[name]

    for name in columns:
        if name in roles:
            continue
        if normalize(name) in FACET_NAMES or name.startswith("_"):
            roles[name] = FACET

    if low_cardinality and rows:
        for name in columns:
            if name in roles:
                continue
            values = [row.get(name) for row in rows if isinstance(row, dict) and row.get(name) not in (None, "")]
            if not values or not all(isinstance(v, (str, int, bool)) for v in values):
                continue
            if len(Counter(values)) <= max(2, len(values) // 5):
                roles[name] = FACET

    return Classification(roles=roles, unassigned=[c for c in columns if c not in roles])


def default_panels(columns, *, skip=(), limit: int = 4) -> list[dict[str, str]]:
    """Panels for a source with no explicit panel config.

    Prompt and gold come first because they are the two columns a reviewer
    almost always wants side by side; attachments next; then the first few
    remaining columns.
    """
    columns = [c for c in columns if c not in skip]
    info = classify(columns)
    chosen: list[str] = []
    for role in (PROMPT, GOLD):
        found = find(columns, role, exclude=tuple(chosen))
        if found:
            chosen.append(found)
    chosen += [c for c in info.attachments if c not in chosen][:2]
    for name in columns:
        if len(chosen) >= limit:
            break
        if name not in chosen:
            chosen.append(name)
    return [{"field": name, "label": name} for name in chosen[:limit]]
