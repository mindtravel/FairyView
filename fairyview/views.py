"""View base class and the adapter registry.

A view is row-at-a-time: it declares the columns it reads and turns one row into
panels. Everything mechanical (finding files, projection, sampling, ids,
facets, provenance) belongs to `fairyview.driver`.

There is one registry. Every entry is an `Adapter` that knows how to validate
its own config shape and produce records, so the driver never branches on
"is this a view or something else".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol, runtime_checkable

from fairyview.record import Rendered
from fairyview.schema import ReviewRecord
from fairyview.source import Source


@dataclass
class View:
    """Row-at-a-time rendering.

    `memo` caches anything derived from the schema (resolved columns, panel
    config). Resolving inside `render()` would re-classify every column once per
    record.
    """

    name: str
    cfg: dict
    source: Source
    sample_cfg: dict | None = None
    _memo: dict = field(default_factory=dict, init=False, repr=False)

    # --- schema-derived values: resolve once ---

    def memo(self, key: str, compute: Callable):
        if key not in self._memo:
            self._memo[key] = compute()
        return self._memo[key]

    def columns(self) -> list[str]:  # pragma: no cover - protocol
        raise NotImplementedError

    def render(self, row: dict) -> Rendered | None:  # pragma: no cover - protocol
        raise NotImplementedError

    def provenance(self) -> dict:
        return {}

    # --- config accessors shared by views ---

    @property
    def facets(self) -> list[str]:
        return list(self.cfg.get("facets") or [])

    @property
    def id_field(self) -> str | None:
        return self.cfg.get("id_field")


@runtime_checkable
class Adapter(Protocol):
    """One registry entry: validate a config, then produce records."""

    name: str
    config_shape: str

    def validate(self, cfg: dict) -> None: ...

    def records(self, cfg: dict, sample_cfg: dict | None, stats: dict) -> list[ReviewRecord]: ...


class RowAdapter:
    """Adapter for a `View`: validate `path`, then run the driver loop."""

    config_shape = "single"
    config_fields = ("path",)

    def __init__(self, name: str, factory: Callable[[dict, Source], View]):
        self.name = name
        self._factory = factory

    def validate(self, cfg: dict) -> None:
        if not cfg.get("path"):
            raise ValueError(f"{self.name}: [source] needs `path`")

    def records(self, cfg: dict, sample_cfg: dict | None, stats: dict) -> list[ReviewRecord]:
        from fairyview.driver import records_from_view
        from fairyview.source import load_source

        source = load_source(cfg)
        view = self._factory(cfg, source)
        view.sample_cfg = sample_cfg
        return records_from_view(view, cfg.get("mask"), stats)


class SourceAdapter:
    """Adapter for a whole-source callable (e.g. a join over two files)."""

    config_shape = "paired"
    config_fields = ("left", "right")

    def __init__(self, name: str, factory: Callable[[dict], Callable[[dict], Iterable[ReviewRecord]]]):
        self.name = name
        self._factory = factory

    def validate(self, cfg: dict) -> None:
        missing = [field for field in self.config_fields if not cfg.get(field)]
        if missing:
            raise ValueError(
                f"{self.name}: [source] needs {missing}; this adapter joins two sides "
                f"and does not take a single `path`"
            )
        for side in self.config_fields:
            if not cfg[side].get("path"):
                raise ValueError(f"{self.name}: [source.{side}] needs `path`")

    def records(self, cfg: dict, sample_cfg: dict | None, stats: dict) -> list[ReviewRecord]:
        from fairyview.sample import sample_records

        stats["source_files"] = [
            {"path": cfg[side]["path"], "bytes": __import__("os").stat(cfg[side]["path"]).st_size
             if __import__("os").path.isfile(cfg[side]["path"]) else None}
            for side in self.config_fields
        ]
        producer = self._factory(cfg)
        if not sample_cfg:
            return list(producer(cfg))
        stratify = sample_cfg.get("stratify")
        return sample_records(
            producer(cfg),
            sample_cfg,
            facet_key=(lambda record: record.facets.get(stratify)) if stratify else (lambda record: None),
        )


_REGISTRY: dict[str, Adapter] = {}


def register_row(name: str):
    def deco(factory: Callable[[dict, Source], View]):
        _REGISTRY[name] = RowAdapter(name, factory)
        return factory

    return deco


def register_source(name: str):
    def deco(factory):
        _REGISTRY[name] = SourceAdapter(name, factory)
        return factory

    return deco


def load_adapter(name: str) -> Adapter:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown adapter {name!r}; known: {sorted(_REGISTRY)}") from None


def registered() -> dict[str, Adapter]:
    return dict(_REGISTRY)


def builtins() -> tuple[str, ...]:
    # Importing the adapter package is what fills the registry; do it here so
    # `from fairyview.views import builtins` never returns an empty tuple.
    import fairyview.adapters  # noqa: F401

    return tuple(sorted(_REGISTRY))


def description(name: str) -> str:
    entry = _REGISTRY.get(name)
    if entry is None:
        return ""
    return "whole-source join" if entry.config_shape == "paired" else "row-at-a-time"


def load_custom(spec: str, base_dir: str | Path | None = None) -> Adapter:
    """`./file.py:func` or `package.module:func` -> an adapter over records."""
    from fairyview.adapters.loader import load_callable

    fn = load_callable(spec, base_dir=base_dir)
    return _CustomAdapter(spec, fn)


class _CustomAdapter:
    config_shape = "custom"
    config_fields = ()

    def __init__(self, name: str, fn):
        self.name = name
        self._fn = fn

    def validate(self, cfg: dict) -> None:
        return None

    def records(self, cfg: dict, sample_cfg: dict | None, stats: dict) -> list[ReviewRecord]:
        from fairyview.sample import sample_records

        if not sample_cfg:
            return list(self._fn(cfg))
        stratify = sample_cfg.get("stratify")
        return sample_records(
            self._fn(cfg),
            sample_cfg,
            facet_key=(lambda record: record.facets.get(stratify)) if stratify else (lambda record: None),
        )
