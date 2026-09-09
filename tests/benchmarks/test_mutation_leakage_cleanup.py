"""tests/benchmarks/test_mutation_leakage_cleanup.py — Mutation Tests for Leak-Free Extraction.

Verifies PR F.7A Semantic Leakage Cleanup:
1. Changing source drawing numbers changes predictions
2. Removing source numbers removes predictions
3. A synthetic unknown project with different counts/dimensions produces those exact new values
4. Keyword presence alone is insufficient to emit a known benchmark quantity
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import fitz
import pytest

from pb_planreader_pdf_extractor import (
    ExtractedPrediction,
    GenericPlanReaderExtractor,
)


def _create_mock_pdf(tmp_path: Path, filename: str, pages_text: list[str]) -> Path:
    pdf_path = tmp_path / filename
    doc = fitz.open()
    for txt in pages_text:
        page = doc.new_page(width=842, height=595)
        page.insert_text((50, 50), txt)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_mutation_1_changing_source_drawing_numbers_changes_predictions(tmp_path: Path) -> None:
    """Proves that changing figured numbers and counts in the drawing alters predictions proportionally."""
    extractor = GenericPlanReaderExtractor()

    # Drawing A: 12m x 6m, 6 trusses, 2 window callouts
    text_a = (
        "GROUND FLOOR PLAN\n"
        "SCALE 1:100\n"
        "DRAWING NO: AD-01\n"
        "12,000 x 6,000\n"
        "TRUSS T1 (6 No.)\n"
        "WINDOW SCHEDULE\n"
        "W17 3,000 x 1,200 mm 2 No. steel casement window\n"
        "D.P.C.\n"
    )
    pdf_a = _create_mock_pdf(tmp_path, "draw_a.pdf", [text_a])
    preds_a = {p.tag: p for p in extractor.extract_from_pdf(pdf_a)}

    assert preds_a["floor_screed"].quantity == 72.0  # 12 * 6
    # Gross wall: 2 * (12 + 6) * 2.8 = 100.8. Deductions: 2 * (3.0 * 1.2) = 7.2. Net wall: 93.6 SM
    assert preds_a["perimeter_walling"].quantity == 93.6
    assert preds_a["perimeter_walling"].metadata["gross_area_m2"] == 100.8
    assert preds_a["perimeter_walling"].metadata["total_deducted_opening_area_m2"] == 7.2
    assert preds_a["roof_trusses"].quantity == 6.0
    assert preds_a["damp_proof_course"].quantity == 36.0  # 2 * (12 + 6)
    assert preds_a["W17"].quantity == 2.0

    # Mutated Drawing B: 18m x 9m, 11 trusses, 4 window callouts
    text_b = (
        "GROUND FLOOR PLAN\n"
        "SCALE 1:100\n"
        "DRAWING NO: AD-01\n"
        "18,000 x 9,000\n"
        "TRUSS T1 (11 No.)\n"
        "WINDOW SCHEDULE\n"
        "W17 3,000 x 1,200 mm 4 No. steel casement window\n"
        "D.P.C.\n"
    )
    pdf_b = _create_mock_pdf(tmp_path, "draw_b.pdf", [text_b])
    preds_b = {p.tag: p for p in extractor.extract_from_pdf(pdf_b)}

    assert preds_b["floor_screed"].quantity == 162.0  # 18 * 9
    # Gross wall: 2 * (18 + 9) * 2.8 = 151.2. Deductions: 4 * (3.0 * 1.2) = 14.4. Net wall: 136.8 SM
    assert preds_b["perimeter_walling"].quantity == 136.8
    assert preds_b["perimeter_walling"].metadata["gross_area_m2"] == 151.2
    assert preds_b["perimeter_walling"].metadata["total_deducted_opening_area_m2"] == 14.4
    assert preds_b["roof_trusses"].quantity == 11.0
    assert preds_b["damp_proof_course"].quantity == 54.0  # 2 * (18 + 9)
    assert preds_b["W17"].quantity == 4.0

    # Predictions strictly changed based on drawing numbers
    assert preds_a["floor_screed"].quantity != preds_b["floor_screed"].quantity
    assert preds_a["perimeter_walling"].quantity != preds_b["perimeter_walling"].quantity
    assert preds_a["roof_trusses"].quantity != preds_b["roof_trusses"].quantity
    assert preds_a["W17"].quantity != preds_b["W17"].quantity


def test_mutation_2_removing_source_numbers_removes_predictions(tmp_path: Path) -> None:
    """Proves that keywords alone without figured numbers/counts produce ZERO predictions."""
    extractor = GenericPlanReaderExtractor()

    # Keywords present, but absolutely zero numbers or figured counts
    unfigured_text = (
        "GROUND FLOOR PLAN\n"
        "DRAWING TITLE: GENERAL LAYOUT\n"
        "verandah finished in screed\n"
        "TRUSS over roof structure\n"
        "steel casement windows with glass\n"
        "mild steel panelled door\n"
        "chalkboard on front wall\n"
        "circular hollow section verandah pillar\n"
        "D.P.C. under masonry walling\n"
        "polythene D.P.M. under bed\n"
        "fabric mesh A142 in floor bed\n"
        "pitched roof with degree slope\n"
        "permanent vents over openings\n"
    )
    pdf_unfigured = _create_mock_pdf(tmp_path, "unfigured.pdf", [unfigured_text])
    preds = extractor.extract_from_pdf(pdf_unfigured)

    # Must produce NO predictions because there are zero drawing dimensions/counts
    pred_tags = {p.tag for p in preds}
    assert "floor_screed" not in pred_tags
    assert "perimeter_walling" not in pred_tags
    assert "roof_trusses" not in pred_tags
    assert "W1" not in pred_tags
    assert "W2" not in pred_tags
    assert "steel_casement_windows" not in pred_tags
    assert "D1" not in pred_tags
    assert "doors_complete" not in pred_tags
    assert "damp_proof_course" not in pred_tags
    assert "substructure_bed_dpm" not in pred_tags
    assert "substructure_a142_mesh" not in pred_tags
    assert "gable_walling" not in pred_tags
    assert "verandah_pillars" not in pred_tags
    assert len(preds) == 0


def test_mutation_3_synthetic_unknown_project_produces_exact_new_values(tmp_path: Path) -> None:
    """Proves an unknown project with novel dimensions produces exact deterministic geometric values."""
    extractor = GenericPlanReaderExtractor()

    sheet_1 = (
        "GROUND FLOOR PLAN\n"
        "SCALE 1:100\n"
        "DRAWING NO: ARC-01\n"
        "24,000 x 12,000\n"
        "2,000mm wide verandah\n"
        "20 degree roof pitch\n"
        "WINDOW & DOOR SCHEDULE\n"
        "W17 3,000 x 1,200 mm 3 No. steel casement window\n"
        "D12 1,000 x 2,100 mm 2 No. timber door\n"
        "2,400mm x 1,200mm black board\n"
    )
    sheet_2 = (
        "BUILDING SECTION A-A\n"
        "SCALE 1:50\n"
        "DRAWING NO: STR-01\n"
        "TRUSS T1 (16 No.)\n"
        "PV\nPV\nPV\nPV\nPV\nPV\nPV\nPV\n"
        "D.P.C.\n"
        "1000 gauge polythene D.P.M.\n"
        "mesh A142\n"
        "plaster and paint to finish internally\n"
        "key pointing to exposed masonry\n"
    )
    pdf_synth = _create_mock_pdf(tmp_path, "synthetic_project.pdf", [sheet_1, sheet_2])
    preds = {p.tag: p for p in extractor.extract_from_pdf(pdf_synth)}

    # Room: 24 x 12 = 288. Verandah: 24 x 2.0 = 48. Total: 336.0 SM
    assert preds["floor_screed"].quantity == 336.0
    # Perimeter: 2 * (24 + 12) = 72.0m. Gross wall: 72 * 2.8 = 201.6 SM
    # Deductions: 3 * (3.0 * 1.2) + 2 * (1.0 * 2.1) = 10.8 + 4.2 = 15.0 m². Net wall: 186.6 SM
    assert preds["perimeter_walling"].quantity == 186.6
    assert preds["perimeter_walling"].metadata["gross_area_m2"] == 201.6
    assert preds["perimeter_walling"].metadata["total_deducted_opening_area_m2"] == 15.0
    # DPC: exactly perimeter 72.0m (NO 67.0 fallback)
    assert preds["damp_proof_course"].quantity == 72.0
    # DPM & Mesh: exactly floor area 336.0 SM (NO 1.06 multiplier)
    assert preds["substructure_bed_dpm"].quantity == 336.0
    assert preds["substructure_a142_mesh"].quantity == 336.0
    # Trusses: exactly 16.0 NO (parsed from text)
    assert preds["roof_trusses"].quantity == 16.0
    # Vents: exactly 8.0 NO (8 PV callouts)
    assert preds["brick_vents"].quantity == 8.0
    # Windows: exactly 3.0 NO with parsed dimensions [3000, 1200]
    assert preds["W17"].quantity == 3.0
    assert preds["W17"].dimensions == [3000.0, 1200.0]
    # Doors: exactly 2.0 NO with parsed dimensions [1000, 2100]
    assert preds["D12"].quantity == 2.0
    assert preds["D12"].dimensions == [1000.0, 2100.0]
    # Chalkboard: parsed dimensions [2400, 1200]
    assert preds["chalkboard"].dimensions == [2400.0, 1200.0]

    # Gable walling: 20 degree pitch, W=12m -> h = 6 * tan(20 deg) = 2.1838m -> area = 12 * 2.1838 = 26.21 SM
    expected_gable = round(12.0 * 6.0 * math.tan(math.radians(20.0)), 2)
    assert preds["gable_walling"].quantity == expected_gable


def test_mutation_4_keyword_presence_alone_is_insufficient_to_emit_benchmark_quantity(tmp_path: Path) -> None:
    """Proves that passing benchmark-specific keywords without drawing evidence never emits benchmark quantities."""
    extractor = GenericPlanReaderExtractor()

    # Craft text using benchmark keywords but zero evidence numbers
    trap_text = (
        "ELEVATION E-01\n"
        "SECTION A-A\n"
        "tenders_ke_kstvet_cbc_classroom tenders_ke_murera_science_lab\n"
        "steel casement windows, W1, W2, mild steel panelled double door, D1\n"
        "verandah, circular hollow section pillars\n"
        "TRUSS T1, masonry piers, foundation layout\n"
        "damp proof course, dpc, polythene dpm, b.r.c mesh a142\n"
        "chalkboard, blackboard, blockboard\n"
        "external key pointing, external render, internal plaster, internal paint\n"
    )
    pdf_trap = _create_mock_pdf(tmp_path, "trap.pdf", [trap_text])
    preds = extractor.extract_from_pdf(pdf_trap)

    # Ensure no benchmark values were emitted
    banned_quantities = {67.0, 196.0, 208.0, 97.0, 132.0, 58.0, 13.0, 4.0}
    for p in preds:
        assert p.quantity not in banned_quantities, (
            f"Prediction {p.tag} emitted benchmark quantity {p.quantity} from keyword trap!"
        )
    assert len(preds) == 0
