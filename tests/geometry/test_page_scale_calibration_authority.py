"""tests/geometry/test_page_scale_calibration_authority.py — Per-page scale calibration status
and conflict handling.

Covers: each page carrying its own isolated ScaleCalibration record, ratio-to-px_per_m
conversion, conflict detection across disagreeing scale sources, the fail-closed status
taxonomy (valid/provisional/unknown/conflicting/manual_required/user_approved/blocked),
the resulting measurement-authority gate, and issue-list preservation for downstream
publish gates.
"""
from __future__ import annotations

import math

import pytest

from pb_geometry_takeoff_model import AuthorityStatus, ScaleCalibration
from pb_page_scale_calibration_authority import (
    POINTS_PER_METRE_AT_1_1,
    PageScaleCalibrationRegistry,
    ScaleCalibrationStatus,
    ScaleSourceReading,
    ScaleSourceType,
    approve_page_scale_calibration,
    check_calibration_freshness,
    measurement_authority_for_page_scale,
    px_per_m_from_ratio,
    resolve_page_scale_calibration,
    unknown_calibration,
)


# ---------------------------------------------------------------------------
# Ratio -> px_per_m conversion, per page, no leakage
# ---------------------------------------------------------------------------

class TestRatioConversionAndIsolation:
    def test_page1_scale_1_100_converts_correctly(self):
        calib = resolve_page_scale_calibration(
            page_no=1,
            sheet_label="A-101",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:100", ratio=100.0, confidence=0.95)],
        )
        assert calib.page_no == 1
        assert calib.ratio_str == "1:100"
        assert calib.px_per_m == pytest.approx(POINTS_PER_METRE_AT_1_1 / 100.0)

    def test_page2_scale_1_50_converts_correctly(self):
        calib = resolve_page_scale_calibration(
            page_no=2,
            sheet_label="A-102",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:50", ratio=50.0, confidence=0.95)],
        )
        assert calib.page_no == 2
        assert calib.ratio_str == "1:50"
        assert calib.px_per_m == pytest.approx(POINTS_PER_METRE_AT_1_1 / 50.0)

    def test_page1_scale_does_not_leak_to_page2(self):
        registry = PageScaleCalibrationRegistry()
        calib1 = resolve_page_scale_calibration(
            page_no=1,
            sheet_label="A-101",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:100", ratio=100.0, confidence=0.95)],
        )
        registry.set(1, calib1)

        # Page 2 has never been given a reading.
        assert registry.get(2) is None

        calib2 = resolve_page_scale_calibration(
            page_no=2,
            sheet_label="A-102",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:50", ratio=50.0, confidence=0.95)],
        )
        registry.set(2, calib2)

        assert registry.get(1).px_per_m == pytest.approx(POINTS_PER_METRE_AT_1_1 / 100.0)
        assert registry.get(2).px_per_m == pytest.approx(POINTS_PER_METRE_AT_1_1 / 50.0)
        assert registry.get(1).px_per_m != registry.get(2).px_per_m

        # Mutating page 1's record must not be visible through page 2's.
        registry.set(1, unknown_calibration(page_no=1, sheet_label="A-101"))
        assert registry.get(1).status == ScaleCalibrationStatus.UNKNOWN.value
        assert registry.get(2).status == ScaleCalibrationStatus.VALID.value


class TestPxPerMFromRatio:
    def test_ratio_100_matches_established_precedent(self):
        # 28.35 px/m at 1:100 is the value already used in test_scale_and_figured_dimensions.py.
        assert px_per_m_from_ratio(100.0) == pytest.approx(28.35, abs=0.01)

    @pytest.mark.parametrize("bad_ratio", [0.0, -50.0, math.nan, math.inf, -math.inf])
    def test_invalid_ratio_raises(self, bad_ratio):
        with pytest.raises(ValueError):
            px_per_m_from_ratio(bad_ratio)


# ---------------------------------------------------------------------------
# Unknown scale blocks commercial measurement
# ---------------------------------------------------------------------------

class TestUnknownScaleBlocks:
    def test_no_readings_produces_unknown_status(self):
        calib = resolve_page_scale_calibration(page_no=3, sheet_label="A-103", readings=[])
        assert calib.status == ScaleCalibrationStatus.UNKNOWN.value

    def test_unknown_page_scale_blocks_commercial_measurement(self):
        calib = resolve_page_scale_calibration(page_no=3, sheet_label="A-103", readings=[])
        assert measurement_authority_for_page_scale(calib) == AuthorityStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# Conflicting sources -> manual_required
