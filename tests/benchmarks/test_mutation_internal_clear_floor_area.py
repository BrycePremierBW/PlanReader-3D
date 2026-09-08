"""tests/benchmarks/test_mutation_internal_clear_floor_area.py

Mutation/red-team suite for pb_internal_clear_floor_area (Phase F.21):
converting an evidenced outer envelope + corroborated wall thickness
into an internal clear floor-finish area. Every dimension in this file
is synthetic and invented for this test -- no benchmark IDs, expected
quantities, or project-specific constants.
"""
from __future__ import annotations

import math

from pb_internal_clear_floor_area import derive_internal_clear_floor_area


class TestGenuineResolution:
    def test_corroborated_thickness_shrinks_area_by_the_rectangle_formula(self) -> None:
        result = derive_internal_clear_floor_area(12.0, 8.0, 0.2)
        assert result.status == "resolved"
        assert result.internal_clear_length_m == 11.6
        assert result.internal_clear_width_m == 7.6
        assert result.internal_clear_area_m2 == round(11.6 * 7.6, 4)

    def test_mutating_thickness_changes_result_deterministically(self) -> None:
        thin = derive_internal_clear_floor_area(20.0, 10.0, 0.1)
        thick = derive_internal_clear_floor_area(20.0, 10.0, 0.3)
        assert thin.internal_clear_area_m2 != thick.internal_clear_area_m2
        assert thick.internal_clear_area_m2 < thin.internal_clear_area_m2
        # Re-running with the same inputs is exactly reproducible.
        again = derive_internal_clear_floor_area(20.0, 10.0, 0.1)
        assert again.internal_clear_area_m2 == thin.internal_clear_area_m2

    def test_mutating_envelope_dimensions_changes_result_deterministically(self) -> None:
        a = derive_internal_clear_floor_area(15.0, 9.0, 0.15)
        b = derive_internal_clear_floor_area(16.0, 9.0, 0.15)
        assert a.internal_clear_area_m2 != b.internal_clear_area_m2


class TestFailClosed:
    def test_missing_thickness_leaves_unresolved(self) -> None:
        result = derive_internal_clear_floor_area(12.0, 8.0, None)
        assert result.status == "unresolved"
        assert result.internal_clear_area_m2 is None

    def test_missing_envelope_dimension_leaves_unresolved(self) -> None:
        assert derive_internal_clear_floor_area(None, 8.0, 0.2).status == "unresolved"
        assert derive_internal_clear_floor_area(12.0, None, 0.2).status == "unresolved"

    def test_excessive_thickness_fails_closed_not_zero_or_negative(self) -> None:
        # Thickness so large it would make a clear dimension non-positive.
        result = derive_internal_clear_floor_area(1.0, 8.0, 0.6)
        assert result.status == "unresolved"
        assert result.internal_clear_area_m2 is None
        assert "non-positive" in result.notes

    def test_exactly_zero_clear_dimension_fails_closed(self) -> None:
        result = derive_internal_clear_floor_area(1.0, 8.0, 0.5)
        assert result.status == "unresolved"

    def test_non_positive_thickness_fails_closed(self) -> None:
        assert derive_internal_clear_floor_area(12.0, 8.0, 0.0).status == "unresolved"
        assert derive_internal_clear_floor_area(12.0, 8.0, -0.1).status == "unresolved"

    def test_non_positive_envelope_dimension_fails_closed(self) -> None:
        assert derive_internal_clear_floor_area(0.0, 8.0, 0.2).status == "unresolved"
        assert derive_internal_clear_floor_area(-5.0, 8.0, 0.2).status == "unresolved"

    def test_non_finite_input_fails_closed(self) -> None:
        assert derive_internal_clear_floor_area(math.inf, 8.0, 0.2).status == "unresolved"
        assert derive_internal_clear_floor_area(12.0, math.nan, 0.2).status == "unresolved"


def test_no_benchmark_ids_expected_quantities_or_project_identity_in_module() -> None:
    import inspect
    import pb_internal_clear_floor_area as module

    source = inspect.getsource(module)
    for forbidden in (
        "KSTVET", "Murera", "kstvet", "murera",
        "13.70", "7.52", "96.748", "97.0", "97.56",
        "expected_quantity", "benchmark_id",
    ):
        assert forbidden not in source, f"leakage: {forbidden!r} found in module source"
