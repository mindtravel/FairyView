# Contributing

## Setup

```bash
pip install -e ".[test,parquet]"
pytest -q
```

## Code layout

One module per responsibility. A change usually touches one row of this table.

```
fairyview/
  schema.py      ReviewRecord / Panel / Span / Score: the contract
  roles.py       column-name vocabulary (which column is the prompt, the gold, ...)
  rows.py        file readers: parquet projection, JSONL byte offsets
  source.py      files + union schema; fails on missing columns, compressed or changed files
  sample.py      reservoir + stratified sampling
  views.py       View base class and the single adapter registry
  driver.py      scan -> sample -> decode -> render -> record; counts every drop
  mask.py        [mask] rules, role kinds, truncation
  record.py      ids, facets and provenance for every record
  build.py       records -> shards -> HTML + manifest.json
  inspect.py     schema -> suggested config
  cli.py         command line
  adapters/      one view per data shape; they read columns and return panels
template/        page.html / app.js / style.css, shipped inside the wheel
presets/         starter configs for `fairyview init --preset`
examples/        runnable demo data and configs
tests/
```

## Adding a view

1. New module in `fairyview/adapters/`. Subclass `View`, implement `columns()`
   (what to read) and `render(row)` (panels), register with `@register_row("name")`.
   A view that needs a whole-source join uses `@register_source`.
2. Do not sample, build ids, or emit HTML in a view; `driver.py` and `record.py` do that.
3. Add a test with a tiny tmp JSONL fixture.
4. Add the view to the table in both READMEs and to `KEYS` in `cli.py`.

## Changing the contract

`fairyview/schema.py` is the stable interface. Bump `SCHEMA_VERSION`, update the
README, and note the change in `CHANGELOG.md`.

## Renderer changes

Plain HTML/CSS/JS in `template/`, no bundler and no dependencies. Every visible
string goes through the `I18N` table in `app.js` (English and Chinese). Keep the
page usable from `file://`: no fetch/XHR for data.

```bash
node --check template/app.js
python -m fairyview build --config examples/demo.toml --out /tmp/demo
```

## Documentation

`README.md` and `README.zh-CN.md` have the same sections in the same order.
Change both in one commit.