# ---------------------------------------------------------------------------

class TestConflictHandling:
    def test_conflicting_title_block_and_scale_bar_produce_manual_required(self):
        calib = resolve_page_scale_calibration(
            page_no=4,
            sheet_label="A-104",
            readings=[
                ScaleSourceReading(source_type=ScaleSourceType.TITLE_BLOCK.value, scale_text="1:100", ratio=100.0, confidence=0.6),
                ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:50", ratio=50.0, confidence=0.9),
            ],
        )
        assert calib.status == ScaleCalibrationStatus.MANUAL_REQUIRED.value
        assert calib.ratio_str == "UNKNOWN"
        assert calib.px_per_m == 0.0
        assert measurement_authority_for_page_scale(calib) == AuthorityStatus.BLOCKED.value
        assert len(calib.issues) >= 1

    def test_agreeing_sources_within_tolerance_resolve_valid(self):
        calib = resolve_page_scale_calibration(
            page_no=5,
            sheet_label="A-105",
            readings=[
                ScaleSourceReading(source_type=ScaleSourceType.TITLE_BLOCK.value, scale_text="1:100", ratio=100.0, confidence=0.6),
                ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:101", ratio=101.0, confidence=0.9),
            ],
        )
        assert calib.status == ScaleCalibrationStatus.VALID.value

    def test_conflicting_inferred_only_sources_produce_conflicting_not_manual_required(self):
        calib = resolve_page_scale_calibration(
            page_no=6,
            sheet_label="A-106",
            readings=[
                ScaleSourceReading(source_type=ScaleSourceType.INFERRED.value, scale_text="~1:100", ratio=100.0, confidence=0.3),
                ScaleSourceReading(source_type=ScaleSourceType.INFERRED.value, scale_text="~1:150", ratio=150.0, confidence=0.3),
            ],
        )
        assert calib.status == ScaleCalibrationStatus.CONFLICTING.value
        assert measurement_authority_for_page_scale(calib) == AuthorityStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# Valid title-block scale is still only provisional for measurement
# ---------------------------------------------------------------------------

class TestTitleBlockAlwaysProvisional:
    def test_valid_title_block_scale_produces_provisional_measurement(self):
        calib = resolve_page_scale_calibration(
            page_no=7,
            sheet_label="A-107",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.TITLE_BLOCK.value, scale_text="1:100", ratio=100.0, confidence=0.7)],
        )
        assert calib.status == ScaleCalibrationStatus.VALID.value
        assert measurement_authority_for_page_scale(calib) == AuthorityStatus.PROVISIONAL.value

    def test_valid_scale_bar_scale_can_be_firm(self):
        calib = resolve_page_scale_calibration(
            page_no=8,
            sheet_label="A-108",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:100", ratio=100.0, confidence=0.95)],
        )
        assert calib.status == ScaleCalibrationStatus.VALID.value
        assert measurement_authority_for_page_scale(calib) == AuthorityStatus.FIRM.value


# ---------------------------------------------------------------------------
# User-approved calibration authority
# ---------------------------------------------------------------------------

class TestUserApproval:
    def test_user_approved_calibration_produces_approved_authority_status(self):
        conflicted = resolve_page_scale_calibration(
            page_no=9,
            sheet_label="A-109",
            readings=[
                ScaleSourceReading(source_type=ScaleSourceType.TITLE_BLOCK.value, scale_text="1:100", ratio=100.0, confidence=0.6),
                ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:50", ratio=50.0, confidence=0.9),
            ],
        )
        assert conflicted.status == ScaleCalibrationStatus.MANUAL_REQUIRED.value

        approved = approve_page_scale_calibration(
            conflicted, approved_ratio=100.0, approved_by="Estimator A"
        )
        assert approved.status == ScaleCalibrationStatus.USER_APPROVED.value
        assert approved.approved_by == "Estimator A"
        assert measurement_authority_for_page_scale(approved) == AuthorityStatus.FIRM.value

    def test_approval_preserves_original_issue_list(self):
        conflicted = resolve_page_scale_calibration(
            page_no=10,
            sheet_label="A-110",
            readings=[
                ScaleSourceReading(source_type=ScaleSourceType.TITLE_BLOCK.value, scale_text="1:100", ratio=100.0, confidence=0.6),
                ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:50", ratio=50.0, confidence=0.9),
            ],
        )
        original_issues = list(conflicted.issues)
        approved = approve_page_scale_calibration(conflicted, approved_ratio=100.0, approved_by="Estimator A")
        for issue in original_issues:
            assert issue in approved.issues

    @pytest.mark.parametrize("bad_ratio", [0.0, -1.0, math.nan, math.inf])
    def test_approval_rejects_invalid_ratio(self, bad_ratio):
        calib = unknown_calibration(page_no=11, sheet_label="A-111")
        with pytest.raises(ValueError):
            approve_page_scale_calibration(calib, approved_ratio=bad_ratio, approved_by="Estimator A")


