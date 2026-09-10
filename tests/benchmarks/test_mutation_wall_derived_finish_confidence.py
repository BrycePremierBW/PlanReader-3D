"""tests/benchmarks/test_mutation_wall_derived_finish_confidence.py

Mutation/red-team suite for GenericPlanReaderExtractor's wall-derived finish
behaviour. Internal plaster/paint may still use the explicitly flagged external
wall-area proxy when no independent internal-face geometry resolves, but an
external key-pointing keyword alone must not create a measured quantity at all.
A finish label can establish scope; it cannot establish extent.

Every dimension used here is synthetic and chosen only to exercise the generic
production path. No benchmark expected quantity, tolerance, scorer, project ID,
or project-specific constant is read or asserted by this file.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _make_synthetic_plan_pdf(tmp_path: Path, *, include_plaster: bool, include_key_pointing: bool) -> Path:
    """A minimal single-page synthetic floor-plan PDF: a figured envelope
    (11.2m x 6.4m, chosen only to satisfy _detect_outer_envelope's
    plausibility checks -- not derived from, or matching, any real
    project) plus optional finish-note keywords."""
    doc = fitz.open()
    page = doc.new_page()

    lines = [
        "GROUND FLOOR PLAN",
        "SCALE 1:100",
        "11,200",
        "6,400",
    ]
    if include_plaster:
        lines.append("TWO-COAT PLASTER TO INTERNAL WALLS")
    if include_key_pointing:
        lines.append("KEY POINTING EXTERNALLY TO EXPOSED BLOCKWORK")

    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    pdf_path = tmp_path / "synthetic_plan.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _extract(tmp_path: Path, **kwargs) -> dict:
    pdf_path = _make_synthetic_plan_pdf(tmp_path, **kwargs)
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(pdf_path)
    return {p.tag: p for p in preds}


class TestDerivedFinishQuantitiesAreHonestlyLowConfidence:
    def test_perimeter_walling_keeps_its_own_independently_measured_confidence(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, include_plaster=True, include_key_pointing=True)
        assert "perimeter_walling" in pred_map
        wall = pred_map["perimeter_walling"]
        assert wall.confidence == 0.6
        assert not (wall.metadata or {}).get("derivation")

    def test_internal_plaster_and_paint_are_marked_as_a_derived_proxy(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, include_plaster=True, include_key_pointing=False)
        assert "internal_plaster" in pred_map
        assert "internal_paint" in pred_map
        for tag in ("internal_plaster", "internal_paint"):
            pred = pred_map[tag]
            assert pred.confidence == 0.5
            assert pred.confidence < pred_map["perimeter_walling"].confidence
            assert pred.metadata["derivation"] == "external_wall_area_proxy_no_internal_face_evidence"
            assert "internal face area" in pred.metadata["note"]

    def test_external_key_pointing_keyword_without_extent_fails_closed(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, include_plaster=False, include_key_pointing=True)
        assert "perimeter_walling" in pred_map
        assert "external_key_pointing" not in pred_map

    def test_supported_proxy_quantities_still_equal_the_source_wall_area(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, include_plaster=True, include_key_pointing=True)
        wall_qty = pred_map["perimeter_walling"].quantity
        assert pred_map["internal_plaster"].quantity == wall_qty
        assert pred_map["internal_paint"].quantity == wall_qty
        assert "external_key_pointing" not in pred_map

    def test_neither_finish_keyword_present_emits_no_derived_predictions(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, include_plaster=False, include_key_pointing=False)
        assert "internal_plaster" not in pred_map
        assert "internal_paint" not in pred_map
        assert "external_key_pointing" not in pred_map
        # The independently measured prediction is unaffected either way.
        assert pred_map["perimeter_walling"].confidence == 0.6

    def test_floor_screed_is_independently_measured_and_untouched(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, include_plaster=True, include_key_pointing=True)
        floor = pred_map["floor_screed"]
        assert floor.confidence == 0.92
        assert not (floor.metadata or {}).get("derivation")
