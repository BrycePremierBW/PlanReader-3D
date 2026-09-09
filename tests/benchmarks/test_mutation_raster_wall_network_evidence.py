"""Mutation/metamorphic tests for F.31 raster wall-network evidence."""
from __future__ import annotations

import inspect
from pathlib import Path

import fitz
import pytest

from pb_raster_wall_network_evidence import resolve_raster_wall_network


BLACK = (0, 0, 0)


def _filled_rect(page: fitz.Page, rect: fitz.Rect) -> None:
    page.draw_rect(rect, color=BLACK, fill=BLACK, width=0.1, overlay=True)


def _make_plan(
    *,
    x0: float = 100.0,
    y0: float = 100.0,
    horizontal_span_m: float = 10.0,
    vertical_span_m: float = 6.0,
    points_per_m: float = 40.0,
    wall_thickness_m: float = 0.2,
    include_partitions: bool = True,
    include_benches: bool = True,
    second_outer: bool = False,
):
    doc = fitz.open()
    page = doc.new_page(width=900, height=700)
    width = horizontal_span_m * points_per_m
    height = vertical_span_m * points_per_m
    t = wall_thickness_m * points_per_m
    x1 = x0 + width
    y1 = y0 + height

    # Four exterior masonry bands, entirely inside the figured outer faces.
    _filled_rect(page, fitz.Rect(x0, y0, x1, y0 + t))
    _filled_rect(page, fitz.Rect(x0, y1 - t, x1, y1))
    _filled_rect(page, fitz.Rect(x0, y0, x0 + t, y1))
    _filled_rect(page, fitz.Rect(x1 - t, y0, x1, y1))

    if include_partitions:
        # Main internal divider: boundary-to-boundary with a 1.0m door gap.
        vx0 = x0 + 5.0 * points_per_m
        _filled_rect(page, fitz.Rect(vx0, y0 + t, vx0 + t, y0 + 3.0 * points_per_m))
        _filled_rect(page, fitz.Rect(vx0, y0 + 4.0 * points_per_m, vx0 + t, y1 - t))

        # Horizontal branch from main divider to right exterior.  Its 0.9m
        # opening remains a gap in the evidence rather than counted masonry.
        hy0 = y0 + 3.0 * points_per_m
        _filled_rect(page, fitz.Rect(vx0 + t, hy0, x0 + 7.5 * points_per_m, hy0 + t))
        _filled_rect(page, fitz.Rect(x0 + 8.4 * points_per_m, hy0, x1 - t, hy0 + t))

        # Shorter top-room divider: top exterior to horizontal branch.
        vx2 = x0 + 7.5 * points_per_m
        _filled_rect(page, fitz.Rect(vx2, y0 + t, vx2 + t, hy0))

    if include_benches:
        # Long, wall-thickness-like furniture/service units.  They are
        # deliberately disconnected from the masonry network and must not be
        # accepted merely because they are parallel double-line rectangles.
        for offset_m in (1.1, 2.0, 3.0):
            bx = x0 + offset_m * points_per_m
            _filled_rect(
                page,
                fitz.Rect(
                    bx,
                    y0 + 1.2 * points_per_m,
                    bx + t,
                    y0 + 4.7 * points_per_m,
                ),
            )

    if second_outer:
        sx0 = 560.0
        sy0 = 370.0
        sx1 = sx0 + width
        sy1 = sy0 + height
        # Keep within page by using a separate landscape-sized page if needed.
        if sx1 > page.rect.width or sy1 > page.rect.height:
            # The test caller uses a compact second rectangle; this fallback is
            # defensive and should not normally run.
            sx0 = 20.0
            sy0 = 390.0
            sx1 = sx0 + width
            sy1 = sy0 + height
        _filled_rect(page, fitz.Rect(sx0, sy0, sx1, sy0 + t))
        _filled_rect(page, fitz.Rect(sx0, sy1 - t, sx1, sy1))
        _filled_rect(page, fitz.Rect(sx0, sy0, sx0 + t, sy1))
        _filled_rect(page, fitz.Rect(sx1 - t, sy0, sx1, sy1))

    return doc, page


def test_recovers_connected_partition_network_and_rejects_benches():
    doc, page = _make_plan()
    try:
        result = resolve_raster_wall_network(
            page,
            horizontal_span_m=10.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.2,
            source_page=1,
        )
        assert result is not None
        assert result.scale_relative_error < 0.02
        assert result.wall_thickness_m == pytest.approx(0.2)
        assert len(result.partition_runs) == 3

        vertical = [run for run in result.partition_runs if run.orientation == "vertical"]
        horizontal = [run for run in result.partition_runs if run.orientation == "horizontal"]
        assert len(vertical) == 2
        assert len(horizontal) == 1

        # Main divider spans essentially the full 6m building depth and carries
        # the deliberately inserted 1m opening.
        main = max(vertical, key=lambda run: run.span_length_m)
        assert main.span_length_m == pytest.approx(6.0, abs=0.25)
        assert any(0.75 <= gap <= 1.25 for gap in main.opening_gaps_m)
        assert main.boundary_connection_count >= 2

        # The three disconnected furniture bands would otherwise look like
        # legitimate 200mm double-line walls.  If they leaked through there
        # would be at least five vertical partition runs.
        assert len(vertical) == 2
        assert result.solid_partition_length_m < result.spanned_partition_length_m
        assert all(run.edge_separation_m == pytest.approx(0.2, abs=0.06) for run in result.partition_runs)
    finally:
        doc.close()