# ---------------------------------------------------------------------------
# NaN / inf / zero scale readings block
# ---------------------------------------------------------------------------

class TestNonFiniteScaleBlocks:
    @pytest.mark.parametrize("bad_ratio", [math.nan, math.inf, -math.inf, 0.0, -100.0])
    def test_nan_inf_zero_negative_ratio_blocks(self, bad_ratio):
        calib = resolve_page_scale_calibration(
            page_no=12,
            sheet_label="A-112",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="bad", ratio=bad_ratio, confidence=0.9)],
        )
        assert calib.status == ScaleCalibrationStatus.BLOCKED.value
        assert measurement_authority_for_page_scale(calib) == AuthorityStatus.BLOCKED.value
        assert len(calib.issues) >= 1


# ---------------------------------------------------------------------------
# Stale / revision-mismatched calibration blocks
# ---------------------------------------------------------------------------

class TestStaleRevisionBlocks:
    def test_stale_revision_mismatch_blocks(self):
        calib = resolve_page_scale_calibration(
            page_no=13,
            sheet_label="A-113",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:100", ratio=100.0, confidence=0.95)],
            revision_id="Rev-A",
        )
        assert calib.status == ScaleCalibrationStatus.VALID.value

        fresh = check_calibration_freshness(calib, current_revision_id="Rev-A")
        assert fresh.status == ScaleCalibrationStatus.VALID.value

        stale = check_calibration_freshness(calib, current_revision_id="Rev-B")
        assert stale.status == ScaleCalibrationStatus.BLOCKED.value
        assert measurement_authority_for_page_scale(stale) == AuthorityStatus.BLOCKED.value
        assert any("stale" in issue.lower() or "revision" in issue.lower() for issue in stale.issues)

    def test_unknown_current_revision_does_not_force_stale(self):
        calib = resolve_page_scale_calibration(
            page_no=14,
            sheet_label="A-114",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:100", ratio=100.0, confidence=0.95)],
            revision_id=None,
        )
        unchanged = check_calibration_freshness(calib, current_revision_id="Rev-Z")
        assert unchanged.status == ScaleCalibrationStatus.VALID.value


# ---------------------------------------------------------------------------
# Issue list is preserved for downstream publish gates
# ---------------------------------------------------------------------------

class TestIssueListPreservedForPublishGates:
    def test_conflict_issue_list_survives_registry_round_trip(self):
        registry = PageScaleCalibrationRegistry()
        calib = resolve_page_scale_calibration(
            page_no=15,
            sheet_label="A-115",
            readings=[
                ScaleSourceReading(source_type=ScaleSourceType.TITLE_BLOCK.value, scale_text="1:100", ratio=100.0, confidence=0.6),
                ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:50", ratio=50.0, confidence=0.9),
            ],
        )
        registry.set(15, calib)
        fetched = registry.get(15)
        assert fetched.issues == calib.issues
        assert len(fetched.issues) >= 1

    def test_every_calibration_record_carries_required_fields(self):
        calib = resolve_page_scale_calibration(
            page_no=16,
            sheet_label="A-116 Floor Plan",
            readings=[ScaleSourceReading(source_type=ScaleSourceType.SCALE_BAR.value, scale_text="1:100", ratio=100.0, confidence=0.95)],
        )
        assert isinstance(calib, ScaleCalibration)
        assert calib.page_no == 16
        assert calib.sheet_label == "A-116 Floor Plan"
        assert calib.scale_text == "1:100"
        assert calib.ratio_str == "1:100"
        assert 0.0 <= calib.confidence <= 1.0
        assert calib.source_type in {s.value for s in ScaleSourceType}
        assert calib.status in {s.value for s in ScaleCalibrationStatus}
        assert isinstance(calib.issues, list)
