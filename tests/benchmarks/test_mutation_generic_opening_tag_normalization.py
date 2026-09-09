from __future__ import annotations

from pb_opening_tag_normalization import (
    find_explicit_opening_tags,
    normalize_opening_tag,
    opening_trade_from_tag,
)


def test_nominal_window_aliases_normalize_generically() -> None:
    for raw in ("W7", "W-07", "W 007", "WINDOW 7", "WIN_07"):
        got = normalize_opening_tag(raw)
        assert got is not None
        assert got.tag == "W7"
        assert got.trade_type == "windows"


def test_nominal_door_aliases_normalize_generically() -> None:
    for raw in ("D12", "D-012", "DOOR 12", "DR_12"):
        got = normalize_opening_tag(raw)
        assert got is not None
        assert got.tag == "D12"
        assert got.trade_type == "doors"


def test_mutating_documented_number_mutates_identity() -> None:
    assert normalize_opening_tag("W17").tag == "W17"
    assert normalize_opening_tag("W18").tag == "W18"
    assert normalize_opening_tag("D31").tag == "D31"


def test_dimensions_without_identity_never_synthesize_tag() -> None:
    assert normalize_opening_tag("2900 x 900 mm steel casement window") is None
    assert normalize_opening_tag("1000 x 2100 mm timber batten door") is None


def test_non_opening_engineering_tags_are_not_misclassified() -> None:
    for raw in ("D8-03-200 C/C", "DWG 12", "R12", "T1"):
        assert normalize_opening_tag(raw) is None
        assert opening_trade_from_tag(raw) is None


def test_find_explicit_tags_preserves_source_identity_and_order() -> None:
    got = find_explicit_opening_tags("Window W-04 adjacent to DOOR 12 and WIN 5")
    assert [(x.tag, x.trade_type) for x in got] == [
        ("W4", "windows"),
        ("D12", "doors"),
        ("W5", "windows"),
    ]


def test_removing_explicit_identity_removes_normalized_prediction_input() -> None:
    assert find_explicit_opening_tags("W-27 1800 x 1200")
    assert find_explicit_opening_tags("1800 x 1200") == []
