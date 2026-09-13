from __future__ import annotations

import math
from dataclasses import replace

import pytest

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_room_faces import reconstruct_room_candidates
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates, assemble_wall_topology
from pb_wall_room_topology_wall_evidence_ranking import (
    REASON_AMBIGUOUS_THICKNESS,
    REASON_CONNECTED,
    REASON_FILL_SUPPORTED,
    REASON_MULTIPLE_SIGNALS_NO_SCALE,
    REASON_NO_EVIDENCE,
    REASON_PAIRED_FACE,
    REASON_ROOM_BOUNDARY,
    find_paired_wall_faces,
    rank_wall_candidates,
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
    return assemble_wall_topology(graph, junctions, relationships, viewport_id="vp_1")


def _assemble_with_rooms(segments):
    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id="doc_1", page_id="p1", viewport_id="vp_1"
    )
    walls, edge_map = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_1")
    rooms = reconstruct_room_candidates(graph, edge_map, document_id="doc_1", viewport_id="vp_1")
    return walls, rooms


def _has_signal(wall, reason):
    """Every evidence-signal name (REASON_PAIRED_FACE, REASON_FILL_SUPPORTED,
    REASON_ROOM_BOUNDARY, REASON_CONNECTED) always lands in
    supporting_evidence_ids, regardless of how many other signals a wall
    also carries; reason_codes instead carries the categorical tier marker
    (MULTIPLE_SIGNALS_*/AMBIGUOUS_THICKNESS/NO_EVIDENCE), never the raw
    signal name itself. Checking supporting_evidence_ids is therefore the
    correct, tier-independent way to ask "was this signal found"."""
    return reason in wall.supporting_evidence_ids


def _by_endpoints(walls, p1, p2):
    p1 = tuple(round(c, 3) for c in p1)
    p2 = tuple(round(c, 3) for c in p2)
    for w in walls:
        wp1 = tuple(round(c, 3) for c in w.centerline_pts[0])
        wp2 = tuple(round(c, 3) for c in w.centerline_pts[-1])
        if {wp1, wp2} == {p1, p2}:
            return w
    raise AssertionError(f"no wall with endpoints {p1}/{p2} among {[(w.centerline_pts[0], w.centerline_pts[-1]) for w in walls]}")


# ---------------------------------------------------------------------------
# A. Real wall shapes that must be recognized
# ---------------------------------------------------------------------------


