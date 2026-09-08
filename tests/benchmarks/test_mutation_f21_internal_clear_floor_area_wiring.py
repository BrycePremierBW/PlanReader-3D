"""tests/benchmarks/test_mutation_f21_internal_clear_floor_area_wiring.py

Mutation/red-team suite proving GenericPlanReaderExtractor's wiring of
pb_internal_clear_floor_area into floor_screed: internal clear
floor-finish area only replaces the outer-envelope basis when a genuine,
corroborated wall thickness resolves (F.15); the structural surface bed,
DPM, and A142 mesh always keep the outer/gross footprint basis
regardless. Every dimension in this file is synthetic and invented for
this test -- no benchmark IDs, expected quantities, source paths, or
project-specific constants.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _make_pdf(tmp_path: Path, name: str, lines: list[str]) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    pdf_path = tmp_path / name
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _plan_lines(*, dims: list[str], extra: list[str] | None = None) -> list[str]:
    return [
        "GROUND FLOOR PLAN",
        "SCALE 1:100",
        *dims,
        *(extra or []),
    ]


class TestGenuineClearAreaResolution:
    def test_corroborated_thickness_shrinks_floor_finish_by_the_rectangle_formula(self, tmp_path: Path) -> None:
        # Two independent, corroborating wall-enclosed chains (150mm
        # thickness each side, distinct internal spans), plus an outer
        # envelope of 12,000 x 8,000mm elsewhere on the same page. Internal
        # span values are deliberately kept well under 5.0m so they cannot
        # themselves compete as outer-envelope candidates in
        # _detect_outer_envelope's own "two largest dimensions" heuristic.
        pdf_path = _make_pdf(tmp_path, "clear_area.pdf", _plan_lines(dims=[
            "12,000", "8,000",
            "150 4,700 150",
            "150 3,200 150",
        ]))
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        pred_map = {p.tag: p for p in preds}
        fs = pred_map["floor_screed"]

        assert fs.metadata["derivation"] == "internal_clear_area_from_resolved_wall_thickness"
        assert fs.metadata["wall_thickness_m"] == 0.15
        expected_clear = round((12.0 - 0.3) * (8.0 - 0.3), 4)
        assert fs.quantity == pytest.approx(expected_clear)
        assert fs.confidence == 0.95
        # Outer/gross area is preserved separately, unchanged.
        assert fs.metadata["outer_envelope_area_m2"] == pytest.approx(12.0 * 8.0)
        assert fs.metadata["gross_floor_area_m2"] == pytest.approx(12.0 * 8.0)

    def test_mutating_thickness_changes_result_deterministically(self, tmp_path: Path) -> None:
        thinner = _make_pdf(tmp_path, "thinner.pdf", _plan_lines(dims=[
            "10,000", "6,000", "100 4,900 100", "100 3,400 100",
        ]))
        thicker = _make_pdf(tmp_path, "thicker.pdf", _plan_lines(dims=[
            "10,000", "6,000", "200 4,700 200", "200 3,200 200",
        ]))
        area_thin = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(thinner)}["floor_screed"].quantity
        area_thick = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(thicker)}["floor_screed"].quantity
        assert area_thin != area_thick
        assert area_thick < area_thin


class TestFailClosedFallback:
    def test_no_thickness_evidence_leaves_area_byte_for_byte_unchanged(self, tmp_path: Path) -> None:
        pdf_path = _make_pdf(tmp_path, "no_thickness.pdf", _plan_lines(dims=["10,000", "6,000"]))
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        pred_map = {p.tag: p for p in preds}
        fs = pred_map["floor_screed"]

        assert fs.quantity == pytest.approx(10.0 * 6.0)
        assert fs.confidence == 0.92
        assert "derivation" not in fs.metadata
        assert "outer_envelope_area_m2" not in fs.metadata

    def test_conflicting_unresolved_thickness_leaves_area_unchanged(self, tmp_path: Path) -> None:
        # A single, uncorroborated wall-enclosed chain -- F.15 requires
        # >=2 independent chains to agree before resolving a thickness.
        pdf_path = _make_pdf(tmp_path, "single_chain.pdf", _plan_lines(dims=[
            "10,000", "6,000", "150 4,700 150",
        ]))
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        pred_map = {p.tag: p for p in preds}
        fs = pred_map["floor_screed"]

        assert fs.quantity == pytest.approx(10.0 * 6.0)
        assert fs.confidence == 0.92
        assert "derivation" not in fs.metadata

    # "Excessive thickness fails closed" is proven at the pure-helper
    # level (test_mutation_internal_clear_floor_area.py) rather than
    # here: _detect_outer_envelope's own plausibility floor (paired
    # candidates need each dimension >=~3-5m to be considered at all)
    # makes an outer envelope small enough for a realistic, F.13-bounded
    # wall thickness (max 0.4m) to force a non-positive clear dimension
    # structurally unreachable through the full extraction pipeline --
    # not a gap in this wiring, a genuine additional layer of protection.

    def test_murera_style_degenerate_repeated_chain_remains_rejected(self, tmp_path: Path) -> None:
        # Real false-positive shape (F.15): a repeated identical-value
        # chain (e.g. rebar spacing) must never corroborate into a
        # resolved thickness, so floor_screed stays on the gross basis.
        pdf_path = _make_pdf(tmp_path, "degenerate.pdf", _plan_lines(dims=[
            "10,000", "6,000", "200 200 200", "200 200 200 200",
        ]))
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        pred_map = {p.tag: p for p in preds}
        fs = pred_map["floor_screed"]

        assert fs.quantity == pytest.approx(10.0 * 6.0)
        assert "derivation" not in fs.metadata


class TestSubstructureBasisUnaffected:
    def test_dpm_and_mesh_keep_the_outer_footprint_basis_when_finish_uses_clear_area(self, tmp_path: Path) -> None:
        pdf_path = _make_pdf(tmp_path, "dpm_mesh_with_clear_area.pdf", _plan_lines(
            dims=["12,000", "8,000", "150 9,700 150", "150 5,700 150"],
            extra=["1000 gauge polythene D.P.M. and B.R.C. mesh A142 reinforcement under bed."],
        ))
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        pred_map = {p.tag: p for p in preds}

        fs = pred_map["floor_screed"]
        assert fs.metadata["derivation"] == "internal_clear_area_from_resolved_wall_thickness"
        clear_area = fs.quantity
        outer_area = fs.metadata["outer_envelope_area_m2"]
        assert clear_area < outer_area

        assert "substructure_bed_dpm" in pred_map
        assert "substructure_a142_mesh" in pred_map
        assert pred_map["substructure_bed_dpm"].quantity == pytest.approx(outer_area)
        assert pred_map["substructure_a142_mesh"].quantity == pytest.approx(outer_area)
        # Neither ever equals the shrunk clear-finish area.
        assert pred_map["substructure_bed_dpm"].quantity != pytest.approx(clear_area)
        assert pred_map["substructure_a142_mesh"].quantity != pytest.approx(clear_area)
