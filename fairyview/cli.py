"""fairyview CLI.

    fairyview build --config configs/x.toml --out out/x
    fairyview dump  --config configs/x.toml --out out/x     # records.jsonl
    fairyview try   --config configs/x.toml --limit 5       # print records
    fairyview adapters                                      # list built-ins
    fairyview init  --path <data> --out configs/x.toml      # scaffold a config
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fairyview.views import builtins, description
from fairyview.build import build, build_records, load_config
from fairyview.inspect import inspect_source


def _cmd_build(args: argparse.Namespace) -> int:
    out = build(args.config, args.out)
    print(f"wrote {out}/index.html")
    return 0


def _cmd_dump(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    records = build_records(load_config(config_path), config_path)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "records.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records to {path}")
    return 0


def _cmd_try(args: argparse.Namespace) -> int:
    """Render a few records to the terminal before building the page."""
    config_path = Path(args.config)
    config = load_config(config_path)
    source = dict(config["source"])
    config = dict(config, source=source)
    records = build_records(config, config_path)[: args.limit]
    if not records:
        print("no records produced; check the adapter and path", file=sys.stderr)
        return 1
    for record in records:
        print("=" * 72)
        print(f"id: {record['id']}")
        print(f"facets: {record['facets']}")
        for name, value in record["fields"]:
            print(f"  {name}: {value}")
        for panel in record["panels"]:
            print(f"--- {panel['label']} ({len(panel['text'])} chars, {len(panel['spans'])} spans)")
            preview = panel["text"][: args.chars].replace("\n", "\\n")
            print(preview + ("..." if len(panel["text"]) > args.chars else ""))
        for score in record["scores"]:
            print(f"  score {score['model']}: {score['value']} ({score['scale']})")
    print("=" * 72)
    print(f"{len(records)} record(s) shown")
    return 0


def _cmd_describe(_: argparse.Namespace) -> int:
    """Machine-readable description for agents and other tools."""
    import json as _json

    from fairyview.schema import SCHEMA_VERSION

    payload = {
        "name": "fairyview",
        "schema_version": SCHEMA_VERSION,
        "commands": {
            "build": "render a review page (--config, --out)",
            "try": "print records to the terminal (--config, --limit)",
            "dump": "write records.jsonl (--config, --out)",
            "init": "scaffold a config; auto mode reads the schema (--path, --out, --kind)",
            "inspect": "list a source's columns with roles, print a matching config (--path, --json)",
            "adapters": "list built-in adapters",
        },
        "adapters": dict(KEYS),
        "config_shapes": {
            "single": "[source] path + glob; row-at-a-time views",
            "paired": "[source.left] and [source.right]; a whole-source join",
            "custom": "kind = './file.py:func' yields ReviewRecords",
        },
        "record": {
            "id": "string",
            "facets": "dict[str, scalar]",
            "fields": "list[[name, value]]",
            "panels": "list[{role, label, text, spans}]",
            "scores": "list[{model, value, scale, reason?, comparable?}]",
            "provenance": "dict (file, row, ...)",
        },
        "span_kinds": ["loss", "prompt", "match", "truncated", "warning", "custom"],
        "custom_adapter": "kind = './file.py:func' (relative to config) or 'package.module:func'",
        "sampling": "[sample] n / seed / stratify; never in adapters",
    }
    print(_json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


KEYS = {
    "auto": "classify the schema with roles.py, then delegate",
    "chat_rows": "messages or conversations; assistant marked as loss",
    "columns_rows": "explicit columns (a.b, a[0].b); panels default to the schema",
    "hf_rows": "one text column per row (parquet / jsonl / json)",
    "paired": "left/right files; before/after, raw/rendered",
    "benchmark_rows": "prompt + gold + per-model outputs + scores",
    "inference_rows": "prompt + per-model outputs, no gold",
}


def _cmd_inspect(args: argparse.Namespace) -> int:
    info = inspect_source(str(Path(args.path).expanduser().resolve()), args.glob)
    if args.out:
        Path(args.out).write_text(info["config"], encoding="utf-8")
        print(f"wrote {args.out} (kind={info['suggestion']['kind']}, "
              f"columns={len(info['columns'])})")
        return 0
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(info["config"])
        for note in info["notes"]:
            print(f"# note: {note}", file=sys.stderr)
    return 0


def _cmd_adapters(_: argparse.Namespace) -> int:
    print("built-in adapters:")
    for name in builtins():
        print(f"  {name:16} {KEYS.get(name, description(name))}")
    print()
    print("custom adapter: kind = \"./my_adapter.py:make_records\" (path relative to the config)")
    print("                kind = \"my_package.module:make_records\"")
    print("available:", ", ".join(builtins()))
    return 0


_PACKAGED_PRESETS = Path(__file__).resolve().parent / "_presets"
PRESET_DIR = _PACKAGED_PRESETS if _PACKAGED_PRESETS.is_dir() else Path(__file__).resolve().parent.parent / "presets"


def _presets() -> dict[str, Path]:
    if not PRESET_DIR.is_dir():
        return {}
    return {p.stem: p for p in sorted(PRESET_DIR.glob("*.toml"))}


def _cmd_presets(_: argparse.Namespace) -> int:
    presets = _presets()
    if not presets:
        print("no presets found", file=sys.stderr)
        return 1
    for name, path in presets.items():
        first = next((line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#")), "")
        print(f"{name:18} {first.lstrip('# ').strip()}")
    return 0


def _fit_preset_to_schema(text: str, path: Path) -> str:
    """Drop preset column names the data does not have, and say which.

    Presets name typical columns (`split`, `id`). Keeping a missing one would
    make the first `try` fail on a column the user never asked for.
    """
    import re

    from fairyview.source import load_source

    glob = re.search(r'^glob = "([^"]*)"', text, re.M)
    columns = set(load_source({"path": str(path), "glob": glob.group(1) if glob else None}).columns)
    removed: list[str] = []

    def fit_list(match: re.Match) -> str:
        names = re.findall(r'"([^"]+)"', match.group(2))
        kept = [n for n in names if n in columns]
        removed.extend(n for n in names if n not in columns)
        return match.group(1) + "[" + ", ".join(f'"{n}"' for n in kept) + "]"

    def fit_scalar(match: re.Match) -> str:
        if match.group(2) in columns:
            return match.group(0)
        removed.append(match.group(2))
        return "# " + match.group(0) + "  # column not in data"

    text = re.sub(r'^(facets = )\[([^\]]*)\]', fit_list, text, flags=re.M)
    text = re.sub(r'^((?:stratify|id_field) = )"([^"]+)"', fit_scalar, text, flags=re.M)
    if removed:
        print(f"note: preset columns not in the data, removed: {sorted(set(removed))}", file=sys.stderr)
    return text


def _cmd_init(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"{out} exists; pass --force to overwrite", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.preset:
        presets = _presets()
        if args.preset not in presets:
            print(f"unknown preset {args.preset!r}; known: {', '.join(presets)}", file=sys.stderr)
            return 1
        text = presets[args.preset].read_text(encoding="utf-8")
        if args.path:
            path = Path(args.path).expanduser().resolve()
            text = text.replace("CHANGE_ME", str(path))
            # Single-source presets only; paired presets point at subfolders.
            if path.exists() and text.count("\npath = ") == 1:
                text = _fit_preset_to_schema(text, path)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} from preset {args.preset}")
        print(f"next: fairyview try --config {out} --limit 3")
        return 0

    path = Path(args.path).expanduser().resolve()
    kind = args.kind
    if kind == "auto":
        # Read the schema so the generated config names the columns that exist.
        # This is the fix for configs that silently produced empty pages.
        info = inspect_source(str(path), args.glob)
        text = info["config"]
        for note in info["notes"]:
            print(f"note: {note}", file=sys.stderr)
    else:
        text = (
            f'title = "{path.name} review"\n'
            f'data_key = "{path.name}"\n'
            'description = "TODO: what this page is for"\n'
            'panel_layout = "stacked"\n'
            "max_inline_records = 500\n"
            "facets = []\n\n"
            "caveats = [\n"
            '  "Sampled data, not a full-population statistic.",\n'
            "]\n\n"
            "[sample]\n"
            "n = 200\n"
            "seed = 0\n\n"
            "[source]\n"
            f'kind = "{kind}"\n'
            f'path = "{path}"\n'
            'glob = "**/*.parquet"\n'
        )
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    print(f"next: fairyview try --config {out} --limit 3")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fairyview")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="render a review page")
    p_build.add_argument("--config", required=True)
    p_build.add_argument("--out", required=True)
    p_build.set_defaults(func=_cmd_build)

    p_dump = sub.add_parser("dump", help="write records as JSONL (debug)")
    p_dump.add_argument("--config", required=True)
    p_dump.add_argument("--out", required=True)
    p_dump.set_defaults(func=_cmd_dump)

    p_try = sub.add_parser("try", help="print a few records to the terminal")
    p_try.add_argument("--config", required=True)
    p_try.add_argument("--limit", type=int, default=5)
    p_try.add_argument("--chars", type=int, default=400)
    p_try.set_defaults(func=_cmd_try)

    p_adapters = sub.add_parser("adapters", help="list built-in adapters")
    p_adapters.set_defaults(func=_cmd_adapters)

    p_describe = sub.add_parser("describe", help="machine-readable description (JSON)")
    p_describe.set_defaults(func=_cmd_describe)

    p_init = sub.add_parser("init", help="scaffold a config from a preset or a data path")
    p_init.add_argument("--path", help="data directory or file; required unless --preset is used")
    p_init.add_argument("--out", required=True)
    p_init.add_argument("--preset", help="start from a shipped preset")
    p_init.add_argument("--kind", default="auto", help="adapter name; auto inspects the schema")
    p_init.add_argument("--glob", help="file glob under --path (default: **/*.parquet)")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=_cmd_init)

    p_inspect = sub.add_parser("inspect", help="describe a source's columns and print a matching config")
    p_inspect.add_argument("--path", required=True)
    p_inspect.add_argument("--glob", help="file glob under --path (default: **/*.parquet)")
    p_inspect.add_argument("--json", action="store_true", help="machine-readable output")
    p_inspect.add_argument("--out", help="write the suggested config here instead of stdout")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_presets = sub.add_parser("presets", help="list recommended configurations")
    p_presets.set_defaults(func=_cmd_presets)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
