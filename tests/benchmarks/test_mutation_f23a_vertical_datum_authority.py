"""tests/benchmarks/test_mutation_f23a_vertical_datum_authority.py

Phase F.23A acceptance suite: generic wall-height / vertical-datum
evidence robustness, and the authority-demotion fix for the
default-height fallback (known safety debt flagged in the F-series
handover: `effective_wall_height_m = resolved_height if evidence exists
else default_ceiling_height_m` can still emit commercially-shaped wall
quantities from an unevidenced assumption).

Investigation finding (documented here, not asserted as a test): a
comprehensive keyword search across every page of both real diagnostic
project PDFs (KSTVET, Murera), plus a spatial check for a genuine
vertical/column-oriented dimension chain near the elevation/section
views, found no stronger generic vertical evidence than F.14's
level-datum parser already recognizes. Murera has genuine, corroborating
level-datum evidence (already resolved by F.14); KSTVET has none. Since
no parser gap was found, this suite instead hardens two things:

1. resolve_wall_height() (F.13) no longer silently collapses genuinely
   disagreeing roof/floor readings via max/min -- it now requires
   corroboration (agreement within tolerance) the same way this module
   already requires it elsewhere (reconcile_duplicate_observations),
   and fails to CONFLICT_MANUAL_REVIEW instead.
2. The default-height fallback in GenericPlanReaderExtractor is
   demoted (never invented a different guessed height) with an explicit
   wall_height_authority metadata field, so a downstream consumer
   gating on confidence or authority cannot mistake an assumption for a
   firm, evidence-based quantity.

Every numeric value in this file is synthetic and invented for this
test -- none are copied from KSTVET's or Murera's real expected values.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_dimension_graph_constraint_engine import ConstraintStatus, resolve_wall_height
from pb_level_datum_extraction import find_level_markers
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


# ---------------------------------------------------------------------------
# Pure parser/resolver level: find_level_markers + resolve_wall_height
# ---------------------------------------------------------------------------

class TestExplicitValidHeightEvidence:
    def test_explicit_roof_and_floor_level_resolve_a_clean_height(self) -> None:
        markers = find_level_markers("Roof Level +2,940", source_page=1) + find_level_markers(
            "Ground floor +140", source_page=1
        )
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert res.clear_height_m == pytest.approx(2.8)


class TestMultipleEquivalentAnnotationsCorroborate:
    def test_two_agreeing_roof_level_readings_resolve_normally(self) -> None:
        markers = (
            find_level_markers("Roof Level +2,940", source_page=1)
            + find_level_markers("Roof Level +2,940", source_page=2)
            + find_level_markers("Ground floor +140", source_page=1)
        )
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert res.clear_height_m == pytest.approx(2.8)

    def test_readings_within_tight_tolerance_still_agree(self) -> None:
        # 1mm apart -- genuine measurement/OCR-level noise, not a real conflict.
        markers = (
            find_level_markers("Roof Level +2,940", source_page=1)
            + find_level_markers("Roof Level +2,941", source_page=2)
            + find_level_markers("Ground floor +140", source_page=1)
        )
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.FULLY_CONSTRAINED.value


class TestConflictingAnnotationsFailClosed:
    def test_genuinely_disagreeing_roof_readings_are_a_conflict_not_a_max(self) -> None:
        # A real disagreement, not noise -- must never be silently resolved
        # by picking the larger (or smaller) reading.
        markers = (
            find_level_markers("Roof Level +2,940", source_page=1)
            + find_level_markers("Roof Level +4,500", source_page=2)
            + find_level_markers("Ground floor +140", source_page=1)
        )
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value
        assert res.clear_height_m is None
        assert res.notes

    def test_genuinely_disagreeing_floor_readings_are_also_a_conflict(self) -> None:
        markers = (
            find_level_markers("Roof Level +2,940", source_page=1)
            + find_level_markers("Ground floor +140", source_page=1)
            + find_level_markers("Ground floor +900", source_page=2)
        )
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value
        assert res.clear_height_m is None


class TestUnrelatedVerticalDimensionsIgnored:
    def test_a_plain_room_dimension_near_the_word_roof_is_not_a_level(self) -> None:
        # "Roof Plan" is a view title, not a level datum -- find_level_markers
        # requires the literal "roof level" phrase, so a plain room
        # dimension appearing near "Roof Plan" must never be misread.
        markers = find_level_markers("ROOF PLAN 1:100 4,500 3,200", source_page=1)
        assert markers == []


class TestRoofRidgeNeverMistakenForWallHeight:
    def test_ridge_level_text_is_not_recognized_as_a_roof_level(self) -> None:
        # "Ridge Level" is a different datum (roof apex) from the
        # wall-plate/eaves level this module targets -- it must not be
        # silently folded into "roof" just because both mention a roof.
        markers = find_level_markers("Ridge Level +6,200", source_page=1)
        assert markers == []


class TestOpeningHeightNeverMistakenForRoomHeight:
    def test_window_height_text_is_not_recognized_as_a_level(self) -> None:
        markers = find_level_markers("Window height 900mm overall", source_page=1)
        assert markers == []

    def test_door_height_text_is_not_recognized_as_a_level(self) -> None:
        markers = find_level_markers("Door height 2,100mm complete", source_page=1)
        assert markers == []


class TestTitleBlockNumbersNeverMistakenForDimensions:
    def test_drawing_number_near_a_genuine_label_is_not_captured_as_its_value(self) -> None:
        # A title-block drawing/revision number sitting near the word
        # "Floor" (e.g. "Floor Plan Drawing No. 2401") must not be read as
        # a floor level value -- "floor level" (the exact phrase) is
        # required, not just the word "floor" near any number.
        markers = find_level_markers("FLOOR PLAN DRAWING NO. 2401 REV B", source_page=1)
        assert markers == []


class TestMissingHeightEvidence:
    def test_no_markers_at_all_is_unresolved(self) -> None:
        res = resolve_wall_height([], scope_id=None)
        assert res.status == ConstraintStatus.UNRESOLVED.value
        assert res.clear_height_m is None

    def test_roof_only_no_floor_is_unresolved(self) -> None:
        markers = find_level_markers("Roof Level +2,940", source_page=1)
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.UNRESOLVED.value


class TestAmbiguousSectionElevationAssociation:
    def test_two_elevations_with_different_heights_fail_closed_as_conflict(self) -> None:
        # find_level_markers has no per-view spatial binding: two distinct
        # elevations on the same page, each genuinely describing a
        # DIFFERENT part of the building at a different height, pool
        # together with no way to tell them apart. This must fail closed
        # (CONFLICT_MANUAL_REVIEW) rather than silently picking one
        # elevation's reading over the other's.
        page_text = (
            "ELEVATION E-01 1:100 Roof Level +2,940 Ground floor +140 "
            "ELEVATION E-02 1:100 Roof Level +3,850 Ground floor +140"
        )
        markers = find_level_markers(page_text, source_page=1)
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.CONFLICT_MANUAL_REVIEW.value


class TestImperialOrNoiseTextRejected:
    def test_imperial_feet_inches_notation_is_not_captured(self) -> None:
        markers = find_level_markers('Roof Level 9\'-6" above datum', source_page=1)
        assert markers == []

    def test_decimal_metre_notation_is_not_captured(self) -> None:
        # This codebase's comma-grouped-millimetre convention deliberately
        # does not recognize a dotted-decimal metre value -- see
        # pb_level_datum_extraction's own module docstring.
        markers = find_level_markers("Roof Level +2.940", source_page=1)
        assert markers == []


class TestMutationOfSyntheticValues:
    @pytest.mark.parametrize(
        "roof_mm,floor_mm,expected_height_m",
        [
            (2500, 100, 2.4),
            (3000, 0, 3.0),
            (2650, -50, 2.7),
            (4100, 350, 3.75),
        ],
    )
    def test_height_resolution_is_deterministic_across_synthetic_values(
        self, roof_mm: int, floor_mm: int, expected_height_m: float
    ) -> None:
        roof_text = f"Roof Level +{roof_mm:,}" if roof_mm >= 0 else f"Roof Level -{abs(roof_mm):,}"
        floor_text = f"Ground floor +{floor_mm:,}" if floor_mm >= 0 else f"Ground floor -{abs(floor_mm):,}"
        markers = find_level_markers(roof_text, source_page=1) + find_level_markers(floor_text, source_page=1)
        res = resolve_wall_height(markers, scope_id=None)
        assert res.status == ConstraintStatus.FULLY_CONSTRAINED.value
        assert res.clear_height_m == pytest.approx(expected_height_m)


# ---------------------------------------------------------------------------
# Extractor-wiring level: default-height authority demotion
# ---------------------------------------------------------------------------

def _make_pdf(tmp_path: Path, name: str, lines: list[str]) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    pdf_path = tmp_path / name
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestDefaultHeightAuthorityDemotion:
    def test_no_height_evidence_demotes_perimeter_walling_confidence_and_authority(self, tmp_path: Path) -> None:
        pdf_path = _make_pdf(tmp_path, "no_height.pdf", [
            "GROUND FLOOR PLAN", "SCALE 1:100", "9,000", "5,500",
        ])
        preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf_path)}
        wall = preds["perimeter_walling"]
        assert wall.confidence == 0.6
        assert wall.metadata["wall_height_source"] == "default_ceiling_height_assumption"
        assert wall.metadata["wall_height_authority"] == "provisional"

    def test_genuine_height_evidence_keeps_the_undemoted_confidence_and_authority(self, tmp_path: Path) -> None:
        pdf_path = _make_pdf(tmp_path, "with_height.pdf", [
            "GROUND FLOOR PLAN", "SCALE 1:100", "9,000", "5,500",
        ])
        # Second page carries a genuine, corroborated level-datum pair.
        doc = fitz.open(str(pdf_path))
        page2 = doc.new_page()
        page2.insert_text((72, 72), "ELEVATION E-01\nSCALE 1:100\nRoof Level +2,940\nGround floor +140", fontsize=11)
        doc.saveIncr()
        doc.close()

        preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf_path)}
        wall = preds["perimeter_walling"]
        assert wall.confidence == 0.93
        assert wall.metadata["wall_height_authority"] == "documented_dimension"
        assert wall.dimensions[1] == pytest.approx(2.8)

    def test_conflicting_height_evidence_falls_back_to_the_demoted_default(self, tmp_path: Path) -> None:
        pdf_path = _make_pdf(tmp_path, "conflicting_height.pdf", [
            "GROUND FLOOR PLAN", "SCALE 1:100", "9,000", "5,500",
        ])
        doc = fitz.open(str(pdf_path))
        page2 = doc.new_page()
        page2.insert_text(
            (72, 72),
            "ELEVATION E-01\nRoof Level +2,940\nGround floor +140\n"
            "ELEVATION E-02\nRoof Level +4,800\nGround floor +140",
            fontsize=11,
        )
        doc.saveIncr()
        doc.close()

        preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf_path)}
        wall = preds["perimeter_walling"]
        # A genuine conflict must fall back to the demoted default, exactly
        # like having no evidence at all -- never guess between the two.
        extractor = GenericPlanReaderExtractor()
        assert wall.dimensions[1] == extractor.default_ceiling_height_m
        assert wall.confidence == 0.6
        assert wall.metadata["wall_height_authority"] == "provisional"
