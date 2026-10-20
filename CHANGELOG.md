# Changelog

## Unreleased

### Changed
- One driver for every view: scan, sample, decode, render. Views only name
  columns and return panels; one adapter registry replaces two.
- Relative data paths resolve against the config file, not the working directory.
- Stratified sampling redistributes unused quota; `n` at or above the row count
  keeps every row.
- The sampling scan reads only key columns; JSONL rows are addressed by byte
  offset and parsed in parallel. Large JSONL builds went from ~60 s to ~3 s.
- Compressed data files are rejected; decompress first.

### Added
- `[mask]`: configurable chat loss/prompt roles, regex rules that produce spans,
  announced truncation (`max_panel_chars`).
- Provenance: source files (path, size, mtime), rows examined, and drop counts
  by reason in `manifest.json` and the page header. `on_drop = "error"`.
- A build fails if a source file changes while it is being read.
- Page language switch (English / 中文) and the `lang` config key.
- `page_size` now reaches the page (it was read but never passed).


## 0.1.0

Initial release.

- `ReviewRecord` contract: `id`, `facets`, `fields`, `panels`, `scores`, `provenance`.
- Adapters: `auto`, `chat_rows`, `hf_rows`, `paired`, `benchmark_rows`, `inference_rows`.
- Shared sampling (`[sample]`: `n`, `seed`, `stratify`).
- Self-contained HTML renderer: card/table views, facet filters, debounced search,
  blind mode, panel layouts, span highlighting, score bars, keep/drop/unsure
  decisions with JSONL export, automatic sharding.
- CLI: `build`, `try`, `dump`, `init`, `presets`, `adapters`, `describe`.
- Six presets: `dataset-chat`, `dataset-text`, `cleaning-paired`, `benchmark`,
  `inference`, `contamination`.
