"""tests/benchmarks/test_mutation_f21_reinforced_floor_slab.py

Mutation/negative/conflict/leakage suite for Phase F.21: generic
reinforced-floor-slab classification and geometry binding
(pb_slab_classification_geometry.py) plus its production wiring into
GenericPlanReaderExtractor's `reinforced_floor_slab` prediction. Every
project name, dimension, and quantity in this file is invented for this
test only -- no benchmark identifiers, gold values, or manifest access
anywhere in this file or in the module under test.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import fitz
import pytest

import pb_slab_classification_geometry as slab_module
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from pb_slab_classification_geometry import (
    CandidateBoundary,
    SlabAnnotationObservation,
    SlabResolutionState,
    SlabThicknessObservation,
    SlabType,
    extract_reinforcement_near,
    extract_slab_annotations_from_text,
    extract_thickness_observations_near,
    resolve_slab_entity,
    resolve_slab_thickness,
    resolve_slabs_from_text,
    validate_boundary_polygon,
)


def _boundary(
    *,
    area_m2: float = 42.0,
    source_page: int = 1,
    polygon=None,
    spatial_envelope=None,
    units_authoritative: bool = True,
    boundary_id: str = "b1",
) -> CandidateBoundary:
    return CandidateBoundary(
        boundary_id=boundary_id,
        polygon=polygon or [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        area_m2=area_m2,
        source_page=source_page,
        units_authoritative=units_authoritative,
        spatial_envelope=spatial_envelope,
    )


def _annotation(
    *,
    position=(5.0, 5.0),
    source_page: int = 1,
    slab_type: str = SlabType.REINFORCED_CONCRETE.value,
    raw_text: str = "RC SLAB",
) -> SlabAnnotationObservation:
    return SlabAnnotationObservation(
        annotation_id="ann1",
        slab_type=slab_type,
        raw_text=raw_text,
        source_page=source_page,
        position=position,
        match_start=0,
        match_end=len(raw_text),
    )


def _build_pdf(tmp_path: Path, lines, name: str = "synthetic.pdf") -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    pdf_path = tmp_path / name
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


# ---------------------------------------------------------------------------
# 1. Thickness mutation changes the resolved thickness.
# ---------------------------------------------------------------------------

class TestThicknessMutation:
    def test_thickness_mutation_changes_resolved_thickness(self):
        boundary = _boundary()
        ann = _annotation()
        e150 = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=150.0, raw_text="150mm")],
            reinforcement=[],
            candidate_boundaries=[boundary],
        )
        e200 = resolve_slab_entity(
            slab_id="s2",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=200.0, raw_text="200mm")],
            reinforcement=[],
            candidate_boundaries=[boundary],
        )
        assert e150.thickness_mm == 150.0
        assert e200.thickness_mm == 200.0
        assert e150.resolution_state == SlabResolutionState.RESOLVED.value
        assert e200.resolution_state == SlabResolutionState.RESOLVED.value


# ---------------------------------------------------------------------------
# 2. Conflicting thicknesses resolve to CONFLICTING and None.
# ---------------------------------------------------------------------------

class TestConflictingThickness:
    def test_conflicting_thickness_resolves_to_conflicting_and_none(self):
        boundary = _boundary()
        ann = _annotation()
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[
                SlabThicknessObservation(value_mm=150.0, raw_text="150mm"),
                SlabThicknessObservation(value_mm=225.0, raw_text="225mm"),
            ],
            reinforcement=[],
            candidate_boundaries=[boundary],
        )
        assert e.resolution_state == SlabResolutionState.CONFLICTING.value
        assert e.thickness_mm is None
        assert e.area_m2 is None


# ---------------------------------------------------------------------------
# 3. Slab keyword without geometry produces no measured quantity.
# ---------------------------------------------------------------------------

class TestNoGeometry:
    def test_slab_keyword_without_geometry_produces_no_measured_quantity(self):
        ann = _annotation()
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=150.0, raw_text="150mm")],
            reinforcement=[],
            candidate_boundaries=[],
        )
        assert e.area_m2 is None
        assert e.resolution_state == SlabResolutionState.UNRESOLVED_BOUNDARY.value

    def test_production_no_dimension_evidence_emits_no_slab_prediction(self, tmp_path: Path) -> None:
        pdf_path = _build_pdf(
            tmp_path,
            [
                "GROUND FLOOR PLAN",
                "SCALE 1:100",
                "150mm THICK RC SLAB",
                "T12@200 EW",
            ],
            "no_dims.pdf",
        )
        preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
        assert not any(p.tag == "reinforced_floor_slab" for p in preds)


# ---------------------------------------------------------------------------
# 4. Slab boundary with annotation but no thickness becomes UNRESOLVED_THICKNESS.
# ---------------------------------------------------------------------------

class TestUnresolvedThickness:
    def test_boundary_with_annotation_but_no_thickness_is_unresolved_thickness(self):
        boundary = _boundary()
        ann = _annotation()
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[],
            reinforcement=[],
            candidate_boundaries=[boundary],
        )
        assert e.resolution_state == SlabResolutionState.UNRESOLVED_THICKNESS.value
        assert e.area_m2 is None


# ---------------------------------------------------------------------------
# 5. Boundary without slab evidence produces no slab.
# ---------------------------------------------------------------------------

class TestBoundaryWithoutSlabEvidence:
    def test_boundary_without_slab_evidence_produces_no_slab(self):
        boundary = _boundary()
        entities = resolve_slabs_from_text(
            "GROUND FLOOR PLAN\n10,000\n6,000\nNO SLAB KEYWORD ANYWHERE ON THIS SHEET",
            candidate_boundaries=[boundary],
        )
        assert entities == []


# ---------------------------------------------------------------------------
# 6. Invalid, open, zero-area and non-finite polygons fail closed.
# ---------------------------------------------------------------------------

class TestBoundaryPolygonValidation:
    @pytest.mark.parametrize(
        "polygon",
        [
            None,
            [],
            [(0.0, 0.0)],
            [(0.0, 0.0), (1.0, 1.0)],
            [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)],  # collinear -> zero area
            [(0.0, 0.0), (float("inf"), 1.0), (2.0, 2.0)],
            [(0.0, 0.0), (float("nan"), 1.0), (2.0, 2.0)],
            [(0.0, 0.0), (0.0, 0.0), (1.0, 1.0)],  # zero-length edge
        ],
    )
    def test_invalid_polygons_fail_closed(self, polygon):
        assert validate_boundary_polygon(polygon) is False

    def test_valid_rectangle_polygon_passes(self):
        assert validate_boundary_polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]) is True


# ---------------------------------------------------------------------------
# 7. Unknown coordinate units do not produce square-metre area.
# ---------------------------------------------------------------------------

class TestUnknownUnits:
    def test_unknown_units_do_not_produce_area(self):
        boundary = _boundary(units_authoritative=False)
        ann = _annotation()
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=150.0, raw_text="150mm")],
            reinforcement=[],
            candidate_boundaries=[boundary],
        )
        assert e.area_m2 is None
        assert e.resolution_state == SlabResolutionState.UNRESOLVED_BOUNDARY.value


# ---------------------------------------------------------------------------
# 8. Annotation outside the boundary is not incorrectly bound.
# ---------------------------------------------------------------------------

class TestAnnotationOutsideBoundary:
    def test_annotation_far_outside_boundary_is_not_bound(self):
        boundary = _boundary()
        ann = _annotation(position=(500.0, 500.0))
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=150.0, raw_text="150mm")],
            reinforcement=[],
            candidate_boundaries=[boundary],
        )
        assert e.resolution_state == SlabResolutionState.UNRESOLVED_BOUNDARY.value
        assert e.area_m2 is None


# ---------------------------------------------------------------------------
# 9. Scale-aware adjacent leader notes bind correctly.
# ---------------------------------------------------------------------------

class TestAdjacentLeaderNoteBinding:
    def test_adjacent_leader_note_binds_within_tolerance(self):
        boundary = _boundary()  # rectangle corners at (0,0)-(10,10)
        ann = _annotation(position=(10.3, 5.0))  # just outside the right edge
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=150.0, raw_text="150mm")],
            reinforcement=[],
            candidate_boundaries=[boundary],
            adjacency_tolerance=0.5,
        )
        assert e.resolution_state == SlabResolutionState.RESOLVED.value
        assert e.area_m2 == boundary.area_m2

    def test_note_beyond_tolerance_does_not_bind(self):
        boundary = _boundary()
        ann = _annotation(position=(20.0, 5.0))  # well outside a 0.5 tolerance
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=150.0, raw_text="150mm")],
            reinforcement=[],
            candidate_boundaries=[boundary],
            adjacency_tolerance=0.5,
        )
        assert e.resolution_state == SlabResolutionState.UNRESOLVED_BOUNDARY.value


# ---------------------------------------------------------------------------
# 10. Overlapping or ambiguous boundaries fail closed.
# ---------------------------------------------------------------------------

class TestAmbiguousBoundaries:
    def test_overlapping_ambiguous_boundaries_fail_closed(self):
        b1 = _boundary(boundary_id="b1", area_m2=40.0)
        b2 = _boundary(boundary_id="b2", area_m2=45.0)
        ann = _annotation()
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=150.0, raw_text="150mm")],
            reinforcement=[],
            candidate_boundaries=[b1, b2],
        )
        assert e.resolution_state == SlabResolutionState.CONFLICTING.value
        assert e.area_m2 is None


# ---------------------------------------------------------------------------
# 11. Multiple independent slabs remain distinct.
# ---------------------------------------------------------------------------

class TestMultipleIndependentSlabs:
    def test_multiple_independent_slabs_remain_distinct(self):
        text = "150mm THICK RC SLAB near the entry.\n\nSUSPENDED RC SLAB 200mm over the mezzanine."
        boundary = _boundary(area_m2=30.0)
        entities = resolve_slabs_from_text(text, candidate_boundaries=[boundary])
        assert len(entities) == 2
        assert entities[0].slab_id != entities[1].slab_id
        assert entities[0].slab_type != entities[1].slab_type


# ---------------------------------------------------------------------------
# 12. Reinforcement variants normalize correctly.
# ---------------------------------------------------------------------------

class TestReinforcementNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("T12@200 EW", "T12@200-EW"),
            ("T12-200 EW", "T12@200-EW"),
            ("T12 @ 200 C/C", "T12@200-CC"),
            ("N12 @ 200 each way", "N12@200-EW"),
        ],
    )
    def test_reinforcement_variants_normalize_to_the_same_canonical_form(self, raw, expected):
        out = extract_reinforcement_near(raw, 0, len(raw), window=0)
        assert len(out) == 1
        assert out[0].reinforcement_type == expected


# ---------------------------------------------------------------------------
# 13. Duplicate reinforcement is suppressed.
# ---------------------------------------------------------------------------

class TestReinforcementDeduplication:
    def test_duplicate_reinforcement_is_suppressed(self):
        text = "T12@200 EW T12@200 EW T12-200 EW"
        out = extract_reinforcement_near(text, 0, len(text), window=0)
        assert len(out) == 1
        assert out[0].reinforcement_type == "T12@200-EW"


# ---------------------------------------------------------------------------
# 14. Unrelated drawing codes are not classified as reinforcement.
# ---------------------------------------------------------------------------

class TestUnrelatedDrawingCodesExcluded:
    def test_unrelated_drawing_code_without_mesh_context_is_ignored(self):
        text = "SEE DETAIL ON DRAWING A142 FOR EDGE PROFILE"
        out = extract_reinforcement_near(text, 0, len(text), window=0)
        assert out == []

    def test_same_shaped_code_with_genuine_mesh_context_is_classified(self):
        text = "FABRIC MESH A142 TOP AND BOTTOM"
        out = extract_reinforcement_near(text, 0, len(text), window=0)
        assert any(r.reinforcement_type == "A142" for r in out)


# ---------------------------------------------------------------------------
# 15. Implausible thicknesses are rejected and recorded.
# ---------------------------------------------------------------------------

class TestImplausibleThicknessRejected:
    def test_implausible_thickness_is_rejected_and_recorded_in_provenance(self):
        boundary = _boundary()
        ann = _annotation()
        e = resolve_slab_entity(
            slab_id="s1",
            annotation=ann,
            thickness_observations=[SlabThicknessObservation(value_mm=5.0, raw_text="5mm")],
            reinforcement=[],
            candidate_boundaries=[boundary],
        )
        assert e.thickness_mm is None
        assert e.resolution_state == SlabResolutionState.UNRESOLVED_THICKNESS.value
        rejected = e.provenance.get("rejected_thickness_observations")
        assert rejected and rejected[0]["value_mm"] == 5.0

    def test_resolve_slab_thickness_directly_separates_accepted_and_rejected(self):
        obs = [
            SlabThicknessObservation(value_mm=150.0, raw_text="150mm"),
            SlabThicknessObservation(value_mm=900.0, raw_text="900mm"),  # implausible
        ]
        value, state, accepted, rejected = resolve_slab_thickness(obs)
        assert value == 150.0
        assert state == SlabResolutionState.RESOLVED.value
        assert len(accepted) == 1
        assert len(rejected) == 1


# ---------------------------------------------------------------------------
# 16. Reordering tokens does not alter results.
# ---------------------------------------------------------------------------

class TestTokenReorderingInvariance:
    @pytest.mark.parametrize(
        "text",
        [
            "150mm THICK RC SLAB",
            "RC SLAB THK 150mm",
            "150 RC SLAB",
        ],
    )
    def test_reordering_thickness_position_does_not_alter_resolved_value(self, text):
        anns = extract_slab_annotations_from_text(text)
        assert len(anns) == 1
        obs = extract_thickness_observations_near(text, anns[0].match_start, anns[0].match_end)
        value, state, _accepted, _rejected = resolve_slab_thickness(obs)
        assert value == 150.0
        assert state == SlabResolutionState.RESOLVED.value


# ---------------------------------------------------------------------------
# 17. Renaming files and moving them into random UUID directories does not
# alter results.
# ---------------------------------------------------------------------------

class TestFilenamePathLeakage:
    def test_renaming_and_moving_the_file_does_not_alter_results(self, tmp_path: Path) -> None:
        original_path = _build_pdf(
            tmp_path,
            [
                "GROUND FLOOR PLAN",
                "SCALE 1:100",
                "10,000",
                "6,000",
                "150mm THICK RC SLAB",
                "T12@200 EW MESH A142 TOP",
            ],
            "original_project_name.pdf",
        )
        renamed_dir = tmp_path / str(uuid.uuid4())
        renamed_dir.mkdir()
        renamed_path = renamed_dir / f"{uuid.uuid4()}.pdf"
        shutil.copy(original_path, renamed_path)

        preds_a = GenericPlanReaderExtractor().extract_from_pdf(original_path)
        preds_b = GenericPlanReaderExtractor().extract_from_pdf(renamed_path)
        slab_a = next(p for p in preds_a if p.tag == "reinforced_floor_slab")
        slab_b = next(p for p in preds_b if p.tag == "reinforced_floor_slab")
        assert slab_a.quantity == slab_b.quantity
        assert slab_a.metadata["thickness_mm"] == slab_b.metadata["thickness_mm"]
        assert slab_a.metadata["reinforcement"] == slab_b.metadata["reinforcement"]


# ---------------------------------------------------------------------------
# 18. Removing or mutating source evidence removes or changes the
# corresponding prediction.
# ---------------------------------------------------------------------------

class TestEvidenceMutationChangesPrediction:
    def test_removing_thickness_evidence_removes_the_prediction(self, tmp_path: Path) -> None:
        with_thickness = GenericPlanReaderExtractor().extract_from_pdf(
            _build_pdf(
                tmp_path,
                ["GROUND FLOOR PLAN", "SCALE 1:100", "10,000", "6,000", "150mm THICK RC SLAB"],
                "with_thickness.pdf",
            )
        )
        without_thickness = GenericPlanReaderExtractor().extract_from_pdf(
            _build_pdf(
                tmp_path,
                ["GROUND FLOOR PLAN", "SCALE 1:100", "10,000", "6,000", "RC SLAB"],
                "without_thickness.pdf",
            )
        )
        assert any(p.tag == "reinforced_floor_slab" for p in with_thickness)
        assert not any(p.tag == "reinforced_floor_slab" for p in without_thickness)

    def test_mutating_thickness_changes_the_prediction_metadata(self, tmp_path: Path) -> None:
        preds_150 = GenericPlanReaderExtractor().extract_from_pdf(
            _build_pdf(
                tmp_path,
                ["GROUND FLOOR PLAN", "SCALE 1:100", "10,000", "6,000", "150mm THICK RC SLAB"],
                "t150.pdf",
            )
        )
        preds_200 = GenericPlanReaderExtractor().extract_from_pdf(
            _build_pdf(
                tmp_path,
                ["GROUND FLOOR PLAN", "SCALE 1:100", "10,000", "6,000", "200mm THICK RC SLAB"],
                "t200.pdf",
            )
        )
        s150 = next(p for p in preds_150 if p.tag == "reinforced_floor_slab")
        s200 = next(p for p in preds_200 if p.tag == "reinforced_floor_slab")
        assert s150.metadata["thickness_mm"] == 150.0
        assert s200.metadata["thickness_mm"] == 200.0
        assert s150.metadata["thickness_mm"] != s200.metadata["thickness_mm"]


# ---------------------------------------------------------------------------
# 19. Extractor source contains no benchmark identifiers, expected
# quantities or manifest access.
# ---------------------------------------------------------------------------

class TestNoBenchmarkLeakageInSource:
    def test_module_source_contains_no_benchmark_identifiers(self) -> None:
        src = Path(slab_module.__file__).read_text(encoding="utf-8").lower()
        forbidden = [
            "kstvet",
            "murera",
            "mbagha",
            "expected_boq",
            "benchmark_rules",
            "expected_quantity",
            "benchmarks/public_tenders",
        ]
        for term in forbidden:
            assert term not in src, f"found forbidden term {term!r} in {slab_module.__file__}"

    def test_module_never_imports_manifest_or_benchmark_modules(self) -> None:
        src = Path(slab_module.__file__).read_text(encoding="utf-8")
        assert "pb_public_tender_benchmark" not in src
        assert "pb_benchmark_accuracy_engine" not in src


# ---------------------------------------------------------------------------
# 20. Existing floor screed, DPM and mesh extraction does not regress.
# ---------------------------------------------------------------------------

class TestNoRegressionToExistingFinishExtraction:
    def test_floor_screed_dpm_and_mesh_are_unchanged_alongside_f21(self, tmp_path: Path) -> None:
        pdf_path = _build_pdf(
            tmp_path,
            [
                "GROUND FLOOR PLAN",
                "SCALE 1:100",
                "10,000",
                "6,000",
                "DAMP PROOF MEMBRANE TO SURFACE BED",
                "150mm THICK RC SLAB",
                "T12@200 EW MESH A142 TOP",
            ],
            "regression.pdf",
        )
        preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf_path)}
        assert preds["floor_screed"].quantity == 60.0
        assert preds["substructure_bed_dpm"].quantity == 60.0
        assert preds["substructure_a142_mesh"].quantity == 60.0
        assert "reinforced_floor_slab" in preds
        assert preds["reinforced_floor_slab"].quantity == 60.0

    def test_no_slab_annotation_leaves_existing_predictions_untouched(self, tmp_path: Path) -> None:
        pdf_path = _build_pdf(
            tmp_path,
            [
                "GROUND FLOOR PLAN",
                "SCALE 1:100",
                "10,000",
                "6,000",
                "DAMP PROOF MEMBRANE TO SURFACE BED",
            ],
            "no_slab_note.pdf",
        )
        preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf_path)}
        assert preds["floor_screed"].quantity == 60.0
        assert preds["substructure_bed_dpm"].quantity == 60.0
        assert "reinforced_floor_slab" not in preds
