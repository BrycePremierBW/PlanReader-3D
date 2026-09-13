"""Adversarial test suite for pb_wall_room_topology_wall_band_evidence.

This exists because an independent validation pass proved a prior research
model's (PR #273's) tier semantics were epistemically unsound: it accepted
room-width pairs and thin frame/glazing pairs as strong "wall" evidence, let
one-hop connectivity and W5 room-boundary participation stand in as
"independent" corroboration when both are circular, and could never
distinguish a real recurring wall thickness from an isolated coincidental
pairing. Every fixture below reproduces one of the specific failure classes
that validation named, plus positive controls proving the replacement model
still recognizes real wall geometry.

None of this is wired into W4's WallCandidate construction or into
HostedOpeningWallBinding -- see the module's own docstring. These tests
validate the STANDALONE evidence model against WallCandidate objects built
by the real, unmodified W1-W4 pipeline.
"""
from __future__ import annotations

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_topology
from pb_wall_room_topology_wall_band_evidence import (
    REASON_BAND_CONTINUITY,
    REASON_INCONSISTENT_LOCAL_THICKNESS,
    REASON_ISOLATED_LOCAL_PAIR,
    REASON_NO_EVIDENCE,
    REASON_REPEATED_MODE,
    REASON_SYMBOL_LIKE,
    rank_wall_band_evidence,
)


def _seg(seg_id, x1, y1, x2, y2, **overrides):
    base = {
        "id": seg_id,
        "kind": "line",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "width": 1.0,
        "stroke": (0, 0, 0),
        "fill": None,
        "layer": "",
        "dashes": "",
    }
    base.update(overrides)
    return base


def _assemble(segments):
    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id="doc_1", page_id="p1", viewport_id="vp_1"
    )
    walls, _ = assemble_wall_topology(graph, junctions, relationships, viewport_id="vp_1")
    return walls


def _by_endpoints(walls, p1, p2):
    p1 = tuple(round(c, 3) for c in p1)
    p2 = tuple(round(c, 3) for c in p2)
    for w in walls:
        wp1 = tuple(round(c, 3) for c in w.centerline_pts[0])
        wp2 = tuple(round(c, 3) for c in w.centerline_pts[-1])
        if {wp1, wp2} == {p1, p2}:
            return w
    raise AssertionError(f"no wall with endpoints {p1}/{p2}")


def _evidence_by_id(walls, **kwargs):
    """Test convenience only: rank_wall_band_evidence returns a list
    positionally aligned with ``walls`` (see its own docstring for why --
    real data can produce two WallCandidates sharing one candidate_id, and
    a dict would silently drop one). None of these synthetic fixtures ever
    produce a duplicate id, so zipping into a dict here is safe and keeps
    the adversarial assertions below readable by id."""
    evidence = rank_wall_band_evidence(walls, **kwargs)
    return dict(zip((w.candidate_id for w in walls), evidence))


# ---------------------------------------------------------------------------
# A. Required validation-failure regressions -- each of these MUST now be
# rejected or kept weak, per the independent validation's own findings.
# ---------------------------------------------------------------------------


def test_furniture_loop_gets_zero_pairing_evidence():
    """A small closed rectangle (furniture symbol): opposite sides pass the
    parallel/gap/overlap test superficially, exactly like a real double-line
    wall's two faces -- but they are the two opposite sides of ONE closed
    quadrilateral, not two faces of one wall. Must get ZERO pairing
    hypotheses at all (not merely fail to reach CORROBORATED) -- there is no
    W5 room-face signal in this module at all to fall back on."""
    walls = _assemble(
        [
            _seg("f0", 500.0, 500.0, 520.0, 500.0),
            _seg("f1", 520.0, 500.0, 520.0, 515.0),
            _seg("f2", 520.0, 515.0, 500.0, 515.0),
            _seg("f3", 500.0, 515.0, 500.0, 500.0),
        ]
    )
    evidence = _evidence_by_id(walls)
    for w in walls:
        ev = evidence[w.candidate_id]
        assert ev.status == EvidenceResolutionStatus.ABSTAINED
        assert ev.reason_codes == (REASON_NO_EVIDENCE,)


