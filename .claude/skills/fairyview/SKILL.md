---
name: fairyview
description: Render a self-contained HTML page to review rows of a dataset, cleaning output, benchmark, or model comparison. Use when the user wants to inspect, sample, compare, or audit data.
---

# FairyView

One idea: **a row becomes a record; a record becomes a page**. The record schema
(`fairyview/schema.py`) is shared by every source, so a new dataset only needs a
config, not a new page.

## Workflow

```bash
fairyview inspect --path <data> --out cfg.toml   # columns + roles + ready config
fairyview try     --config cfg.toml --limit 3    # must print records before building
fairyview build   --config cfg.toml --out out/x
```

`inspect` reads the real schema and fills the field names for you. Never invent a
column name. If it picks the wrong kind, override `kind` in `[source]`.

## Config

```toml
[sample]            n = 200
                    stratify = "source"        # optional
[source]            kind = "auto"               # or chat_rows / hf_rows /
                    path = "..."                # columns_rows / benchmark_rows /
                    glob = "**/*.parquet"       # inference_rows / paired
```

Extra `[source]` keys per kind: `messages_field`, `text_field`, `prompt_field`,
`gold_field`, `panels`, `scores`, `id_field`. Plus top-level `facets` (filters and
stratification) and `lang` (`en` / `zh`). Relative `path` is relative to the config.

`paired` is the one whole-source adapter: it takes `[source.left]` and
`[source.right]` instead of a single `path`.

Custom shape: `kind = "./adapter.py:make_records"`, yielding `ReviewRecord`s.

Masks are rules, not code (`fairyview/mask.py`):

```toml
[mask]
loss_roles = ["assistant"]      # chat: supervised roles; prompt_roles likewise
max_panel_chars = 20000         # cut is written into the text, never silent
[[mask.rules]]                  # regex -> span; earlier rules win overlaps
pattern = "<think>.*?</think>"
kind = "loss"                   # loss / prompt / match / warning / custom
label = "think"
```

## Rules

- A source with no `source` column needs `facets = []`; otherwise the scan has
  no column to read. `inspect` handles this.
- Data must be uncompressed parquet / JSONL / JSON; `.gz` etc. are rejected
  (`gunzip -k` first). JSONL rows are addressed by byte offset, and a file
  that changes mid-build fails the build.
- Every dropped row is counted by reason in `manifest.json` and printed to
  stderr; `on_drop = "error"` in `[source]` makes any drop fatal. Source files
  (path, bytes, mtime) are recorded and shown on the page.
- Empty page means the projection or the facet column is wrong. Run `try` first;
  a build that writes `record_count: 0` is a failure, not an empty dataset.
- `caveats` must say what the page does *not* prove: sampling, character-level
  spans, uncalibrated scores.
- Adapters produce panels; they never build ids, facets, or HTML. That lives in
  `driver.py` / `record.py`.

## Project-specific setup

Server paths, sync scripts and private configs belong to the project that uses
FairyView, not to this skill. Look for a `review/` folder in that project.
