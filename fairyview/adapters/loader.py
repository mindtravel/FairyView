"""Custom adapter loading: `./file.py:func` or `package.module:func`."""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path


def _load_file_adapter(path: Path, func_name: str):
    if not path.exists():
        raise FileNotFoundError(f"adapter file not found: {path}")
    module_name = f"_fairyview_adapter_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load adapter from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, func_name):
        raise AttributeError(f"{path} has no function {func_name!r}")
    return getattr(module, func_name)


def load_callable(spec: str, base_dir: str | os.PathLike | None = None):
    if ":" not in spec:
        raise KeyError(f"{spec!r} is not a custom adapter; expected './file.py:func' or 'module:func'")
    target, func_name = spec.rsplit(":", 1)
    if target.startswith(".") or target.endswith(".py") or os.sep in target:
        path = Path(target)
        if not path.is_absolute():
            path = Path(base_dir or ".") / target
        return _load_file_adapter(path.resolve(), func_name)
    return getattr(importlib.import_module(target), func_name)