def test_hatch_tick_touching_evidenced_neighbor_gains_no_authority():
    """A single 45-degree hatch tick attached at one end to a genuine,
    strongly-evidenced paired-face wall. There is no bare-connectivity
    signal in this model at all -- touching an evidenced neighbour, with no
    pairing hypothesis of the tick's own, must stay ABSTAINED."""
    walls = _assemble(
        [
            _seg("wall_a", 0.0, 0.0, 300.0, 0.0),
            _seg("wall_b", 0.0, 12.0, 300.0, 12.0),
            _seg("tick", 150.0, 0.0, 156.0, 6.0),
        ]
    )
    evidence = _evidence_by_id(walls)
    tick = _by_endpoints(walls, (150.0, 0.0), (156.0, 6.0))
    ev = evidence[tick.candidate_id]
    assert ev.status == EvidenceResolutionStatus.ABSTAINED
    assert ev.reason_codes == (REASON_NO_EVIDENCE,)


def test_isolated_room_width_pair_never_reaches_corroborated():
    """Two long parallel lines ~0.97m apart (a real room-width separation,
    not a wall thickness) -- isolated: nowhere else in this drawing does
    anything else pair at a similar gap, and nothing else is topologically
    adjacent at a matching thickness. Falls inside the same broad
    plausible-gap window this module must accept SOME real wall thicknesses
    through (no project-specific cutoff), so the only thing that can
    legitimately keep it out of CORROBORATED is the independence
    requirement itself."""
    scale_pt_per_m = 30.0
    gap_pt = 0.97 * scale_pt_per_m  # 29.1pt -- inside [1.5, 40]
    walls = _assemble(
        [
            _seg("room_a", 0.0, 0.0, 400.0, 0.0),
            _seg("room_b", 0.0, gap_pt, 400.0, gap_pt),
        ]
    )
    evidence = _evidence_by_id(walls, scale_pt_per_m=scale_pt_per_m)
    for w in walls:
        ev = evidence[w.candidate_id]
        assert ev.status != EvidenceResolutionStatus.CORROBORATED
        assert ev.reason_codes == (REASON_ISOLATED_LOCAL_PAIR,)


def test_closed_single_line_room_stays_non_authoritative():
    """A plain single-line rectangle (no double-line convention): under the
    old model this reached CANDIDATE purely via W5 room-boundary
    participation. This module has no room-face concept at all, so every
    side must simply have no evidence."""
    walls = _assemble(
        [
            _seg("s0", 0.0, 0.0, 300.0, 0.0),
            _seg("s1", 300.0, 0.0, 300.0, 200.0),
            _seg("s2", 300.0, 200.0, 0.0, 200.0),
            _seg("s3", 0.0, 200.0, 0.0, 0.0),
        ]
    )
    evidence = _evidence_by_id(walls)
    for w in walls:
        assert evidence[w.candidate_id].status == EvidenceResolutionStatus.ABSTAINED


def test_stepped_parallel_ladder_flagged_symbol_like():
    """A repeated stepped/rung pattern (e.g. a fence, a stair-tread hatch,
    a repeated furniture ladder): several SHORT parallel-pair "rungs" at the
    SAME (gap, length) shape, at spatially distinct positions along a long
    run. Each rung individually passes the parallel/gap/overlap/local-
    consistency test exactly like a genuine short wall return would -- the
    only thing that can distinguish it generically is that the EXACT shape
    repeats identically many times, which real, individually-dimensioned
    wall returns essentially never do."""
    segments = []
    for i in range(5):
        x0 = i * 60.0
        segments.append(_seg(f"top_{i}", x0, 0.0, x0 + 18.0, 0.0))
        segments.append(_seg(f"bot_{i}", x0, 8.0, x0 + 18.0, 8.0))
    walls = _assemble(segments)
    evidence = _evidence_by_id(walls)
    for w in walls:
        ev = evidence[w.candidate_id]
        assert ev.status == EvidenceResolutionStatus.ABSTAINED
        assert ev.reason_codes == (REASON_SYMBOL_LIKE,)


def test_repeating_stub_pattern_not_promoted_to_wall_thickness():
    """A KSTVET-shaped case: many short, IDENTICAL stubs at one recurring
    thickness (e.g. 0.63m at some scale) -- superficially exactly what the
    repeated-thickness-MODE signal looks for, but the identical-shape
    repetition check must veto it before mode-clustering ever gets to
    promote it, since these are the same shape stamped repeatedly, not
    independently-dimensioned wall runs that happen to share a thickness."""
    scale_pt_per_m = 30.0
    gap_pt = 0.63 * scale_pt_per_m  # ~18.9pt
    segments = []
    for i in range(4):
        x0 = i * 40.0
        segments.append(_seg(f"top_{i}", x0, 0.0, x0 + 14.0, 0.0))
        segments.append(_seg(f"bot_{i}", x0, gap_pt, x0 + 14.0, gap_pt))
    walls = _assemble(segments)
    evidence = _evidence_by_id(walls, scale_pt_per_m=scale_pt_per_m)
    for w in walls:
        ev = evidence[w.candidate_id]
        assert ev.status == EvidenceResolutionStatus.ABSTAINED
        assert ev.reason_codes == (REASON_SYMBOL_LIKE,)


