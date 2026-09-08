"""tests/benchmarks/test_mutation_dimension_chain_evidence_extractor.py

Mutation/red-team suite for pb_dimension_chain_evidence_extractor: spatial
(word-bounding-box) reconstruction of collinear dimension chains, and
corroborated wall-thickness resolution across them. Every dimension value
in this file is synthetic and invented for this test.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_dimension_chain_evidence_extractor import (
    extract_dimension_chains_from_page,
    resolve_corroborated_wall_thickness_m,
)


def _make_page(tmp_path: Path, lines: list[str]) -> "fitz.Page":
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    # Re-open from bytes so get_text("words") reads back a fully committed page.
    pdf_bytes = doc.tobytes()
    doc.close()
    reopened = fitz.open(stream=pdf_bytes, filetype="pdf")
    return reopened[0]


class TestChainReconstruction:
    def test_two_distinct_lines_produce_two_separate_chains(self, tmp_path: Path) -> None:
        page = _make_page(tmp_path, ["150 9,850 150", "150 3,000 150"])
        chains = extract_dimension_chains_from_page(page, page_num=1)
        assert len(chains) == 2
        values_by_chain = [[o.value_m for o in c.observations] for c in chains]
        assert [0.15, 9.85, 0.15] in values_by_chain
        assert [0.15, 3.0, 0.15] in values_by_chain

    def test_observations_within_a_row_are_ordered_left_to_right(self, tmp_path: Path) -> None:
        page = _make_page(tmp_path, ["150 9,850 150"])
        chains = extract_dimension_chains_from_page(page, page_num=1)
        assert len(chains) == 1
        xs = [o.bbox[0] for o in chains[0].observations]
        assert xs == sorted(xs)

    def test_non_dimension_text_contributes_no_chain(self, tmp_path: Path) -> None:
        page = _make_page(tmp_path, ["GROUND FLOOR PLAN", "SCALE 1:100"])
        chains = extract_dimension_chains_from_page(page, page_num=1)
        assert chains == []

    def test_year_like_token_is_excluded_from_a_chain(self, tmp_path: Path) -> None:
        # "2024" is 4-digit-shaped like a dimension token but must be
        # rejected as a bare calendar year, not folded into a chain.
        page = _make_page(tmp_path, ["150 2024 9,850 150"])
        chains = extract_dimension_chains_from_page(page, page_num=1)
        assert len(chains) == 1
        values = [o.value_m for o in chains[0].observations]
        assert 2.024 not in values
        assert values == [0.15, 9.85, 0.15]


class TestCorroboratedWallThickness:
    def test_two_independent_chains_agreeing_resolve_thickness(self, tmp_path: Path) -> None:
        page = _make_page(tmp_path, ["150 9,850 150", "150 3,000 150"])
        chains = extract_dimension_chains_from_page(page, page_num=1)
        thickness = resolve_corroborated_wall_thickness_m(chains)
        assert thickness == 0.15

    def test_single_chain_alone_does_not_resolve(self, tmp_path: Path) -> None:
        # Real project finding: a single chain's own classification is not
        # trustworthy enough on its own -- at least two independent chains
        # must agree.
        page = _make_page(tmp_path, ["150 9,850 150"])
        chains = extract_dimension_chains_from_page(page, page_num=1)
        assert resolve_corroborated_wall_thickness_m(chains) is None

    def test_degenerate_all_equal_chains_never_corroborate(self, tmp_path: Path) -> None:
        # Real false positive found against a live project PDF: a repeated
        # rebar-spacing / fill-thickness callout ("200 200 200 200 200
        # 200") on a structural detail sheet independently satisfies the
        # wall-thickness plausibility range at both ends, even repeated
        # across two such rows -- neither is a wall-span-wall bracket and
        # must never corroborate into a resolved thickness.
        page = _make_page(tmp_path, ["200 200 200", "200 200 200 200"])
        chains = extract_dimension_chains_from_page(page, page_num=1)
        assert resolve_corroborated_wall_thickness_m(chains) is None

    def test_disagreeing_thickness_candidates_do_not_corroborate(self, tmp_path: Path) -> None:
        page = _make_page(tmp_path, ["150 9,850 150", "250 3,000 250"])
        chains = extract_dimension_chains_from_page(page, page_num=1)
        assert resolve_corroborated_wall_thickness_m(chains) is None

    def test_no_chains_resolves_to_none(self) -> None:
        assert resolve_corroborated_wall_thickness_m([]) is None
