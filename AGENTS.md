# Working on FairyView (notes for coding agents)

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the code layout. These are the
invariants a change must keep.

## Invariants

- **Traceable.** Every record has source file + row in `provenance`; `manifest.json`
  lists source files with size and mtime.
- **Raw first.** Panel text is the original field text. Truncation is written
  into the text (`mask.truncate`), never silent.
- **Loud failure.** Missing columns raise with the available columns. Every
  dropped row is counted by reason (`driver._check_drops`). A build that writes
  `record_count: 0` is a failure.
- **Cheap scan.** The sampling scan reads only facet / id / stratify columns;
  heavy columns are decoded for sampled rows only. `tests/test_mask.py` pins this.
- Views read columns and return panels. They never sample, build ids, or emit HTML.
- Spans are character offsets into their panel's text, validated in `schema.validate()`.
- Renderer: no npm, no bundler, no CDN; every visible string goes through `I18N`.
- Every config key is documented in both READMEs.

## Where to make a change

| Task | File |
|---|---|
| New data shape | `fairyview/adapters/`, `@register_row` / `@register_source` |
| Column-name guessing | `roles.py` |
| Highlighting | `mask.py` (rules) or the view's `render` |
| Sampling | `sample.py` |
| Page widget or text | `template/`, plus both languages in `I18N` |
| Config option | read it where it is used, then document it in both READMEs |

## Verification

```bash
pytest -q
node --check template/app.js
python -m fairyview build --config examples/demo.toml --out /tmp/demo
python -m fairyview build --config examples/benchmark.toml --out /tmp/bench
```