def test_isolated_glazing_frame_gap_never_becomes_masonry():
    """A single, isolated thin gap in the real glazing/frame range
    (55-78mm) -- must not become masonry merely from passing the pairing
    test once. No hardcoded "reject 55-78mm" rule exists anywhere in the
    model; this must fall out of the independence requirement alone, the
    same mechanism that rejects the isolated room-width pair above."""
    # A scale where 65mm lands safely above Stage A's own 2.5pt node-snap
    # tolerance (below it, build_wall_graph_for_viewport would snap the two
    # faces' endpoints together before this module ever sees two separate
    # candidates to pair -- a real, generic interaction with the upstream
    # pipeline, not a threshold of this module's own choosing).
    scale_pt_per_m = 50.0
    gap_pt = 0.065 * scale_pt_per_m  # 65mm -> 3.25pt, inside [1.5, 40]
    walls = _assemble(
        [
            _seg("frame_a", 0.0, 0.0, 300.0, 0.0),
            _seg("frame_b", 0.0, gap_pt, 300.0, gap_pt),
        ]
    )
    evidence = _evidence_by_id(walls, scale_pt_per_m=scale_pt_per_m)
    for w in walls:
        ev = evidence[w.candidate_id]
        assert ev.status != EvidenceResolutionStatus.CORROBORATED
        assert ev.reason_codes == (REASON_ISOLATED_LOCAL_PAIR,)


# ---------------------------------------------------------------------------
# B. Positive controls -- the replacement model must still recognize real
# wall geometry, not merely reject everything.
# ---------------------------------------------------------------------------


def test_legitimate_repeated_masonry_thickness_reaches_corroborated():
    """Real ~200mm Lamu-like masonry: the SAME thickness recurs at two
    spatially distinct wall runs (repeated mode) AND the two runs are
    topologically adjacent at a shared corner with matching thickness (band
    continuity) -- two genuinely independent structural signals, plus a
    real scale authority resolving physical plausibility. This is the one
    path this model allows to CORROBORATED."""
    # 0.25m at 40pt/m = 10pt -- comfortably outside Stage A's own 2.5-7.5pt
    # near-miss dangling-end review band (see module note below), so the
    # corner's own real ENDPOINT/L_CORNER classification is not disturbed.
    scale_pt_per_m = 40.0
    gap_pt = 0.25 * scale_pt_per_m  # 250mm -> 10.0pt

    segments = [
        # Run 1: south wall, double-line. Both faces mitered to the true
        # corner point, exactly as a real double-line wall corner is drawn
        # (both faces turn together, offset by the same thickness) --
        # s0b stops short by gap_pt so it meets s1b exactly at the inner
        # corner, matching s0/s1's own outer corner.
        _seg("s0", 0.0, 0.0, 300.0, 0.0),
        _seg("s0b", 0.0, gap_pt, 300.0 - gap_pt, gap_pt),
        # Run 2: east wall, double-line, meeting run 1 at a shared outer
        # corner node (300,0) and a shared inner corner node
        # (300-gap_pt, gap_pt) -- band-continuity adjacency for BOTH faces.
        _seg("s1", 300.0, 0.0, 300.0, 250.0),
        _seg("s1b", 300.0 - gap_pt, gap_pt, 300.0 - gap_pt, 250.0),
        # Run 3: a spatially DISTANT, unrelated wall at the SAME thickness
        # -- the second, spatially-distinct occurrence the repeated-mode
        # signal requires.
        _seg("s2", 800.0, 800.0, 1100.0, 800.0),
        _seg("s2b", 800.0, 800.0 + gap_pt, 1100.0, 800.0 + gap_pt),
    ]
    walls = _assemble(segments)
    evidence = _evidence_by_id(walls, scale_pt_per_m=scale_pt_per_m)

    s0 = _by_endpoints(walls, (0.0, 0.0), (300.0, 0.0))
    s0b = _by_endpoints(walls, (0.0, gap_pt), (300.0 - gap_pt, gap_pt))
    ev_s0 = evidence[s0.candidate_id]
    ev_s0b = evidence[s0b.candidate_id]
    assert ev_s0.status == EvidenceResolutionStatus.CORROBORATED
    assert ev_s0b.status == EvidenceResolutionStatus.CORROBORATED
    assert ev_s0.thickness_m == 0.25
    assert REASON_REPEATED_MODE in ev_s0.supporting_evidence_ids
    assert REASON_BAND_CONTINUITY in ev_s0.supporting_evidence_ids


