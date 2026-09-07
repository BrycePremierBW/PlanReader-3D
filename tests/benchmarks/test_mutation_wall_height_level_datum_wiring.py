"""tests/benchmarks/test_mutation_wall_height_level_datum_wiring.py

Mutation/red-team suite for GenericPlanReaderExtractor's wiring of
pb_level_datum_extraction + pb_dimension_graph_constraint_engine.
resolve_wall_height() into the perimeter/wall-area computation: the
extractor must use a genuinely resolved level-datum height when the
drawing set provides one, and must fall back to the unchanged
default_ceiling_height_m behaviour, byte-for-byte, when it does not.
Every dimension and level value is synthetic and invented for this test.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _make_plan_pdf(tmp_path: Path, *, extra_lines: list[str]) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "GROUND FLOOR PLAN",
        "SCALE 1:100",
        "10,000",
        "6,000",
        *extra_lines,
    ]
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    pdf_path = tmp_path / "synthetic_plan.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_elevation_page(doc: "fitz.Document", *, roof: str, floor: str) -> None:
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        f"ELEVATION E-01\nSCALE 1:100\n{roof}\n{floor}",
        fontsize=11,
    )


def _extract(tmp_path: Path, *, with_level_evidence: bool) -> dict:
    doc = fitz.open()
    plan_page = doc.new_page()
    plan_page.insert_text(
        (72, 72),
        "GROUND FLOOR PLAN\nSCALE 1:100\n10,000\n6,000",
        fontsize=11,
    )
    if with_level_evidence:
        _make_elevation_page(doc, roof="Roof Level +3,150", floor="Ground floor +150")
    pdf_path = tmp_path / "synthetic_multi_page.pdf"
    doc.save(str(pdf_path))
    doc.close()
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(pdf_path)
    return {p.tag: p for p in preds}


class TestWallHeightLevelDatumWiring:
    def test_no_level_evidence_falls_back_to_unchanged_default_behaviour(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, with_level_evidence=False)
        wall = pred_map["perimeter_walling"]
        extractor = GenericPlanReaderExtractor()
        assert wall.dimensions[1] == extractor.default_ceiling_height_m
        assert wall.confidence == 0.88
        assert wall.metadata["wall_height_source"] == "default_ceiling_height_assumption"

    def test_genuine_level_evidence_overrides_the_default_height(self, tmp_path: Path) -> None:
        pred_map = _extract(tmp_path, with_level_evidence=True)
        wall = pred_map["perimeter_walling"]
        assert wall.dimensions[1] == 3.0  # 3.150 roof - 0.150 floor
        assert wall.confidence == 0.93
        assert wall.metadata["wall_height_source"] == "resolved_level_datum_evidence"
        perimeter_m = 2 * (10.0 + 6.0)
        assert wall.quantity == pytest.approx(round(perimeter_m * 3.0, 2))

    def test_one_sided_level_evidence_leaves_height_unresolved_and_falls_back(self, tmp_path: Path) -> None:
        doc = fitz.open()
        plan_page = doc.new_page()
        plan_page.insert_text(
            (72, 72),
            "GROUND FLOOR PLAN\nSCALE 1:100\n10,000\n6,000",
            fontsize=11,
        )
        _make_elevation_page(doc, roof="Roof Level +3,150", floor="")
        pdf_path = tmp_path / "one_sided.pdf"
        doc.save(str(pdf_path))
        doc.close()
        extractor = GenericPlanReaderExtractor()
        preds = {p.tag: p for p in extractor.extract_from_pdf(pdf_path)}
        wall = preds["perimeter_walling"]
        assert wall.dimensions[1] == extractor.default_ceiling_height_m
        assert wall.metadata["wall_height_source"] == "default_ceiling_height_assumption"