def test_disconnected_wall_thickness_like_furniture_does_not_form_network():
    doc, page = _make_plan(include_partitions=False, include_benches=True)
    try:
        assert resolve_raster_wall_network(
            page,
            horizontal_span_m=10.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.2,
        ) is None
    finally:
        doc.close()


def test_wrong_independent_horizontal_span_breaks_scale_corroboration():
    doc, page = _make_plan()
    try:
        assert resolve_raster_wall_network(
            page,
            horizontal_span_m=12.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.2,
        ) is None
    finally:
        doc.close()


def test_wall_thickness_mutation_must_match_raster_double_line_spacing():
    doc, page = _make_plan()
    try:
        good = resolve_raster_wall_network(
            page,
            horizontal_span_m=10.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.2,
        )
        bad = resolve_raster_wall_network(
            page,
            horizontal_span_m=10.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.4,
        )
        assert good is not None
        assert bad is None
    finally:
        doc.close()


def test_translation_preserves_metric_wall_network():
    doc_a, page_a = _make_plan(x0=100.0, y0=100.0)
    doc_b, page_b = _make_plan(x0=180.0, y0=180.0)
    try:
        a = resolve_raster_wall_network(
            page_a,
            horizontal_span_m=10.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.2,
        )
        b = resolve_raster_wall_network(
            page_b,
            horizontal_span_m=10.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.2,
        )
        assert a is not None and b is not None
        assert a.solid_partition_length_m == pytest.approx(b.solid_partition_length_m, abs=0.08)
        assert a.spanned_partition_length_m == pytest.approx(b.spanned_partition_length_m, abs=0.08)
        assert [r.orientation for r in a.partition_runs] == [r.orientation for r in b.partition_runs]
    finally:
        doc_a.close()
        doc_b.close()


def test_uniform_scale_mutation_preserves_metric_network():
    doc_a, page_a = _make_plan(points_per_m=32.0)
    doc_b, page_b = _make_plan(points_per_m=46.0)
    try:
        a = resolve_raster_wall_network(
            page_a,
            horizontal_span_m=10.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.2,
        )
        b = resolve_raster_wall_network(
            page_b,
            horizontal_span_m=10.0,
            vertical_span_m=6.0,
            wall_thickness_m=0.2,
        )
        assert a is not None and b is not None
        assert a.px_per_m != pytest.approx(b.px_per_m)
        assert a.solid_partition_length_m == pytest.approx(b.solid_partition_length_m, abs=0.12)
        assert a.spanned_partition_length_m == pytest.approx(b.spanned_partition_length_m, abs=0.12)
    finally:
        doc_a.close()
        doc_b.close()


def test_two_comparable_outer_rectangles_fail_closed():
    # Compact 6m x 4m geometry fits two independent candidates on one page.
    doc = fitz.open()
    page = doc.new_page(width=900, height=700)
    ppm = 38.0
    t = 0.2 * ppm

    def outer(x0: float, y0: float):
        x1, y1 = x0 + 6.0 * ppm, y0 + 4.0 * ppm
        _filled_rect(page, fitz.Rect(x0, y0, x1, y0 + t))
        _filled_rect(page, fitz.Rect(x0, y1 - t, x1, y1))
        _filled_rect(page, fitz.Rect(x0, y0, x0 + t, y1))
        _filled_rect(page, fitz.Rect(x1 - t, y0, x1, y1))
        # Add a simple boundary-connected internal cross so either outer box
        # would otherwise be a valid wall network.
        vx = x0 + 3.0 * ppm
        _filled_rect(page, fitz.Rect(vx, y0 + t, vx + t, y1 - t))
        hy = y0 + 2.0 * ppm
        _filled_rect(page, fitz.Rect(vx + t, hy, x1 - t, hy + t))

    outer(70, 70)
    outer(500, 380)
    try:
        assert resolve_raster_wall_network(
            page,
            horizontal_span_m=6.0,
            vertical_span_m=4.0,
            wall_thickness_m=0.2,
        ) is None
    finally:
        doc.close()


def test_invalid_or_missing_authority_inputs_fail_closed():
    doc, page = _make_plan()
    try:
        for kwargs in (
            {"horizontal_span_m": 0.0, "vertical_span_m": 6.0, "wall_thickness_m": 0.2},
            {"horizontal_span_m": 10.0, "vertical_span_m": 0.0, "wall_thickness_m": 0.2},
            {"horizontal_span_m": 10.0, "vertical_span_m": 6.0, "wall_thickness_m": 0.0},
            {"horizontal_span_m": 10.0, "vertical_span_m": 6.0, "wall_thickness_m": float("nan")},
        ):
            assert resolve_raster_wall_network(page, **kwargs) is None
    finally:
        doc.close()


def test_module_has_no_benchmark_or_expected_answer_access():
    import pb_raster_wall_network_evidence as module

    source = inspect.getsource(module).lower()
    forbidden = [
        "tenders_ke_",
        "ghazi",
        "kstvet",
        "murera",
        "umma",
        "expected_boq_summary",
        "benchmark_rules",
        "expected_quantity",
    ]
    for term in forbidden:
        assert term not in source