def test_paired_double_line_exterior_wall_is_proved():
    """Two long, parallel lines a plausible wall-thickness apart, running
    the same direction with full overlap -- the classic double-line
    exterior wall convention. Both lines' own resulting WallCandidates must
    show paired-face evidence."""
    segments = [
        _seg("outer", 0, 0, 300, 0),
        _seg("inner", 0, 15, 300, 15),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert len(ranked) == 2
    for w in ranked:
        assert _has_signal(w, REASON_PAIRED_FACE)
        assert w.status == EvidenceResolutionStatus.CANDIDATE
        assert w.confidence > 0.0


def test_short_real_wall_return_with_paired_face_is_not_penalized():
    """A short (20pt) return -- e.g. a door reveal or pilaster -- that
    still has a genuine paired face must be evidenced exactly like a long
    one. Length itself must never enter the decision."""
    segments = [
        _seg("outer", 0, 0, 20, 0),
        _seg("inner", 0, 12, 20, 12),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert all(_has_signal(w, REASON_PAIRED_FACE) for w in ranked)
    assert all(w.status != EvidenceResolutionStatus.ABSTAINED for w in ranked)


def test_internal_partition_paired_faces_evidenced_like_exterior():
    """An internal partition (thin, short run entirely inside a larger
    footprint) with a genuine paired face is evidenced the same way an
    exterior wall is -- no special-casing by position."""
    segments = [
        _seg("a", 50, 50, 150, 50),
        _seg("b", 50, 60, 150, 60),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert all(w.status != EvidenceResolutionStatus.ABSTAINED for w in ranked)


def test_t_junction_single_faced_stem_inherits_evidence_from_paired_bar():
    """A T junction: the bar is a genuine paired-face double-line wall; the
    stem is drawn as a SINGLE line only (no partner of its own -- e.g. a
    partition whose far face wasn't separately digitised) but attaches at
    the bar's own junction node. The stem must inherit corroborating
    connectivity evidence from the independently-evidenced bar, not be
    abstained for lacking its own pair."""
    segments = [
        _seg("bar1", 0, 0, 150, 0),
        _seg("bar1b", 0, 10, 150, 10),
        _seg("bar2", 150, 0, 300, 0),
        _seg("bar2b", 150, 10, 300, 10),
        _seg("stem", 150, 0, 150, -80),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    stem = _by_endpoints(ranked, (150, 0), (150, -80))
    assert _has_signal(stem, REASON_CONNECTED)
    assert stem.status != EvidenceResolutionStatus.ABSTAINED
    # W4 chains straight through the T-branch's collinear side as one
    # interior vertex rather than breaking the bar into two candidates --
    # this is exactly the case the interior-touch spatial check exists for.
    bar = _by_endpoints(ranked, (0, 0), (300, 0))
    assert _has_signal(bar, REASON_PAIRED_FACE)


def test_l_corner_single_faced_arm_inherits_evidence_from_paired_wall():
    """An L corner: one arm is a genuine paired-face wall; the other arm is
    a single unpaired line attached at the shared corner. The unpaired arm
    must inherit connectivity evidence from its evidenced neighbour."""
    segments = [
        _seg("s0", 0, 0, 300, 0),
        _seg("s0b", 0, 10, 300, 10),
        _seg("s1", 300, 0, 300, 300),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    s1 = _by_endpoints(ranked, (300, 0), (300, 300))
    assert _has_signal(s1, REASON_CONNECTED)
    assert s1.status != EvidenceResolutionStatus.ABSTAINED


def test_x_crossing_of_two_independently_paired_walls_is_not_abstained():
    """An X crossing of two full double-line walls: each arm already has
    its own direct paired-face evidence independent of the crossing, so
    the crossing topology itself must not break or weaken that evidence."""
    segments = [
        _seg("h", -150, 0, 150, 0),
        _seg("hb", -150, 10, 150, 10),
        _seg("v", 0, -150, 0, 150),
        _seg("vb", 10, -150, 10, 150),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert all(w.status != EvidenceResolutionStatus.ABSTAINED for w in ranked)
    assert all(_has_signal(w, REASON_PAIRED_FACE) for w in ranked)


def test_paired_faces_with_wall_like_fill_gets_both_high_signals():
    """A wall drawn with BOTH a paired-line convention and a solid fill
    between the faces (some drawings do both) should show both signals."""
    segments = [
        _seg("a", 0, 0, 200, 0),
        _seg("b", 0, 20, 200, 20),
    ]
    walls, _ = _assemble(segments)
    fills = [(0.0, 0.0, 200.0, 20.0)]
    ranked = rank_wall_candidates(walls, wall_like_fills=fills)
    for w in ranked:
        assert _has_signal(w, REASON_PAIRED_FACE)
        assert _has_signal(w, REASON_FILL_SUPPORTED)


def test_wall_only_evidenced_by_fill_not_paired_line_still_corroborated():
    """A single stroked line that happens to coincide with one edge of a
    real wall-like fill (the OTHER face never drawn as a line at all, e.g.
    it's the building's own outer boundary and only one face was digitised
    as a stroke) is still evidenced via the fill signal alone."""
    segments = [_seg("a", 0, 0, 200, 0)]
    walls, _ = _assemble(segments)
    fills = [(0.0, -2.0, 200.0, 0.0)]  # fill's own bottom edge sits at y=0, matching the line
    ranked = rank_wall_candidates(walls, wall_like_fills=fills)
    assert len(ranked) == 1
    w = ranked[0]
    assert _has_signal(w, REASON_FILL_SUPPORTED)
    assert w.status != EvidenceResolutionStatus.ABSTAINED


def test_room_boundary_participation_is_corroborating_evidence():
    """A closed rectangle's four sides all bound a real room face -- each
    side should carry room-boundary evidence even where no paired face
    exists (single-line rectangle, no double-line convention here)."""
    segments = [
        _seg("s0", 0, 0, 300, 0),
        _seg("s1", 300, 0, 300, 200),
        _seg("s2", 300, 200, 0, 200),
        _seg("s3", 0, 200, 0, 0),
    ]
    walls, rooms = _assemble_with_rooms(segments)
    assert len(rooms) == 1
    ranked = rank_wall_candidates(walls, rooms=rooms)
    for w in ranked:
        assert _has_signal(w, REASON_ROOM_BOUNDARY)
        assert w.status != EvidenceResolutionStatus.ABSTAINED


def test_repeated_openings_do_not_prevent_paired_face_evidence():
    """A wall interrupted twice by real openings (three collinear fragments
    per face) -- W4 keeps each fragment a separate WallCandidate (no
    CONTINUES_AS across an L_CORNER-like break), but each fragment must
    still pair against its own opposite-face counterpart independently."""
    segments = [
        _seg("a1", 0, 0, 60, 0), _seg("a2", 100, 0, 160, 0), _seg("a3", 200, 0, 260, 0),
        _seg("b1", 0, 15, 60, 15), _seg("b2", 100, 15, 160, 15), _seg("b3", 200, 15, 260, 15),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert len(ranked) == 6
    assert all(w.status != EvidenceResolutionStatus.ABSTAINED for w in ranked)


# ---------------------------------------------------------------------------
# B. Non-wall geometry that must remain rejected
# ---------------------------------------------------------------------------


def test_isolated_glazing_bar_is_rejected():
    """A single short stroke with no paired face, no fill, no room
    boundary, and (isolated on the page) no real connectivity."""
    segments = [_seg("glazing", 100.0, 100.0, 118.0, 100.0)]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert len(ranked) == 1
    assert ranked[0].status == EvidenceResolutionStatus.ABSTAINED
    assert REASON_NO_EVIDENCE in ranked[0].reason_codes


def test_isolated_dimension_witness_line_is_rejected():
    segments = [_seg("dim", 400.0, 400.0, 400.0, 460.0)]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert ranked[0].status == EvidenceResolutionStatus.ABSTAINED


def test_isolated_furniture_rectangle_lines_are_rejected():
    """A furniture symbol drawn as 4 short unconnected lines, far from any
    real wall, with no fill and no paired-thickness match to each other
    (aspect too square-ish / gaps too small to look like a wall band)."""
    segments = [
        _seg("f0", 500.0, 500.0, 520.0, 500.0),
        _seg("f1", 520.0, 500.0, 520.0, 515.0),
        _seg("f2", 520.0, 515.0, 500.0, 515.0),
        _seg("f3", 500.0, 515.0, 500.0, 500.0),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    # A closed 4-sided loop like this DOES form a room boundary once W5 runs
    # over it in isolation -- deliberately not passing rooms= here, matching
    # a real page where this furniture symbol sits inside a much larger,
    # separately-evidenced room rather than forming its own. Without room
    # participation and with no paired opposite-direction match (each side's
    # only "parallel" candidate is perpendicular, not parallel), every side
    # must abstain.
    assert all(w.status == EvidenceResolutionStatus.ABSTAINED for w in ranked)


def test_annotation_table_border_is_rejected():
    """A table/border rectangle far from any real wall geometry, alone on
    the page -- same shape class as the furniture case, same expectation."""
    segments = [
        _seg("t0", 900.0, 900.0, 1000.0, 900.0),
        _seg("t1", 1000.0, 900.0, 1000.0, 950.0),
        _seg("t2", 1000.0, 950.0, 900.0, 950.0),
        _seg("t3", 900.0, 950.0, 900.0, 900.0),
    ]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert all(w.status == EvidenceResolutionStatus.ABSTAINED for w in ranked)


def test_isolated_parallel_lines_beyond_wall_thickness_are_not_paired():
    """Two long parallel lines much too far apart to be one wall's own two
    faces (e.g. two separate walls on either side of a corridor) must not
    be paired with each other."""
    segments = [
        _seg("a", 0, 0, 300, 0),
        _seg("b", 0, 200, 300, 200),
    ]
    walls, _ = _assemble(segments)
    pairs = find_paired_wall_faces(walls)
    assert all(not v for v in pairs.values())


def test_two_unrelated_jambs_are_not_automatically_a_wall_band():
    """Two short vertical fragments with similar y-extents but NOT a
    plausible wall-thickness gap apart (mirroring the real defect-2 shape
    from the hosted-opening locality audit, at the wall-evidence layer
    instead) must not be paired."""
    segments = [
        _seg("j1", 100.0, 100.0, 100.0, 140.0),
        _seg("j2", 160.0, 100.0, 160.0, 140.0),
    ]
    walls, _ = _assemble(segments)
    pairs = find_paired_wall_faces(walls)
    assert all(not v for v in pairs.values())
    ranked = rank_wall_candidates(walls)
    assert all(w.status == EvidenceResolutionStatus.ABSTAINED for w in ranked)


def test_single_hatch_tick_survives_structural_filter_but_is_not_promoted():
    """One short ~45-degree diagonal stroke -- Stage A's own dash/layer-only
    pre-filter never excludes it (undashed, unlayered), but with nothing
    else nearby it must not be promoted to a credible wall on its own."""
    segments = [_seg("tick", 700.0, 700.0, 706.0, 706.0)]
    walls, _ = _assemble(segments)
    ranked = rank_wall_candidates(walls)
    assert ranked[0].status == EvidenceResolutionStatus.ABSTAINED


def test_nearby_unrelated_parallel_geometry_does_not_pair_across_a_gap_too_wide():
    """Two parallel lines close enough in angle but with a gap well beyond
    any plausible wall thickness -- must not pair merely for being
    "nearby" in some looser sense."""
    segments = [
        _seg("a", 0, 0, 300, 0),
        _seg("b", 0, 55, 300, 55),  # 55pt gap, over DEFAULT_MAX_THICKNESS_PT=40
    ]
    walls, _ = _assemble(segments)
    pairs = find_paired_wall_faces(walls)
    assert all(not v for v in pairs.values())


# ---------------------------------------------------------------------------
# C. Ambiguity / conflicting evidence
# ---------------------------------------------------------------------------


def test_conflicting_thickness_pairings_are_flagged_ambiguous_not_guessed():
    """One candidate line has TWO plausible paired-face partners at
    meaningfully different thicknesses (e.g. it sits between two other
    lines, either of which could be "the other face") -- must fail closed
    to ambiguous rather than silently pick the nearer one."""
    segments = [
        _seg("mid", 0, 20, 300, 20),
        _seg("near", 0, 10, 300, 10),   # 10pt away
        _seg("far", 0, 35, 300, 35),    # 15pt away -- both plausible, disagree by 5pt (> 2.0 tol)
    ]
    walls, _ = _assemble(segments)
    mid_wall = _by_endpoints(walls, (0, 20), (300, 20))
    ranked = rank_wall_candidates(walls)
    mid_ranked = next(w for w in ranked if w.candidate_id == mid_wall.candidate_id)
    assert REASON_AMBIGUOUS_THICKNESS in mid_ranked.reason_codes
    assert mid_ranked.status == EvidenceResolutionStatus.CANDIDATE


def test_ambiguous_pairing_survives_a_real_data_candidate_id_collision():
    """Regression: running this module against real Baghau p36 vector
    geometry crashed with ValueError('supporting_evidence_ids must be
    unique'). Root cause, confirmed by direct inspection: W4's own
    ``assemble_wall_candidates`` (unmodified, out of this module's scope)
    can assign the SAME candidate_id to two distinct chains that share
    both outer endpoints but differ in their interior vertices -- a
    pre-existing property of real, messy CAD geometry that never surfaces
    on clean synthetic fixtures. When a wall pairs ambiguously against
    that colliding id from two genuinely different partner objects, the
    naive supporting_evidence_ids formatting collided into duplicate
    strings, tripping WallCandidate's own uniqueness validation. This
    reproduces that shape directly (no real PDF needed) by forcing two
    distinct WallCandidate objects to share one candidate_id via
    dataclasses.replace, then pairing a third wall ambiguously against
    both copies."""
    segments = [
        _seg("mid", 0, 20, 300, 20),
        _seg("near", 0, 10, 300, 10),
        _seg("far", 0, 35, 300, 35),
    ]
    walls, _ = _assemble(segments)
    mid_wall = _by_endpoints(walls, (0, 20), (300, 20))
    near_wall = _by_endpoints(walls, (0, 10), (300, 10))
    far_wall = _by_endpoints(walls, (0, 35), (300, 35))
    colliding_id = "wall_forced_collision"
    collided_near = replace(near_wall, candidate_id=colliding_id)
    collided_far = replace(far_wall, candidate_id=colliding_id)
    collided_walls = [mid_wall, collided_near, collided_far]

    ranked = rank_wall_candidates(collided_walls)  # must not raise

    mid_ranked = next(w for w in ranked if w.candidate_id == mid_wall.candidate_id)
    assert REASON_AMBIGUOUS_THICKNESS in mid_ranked.reason_codes
    assert len(mid_ranked.supporting_evidence_ids) == len(set(mid_ranked.supporting_evidence_ids))


# ---------------------------------------------------------------------------
# D. Scale authority / CORROBORATED promotion
# ---------------------------------------------------------------------------


def test_multiple_signals_without_scale_stays_candidate_not_corroborated():
    """Paired face + room boundary (two independent signals) without a
    scale authority must NOT reach CORROBORATED -- WallCandidate's own
    validation forbids CORROBORATED while thickness_authority stays
    PROVISIONAL, and this module never invents a scale to get around it."""
    segments = [
        _seg("s0", 0, 0, 300, 0), _seg("s0b", 0, 15, 300, 15),
        _seg("s1", 300, 0, 300, 200), _seg("s1b", 285, 0, 285, 200),
        _seg("s2", 300, 200, 0, 200), _seg("s2b", 300, 185, 0, 185),
        _seg("s3", 0, 200, 0, 0), _seg("s3b", 15, 200, 15, 0),
    ]
    walls, rooms = _assemble_with_rooms(segments)
    ranked = rank_wall_candidates(walls, rooms=rooms)
    assert len(ranked) >= 4
    assert all(w.status != EvidenceResolutionStatus.CORROBORATED for w in ranked)
    assert any(REASON_MULTIPLE_SIGNALS_NO_SCALE in w.reason_codes for w in ranked)


def test_multiple_signals_with_scale_authority_resolves_real_thickness():
    """The same fixture, with a caller-supplied scale authority, DOES reach
    CORROBORATED with a real, resolved thickness_m and PDF_SCALED
    authority -- never invented, always derived from the paired-face gap."""
    from pb_geometry_takeoff_model import MeasurementAuthorityType

    segments = [
        _seg("s0", 0, 0, 300, 0), _seg("s0b", 0, 15, 300, 15),
        _seg("s1", 300, 0, 300, 200), _seg("s1b", 285, 0, 285, 200),
        _seg("s2", 300, 200, 0, 200), _seg("s2b", 300, 185, 0, 185),
        _seg("s3", 0, 200, 0, 0), _seg("s3b", 15, 200, 15, 0),
    ]
    walls, rooms = _assemble_with_rooms(segments)
    ranked = rank_wall_candidates(walls, rooms=rooms, scale_pt_per_m=30.0)
    corroborated = [w for w in ranked if w.status == EvidenceResolutionStatus.CORROBORATED]
    assert corroborated, "expected at least one CORROBORATED wall once scale authority is supplied"
    for w in corroborated:
        assert w.thickness_m is not None
        assert w.thickness_authority == MeasurementAuthorityType.PDF_SCALED
        assert 0.3 <= w.thickness_m <= 0.6  # 15pt / 30pt-per-m = 0.5m


# ---------------------------------------------------------------------------
# E. Metamorphic invariance
# ---------------------------------------------------------------------------


def _rotate(x, y, deg):
    rad = math.radians(deg)
    return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))


def _transform_segments(segments, *, dx=0.0, dy=0.0, deg=0.0, scale=1.0):
    out = []
    for s in segments:
        x1, y1 = _rotate(s["x1"] * scale, s["y1"] * scale, deg)
        x2, y2 = _rotate(s["x2"] * scale, s["y2"] * scale, deg)
        out.append(_seg(s["id"], x1 + dx, y1 + dy, x2 + dx, y2 + dy))
    return out


_BASE_PAIRED_WALL = [
    _seg("outer", 0, 0, 300, 0),
    _seg("inner", 0, 15, 300, 15),
]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dx": 137.5, "dy": -250.0},
        {"deg": 90.0},
        {"deg": 180.0},
        {"deg": 270.0},
        {"scale": 0.5},
        {"scale": 1.35},
        {"scale": 2.0},
    ],
    ids=["translate", "rotate90", "rotate180", "rotate270", "scale_half", "scale_1_35x", "scale_double"],
)
def test_paired_face_evidence_is_metamorphically_invariant(kwargs):
    transformed = _transform_segments(_BASE_PAIRED_WALL, **kwargs)
    walls, _ = _assemble(transformed)
    ranked = rank_wall_candidates(walls)
    assert len(ranked) == 2
    assert all(w.status != EvidenceResolutionStatus.ABSTAINED for w in ranked)
    assert all(REASON_PAIRED_FACE in w.reason_codes or w.supporting_evidence_ids == (REASON_PAIRED_FACE,) for w in ranked)
