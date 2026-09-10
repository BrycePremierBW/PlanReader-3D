"""tests/benchmarks/test_mutation_internal_face_area_wall_thickness_wiring.py

Mutation/red-team suite for GenericPlanReaderExtractor's wiring of
pb_dimension_chain_evidence_extractor's corroborated wall-thickness
resolution into internal_plaster/internal_paint: these must switch from
the external-wall-area proxy to a genuine internal-face-area derivation
only when wall-thickness evidence is corroborated, must fall back to the
unchanged proxy behaviour otherwise, and must never let wall-thickness
resolution manufacture a separate external key-pointing quantity. A
keyword-only pointing note has no measured extent and therefore remains
absent in both paths. Every dimension value is synthetic and invented for
this test.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _build_pdf(tmp_path: Path, *, with_wall_thickness_evidence: bool) -> Path:
    doc = fitz.open()
    plan_lines = [
        "GROUND FLOOR PLAN",
        "SCALE 1:100",
        "10,000",
        "6,000",
        "12 mm two-coat plaster to internal walls",
        "Extra over walling for key pointing externally",
    ]
    if with_wall_thickness_evidence:
        # Two independent, corroborating wall-enclosed dimension chains
        # (thickness 150mm each side, distinct internal spans) placed as
        # separate lines so they land in separate y-bands.
        plan_lines.append("150 9,700 150")
        plan_lines.append("150 5,700 150")
    plan_page = doc.new_page()
    plan_page.insert_text((72, 72), "\n".join(plan_lines), fontsize=11)
    pdf_path = tmp_path / "synthetic_internal_face.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _extract(tmp_path: Path, *, with_wall_thickness_evidence: bool) -> dict:
    pdf_path = _build_pdf(tmp_path, with_wall_thickness_evidence=with_wall_thickness_evidence)
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(pdf_path)
    return {p.tag: p for p in preds}


class TestInternalFaceAreaWiring:
    def test_no_corroborated_thickness_keeps_unchanged_proxy_behaviour(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, with_wall_thickness_evidence=False)
        wall = pred_map["perimeter_walling"]
        plaster = pred_map["internal_plaster"]
        assert plaster.quantity == wall.quantity
        assert plaster.confidence == 0.5
        assert plaster.metadata["derivation"] == "external_wall_area_proxy_no_internal_face_evidence"

    def test_corroborated_thickness_produces_a_genuinely_smaller_internal_face_area(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, with_wall_thickness_evidence=True)
        wall = pred_map["perimeter_walling"]
        plaster = pred_map["internal_plaster"]
        paint = pred_map["internal_paint"]

        assert plaster.metadata["derivation"] == "internal_face_area_from_resolved_wall_thickness"
        assert plaster.metadata["wall_thickness_m"] == 0.15
        # 0.65, not 0.8: this fixture provides genuine wall-thickness
        # evidence but no level-datum height evidence (F.23A), so the
        # height itself is still only the assumed default -- the result
        # must not be presented at full confidence on that basis alone.
        assert plaster.confidence == 0.65
        assert plaster.metadata["wall_height_authority"] == "provisional"
        # Internal perimeter = external perimeter - 8 * thickness; a real,
        # strictly smaller internal face area than the external wall's.
        expected_internal_perimeter = wall.dimensions[0] - 8 * 0.15
        expected_internal_area = round(expected_internal_perimeter * wall.dimensions[1], 4)
        assert plaster.quantity == pytest.approx(expected_internal_area)
        assert plaster.quantity < wall.quantity
        assert paint.quantity == plaster.quantity

    def test_keyword_only_external_key_pointing_stays_absent_across_internal_face_paths(self, tmp_path: Path) -> None:
        pred_map_without = _extract(tmp_path, with_wall_thickness_evidence=False)
        pred_map_with = _extract(tmp_path, with_wall_thickness_evidence=True)
        assert "external_key_pointing" not in pred_map_without
        assert "external_key_pointing" not in pred_map_with
        assert "perimeter_walling" in pred_map_without
        assert "perimeter_walling" in pred_map_with
