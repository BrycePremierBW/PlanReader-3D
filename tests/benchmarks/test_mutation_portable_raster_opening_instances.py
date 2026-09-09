from __future__ import annotations

from pb_portable_raster_ocr import (
    RasterOpeningInstanceEvidence,
    deduplicate_tiled_ocr_lines,
    extract_opening_instance_evidence,
    resolve_cross_page_opening_instances,
)


def _line(text: str, x: float, y: float, confidence: float = 0.97):
    return {
        "text": text,
        "bounding_box": [x, y, x + 24.0, y + 12.0],
        "confidence": confidence,
    }


def test_overlapping_tile_duplicates_do_not_inflate_count() -> None:
    lines = [
        _line("W-17", 100, 100),
        _line("W-17", 102, 101, 0.92),  # same physical label from overlap tile
        _line("W-17", 240, 100),       # separate physical placement
        _line("D-4", 350, 100),
    ]
    evidence = {e.tag: e for e in extract_opening_instance_evidence(lines, source_page=3)}
    assert evidence["W17"].quantity == 2
    assert evidence["D4"].quantity == 1


def test_mutating_one_physical_tag_changes_only_that_count() -> None:
    baseline = [_line("W3", 20, 20), _line("W3", 120, 20), _line("D2", 20, 80)]
    mutated = baseline + [_line("W3", 220, 20)]
    before = {e.tag: e.quantity for e in extract_opening_instance_evidence(baseline, source_page=1)}
    after = {e.tag: e.quantity for e in extract_opening_instance_evidence(mutated, source_page=1)}
    assert before == {"D2": 1, "W3": 2}
    assert after == {"D2": 1, "W3": 3}


def test_singleton_type_legend_fails_closed() -> None:
    lines = [_line("W1", 20, 20), _line("W2", 20, 50), _line("D1", 20, 80)]
    assert extract_opening_instance_evidence(lines, source_page=1) == []


def test_aliases_normalize_but_separate_placements_remain_distinct() -> None:
    lines = [
        _line("W-03", 20, 20),
        _line("WINDOW 3", 120, 20),
        _line("DR-2", 20, 80),
    ]
    evidence = {e.tag: e for e in extract_opening_instance_evidence(lines, source_page=7)}
    assert evidence["W3"].quantity == 2
    assert evidence["W3"].trade_type == "windows"
    assert evidence["D2"].quantity == 1


def test_low_confidence_tag_is_not_firm_instance_evidence() -> None:
    lines = [_line("W8", 20, 20, 0.99), _line("W8", 120, 20, 0.61)]
    assert extract_opening_instance_evidence(lines, source_page=1) == []


def test_schedule_row_with_explicit_quantity_is_not_recounted_as_one_instance() -> None:
    lines = [
        _line("W5 - 1800 x 1200 - 7 No.", 20, 20),
        _line("D2 - 900 x 2100 - 3 No.", 20, 50),
    ]
    assert extract_opening_instance_evidence(lines, source_page=1) == []


def test_cross_page_agreement_corroborates_without_summing() -> None:
    evidence = [
        RasterOpeningInstanceEvidence("W9", "windows", 4, 2, 0.91, ()),
        RasterOpeningInstanceEvidence("W9", "windows", 4, 5, 0.95, ()),
    ]
    resolved = resolve_cross_page_opening_instances(evidence)
    assert len(resolved) == 1
    assert resolved[0].quantity == 4
    assert resolved[0].source_page == 5


def test_cross_page_disagreement_fails_closed() -> None:
    evidence = [
        RasterOpeningInstanceEvidence("D7", "doors", 2, 2, 0.96, ()),
        RasterOpeningInstanceEvidence("D7", "doors", 3, 4, 0.97, ()),
    ]
    assert resolve_cross_page_opening_instances(evidence) == []


def test_dedup_requires_matching_text() -> None:
    lines = [_line("W1", 20, 20), _line("W2", 20, 20)]
    deduped = deduplicate_tiled_ocr_lines(lines)
    assert {row["text"] for row in deduped} == {"W1", "W2"}
