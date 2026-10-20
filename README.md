# FairyView

**English** · [中文](README.zh-CN.md)

Turn any dataset, cleaning output, benchmark, or set of model outputs into one self-contained HTML page for human review. No server, no JS build: the output is a folder you open with a double click.

```bash
pip install "fairyview[parquet] @ git+https://github.com/mindtravel/FairyView"
fairyview inspect --path data/my_dataset --out review.toml   # reads the schema, writes a config
fairyview try     --config review.toml --limit 3             # records in the terminal
fairyview build   --config review.toml --out out/my_dataset  # open out/my_dataset/index.html
```

---

## How it works

```
data files ──view──► records ──renderer──► index.html
            (reads columns)  (one schema)  (one template)
```

A **row becomes a record; a record becomes a page.** Every source produces the same record shape (`fairyview/schema.py`), so a new dataset needs a config, not a new page.

Three rules hold for every build:

- **Traceable.** Each record carries its source file and row number. The page header and `manifest.json` list every source file with its size and mtime.
- **Raw first.** Panels show the original field text. Nothing is rewritten; truncation (if you ask for it) is written into the text itself.
- **Loud failure.** A missing column fails the build and lists the available ones. Every row that produces no record is counted by reason in the manifest and printed to stderr; `on_drop = "error"` makes any drop fatal.

## Choosing a view

`inspect` picks one from the schema; override it with `kind` in `[source]`.

| `kind` | Data shape | Page shows |
|---|---|---|
| `auto` | anything | the view `inspect` would pick |
| `chat_rows` | `messages` / `conversations` | turns, with supervised roles marked as loss |
| `hf_rows` | one text column | text with facets |
| `columns_rows` | chosen columns (`a.b`, `a[0].b`) | one panel per column |
| `benchmark_rows` | prompt + gold + model outputs | question, reference, each answer, scores |
| `inference_rows` | prompt + model outputs | outputs side by side |
| `paired` | two sources joined by key | before / after, with drop reason |
| `./file.py:func` | anything else | whatever your function yields |

## Config

```toml
title = "GSM8K review"
data_key = "gsm8k-2026-10"   # decisions in the browser are keyed by this
facets = ["split"]           # filter controls; [] if the data has none
caveats = ["Sampled rows, not a full-population statistic."]
lang = "en"                  # page language: en / zh; the reader can switch

[sample]
n = 200
seed = 0
stratify = "split"           # optional

[source]
kind = "benchmark_rows"
path = "data/gsm8k"          # relative to this config file
glob = "**/*.parquet"
```

**Page.** `panel_layout` (`side_by_side` / `stacked` / `toggle`), `blinded_default` (hide scores until the reader asks), `max_inline_records` (above this, records are split into shards), `page_size` (cards rendered per "load more", default 100).

**Sampling.** Reservoir sampling over a streamed index, deterministic for a given `seed`. With `stratify`, the budget is split evenly across strata; a stratum smaller than its share is taken whole and the rest is redistributed, so `n` at or above the row count keeps every row.

**Source fields.** Field names are filled by `inspect`; set them only to override.

| Key | Used by |
|---|---|
| `messages_field`, `system_field` | `chat_rows` |
| `text_field`, `fields` | `hf_rows` |
| `panels = [{field, label}]`, `scores`, `auto_panels`, `skip_empty` | `columns_rows` |
| `prompt_field`, `gold_field`, `outputs_field`, `score_field`, `scoring` | `benchmark_rows`, `inference_rows` |
| `[source.left]`, `[source.right]`, `join_field`, `reason_field`, `fields` | `paired` |
| `id_field`, `on_drop` (`report` / `error`) | all |

**Masks.** Highlighting is configured as rules, not code:

```toml
[mask]
loss_roles = ["assistant"]          # chat: supervised roles
prompt_roles = ["user", "system"]   # chat: context-only roles
max_panel_chars = 20000             # optional cut, announced in the text

[[mask.rules]]                      # regex -> highlighted span
pattern = "<think>.*?</think>"
kind = "loss"                       # loss / prompt / match / warning / custom
label = "reasoning"
```

Rules apply to every panel. When rules overlap, the earlier one wins. Spans are character offsets, not tokens.

**Data files.** Uncompressed parquet, JSONL, or JSON. Compressed files (`.gz`, `.bz2`, `.xz`, `.zst`) are rejected; decompress them first (`gunzip -k`). JSONL rows are addressed by byte offset, so a file that changes during a build fails it.

## The page

Card and table views, facet filters, search, panel layouts, span highlighting, score bars, blind mode, an English/中文 switch, and keep / drop / unsure decisions stored in the browser and exported as `decisions.jsonl`. Scores with different `scale` values are never merged. Large reviews are sharded and still open from `file://`.

## Custom adapter

```python
# my_adapter.py, next to the config. No packaging needed.
from fairyview.schema import Panel, ReviewRecord

def make_records(cfg):
    for i, row in enumerate(load_rows(cfg["path"])):
        yield ReviewRecord(
            id=row["id"],
            facets={"source": row["source"]},
            panels=[Panel(role="text", label="body", text=row["text"])],
            provenance={"file": cfg["path"], "row": i},
        )
```

```toml
[source]
kind = "./my_adapter.py:make_records"
path = "data/"
```

## CLI

| Command | Purpose |
|---|---|
| `inspect --path P [--out cfg.toml]` | columns, roles, and a ready config |
| `try --config C --limit N` | print records; run before `build` |
| `build --config C --out DIR` | write the page |
| `dump --config C --out DIR` | write `records.jsonl` |
| `init --preset NAME` / `presets` | start from a preset |
| `adapters` / `describe` | list views; machine-readable summary for agents |

## Development

```bash
pip install -e ".[test,parquet]"
pytest -q
```

Code layout and contribution rules: [CONTRIBUTING.md](CONTRIBUTING.md). Notes for coding agents: [AGENTS.md](AGENTS.md). Changes: [CHANGELOG.md](CHANGELOG.md).

Apache-2.0.
