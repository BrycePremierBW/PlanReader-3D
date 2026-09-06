"""tests/geometry/test_figured_dimension_authority.py — Figured-dimension measurement authority.

Covers text extraction/normalization (mm and m units), figured-vs-scaled precedence,
delta tracking and tolerance warnings, fail-closed rejection of malformed/negative/
zero/non-finite dimension values, and scale-reliability-gated fallback to provisional
scaled geometry.
"""
from __future__ import annotations

import math

import pytest

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_figured_dimension_authority import (
    DimensionParseError,
    MeasurementAuthorityResult,
    parse_figured_dimension_mm,
    resolve_measurement_authority,
)


# ---------------------------------------------------------------------------
# parse_figured_dimension_mm — text extraction/normalization
# ---------------------------------------------------------------------------

class TestParseFiguredDimensionMm:
    def test_bare_number_defaults_to_mm(self):
        assert parse_figured_dimension_mm("6500") == pytest.approx(6500.0)

    def test_explicit_mm_suffix(self):
        assert parse_figured_dimension_mm("6500mm") == pytest.approx(6500.0)
        assert parse_figured_dimension_mm("6500 mm") == pytest.approx(6500.0)
        assert parse_figured_dimension_mm("6500MM") == pytest.approx(6500.0)

    def test_metre_suffix_converts_to_mm(self):
        assert parse_figured_dimension_mm("6.5m") == pytest.approx(6500.0)
        assert parse_figured_dimension_mm("6.5 M") == pytest.approx(6500.0)

    def test_thousands_separator_supported(self):
        assert parse_figured_dimension_mm("6,500mm") == pytest.approx(6500.0)

    def test_decimal_mm_supported(self):
        assert parse_figured_dimension_mm("6500.5mm") == pytest.approx(6500.5)

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_empty_or_missing_is_malformed(self, raw):
        with pytest.raises(DimensionParseError):
            parse_figured_dimension_mm(raw)

    @pytest.mark.parametrize("raw", ["GG50mm", "approx 6500", "6500mm approx", "six thousand", "6500cm"])
    def test_unparseable_text_is_malformed(self, raw):
        with pytest.raises(DimensionParseError):
            parse_figured_dimension_mm(raw)

    @pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "infinity", "-inf"])
    def test_nan_and_infinite_literals_are_malformed(self, raw):
        with pytest.raises(DimensionParseError):
            parse_figured_dimension_mm(raw)

    @pytest.mark.parametrize("raw", ["0", "0mm", "0.0m"])
    def test_zero_is_rejected(self, raw):
        with pytest.raises(DimensionParseError):
            parse_figured_dimension_mm(raw)

    @pytest.mark.parametrize("raw", ["-500mm", "-1m"])
    def test_negative_is_rejected(self, raw):
        with pytest.raises(DimensionParseError):
            parse_figured_dimension_mm(raw)


# ---------------------------------------------------------------------------
# resolve_measurement_authority — figured beats scaled precedence
# ---------------------------------------------------------------------------

class TestFiguredBeatsScaled:
    def test_figured_6500_beats_scaled_6480(self):
        result = resolve_measurement_authority(figured_text="6500mm", scaled_mm=6480.0)
        assert result.value_m == pytest.approx(6.5)
        assert result.source_type == MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
        assert result.authority_status == AuthorityStatus.FIRM.value

    def test_delta_recorded_as_20mm(self):
        result = resolve_measurement_authority(figured_text="6500mm", scaled_mm=6480.0)
        assert result.scaled_delta_mm == pytest.approx(20.0)

    def test_small_delta_passes_with_info(self):
        # 20mm on 6500mm = 0.31%, well under the 5% tolerance -> passes, but the
        # delta is still surfaced as informational metadata, not silently dropped.
        result = resolve_measurement_authority(figured_text="6500mm", scaled_mm=6480.0)
        assert result.authority_status == AuthorityStatus.FIRM.value
        assert result.scaled_delta_mm == pytest.approx(20.0)
        assert "delta" in result.notes.lower()

    def test_large_delta_returns_review_required_with_warning(self):
        # 1500mm on 6500mm = 23%, over the 5% tolerance.
        result = resolve_measurement_authority(figured_text="6500mm", scaled_mm=8000.0)
        assert result.authority_status == AuthorityStatus.REVIEW_REQUIRED.value
        assert result.scaled_delta_mm == pytest.approx(1500.0)
        assert "warning" in result.notes.lower() or "exceed" in result.notes.lower()

    def test_figured_via_metres_input_matches_mm_input(self):
        via_m = resolve_measurement_authority(figured_text="6.5m", scaled_mm=6480.0)
        via_mm = resolve_measurement_authority(figured_text="6500mm", scaled_mm=6480.0)
        assert via_m.value_m == pytest.approx(via_mm.value_m)
        assert via_m.scaled_delta_mm == pytest.approx(via_mm.scaled_delta_mm)

    def test_figured_without_scaled_is_firm_with_no_delta(self):
        result = resolve_measurement_authority(figured_text="6200mm", scaled_mm=None)
        assert result.value_m == pytest.approx(6.2)
        assert result.authority_status == AuthorityStatus.FIRM.value
        assert result.scaled_delta_mm is None


