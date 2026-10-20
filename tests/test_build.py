import json
from pathlib import Path

from fairyview.build import build


CONFIG = """
title = "t </title> & <script>"
data_key = "demo"
max_inline_records = 3
facets = ["source"]

[sample]
n = 4
seed = 0

[source]
kind = "{kind}"
path = "{path}"
glob = "**/*.jsonl"
"""


def _write_rows(path: Path, count: int) -> None:
    lines = []
    for i in range(count):
        lines.append(
            json.dumps(
                {
                    "messages": [
                        {"role": "user", "content": f"q{i}"},
                        {"role": "assistant", "content": f"a{i}"},
                    ],
                    "source": "s",
                }
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def test_single_file_output(tmp_path: Path):
    data = tmp_path / "data.jsonl"
    _write_rows(data, 2)
    cfg = tmp_path / "c.toml"
    cfg.write_text(CONFIG.format(kind="chat_rows", path=data), encoding="utf-8")

    out = build(str(cfg), str(tmp_path / "out"))
    assert (out / "index.html").exists()
    assert (out / "records.js").exists()
    text = (out / "index.html").read_text(encoding="utf-8")
    assert "records.js" in text
    # Title is escaped in the page shell.
    assert "<script>" not in text.split("<body>")[0]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["record_count"] == 2
    # top-level facets reach the page and every record
    assert json.loads((out / "config.js").read_text().split("=", 1)[1].strip().rstrip(";"))["facets"] == ["source"]


def test_sharded_output_only_loads_index(tmp_path: Path):
    data = tmp_path / "data.jsonl"
    _write_rows(data, 10)
    cfg = tmp_path / "c.toml"
    cfg.write_text(CONFIG.format(kind="chat_rows", path=data), encoding="utf-8")

    out = build(str(cfg), str(tmp_path / "out"))
    shards = list((out / "shards").glob("shard-*.js"))
    assert len(shards) == 2  # 10 records sampled to 4, page 3 -> 2 shards
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'src="shard_index.js"' in html
    assert 'src="shards/shard-000.js"' not in html


def test_relative_data_path_is_relative_to_the_config(tmp_path, monkeypatch):
    import json

    from fairyview.build import build

    project = tmp_path / "project"
    project.mkdir()
    (project / "rows.jsonl").write_text('{"id": "1", "text": "hello"}\n', encoding="utf-8")
    (project / "c.toml").write_text(
        'title="t"\n[source]\nkind="hf_rows"\npath="rows.jsonl"\ntext_field="text"\nid_field="id"\n',
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    out = build(str(project / "c.toml"), str(tmp_path / "out"))
    assert json.loads((out / "manifest.json").read_text())["record_count"] == 1
