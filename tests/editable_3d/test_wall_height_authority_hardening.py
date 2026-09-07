"""tests/editable_3d/test_wall_height_authority_hardening.py — PR D.5 test suite.

Height is one of the largest wall-area error sources. WallHeightAuthority already
existed as a descriptive label (#147); this suite proves it's now actually
*enforced* — unknown height blocks wall area, a model-estimated or raked/stair wall
can never silently claim firm authority, and a figured mm height converts to metres
using the same parser B.2 already validated.
"""
from __future__ import annotations

import pytest

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_model import (
    WallHeightAuthority,
    WallModel,
    resolve_wall_height_from_figured_dimension,
)


def _wall(**overrides):
    defaults = dict(
        wall_id="W_01",
        level_id="L_01",
        start_pt=(0.0, 0.0),
        end_pt=(4.0, 0.0),
        length_m=4.0,
        height_m=2.7,
        height_authority=WallHeightAuthority.DOCUMENTED_CEILING_HEIGHT.value,
        authority_status=AuthorityStatus.FIRM.value,
    )
    defaults.update(overrides)
    return WallModel(**defaults)


class TestUnknownHeightBlocksWallArea:
    def test_unknown_height_authority_forces_blocked_and_zero_area(self):
        wall = _wall(
            height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value,
            authority_status=AuthorityStatus.FIRM.value,  # caller wrongly claims firm
        )
        assert wall.authority_status == AuthorityStatus.BLOCKED.value
        assert wall.gross_area_m2 == 0.0
        assert wall.net_area_m2 == 0.0

    def test_unknown_height_blocks_even_with_a_plausible_positive_height_value(self):
        # The height_m itself is numerically fine — the point is we don't know
        # *where it came from*, so it must never be trusted for a commercial area.
        wall = _wall(height_m=2.4, height_authority=WallHeightAuthority.UNKNOWN_HEIGHT.value)
        assert wall.authority_status == AuthorityStatus.BLOCKED.value
        assert wall.gross_area_m2 == 0.0


class TestFiguredHeightConversion:
    def test_2700mm_figured_height_converts_to_2_7_metres(self):
        assert resolve_wall_height_from_figured_dimension("2700mm") == pytest.approx(2.7)

    def test_bare_number_and_metre_suffix_also_convert(self):
        assert resolve_wall_height_from_figured_dimension("2700") == pytest.approx(2.7)
        assert resolve_wall_height_from_figured_dimension("2.7m") == pytest.approx(2.7)

    def test_figured_dimension_wall_height_is_firm(self):
        height_m = resolve_wall_height_from_figured_dimension("2700mm")
        wall = _wall(
            height_m=height_m,
            height_authority=WallHeightAuthority.FIGURED_DIMENSION.value,
            authority_status=AuthorityStatus.FIRM.value,
        )
        assert wall.height_m == pytest.approx(2.7)
        assert wall.authority_status == AuthorityStatus.FIRM.value

    def test_malformed_figured_height_text_rejected(self):
        from pb_figured_dimension_authority import DimensionParseError

        with pytest.raises(DimensionParseError):
            resolve_wall_height_from_figured_dimension("GG50mm")


class TestSectionHeightTracePreserved:
    def test_section_derived_height_records_source_sheet_and_level(self):
        wall = _wall(
            height_authority=WallHeightAuthority.SECTION_DERIVED.value,
            height_source_sheet="SEC-02",
            height_source_level="Level 1",
        )
        assert wall.height_source_sheet == "SEC-02"
        assert wall.height_source_level == "Level 1"
        d = wall.to_dict()
        assert d["height_source_sheet"] == "SEC-02"
        assert d["height_source_level"] == "Level 1"


class TestModelEstimatedHeightIsProvisional:
    def test_model_estimated_height_cannot_claim_firm(self):
        wall = _wall(
            height_authority=WallHeightAuthority.MODEL_ESTIMATED.value,
            authority_status=AuthorityStatus.FIRM.value,  # caller wrongly claims firm
        )
        assert wall.authority_status == AuthorityStatus.PROVISIONAL.value

    def test_model_estimated_height_can_still_be_requested_as_review_required(self):
        # A caller may always request something *more* conservative than the ceiling.
        wall = _wall(
            height_authority=WallHeightAuthority.MODEL_ESTIMATED.value,
            authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
        )
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value


