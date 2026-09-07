"""tests/benchmarks/test_mutation_structural_bay_pillar_count.py

Mutation/red-team suite for pb_structural_bay_pillar_count.py: a row of N
equal (or near-equal) structural bays between two end supports requires
N+1 support points. Every value in this file is synthetic and invented
for this test — none are drawn from, or tuned to reproduce, any real
benchmark project's expected ground truth.
"""
from __future__ import annotations

import pytest

from pb_structural_bay_pillar_count import (
    derive_support_count_from_bay_chain,
    find_uniform_bay_runs,
)


class TestDeriveSupportCountFromBayChain:
    def test_three_equal_bays_yields_four_supports(self):
        result = derive_support_count_from_bay_chain([3.15, 3.15, 3.15])
        assert result.status == "resolved"
        assert result.bay_count == 3
        assert result.support_count == 4
        assert result.bay_spans_m == [3.15, 3.15, 3.15]

    def test_adding_a_fourth_bay_yields_five_supports(self):
        result = derive_support_count_from_bay_chain([3.15, 3.15, 3.15, 3.15])
        assert result.status == "resolved"
        assert result.bay_count == 4
        assert result.support_count == 5

    def test_near_equal_bays_within_tolerance_still_resolve(self):
        result = derive_support_count_from_bay_chain([3.15, 3.05, 3.20])
        assert result.status == "resolved"
        assert result.bay_count == 3
        assert result.support_count == 4

    def test_a_single_span_is_unresolved(self):
        result = derive_support_count_from_bay_chain([3.15])
        assert result.status == "unresolved"
        assert result.support_count is None
        assert result.notes

    def test_no_spans_at_all_is_unresolved(self):
        result = derive_support_count_from_bay_chain([])
        assert result.status == "unresolved"
        assert result.support_count is None

    def test_genuinely_dissimilar_spans_are_unresolved_not_averaged(self):
        # 1.2m and 6.0m are not the same structural bay pattern -- this
        # must never be silently averaged into a fake "typical bay".
        result = derive_support_count_from_bay_chain([1.2, 6.0])
        assert result.status == "unresolved"
        assert result.support_count is None

    def test_zero_and_negative_values_are_filtered_before_evaluation(self):
        result = derive_support_count_from_bay_chain([3.15, -1.0, 3.2, 0.0])
        assert result.status == "resolved"
        assert result.bay_count == 2
        assert result.support_count == 3
        assert result.bay_spans_m == [3.15, 3.2]

    def test_deviation_just_within_tolerance_resolves(self):
        # 3.0 and 3.24 differ by exactly 8% of their mean (3.12) -- right
        # at the default tolerance boundary.
        result = derive_support_count_from_bay_chain([3.0, 3.24], relative_tolerance=0.08)
        assert result.status == "resolved"

    def test_deviation_beyond_tolerance_is_unresolved(self):
        # 3.0 and 3.6 differ by ~9.1% of their mean (3.3) -- just past the
        # default 8% tolerance.
        result = derive_support_count_from_bay_chain([3.0, 3.6], relative_tolerance=0.08)
        assert result.status == "unresolved"

    def test_fewer_than_min_bays_is_unresolved_even_if_uniform(self):
        result = derive_support_count_from_bay_chain([3.15], min_bays=2)
        assert result.status == "unresolved"


class TestFindUniformBayRuns:
    def test_a_genuine_run_embedded_in_noise_is_found(self):
        # 0.9 (too small to be a bay) and 12.5 (too large) are filtered by
        # the plausibility range; only the three 3.15m values form a run.
        values = [0.9, 3.15, 3.15, 3.15, 12.5]
        runs = find_uniform_bay_runs(values)
        assert len(runs) == 1
        assert runs[0].bay_count == 3
        assert runs[0].support_count == 4

    def test_no_genuine_run_returns_empty(self):
        values = [1.2, 4.4, 2.9, 6.7]
        runs = find_uniform_bay_runs(values)
        assert runs == []

    def test_two_separate_runs_are_both_reported_independently(self):
        # A structural grid at ~3.15m and a completely separate, unrelated
        # run at ~2.10m elsewhere on the same page -- both are real, and
        # neither should be merged into or overwrite the other.
        values = [3.15, 3.15, 3.15, 7.5, 2.10, 2.10]
        runs = find_uniform_bay_runs(values)
        assert len(runs) == 2
        bay_counts = sorted(r.bay_count for r in runs)
        assert bay_counts == [2, 3]

    def test_a_run_shorter_than_min_bays_is_not_reported(self):
        values = [3.15, 7.7, 9.0]  # no two adjacent plausible-range values agree
        runs = find_uniform_bay_runs(values)
        assert runs == []

    def test_maximal_run_is_reported_not_a_shorter_prefix(self):
        values = [3.15, 3.15, 3.15, 3.15]
        runs = find_uniform_bay_runs(values)
        assert len(runs) == 1
        assert runs[0].bay_count == 4  # not 2 or 3 -- the full run