# ---------------------------------------------------------------------------
# Fail-closed rejection of malformed/negative/zero/non-finite figured values
# ---------------------------------------------------------------------------

class TestMalformedDimensionBlocks:
    def test_malformed_figured_text_blocks_even_with_valid_scaled(self):
        result = resolve_measurement_authority(
            figured_text="GG50mm", scaled_mm=6500.0, scale_reliable=True
        )
        assert result.authority_status == AuthorityStatus.BLOCKED.value
        assert result.value_m is None

    def test_negative_figured_value_blocks(self):
        result = resolve_measurement_authority(figured_text="-500mm", scaled_mm=6500.0)
        assert result.authority_status == AuthorityStatus.BLOCKED.value

    def test_zero_figured_value_blocks(self):
        result = resolve_measurement_authority(figured_text="0mm", scaled_mm=6500.0)
        assert result.authority_status == AuthorityStatus.BLOCKED.value

    def test_nan_figured_mm_direct_value_blocks(self):
        result = resolve_measurement_authority(figured_mm=math.nan, scaled_mm=6500.0)
        assert result.authority_status == AuthorityStatus.BLOCKED.value

    def test_infinite_figured_mm_direct_value_blocks(self):
        result = resolve_measurement_authority(figured_mm=math.inf, scaled_mm=6500.0)
        assert result.authority_status == AuthorityStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# Missing figured dimension: fallback to scaled is gated on scale reliability
# ---------------------------------------------------------------------------

class TestScaleReliabilityGatesFallback:
    def test_missing_dimension_falls_back_to_scaled_provisional_when_reliable(self):
        result = resolve_measurement_authority(scaled_mm=6500.0, scale_reliable=True)
        assert result.authority_status == AuthorityStatus.PROVISIONAL.value
        assert result.source_type == MeasurementAuthorityType.PDF_SCALED.value
        assert result.value_m == pytest.approx(6.5)

    def test_unreliable_scale_and_no_figured_blocks(self):
        result = resolve_measurement_authority(scaled_mm=6500.0, scale_reliable=False)
        assert result.authority_status == AuthorityStatus.BLOCKED.value
        assert result.value_m is None

    def test_unreliable_scale_is_ignored_even_if_numerically_valid(self):
        # A numerically valid px-derived mm value must not silently become
        # provisional truth when the page's scale itself was never calibrated.
        reliable = resolve_measurement_authority(scaled_mm=6500.0, scale_reliable=True)
        unreliable = resolve_measurement_authority(scaled_mm=6500.0, scale_reliable=False)
        assert reliable.authority_status != unreliable.authority_status

    def test_nothing_provided_blocks(self):
        result = resolve_measurement_authority(scaled_mm=None, scale_reliable=True)
        assert result.authority_status == AuthorityStatus.BLOCKED.value

    def test_invalid_scaled_value_treated_as_unavailable(self):
        result = resolve_measurement_authority(scaled_mm=math.nan, scale_reliable=True)
        assert result.authority_status == AuthorityStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# Every result carries authority metadata
# ---------------------------------------------------------------------------

class TestResultAlwaysCarriesAuthorityMetadata:
    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(figured_text="6500mm", scaled_mm=6480.0),
            dict(figured_text="6500mm", scaled_mm=8000.0),
            dict(figured_text="6200mm", scaled_mm=None),
            dict(scaled_mm=6500.0, scale_reliable=True),
            dict(scaled_mm=6500.0, scale_reliable=False),
            dict(figured_text="GG50mm", scaled_mm=6500.0),
            dict(scaled_mm=None, scale_reliable=True),
        ],
    )
    def test_result_always_has_source_type_and_authority_status(self, kwargs):
        result = resolve_measurement_authority(**kwargs)
        assert isinstance(result, MeasurementAuthorityResult)
        assert result.authority_status in {s.value for s in AuthorityStatus}
        # source_type is None only for the "nothing at all was provided" case.
        if kwargs.get("scaled_mm") is not None or kwargs.get("figured_text") is not None:
            assert result.source_type is not None
        assert result.authority_status  # always populated, never blank
