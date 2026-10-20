import json
from pathlib import Path

import pytest

from fairyview import mask
from fairyview.build import build
from fairyview.schema import Panel, Span


def _cfg(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "c.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _write(path: Path, rows) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def test_rules_produce_spans_of_the_configured_kind():
    rules = mask.parse_rules({"rules": [{"pattern": r"<\|start_think\|>.*?<\|end_think\|>", "kind": "loss"}]})
    text = "a <|start_think|>why<|end_think|> b"
    spans = mask.apply_rules(text, rules)
    assert len(spans) == 1
    assert spans[0].kind == "loss"
    assert text[spans[0].start : spans[0].end] == "<|start_think|>why<|end_think|>"


def test_overlapping_rules_keep_the_first():
    rules = mask.parse_rules(
        {
            "rules": [
                {"pattern": "abcdef", "kind": "loss"},
                {"pattern": "cde", "kind": "match"},
            ]
        }
    )
    spans = mask.apply_rules("xxabcdef", rules)
    assert [s.kind for s in spans] == ["loss"]


def test_invalid_regex_fails_loudly():
    with pytest.raises(ValueError, match="not valid regex"):
        mask.parse_rules({"rules": [{"pattern": "(", "kind": "loss"}]})


def test_truncation_is_marked_in_the_text():
    text, truncated, original = mask.truncate("x" * 100, 10)
    assert truncated and original == 100
    assert text.startswith("x" * 10)
    assert "truncated" in text and "100" in text


def test_truncated_span_survives_validation():
    panels = mask.finalize_panels(
        [Panel(role="t", label="t", text="word " * 100, spans=[Span(0, 500, "loss")])],
        {"max_panel_chars": 50},
    )
    for span in panels[0].spans:
        assert span.end <= len(panels[0].text)


def test_build_reports_dropped_rows(tmp_path: Path):
    data = _write(
        tmp_path / "x.jsonl",
        [{"id": str(i), "text": "ok" if i % 2 else ""} for i in range(6)],
    )
    cfg = _cfg(
        tmp_path,
        f'''title="d"
data_key="d"
[sample]
n = 6
[source]
kind = "hf_rows"
path = "{data}"
text_field = "text"
id_field = "id"
''',
    )
    out = build(str(cfg), str(tmp_path / "o"))
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["rows_examined"] == 6
    assert manifest["record_count"] == 3
    assert manifest["dropped"] == {"no panel produced": 3}
    assert manifest["dropped_examples"][0]["reason"] == "no panel produced"


def test_on_drop_error_turns_drops_into_failure(tmp_path: Path):
    data = _write(tmp_path / "x.jsonl", [{"id": "1", "text": ""}])
    cfg = _cfg(
        tmp_path,
        f'''title="d"
data_key="d"
[source]
kind = "hf_rows"
path = "{data}"
text_field = "text"
id_field = "id"
on_drop = "error"
''',
    )
    with pytest.raises(ValueError, match="dropped 1 rows"):
        build(str(cfg), str(tmp_path / "o"))


def test_manifest_records_source_files(tmp_path: Path):
    data = _write(tmp_path / "x.jsonl", [{"id": "1", "text": "ok"}])
    cfg = _cfg(
        tmp_path,
        f'''title="d"
data_key="d"
[source]
kind = "hf_rows"
path = "{data}"
text_field = "text"
id_field = "id"
''',
    )
    out = build(str(cfg), str(tmp_path / "o"))
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["source_files"][0]["path"] == "x.jsonl"
    assert manifest["source_files"][0]["bytes"] == data.stat().st_size


def test_chat_mask_roles_are_configurable(tmp_path: Path):
    data = _write(
        tmp_path / "x.jsonl",
        [{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}],
    )
    cfg = _cfg(
        tmp_path,
        f'''title="d"
data_key="d"
[sample]
n = 1
[source]
kind = "chat_rows"
path = "{data}"
facets = []

[mask]
loss_roles = ["user"]
prompt_roles = ["assistant"]
''',
    )
    out = build(str(cfg), str(tmp_path / "o"))
    records = json.loads((out / "records.js").read_text().split("=", 1)[1].strip().rstrip(";"))
    kinds = [s["kind"] for s in records[0]["panels"][0]["spans"]]
    assert kinds == ["loss", "prompt"]


def test_sampling_scan_does_not_decode_heavy_columns(tmp_path: Path, monkeypatch):
    from fairyview.source import Source

    seen = []
    original = Source.iter_index

    def spy(self, projection, *, owner):
        seen.append(list(projection))
        return original(self, projection, owner=owner)

    monkeypatch.setattr(Source, "iter_index", spy)
    data = _write(
        tmp_path / "x.jsonl",
        [{"source": "a", "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}] * 4,
    )
    cfg = _cfg(
        tmp_path,
        f'''title="d"
data_key="d"
facets = ["source"]
[sample]
n = 2
stratify = "source"
[source]
kind = "chat_rows"
path = "{data}"
''',
    )
    out = build(str(cfg), str(tmp_path / "o"))
    assert seen == [["source"]]
    assert json.loads((out / "manifest.json").read_text())["record_count"] == 2


def test_allocate_takes_everything_when_budget_exceeds_rows():
    from fairyview.sample import allocate

    assert allocate([53, 86, 26], 200) == [53, 86, 26]
    take = allocate([53, 86, 26], 150)
    assert sum(take) == 150 and take[2] == 26 and take[0] == 53
    assert allocate([5, 5, 5], 2) == [1, 1, 0]


def test_jsonl_offsets_read_back_the_same_rows(tmp_path: Path):
    from fairyview.source import load_source

    rows = [{"id": str(i), "text": "x" * i} for i in range(50)]
    data = _write(tmp_path / "x.jsonl", rows)
    source = load_source({"path": str(data)})
    keys = [key for key, _ in source.iter_index(["id"], owner="t")]
    assert all(key.offset is not None for key in keys)
    decoded = source.read(keys[::7], ["id", "text"])
    assert [decoded[k]["id"] for k in keys[::7]] == [str(i) for i in range(0, 50, 7)]


def test_parallel_scan_matches_sequential(tmp_path: Path, monkeypatch):
    from fairyview import rows as rows_mod

    data = _write(tmp_path / "x.jsonl", [{"s": i % 3, "p": "y" * 50} for i in range(400)])
    monkeypatch.setattr(rows_mod, "CHUNK_BYTES", 1000)
    assert len(rows_mod._chunk_bounds(str(data))) > 10
    got = list(rows_mod.scan_jsonl(str(data), ["s"]))
    assert len(got) == 400 and [r["s"] for _, r in got] == [i % 3 for i in range(400)]


def test_compressed_files_are_rejected(tmp_path: Path):
    import gzip

    from fairyview.source import load_source

    with gzip.open(tmp_path / "x.jsonl.gz", "wt") as handle:
        handle.write('{"a": 1}\n')
    with pytest.raises(ValueError, match="Decompress first"):
        load_source({"path": str(tmp_path), "glob": "*.jsonl*"})


def test_file_changed_between_scan_and_read_fails(tmp_path: Path):
    from fairyview.source import load_source

    data = _write(tmp_path / "x.jsonl", [{"id": "1"}, {"id": "2"}])
    source = load_source({"path": str(data)})
    keys = [key for key, _ in source.iter_index(["id"], owner="t")]
    _write(data, [{"id": "changed", "pad": "x" * 10}, {"id": "2"}])
    with pytest.raises(RuntimeError, match="changed while it was being read"):
        source.read(keys, ["id"])