def test_real_short_wall_return_survives_via_band_continuity():
    """A short (18pt) paired-face return, topologically adjacent (shared
    corner) to a long, independently locally-consistent wall of matching
    thickness. Length must never disqualify -- the short return must reach
    the same two-independent-signal tier as any other band member once it
    has a genuine adjacent, matching-thickness neighbour."""
    # Outside Stage A's own 2.5-7.5pt near-miss dangling-end review band.
    scale_pt_per_m = 40.0
    gap_pt = 0.25 * scale_pt_per_m  # 250mm -> 10.0pt

    segments = [
        _seg("long_a", 0.0, 0.0, 300.0, 0.0),
        _seg("long_b", 0.0, gap_pt, 300.0, gap_pt),
        # Short return at the corner (300,*), only 18pt long.
        _seg("short_a", 300.0, 0.0, 300.0, 18.0),
        _seg("short_b", 300.0 - gap_pt, 0.0, 300.0 - gap_pt, 18.0),
        # A second, spatially distinct occurrence of the same thickness so
        # this is a genuine repeated mode too, not relying on band
        # continuity alone.
        _seg("far_a", 900.0, 900.0, 1200.0, 900.0),
        _seg("far_b", 900.0, 900.0 + gap_pt, 1200.0, 900.0 + gap_pt),
    ]
    walls = _assemble(segments)
    evidence = _evidence_by_id(walls, scale_pt_per_m=scale_pt_per_m)
    short_return = _by_endpoints(walls, (300.0, 0.0), (300.0, 18.0))
    ev = evidence[short_return.candidate_id]
    assert ev.status != EvidenceResolutionStatus.ABSTAINED
    assert REASON_BAND_CONTINUITY in ev.supporting_evidence_ids


def test_opening_interruption_preserves_band_continuity():
    """Two collinear wall runs of the SAME thickness, separated by a real
    opening gap (dangling ends, not sharing a node) -- must still be
    recognized as one continuing wall band via the collinear-gap-partner
    adjacency test, exactly like W7's own dangling-end evidence."""
    # Outside Stage A's own 2.5-7.5pt near-miss dangling-end review band.
    scale_pt_per_m = 40.0
    gap_pt = 0.25 * scale_pt_per_m  # 250mm -> 10.0pt

    segments = [
        _seg("left_a", 0.0, 0.0, 150.0, 0.0),
        _seg("left_b", 0.0, gap_pt, 150.0, gap_pt),
        # A real opening gap: dangling ends from x=150 to x=200 (50pt gap,
        # well under half of either wall's own ~150pt length).
        _seg("right_a", 200.0, 0.0, 350.0, 0.0),
        _seg("right_b", 200.0, gap_pt, 350.0, gap_pt),
        # Distinct second occurrence for a genuine repeated mode.
        _seg("far_a", 900.0, 900.0, 1100.0, 900.0),
        _seg("far_b", 900.0, 900.0 + gap_pt, 1100.0, 900.0 + gap_pt),
    ]
    walls = _assemble(segments)
    evidence = _evidence_by_id(walls, scale_pt_per_m=scale_pt_per_m)
    left = _by_endpoints(walls, (0.0, 0.0), (150.0, 0.0))
    right = _by_endpoints(walls, (200.0, 0.0), (350.0, 0.0))
    ev_left = evidence[left.candidate_id]
    ev_right = evidence[right.candidate_id]
    assert REASON_BAND_CONTINUITY in ev_left.supporting_evidence_ids
    assert REASON_BAND_CONTINUITY in ev_right.supporting_evidence_ids