class TestRakeCannotSilentlyUseFlatWallFormula:
    def test_raked_wall_cannot_claim_firm_without_approval(self):
        wall = _wall(
            wall_id="W_RAKE", wall_type="raked", height_m=3.5,
            height_authority=WallHeightAuthority.RAKED_WALL.value,
            authority_status=AuthorityStatus.FIRM.value,  # caller wrongly claims firm
        )
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        # The flat-formula estimate is still computed (visible for reference)...
        assert wall.gross_area_m2 == pytest.approx(4.0 * 3.5)
        # ...but it was never allowed to become confidently firm on its own.

    def test_stair_wall_cannot_claim_firm_without_approval(self):
        wall = _wall(
            wall_id="W_STAIR", wall_type="stair", height_m=4.2,
            height_authority=WallHeightAuthority.STAIR_WALL.value,
            authority_status=AuthorityStatus.FIRM.value,
        )
        assert wall.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

    def test_raked_wall_can_become_firm_once_explicitly_approved(self):
        wall = _wall(
            wall_id="W_RAKE_APPROVED", wall_type="raked", height_m=3.5,
            height_authority=WallHeightAuthority.RAKED_WALL.value,
            authority_status=AuthorityStatus.FIRM.value,
            approved_by="Lead Estimator Bryce",
        )
        # Explicit approver attribution present -> the flat-formula estimate for a
        # raked wall may stand as firm because a human reviewed it, not the formula.
        assert wall.authority_status == AuthorityStatus.FIRM.value
        assert wall.approved_by == "Lead Estimator Bryce"

    def test_standard_wall_type_is_unaffected_by_the_rake_guard(self):
        wall = _wall(wall_type="standard", authority_status=AuthorityStatus.FIRM.value)
        assert wall.authority_status == AuthorityStatus.FIRM.value


class TestCorrectedHeightInvalidatesQuantity:
    def test_correcting_height_stales_the_linked_takeoff_row(self):
        from pb_editable_3d_correction_model import (
            CorrectionField,
            CorrectionSource,
            Editable3DCorrectionLedger,
            EditableGeometryObject,
            EditableObjectType,
        )
        from pb_takeoff_output_authority import TakeoffSourceType, create_takeoff_output_row
        from pb_editable_3d_quantity_recalculation import (
            RecalculationTarget,
            recalculate_quantities_for_correction,
        )

        row = create_takeoff_output_row(
            quantity_id="QTY-WALL-H1", description="Wall H1 Gross Area", value=10.8,
            unit="m²", source_type=TakeoffSourceType.DOCUMENTED_DIMENSION,
            source_page=2, source_sheet="WD-02", geometry_ref="WALL-H1", dimension_text_id="DIM-H1",
        )
        assert row.is_publishable is True

        ledger = Editable3DCorrectionLedger()
        ledger.register_object(EditableGeometryObject(
            object_id="WALL-H1", object_type=EditableObjectType.WALL.value,
            source_page=2, source_sheet="WD-02", geometry_ref="WALL-H1",
            coordinates_or_measurements={"length": 4.0, "height": 2.7},
            authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS",
        ))
        outcome = ledger.apply_correction(
            correction_id="CORR-HEIGHT-1", object_id="WALL-H1",
            field=CorrectionField.HEIGHT.value, new_value=3.0,
            reason="Corrected from structural section", actor="Estimator A",
            source=CorrectionSource.SCHEDULE_REVIEW.value,
        )
        assert outcome.ok is True
        obj_after = ledger.get_object("WALL-H1")
        assert obj_after.authority_status == AuthorityStatus.REVIEW_REQUIRED.value

        results = recalculate_quantities_for_correction(outcome.event, obj_after, existing_rows=[row])
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)
        assert gross.old_row.is_publishable is False
        assert "stale_after_geometry_correction" in gross.old_row.blocking_reasons
        assert gross.new_row.is_publishable is False
        assert gross.new_value == pytest.approx(12.0)


class TestApprovedCorrectedHeightAllowsNewQuantityToProgress:
    def test_approving_the_corrected_height_lets_a_new_row_become_publishable(self):
        from pb_editable_3d_correction_model import (
            CorrectionField,
            CorrectionSource,
            Editable3DCorrectionLedger,
            EditableGeometryObject,
            EditableObjectType,
            approve_corrected_geometry,
        )
        from pb_takeoff_output_authority import approve_takeoff_output_row
        from pb_editable_3d_quantity_recalculation import (
            RecalculationTarget,
            recalculate_quantities_for_correction,
        )

        ledger = Editable3DCorrectionLedger()
        ledger.register_object(EditableGeometryObject(
            object_id="WALL-H2", object_type=EditableObjectType.WALL.value,
            source_page=2, source_sheet="WD-02", geometry_ref="WALL-H2",
            coordinates_or_measurements={"length": 4.0, "height": 2.7},
            authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS",
        ))
        outcome = ledger.apply_correction(
            correction_id="CORR-HEIGHT-2", object_id="WALL-H2",
            field=CorrectionField.HEIGHT.value, new_value=3.0,
            reason="Corrected from structural section", actor="Estimator A",
            source=CorrectionSource.SCHEDULE_REVIEW.value,
        )
        assert outcome.ok is True
        obj_after = ledger.get_object("WALL-H2")

        results = recalculate_quantities_for_correction(outcome.event, obj_after)
        gross = next(r for r in results if r.target == RecalculationTarget.WALL_GROSS_AREA.value)
        assert gross.new_row.is_publishable is False

        # Approve the corrected geometry at its new revision (D.2's gate).
        approve_corrected_geometry(
            ledger, object_id="WALL-H2", approved_by="Lead Estimator Bryce",
            current_revision_hash=obj_after.revision_hash,
        )

        # A newly-created row, explicitly approved (B.4's approval helper), can now
        # progress to publishable — approval remains a separate, later act.
        approved_new_row = approve_takeoff_output_row(gross.new_row, approved_by="Lead Estimator Bryce")
        assert approved_new_row.is_publishable is True
        assert approved_new_row.revision_hash == obj_after.revision_hash
