"""tests/benchmarks/test_mutation_wall_derived_finish_confidence.py

Mutation/red-team suite for a generic fail-closed fix in
GenericPlanReaderExtractor.extract_from_pdf(): internal_plaster,
internal_paint, and external_key_pointing are keyword-triggered and copy
their quantity verbatim from perimeter_walling's own (independently,
geometrically measured) net wall area -- this extractor has no
wall-thickness evidence, so it cannot compute a true internal-face area
distinct from the external one. Presenting a blind copy at the same
confidence as an independent measurement is an honesty failure, not merely
an accuracy one: it lets a "derived, unverified" quantity masquerade as
equally authoritative as a directly measured one.

Root-cause evidence (from running the real extractor against a real, if
diagnostic-only, benchmark PDF during development): perimeter_walling,
internal_plaster, internal_paint, and external_key_pointing all reported
the identical opening-deducted net wall area at confidence 0.82-0.88, with
no signal anywhere that three of those four numbers were unverified
copies rather than independent measurements. This suite locks in the fix:
confidence is reduced and a `derivation` + `note` metadata pair explains
why, for every one of the copied predictions -- while the source
prediction (perimeter_walling) and any independently-measured prediction
(floor_screed) keep their original confidence untouched. No specific
project's expected quantities are read or asserted anywhere in this file;
every dimension used is synthetic and chosen only to exercise this code
path validly.
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

    def test_external_key_pointing_is_marked_as_keyword_triggered(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, include_plaster=False, include_key_pointing=True)
        assert "external_key_pointing" in pred_map
        pred = pred_map["external_key_pointing"]
        assert pred.confidence == 0.5
        assert pred.confidence < pred_map["perimeter_walling"].confidence
        assert pred.metadata["derivation"] == "external_wall_area_copy_keyword_triggered"

    def test_derived_quantities_still_equal_the_source_wall_area_unchanged(self, tmp_path: Path) -> None:
        # The fix must only ever change confidence/metadata honesty, never
        # the quantity itself -- benchmark scoring must be byte-for-byte
        # unaffected by this change.
        pred_map = _extract(tmp_path, include_plaster=True, include_key_pointing=True)
        wall_qty = pred_map["perimeter_walling"].quantity
        assert pred_map["internal_plaster"].quantity == wall_qty
        assert pred_map["internal_paint"].quantity == wall_qty
        assert pred_map["external_key_pointing"].quantity == wall_qty

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
