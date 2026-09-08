"""Mutation/red-team tests for evidenced internal clear floor-finish geometry.

All dimensions are synthetic.  These tests contain no benchmark identities, source
paths, or expected project quantities.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_floor_finish_geometry import derive_internal_clear_rectangular_area
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _build_pdf(
    tmp_path: Path,
    *,
    wall_thickness_mm: int | None = None,
    conflicting_thickness: bool = False,
    degenerate_equal_chain: bool = False,
    include_bed_specs: bool = False,
) -> Path:
    doc = fitz.open()
    lines = [
        "GROUND FLOOR PLAN",
        "SCALE 1:100",
        "10,000",
        "6,000",
    ]
    if wall_thickness_mm is not None:
        clear_l = 10000 - 2 * wall_thickness_mm
        clear_w = 6000 - 2 * wall_thickness_mm
        lines.append(f"{wall_thickness_mm} {clear_l:,} {wall_thickness_mm}")
        if conflicting_thickness:
            other = wall_thickness_mm + 50
            other_clear = 6000 - 2 * other
            lines.append(f"{other} {other_clear:,} {other}")
        else:
            lines.append(f"{wall_thickness_mm} {clear_w:,} {wall_thickness_mm}")
    if degenerate_equal_chain:
        lines.extend(("200 200 200 200", "200 200 200 200"))
    if include_bed_specs:
        lines.extend(("D.P.M. under floor bed", "A142 mesh reinforcement to floor bed"))

    page = doc.new_page()
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    path = tmp_path / "synthetic_clear_floor_finish.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _extract(path: Path) -> dict:
    predictions = GenericPlanReaderExtractor().extract_from_pdf(path)
    return {prediction.tag: prediction for prediction in predictions}


def test_pure_helper_derives_clear_rectangular_area_exactly() -> None:
    result = derive_internal_clear_rectangular_area(12.0, 7.0, 0.15)
    assert result is not None
    assert result.clear_length_m == 11.7
    assert result.clear_width_m == 6.7
    assert result.outer_area_m2 == 84.0
    assert result.internal_clear_area_m2 == pytest.approx(78.39)


def test_pure_helper_mutates_deterministically_with_thickness() -> None:
    thin = derive_internal_clear_rectangular_area(12.0, 7.0, 0.10)
    thick = derive_internal_clear_rectangular_area(12.0, 7.0, 0.20)
    assert thin is not None and thick is not None
    assert thin.internal_clear_area_m2 == pytest.approx(80.24)
    assert thick.internal_clear_area_m2 == pytest.approx(76.56)
    assert thick.internal_clear_area_m2 < thin.internal_clear_area_m2


def test_pure_helper_fails_closed_for_missing_or_physically_invalid_thickness() -> None:
    assert derive_internal_clear_rectangular_area(12.0, 7.0, None) is None
    assert derive_internal_clear_rectangular_area(12.0, 7.0, 0.0) is None
    assert derive_internal_clear_rectangular_area(0.3, 0.3, 0.2) is None


def test_no_corroborated_thickness_leaves_floor_finish_unchanged(tmp_path: Path) -> None:
    pred = _extract(_build_pdf(tmp_path))
    assert pred["floor_screed"].quantity == pytest.approx(60.0)
    assert pred["floor_screed"].metadata.get("floor_finish_area_derivation") in (None, "outer_footprint_no_clear_face_evidence")


def test_corroborated_thickness_uses_internal_clear_floor_finish(tmp_path: Path) -> None:
    pred = _extract(_build_pdf(tmp_path, wall_thickness_mm=150))
    floor = pred["floor_screed"]
    assert floor.quantity == pytest.approx((10.0 - 0.30) * (6.0 - 0.30))
    assert floor.metadata["floor_finish_area_derivation"] == "internal_clear_rectangle_from_corroborated_wall_thickness"
    assert floor.metadata["wall_thickness_m"] == pytest.approx(0.15)
    assert floor.metadata["structural_bed_area_m2"] == pytest.approx(60.0)
    assert floor.metadata["internal_clear_floor_area_m2"] == pytest.approx(55.29)


def test_mutated_corroborated_thickness_changes_only_evidenced_clear_area(tmp_path: Path) -> None:
    pred = _extract(_build_pdf(tmp_path, wall_thickness_mm=200))
    assert pred["floor_screed"].quantity == pytest.approx((10.0 - 0.40) * (6.0 - 0.40))
    assert pred["floor_screed"].metadata["wall_thickness_m"] == pytest.approx(0.20)


def test_conflicting_thickness_evidence_fails_closed_to_existing_area(tmp_path: Path) -> None:
    pred = _extract(_build_pdf(tmp_path, wall_thickness_mm=150, conflicting_thickness=True))
    assert pred["floor_screed"].quantity == pytest.approx(60.0)


def test_degenerate_repeated_dimension_chain_does_not_shrink_floor(tmp_path: Path) -> None:
    pred = _extract(_build_pdf(tmp_path, degenerate_equal_chain=True))
    assert pred["floor_screed"].quantity == pytest.approx(60.0)


def test_dpm_and_mesh_retain_structural_bed_area_when_finish_uses_clear_area(tmp_path: Path) -> None:
    pred = _extract(_build_pdf(tmp_path, wall_thickness_mm=150, include_bed_specs=True))
    assert pred["floor_screed"].quantity == pytest.approx(55.29)
    assert pred["substructure_bed_dpm"].quantity == pytest.approx(60.0)
    assert pred["substructure_a142_mesh"].quantity == pytest.approx(60.0)
