import json
from pathlib import Path

import pytest

from fairyview.adapters.loader import load_callable
from fairyview.views import registered
from fairyview.adapters.chat_rows import coerce_messages, render_messages
from fairyview.driver import build_records


def _config(kind: str, path: Path, **extra) -> dict:
    source = {"kind": kind, "path": str(path), "glob": "**/*.jsonl", **extra}
    return {"source": source}


def test_coerce_messages_accepts_list_json_and_python_literal():
    messages = [{"role": "user", "content": "hi"}]
    assert coerce_messages(messages) == messages
    assert coerce_messages(json.dumps(messages)) == messages
    assert coerce_messages(str(messages)) == messages
    assert coerce_messages(None) == []


def test_render_marks_only_assistant_as_loss():
    text, spans = render_messages(
        [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
    )
    kinds = [span.kind for span in spans]
    assert kinds == ["prompt", "loss"]
    for span in spans:
        assert text[span.start : span.end] in ("q", "a")


def test_chat_rows_reads_jsonl(tmp_path: Path):
    rows = [{"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}], "source": "s"}]
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    config = _config("chat_rows", path, facets=["source"])
    records = build_records(config, tmp_path / "c.toml")
    assert len(records) == 1
    assert records[0]["facets"]["source"] == "s"
    assert records[0]["panels"][0]["spans"][1]["kind"] == "loss"


def test_unknown_facet_column_fails_loudly(tmp_path: Path):
    """A missing facet column used to yield an empty page with no error."""
    rows = [{"conversations": [{"from": "human", "value": "hi"}, {"from": "gpt", "value": "ok"}]}]
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    config = _config("chat_rows", path, facets=["source"])
    with pytest.raises(ValueError, match="not found"):
        build_records(config, tmp_path / "c.toml")


def test_chat_rows_accepts_sharegpt_without_facets(tmp_path: Path):
    rows = [{"conversations": [{"from": "human", "value": "hi"}, {"from": "gpt", "value": "ok"}]}]
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    config = _config("chat_rows", path, facets=[])
    records = build_records(config, tmp_path / "c.toml")
    assert len(records) == 1
    assert "gpt" in records[0]["panels"][0]["text"]


def test_auto_detects_chat_shape(tmp_path: Path):
    rows = [{"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]}]
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    records = build_records(_config("auto", path), tmp_path / "c.toml")
    # "chat" is the value `auto` wrote before it delegated to named views.
    # Downstream filters and saved decisions rely on it; do not rename.
    assert records[0]["provenance"]["mode"] == "chat"


def test_auto_reports_unknown_columns(tmp_path: Path):
    path = tmp_path / "data.jsonl"
    path.write_text(json.dumps({"weird": 1}) + "\n", encoding="utf-8")
    # Unknown columns fall back to columns_rows, which derives panels from the
    # schema rather than producing an empty page.
    records = build_records(_config("auto", path), tmp_path / "c.toml")
    assert records[0]["panels"][0]["text"] == "1"


def test_local_adapter_file_relative_to_config(tmp_path: Path):
    adapter_py = tmp_path / "my_adapter.py"
    adapter_py.write_text(
        "from fairyview.schema import Panel, ReviewRecord\n"
        "def make_records(cfg):\n"
        "    yield ReviewRecord(id='x', panels=[Panel(role='text', label='t', text='hello')])\n",
        encoding="utf-8",
    )
    adapter = load_callable("./my_adapter.py:make_records", base_dir=tmp_path)
    records = list(adapter({}))
    assert records[0].id == "x"


def test_all_builtins_registered():
    assert set(registered()) == {
        "auto",
        "benchmark_rows",
        "chat_rows",
        "columns_rows",
        "hf_rows",
        "inference_rows",
        "paired",
    }


def test_benchmark_rows_keeps_model_columns_in_projection(tmp_path: Path):
    """A parquet projection that drops model_* columns used to skip every row."""
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    path = tmp_path / "b.parquet"
    pq.write_table(
        pa.table(
            {
                "question": [f"q{i}" for i in range(4)],
                "gold": ["g"] * 4,
                "model_a": ["aa"] * 4,
                "model_b": ["bb"] * 4,
            }
        ),
        path,
    )
    records = build_records(
        {"source": {"kind": "benchmark_rows", "path": str(tmp_path), "glob": "*.parquet"}},
        tmp_path / "c.toml",
    )
    assert len(records) == 4
    labels = [panel["label"] for panel in records[0]["panels"]]
    assert any("a" in label for label in labels) and any("b" in label for label in labels)


def test_inference_rows_has_no_gold(tmp_path: Path):
    path = tmp_path / "i.jsonl"
    path.write_text(
        "\n".join(json.dumps({"prompt": f"p{i}", "model_x": "x"}) for i in range(3)),
        encoding="utf-8",
    )
    records = build_records(_config("inference_rows", path), tmp_path / "c.toml")
    assert len(records) == 3
    roles = [panel["role"] for panel in records[0]["panels"]]
    assert "gold" not in roles


def test_paired_joins_by_id(tmp_path: Path):
    left = tmp_path / "l.jsonl"
    right = tmp_path / "r.jsonl"
    left.write_text("\n".join(json.dumps({"id": str(i), "text": f"b{i}"}) for i in range(3)), encoding="utf-8")
    right.write_text("\n".join(json.dumps({"id": str(i), "text": f"a{i}"}) for i in range(3)), encoding="utf-8")

    # `paired` has no top-level path; validate() must say so instead of KeyError.
    with pytest.raises(ValueError, match="left"):
        build_records({"source": {"kind": "paired", "path": str(left)}}, tmp_path / "c.toml")

    config = {
        "source": {
            "kind": "paired",
            "join_field": "id",
            "left": {"path": str(left), "glob": "*.jsonl"},
            "right": {"path": str(right), "glob": "*.jsonl"},
        }
    }
    records = build_records(config, tmp_path / "c.toml")
    assert len(records) == 3
    assert [panel["text"] for panel in records[0]["panels"]] == ["b0", "a0"]


def test_inspect_suggests_config_for_prompt_gold_source(tmp_path: Path):
    from fairyview.inspect import inspect_source

    path = tmp_path / "bc.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"id": f"r{i}", "topic": "Art", "question": "q", "answer": "a"}) for i in range(5)
        ),
        encoding="utf-8",
    )
    info = inspect_source(str(path))
    roles_by_column = {c["name"]: c["role"] for c in info["columns"]}
    assert roles_by_column["question"] == "prompt"
    assert roles_by_column["answer"] == "gold"
    assert roles_by_column["topic"] == "facet"
    assert info["suggestion"]["kind"] == "columns_rows"
    assert 'field = "question"' in info["config"]
