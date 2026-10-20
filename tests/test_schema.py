import pytest

from fairyview.schema import Panel, ReviewRecord, Score, Span


def test_span_inside_panel_is_valid():
    record = ReviewRecord(
        id="a",
        panels=[Panel(role="text", label="t", text="hello", spans=[Span(0, 5, "loss")])],
    )
    record.validate()


def test_span_outside_panel_is_rejected():
    record = ReviewRecord(
        id="a",
        panels=[Panel(role="text", label="t", text="hello", spans=[Span(2, 9, "loss")])],
    )
    with pytest.raises(ValueError, match="outside panel"):
        record.validate()


def test_empty_id_is_rejected():
    with pytest.raises(ValueError, match="id"):
        ReviewRecord(id="").validate()


def test_score_round_trip():
    score = Score(model="m", value=0.5, scale="0-1", comparable=False)
    assert score.to_dict()["comparable"] is False