def test_inconsistent_gap_along_run_flagged_not_corroborated():
    """A pair whose gap wanders noticeably along its own overlap (e.g. two
    lines that converge/diverge, a near-miss rather than a real parallel
    wall face) must be flagged inconsistent, not silently averaged into a
    plausible-looking mean gap. The overall slope is kept under this
    module's own 2.5-degree pairing angle tolerance (so the pair is still
    tested as "parallel enough" at all -- a real look-alike near-miss, not
    something the angle test alone would already reject), while the gap
    itself still varies by far more than the local-consistency tolerance
    allows."""
    walls = _assemble(
        [
            _seg("a", 0.0, 0.0, 300.0, 0.0),
            # angle = atan(10/300) = 1.91deg, under the 2.5deg pairing
            # tolerance; gap halves from 20pt to 10pt across the run --
            # real wall faces do not do this.
            _seg("b", 0.0, 20.0, 300.0, 10.0),
        ]
    )
    evidence = _evidence_by_id(walls)
    for w in walls:
        ev = evidence[w.candidate_id]
        assert ev.status != EvidenceResolutionStatus.CORROBORATED
        assert ev.reason_codes == (REASON_INCONSISTENT_LOCAL_THICKNESS,)


def test_no_evidence_for_isolated_unpaired_line():
    walls = _assemble([_seg("lonely", 500.0, 500.0, 700.0, 500.0)])
    evidence = _evidence_by_id(walls)
    ev = evidence[walls[0].candidate_id]
    assert ev.status == EvidenceResolutionStatus.ABSTAINED
    assert ev.reason_codes == (REASON_NO_EVIDENCE,)


def test_corroborated_never_reached_without_scale_authority():
    """Even with repeated mode AND band continuity both present, no scale
    authority means no resolvable thickness_m -- CORROBORATED must never be
    reached without one, matching WallCandidate's own contract rule that
    CORROBORATED cannot coexist with an unresolved thickness authority."""
    gap_pt = 6.0
    segments = [
        _seg("s0", 0.0, 0.0, 300.0, 0.0),
        _seg("s0b", 0.0, gap_pt, 300.0, gap_pt),
        _seg("s1", 300.0, 0.0, 300.0, 250.0),
        _seg("s1b", 300.0 - gap_pt, 0.0, 300.0 - gap_pt, 250.0),
        _seg("s2", 800.0, 800.0, 1100.0, 800.0),
        _seg("s2b", 800.0, 800.0 + gap_pt, 1100.0, 800.0 + gap_pt),
    ]
    walls = _assemble(segments)
    evidence = _evidence_by_id(walls, scale_pt_per_m=None)
    for w in walls:
        assert evidence[w.candidate_id].status != EvidenceResolutionStatus.CORROBORATED


# ---------------------------------------------------------------------------
# C. Metamorphic invariance
# ---------------------------------------------------------------------------


def test_metamorphic_translation_rotation_scale_preserve_verdicts():
    import math

    def _rotate(x, y, deg):
        rad = math.radians(deg)
        return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))

    def _transform(segments, *, dx=0.0, dy=0.0, deg=0.0, scale=1.0):
        out = []
        for s in segments:
            x1, y1 = _rotate(s["x1"] * scale, s["y1"] * scale, deg)
            x2, y2 = _rotate(s["x2"] * scale, s["y2"] * scale, deg)
            out.append(_seg(s["id"], x1 + dx, y1 + dy, x2 + dx, y2 + dy))
        return out

    base_scale_pt_per_m = 30.0
    gap_pt = 0.2 * base_scale_pt_per_m
    base_segments = [
        _seg("s0", 0.0, 0.0, 300.0, 0.0),
        _seg("s0b", 0.0, gap_pt, 300.0, gap_pt),
        _seg("s1", 300.0, 0.0, 300.0, 250.0),
        _seg("s1b", 300.0 - gap_pt, 0.0, 300.0 - gap_pt, 250.0),
        _seg("s2", 800.0, 800.0, 1100.0, 800.0),
        _seg("s2b", 800.0, 800.0 + gap_pt, 1100.0, 800.0 + gap_pt),
    ]

    for kwargs, scale_factor in [
        ({"dx": 400.0, "dy": -900.0}, 1.0),
        ({"deg": 90.0}, 1.0),
        ({"deg": 41.0}, 1.0),
        ({"scale": 0.5}, 0.5),
        ({"scale": 2.0}, 2.0),
    ]:
        transformed = _transform(base_segments, **kwargs)
        scale_pt_per_m = base_scale_pt_per_m * scale_factor
        walls = _assemble(transformed)
        evidence = _evidence_by_id(walls, scale_pt_per_m=scale_pt_per_m)
        statuses = {ev.status for ev in evidence.values()}
        assert EvidenceResolutionStatus.CORROBORATED in statuses, kwargs
        for ev in evidence.values():
            if ev.thickness_m is not None:
                assert abs(ev.thickness_m - 0.2) < 1e-3, kwargs
