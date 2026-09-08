"""Synthetic mutation/red-team coverage for F.22 component floor finishes.

All project geometry and dimensions in this file are invented.  No benchmark IDs,
expected quantities, project names, source filenames, or gold values are used.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_component_floor_finish_geometry import derive_component_aware_floor_finish_area
from pb_multi_space_footprint_geometry import (
    MultiSpaceFootprintBuilder,
    MultiSpaceFootprintEngine,
    SpaceComponent,
    SpaceType,
)
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _confirmed_main_and_verandah(*, thickness_m: float = 0.20):
    builder = MultiSpaceFootprintBuilder()
    builder.add_main_room(length_m=12.0, width_m=8.0)
    builder.add_verandah(length_m=12.0, width_m=2.0, adjacency="front")
    footprint = builder.build()
    return footprint, derive_component_aware_floor_finish_area(footprint, thickness_m)


def test_enclosed_main_shrinks_to_clear_faces_but_verandah_stays_full_area() -> None:
    footprint, result = _confirmed_main_and_verandah(thickness_m=0.20)
    assert result is not None
    assert footprint.gross_floor_area_m2 == pytest.approx(120.0)
    assert result.structural_footprint_area_m2 == pytest.approx(120.0)
    assert result.main_clear_length_m == pytest.approx(11.6)
    assert result.main_clear_width_m == pytest.approx(7.6)
    assert result.main_clear_area_m2 == pytest.approx(88.16)
    assert result.open_verandah_area_m2 == pytest.approx(24.0)
    assert result.floor_finish_area_m2 == pytest.approx(112.16)


def test_wall_thickness_mutation_changes_only_clear_enclosed_component() -> None:
    footprint, thin = _confirmed_main_and_verandah(thickness_m=0.10)
    thick = derive_component_aware_floor_finish_area(footprint, 0.25)
    assert thin is not None and thick is not None
    assert thin.open_verandah_area_m2 == thick.open_verandah_area_m2 == pytest.approx(24.0)
    assert thick.main_clear_area_m2 < thin.main_clear_area_m2
    assert thick.floor_finish_area_m2 < thin.floor_finish_area_m2
    assert thin.structural_footprint_area_m2 == thick.structural_footprint_area_m2 == pytest.approx(120.0)


@pytest.mark.parametrize("bad_thickness", [None, 0.0, -0.1, float("inf"), float("nan")])
def test_missing_or_invalid_thickness_fails_closed(bad_thickness: float | None) -> None:
    footprint, _ = _confirmed_main_and_verandah()
    assert derive_component_aware_floor_finish_area(footprint, bad_thickness) is None


def test_partial_verandah_geometry_fails_closed() -> None:
    builder = MultiSpaceFootprintBuilder()
    builder.add_main_room(length_m=12.0, width_m=8.0)
    builder.add_verandah(length_m=12.0, width_m=None, adjacency="front")
    footprint = builder.build()
    assert derive_component_aware_floor_finish_area(footprint, 0.20) is None


def test_unsupported_ancillary_component_fails_closed() -> None:
    components = [
        SpaceComponent(
            space_id="main",
            space_type=SpaceType.MAIN_BUILDING.value,
            label="Main",
            length_m=12.0,
            width_m=8.0,
        ),
        SpaceComponent(
            space_id="annex",
            space_type=SpaceType.ANCILLARY.value,
            label="Annex",
            length_m=3.0,
            width_m=2.0,
        ),
    ]
    footprint = MultiSpaceFootprintEngine.evaluate(components)
    assert derive_component_aware_floor_finish_area(footprint, 0.20) is None


def test_void_geometry_fails_closed_instead_of_guessing_clear_face_offsets() -> None:
    components = [
        SpaceComponent(
            space_id="main",
            space_type=SpaceType.MAIN_BUILDING.value,
            label="Main",
            length_m=12.0,
            width_m=8.0,
        ),
        SpaceComponent(
            space_id="court",
            space_type=SpaceType.COURTYARD_VOID.value,
            label="Court",
            length_m=2.0,
            width_m=2.0,
            is_void=True,
        ),
    ]
    footprint = MultiSpaceFootprintEngine.evaluate(components)
    assert derive_component_aware_floor_finish_area(footprint, 0.20) is None


def test_physically_consuming_thickness_fails_closed() -> None:
    builder = MultiSpaceFootprintBuilder()
    builder.add_main_room(length_m=0.6, width_m=0.5)
    footprint = builder.build()
    assert derive_component_aware_floor_finish_area(footprint, 0.30) is None


def _synthetic_pdf(
    tmp_path: Path,
    *,
    wall_rows: tuple[str, str] | None,
    include_substructure_specs: bool = False,
) -> Path:
    lines = [
        "GROUND FLOOR PLAN",
        "SCALE 1:100",
        "12,000",
        "8,000",
        "2,000mm wide verandah finished in screed",
    ]
    if wall_rows is not None:
        lines.extend(wall_rows)
    if include_substructure_specs:
        lines.extend((
            "D.P.M. under floor bed",
            "A142 mesh reinforcement to floor bed",
            "100mm R.C. slab on well compacted hardcore",
        ))

    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    y = 50
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 22
    path = tmp_path / "synthetic_component_floor.pdf"
    doc.save(path)
    doc.close()
    return path


def _pred_map(path: Path):
    return {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(path)}


def test_extractor_uses_clear_main_plus_full_verandah_when_thickness_corroborates(tmp_path: Path) -> None:
    preds = _pred_map(_synthetic_pdf(
        tmp_path,
        wall_rows=("200 11,600 200", "200 7,600 200"),
    ))
    floor = preds["floor_screed"]
    assert floor.quantity == pytest.approx(112.16)
    assert floor.metadata["structural_bed_area_m2"] == pytest.approx(120.0)
    assert floor.metadata["main_clear_floor_area_m2"] == pytest.approx(88.16)
    assert floor.metadata["open_verandah_floor_area_m2"] == pytest.approx(24.0)
    assert floor.metadata["floor_finish_area_derivation"] == "component_clear_main_plus_evidenced_verandah"


def test_extractor_without_corroborated_thickness_preserves_existing_outer_area(tmp_path: Path) -> None:
    preds = _pred_map(_synthetic_pdf(tmp_path, wall_rows=None))
    floor = preds["floor_screed"]
    assert floor.quantity == pytest.approx(120.0)
    assert "floor_finish_area_derivation" not in floor.metadata


def test_conflicting_thickness_chains_preserve_existing_outer_area(tmp_path: Path) -> None:
    preds = _pred_map(_synthetic_pdf(
        tmp_path,
        wall_rows=("150 11,700 150", "250 7,500 250"),
    ))
    assert preds["floor_screed"].quantity == pytest.approx(120.0)


def test_substructure_siblings_keep_structural_footprint_not_clear_finish(tmp_path: Path) -> None:
    preds = _pred_map(_synthetic_pdf(
        tmp_path,
        wall_rows=("200 11,600 200", "200 7,600 200"),
        include_substructure_specs=True,
    ))
    assert preds["floor_screed"].quantity == pytest.approx(112.16)
    assert preds["substructure_bed_dpm"].quantity == pytest.approx(120.0)
    assert preds["substructure_a142_mesh"].quantity == pytest.approx(120.0)
    assert preds["substructure_surface_bed"].quantity == pytest.approx(120.0)
