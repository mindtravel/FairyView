"""Turn review records + a config into a self-contained HTML directory."""

from __future__ import annotations

import hashlib
import html
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from fairyview.driver import build_records  # re-exported; one driver for all adapters
from fairyview.schema import SCHEMA_VERSION

_PACKAGED = Path(__file__).resolve().parent / "_template"
TEMPLATE_DIR = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parent.parent / "template"
DEFAULT_MAX_INLINE = 500


def load_config(path: str | Path) -> dict:
    path = Path(path)
    if path.suffix == ".toml":
        return tomllib.loads(path.read_text(encoding="utf-8"))
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    raise ValueError(f"unsupported config format: {path.suffix}; use .toml or .json")


def config_hash(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def _js_embed(obj, name: str) -> str:
    """Embed JSON as a JS assignment.

    `</` is escaped so data containing `</script>` cannot end the tag.
    """
    text = json.dumps(obj, ensure_ascii=False, default=str)
    text = text.replace("</", "<\\/")
    return f"window.{name} = {text};\n"


def build(config_path: str, out_dir: str) -> Path:
    config_path = Path(config_path)
    config = load_config(config_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "shards").mkdir(exist_ok=True)

    stats: dict = {}
    records = build_records(config, config_path, stats)
    max_inline = int(config.get("max_inline_records", DEFAULT_MAX_INLINE))

    page = (TEMPLATE_DIR / "page.html").read_text(encoding="utf-8")
    app_js = (TEMPLATE_DIR / "app.js").read_text(encoding="utf-8")
    style_css = (TEMPLATE_DIR / "style.css").read_text(encoding="utf-8")

    # Data files. A sharded review loads shard_index.js only; app.js pulls each
    # shard on demand, so a large review does not load everything up front.
    shard_files: list[str] = []
    if len(records) <= max_inline:
        data_files = [("records.js", _js_embed(records, "REVIEW_RECORDS"))]
        data_tags = ['<script src="records.js"></script>']
    else:
        per_shard = max_inline
        chunks = [records[i : i + per_shard] for i in range(0, len(records), per_shard)]
        data_files = []
        for index, chunk in enumerate(chunks):
            name = f"shards/shard-{index:03d}.js"
            shard_files.append(name)
            data_files.append((name, _js_embed(chunk, f"REVIEW_SHARD_{index}")))
        data_files.append(
            (
                "shard_index.js",
                _js_embed(
                    {"shards": shard_files, "records_per_shard": per_shard, "total": len(records)},
                    "REVIEW_SHARD_INDEX",
                ),
            )
        )
        data_tags = ['<script src="shard_index.js"></script>']

    view_config = {
        "title": config.get("title", "Data review"),
        "description": config.get("description", ""),
        "caveats": config.get("caveats", []),
        "facets": config.get("facets", []),
        "panel_layout": config.get("panel_layout", "side_by_side"),
        "lang": config.get("lang"),
        "page_size": int(config.get("page_size", 100)),
        "blinded_default": bool(config.get("blinded_default", False)),
        "config_hash": config_hash(config),
        "data_key": config.get("data_key") or config.get("title", "data review"),
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "record_count": len(records),
        "rows_examined": stats.get("rows_examined"),
        "dropped": stats.get("dropped", {}),
        "source_files": stats.get("source_files", []),
        "sharded": bool(shard_files),
    }

    (out / "config.js").write_text(_js_embed(view_config, "REVIEW_CONFIG"), encoding="utf-8")
    for name, payload in data_files:
        (out / name).write_text(payload, encoding="utf-8")
    (out / "app.js").write_text(app_js, encoding="utf-8")
    (out / "style.css").write_text(style_css, encoding="utf-8")
    (out / f"config{config_path.suffix}").write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "config_hash": view_config["config_hash"],
                "data_key": view_config["data_key"],
                "generated_at": view_config["generated_at"],
                "record_count": len(records),
        "rows_examined": stats.get("rows_examined"),
        "dropped": stats.get("dropped", {}),
        "source_files": stats.get("source_files", []),
                "shards": shard_files,
                "schema_version": SCHEMA_VERSION,
                "source_files": stats.get("source_files", []),
                "rows_examined": stats.get("rows_examined"),
                "dropped": stats.get("dropped", {}),
                "dropped_examples": stats.get("dropped_examples", []),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    page = page.replace("{{TITLE}}", html.escape(view_config["title"]))
    page = page.replace("{{DESCRIPTION}}", html.escape(view_config["description"]))
    page = page.replace("{{DATA_SCRIPTS}}", "\n".join(data_tags))
    (out / "index.html").write_text(page, encoding="utf-8")
    return out
