"""tests/benchmarks/test_mutation_structural_pillar_extraction_wiring.py

Mutation/red-team suite for GenericPlanReaderExtractor's wiring of
pb_structural_bay_pillar_count.py into the real extraction path: a
structural_columns prediction is only emitted when BOTH a genuine,
unambiguous repeated-bay dimension pattern AND a support-element keyword
are present on the same page. Every dimension value is synthetic and
invented for this test file.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _make_pillar_pdf(tmp_path: Path, *, include_keyword: bool, dims: list[str]) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    lines = ["GROUND FLOOR PLAN", "SCALE 1:100", *dims]
    if include_keyword:
        lines.append("300 x 300mm CONCRETE COLUMNS TO VERANDAH")
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    pdf_path = tmp_path / "synthetic_pillars.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _extract(tmp_path: Path, **kwargs) -> dict:
    pdf_path = _make_pillar_pdf(tmp_path, **kwargs)
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(pdf_path)
    return {p.tag: p for p in preds}


class TestStructuralColumnWiring:
    def test_keyword_plus_genuine_bay_chain_emits_a_column_count(self, tmp_path: Path) -> None:
        # 4 near-equal bays of ~3.30m -> 5 supports.
        pred_map = _extract(
            tmp_path, include_keyword=True,
            dims=["3,300", "3,350", "3,280", "3,320"],
        )
        assert "structural_columns" in pred_map
        pred = pred_map["structural_columns"]
        assert pred.trade_type == "structure"
        assert pred.unit == "NO"
        assert pred.quantity == 5.0
        assert pred.metadata["bay_count"] == 4
        assert pred.confidence == 0.7

    def test_keyword_without_a_genuine_bay_chain_emits_nothing(self, tmp_path: Path) -> None:
        # A single dimension, or genuinely dissimilar ones, is not a bay
        # chain -- the keyword alone must never be enough.
        pred_map = _extract(tmp_path, include_keyword=True, dims=["9,850"])
        assert "structural_columns" not in pred_map

    def test_genuine_bay_chain_without_the_keyword_emits_nothing(self, tmp_path: Path) -> None:
        # A repeated dimension pattern on its own (e.g. window spacing) is
        # not evidence of a structural support line without the keyword.
        pred_map = _extract(
            tmp_path, include_keyword=False,
            dims=["3,300", "3,350", "3,280", "3,320"],
        )
        assert "structural_columns" not in pred_map

    def test_ambiguous_multiple_candidate_runs_are_left_unresolved(self, tmp_path: Path) -> None:
        # Two distinct, unrelated repeated-dimension patterns on the same
        # page (e.g. a structural grid at ~3.3m and separately-repeated
        # ~2.1m spans) -- genuinely ambiguous which one is the support
        # line; must not guess by picking either.
        pred_map = _extract(
            tmp_path, include_keyword=True,
            dims=["3,300", "3,300", "3,300", "9,600", "2,100", "2,100"],
        )
        assert "structural_columns" not in pred_map

    def test_derivation_metadata_is_fully_traceable(self, tmp_path: Path) -> None:
        pred_map = _extract(
            tmp_path, include_keyword=True,
            dims=["4,000", "4,000", "4,000"],
        )
        pred = pred_map["structural_columns"]
        assert pred.metadata["derivation"] == "bay_count_plus_one_from_repeated_dimension_chain"
        assert pred.metadata["bay_spans_m"] == [4.0, 4.0, 4.0]
        assert pred.quantity == 4.0  # 3 bays + 1
