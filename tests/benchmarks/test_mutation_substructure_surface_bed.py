"""tests/benchmarks/test_mutation_substructure_surface_bed.py

Mutation/red-team suite for GenericPlanReaderExtractor's substructure
surface-bed detection: a sibling prediction to the existing
substructure_bed_dpm / substructure_a142_mesh, sharing the same floor
area (tot_flr) but for the ground-bearing slab's own concrete rather
than its DPM or mesh reinforcement. Every dimension and note phrase in
this file is synthetic and invented for this test.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _make_pdf(tmp_path: Path, name: str, extra_note: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "GROUND FLOOR PLAN",
        "SCALE 1:100",
        "10,000",
        "6,000",
        extra_note,
    ]
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    pdf_path = tmp_path / name
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestSurfaceBedDetection:
    def test_rc_slab_on_hardcore_is_recognized(self) -> None:
        ex = GenericPlanReaderExtractor()
        assert ex._has_surface_bed_specification(
            "75mm thick R.C slab on well compacted hardcore on well compacted earth"
        )

    def test_surface_bed_with_blinding_is_recognized(self) -> None:
        ex = GenericPlanReaderExtractor()
        assert ex._has_surface_bed_specification(
            "125mm thick reinforced concrete surface bed on blinding layer"
        )

    def test_slab_term_alone_without_ground_context_is_rejected(self) -> None:
        # A roof or suspended slab mention must never be misread as a
        # ground-bearing surface bed just because "slab" appears.
        ex = GenericPlanReaderExtractor()
        assert not ex._has_surface_bed_specification(
            "150mm thick R.C slab at roof level, cantilevered over verandah"
        )

    def test_ground_context_alone_without_bed_term_is_rejected(self) -> None:
        ex = GenericPlanReaderExtractor()
        assert not ex._has_surface_bed_specification(
            "hardcore filling compacted in 150mm layers under paving"
        )

    def test_unrelated_text_is_rejected(self) -> None:
        ex = GenericPlanReaderExtractor()
        assert not ex._has_surface_bed_specification("steel casement windows with clear glass")


class TestSurfaceBedWiring:
    def test_genuine_evidence_produces_a_prediction_sharing_floor_area(self, tmp_path: Path) -> None:
        pdf_path = _make_pdf(
            tmp_path, "surface_bed.pdf",
            "75mm thick R.C slab on well compacted hardcore on well compacted earth to S.E detail.",
        )
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        pred_map = {p.tag: p for p in preds}
        assert "substructure_surface_bed" in pred_map
        bed = pred_map["substructure_surface_bed"]
        assert bed.trade_type == "structure"
        assert bed.unit == "SM"
        assert bed.confidence == 0.90
        assert bed.quantity == pred_map["floor_screed"].quantity

    def test_no_evidence_produces_no_prediction(self, tmp_path: Path) -> None:
        pdf_path = _make_pdf(tmp_path, "no_surface_bed.pdf", "General notes: nothing relevant here.")
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        pred_map = {p.tag: p for p in preds}
        assert "substructure_surface_bed" not in pred_map

    def test_dpm_and_mesh_evidence_do_not_trigger_surface_bed_on_their_own(self, tmp_path: Path) -> None:
        # DPM/mesh specification must remain independently gated -- the new
        # surface-bed sibling must not fire just because its neighbours did.
        pdf_path = _make_pdf(
            tmp_path, "dpm_mesh_only.pdf",
            "1000 gauge polythene D.P.M. and B.R.C. mesh A142 reinforcement under bed.",
        )
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        pred_map = {p.tag: p for p in preds}
        assert "substructure_bed_dpm" in pred_map
        assert "substructure_a142_mesh" in pred_map
        assert "substructure_surface_bed" not in pred_map
