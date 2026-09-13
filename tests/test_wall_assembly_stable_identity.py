"""Regression coverage for the W4 candidate_id collision fix.

Real defect, confirmed by direct inspection of real Baghau p36 vector data
(session record, not reproduced here since benchmarks/sources/ is
gitignored): W4's own ``_canonical_wall_candidate_id`` hashed ONLY a chain's
two outer endpoint coordinates. Two geometrically DISTINCT diagonal traces
(different constituent Stage-A edges, different interior paths -- each
individually only a couple of degrees off straight, well within normal
drafting/collinear-merge tolerance, so neither chain's own interior points
looked like a "real corner" under a naive per-step angle test) shared both
outer endpoints and collided onto the same id. That collision later crashed
a downstream evidence-ranking pass expecting per-object identity uniqueness
(``supporting_evidence_ids must be unique``).

These tests reproduce the real geometry's shape synthetically (same
approximate magnitudes: ~100pt run, sub-2pt perpendicular deviation between
the two colliding chains' own interior paths) so the fix is verified without
needing the gitignored source PDF, and prove the four properties the
workstream mandate requires of the replacement identity function.
"""
from __future__ import annotations

import math

from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_topology


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


def _wall_endpoints(wall):
    return {
        tuple(round(c, 3) for c in wall.centerline_pts[0]),
        tuple(round(c, 3) for c in wall.centerline_pts[-1]),
    }


# ---------------------------------------------------------------------------
# Property 2: different interior paths, same endpoints -> different identity
# (the actual defect this fix closes)
# ---------------------------------------------------------------------------


def test_two_distinct_diagonal_chains_sharing_both_endpoints_get_different_ids():
    """Reproduces the real Baghau shape: two chains share exact outer
    endpoints (632.78,252.49)/(531.91,215.91)-equivalent, each individually
    only a couple of degrees off dead straight (so a naive per-step
    collinearity test would collapse both to "no real corner"), but their
    own interior paths deviate from the shared chord by measurably different
    amounts. A third, unrelated node midway on EACH chain (degree 3) is what
    keeps Stage A/W3 from collinear-merging them away entirely, matching the
    real data's own graph shape."""
    # Chain A: three collinear-ish segments forming one wall's own path.
    chain_a = [
        _seg("a1", 0.0, 0.0, 50.4, 16.8),
        _seg("a2", 50.4, 16.8, 75.2, 25.9),
        _seg("a3", 75.2, 25.9, 100.9, 36.6),
    ]
    # A third stub touching each interior node so it stays a real graph
    # junction (degree 3), matching why these survive as separate chain
    # points in the real data rather than being collinear-merged away.
    stubs_a = [
        _seg("sa1", 50.4, 16.8, 50.4, 40.0),
        _seg("sa2", 75.2, 25.9, 75.2, 50.0),
    ]
    chain_b = [
        _seg("b1", 0.0, 0.0, 50.2, 18.8),
        _seg("b2", 50.2, 18.8, 75.1, 27.9),
        _seg("b3", 75.1, 27.9, 100.9, 36.6),
    ]
    stubs_b = [
        _seg("sb1", 50.2, 18.8, 50.2, 40.0),
        _seg("sb2", 75.1, 27.9, 75.1, 50.0),
    ]

    walls_a, _ = _assemble(chain_a + stubs_a)
    walls_b, _ = _assemble(chain_b + stubs_b)

    diag_a = next(w for w in walls_a if len(w.centerline_pts) >= 3)
    diag_b = next(w for w in walls_b if len(w.centerline_pts) >= 3)

    assert _wall_endpoints(diag_a) == {(0.0, 0.0), (100.9, 36.6)}
    assert _wall_endpoints(diag_b) == {(0.0, 0.0), (100.9, 36.6)}
    assert diag_a.candidate_id != diag_b.candidate_id, (
        "two geometrically distinct interior paths sharing both endpoints "
        "must not collide onto the same candidate_id"
    )


# ---------------------------------------------------------------------------
# Property 1: same physical wall, differently segmented -> stable identity
# ---------------------------------------------------------------------------


def test_same_straight_wall_different_fragment_counts_same_id():
    one_piece, _ = _assemble([_seg("a", 0.0, 0.0, 300.0, 0.0)])
    two_pieces, _ = _assemble([_seg("a", 0.0, 0.0, 130.0, 0.0), _seg("b", 130.0, 0.0, 300.0, 0.0)])
    five_pieces, _ = _assemble(
        [
            _seg("a", 0.0, 0.0, 40.0, 0.0),
            _seg("b", 40.0, 0.0, 90.0, 0.0),
            _seg("c", 90.0, 0.0, 180.0, 0.0),
            _seg("d", 180.0, 0.0, 260.0, 0.0),
            _seg("e", 260.0, 0.0, 300.0, 0.0),
        ]
    )
    assert one_piece[0].candidate_id == two_pieces[0].candidate_id == five_pieces[0].candidate_id


def test_same_diagonal_wall_different_fragment_positions_same_id():
    """A genuinely straight (exactly collinear) diagonal wall, re-chunked at
    completely different intermediate points, must still resolve to the
    same id -- the shape fingerprint samples the path's own geometry at
    fixed arc-length fractions, not at whatever vertices happen to exist."""
    whole, _ = _assemble([_seg("a", 10.0, 5.0, 210.0, 105.0)])
    split_near_start, _ = _assemble(
        [_seg("a", 10.0, 5.0, 30.0, 15.0), _seg("b", 30.0, 15.0, 210.0, 105.0)]
    )
    split_at_thirds, _ = _assemble(
        [
            _seg("a", 10.0, 5.0, 76.67, 38.33),
            _seg("b", 76.67, 38.33, 143.33, 71.67),
            _seg("c", 143.33, 71.67, 210.0, 105.0),
        ]
    )
    assert whole[0].candidate_id == split_near_start[0].candidate_id == split_at_thirds[0].candidate_id


# ---------------------------------------------------------------------------
# Property 3: order (direction of traversal) invariance
# ---------------------------------------------------------------------------


def test_reversed_traversal_direction_same_id():
    forward, _ = _assemble([_seg("a", 12.0, 7.0, 212.0, 107.0)])
    backward, _ = _assemble([_seg("a", 212.0, 107.0, 12.0, 7.0)])
    assert forward[0].candidate_id == backward[0].candidate_id


def test_reversed_traversal_direction_same_id_for_bent_chain():
    """Same check for a chain with a real interior deviation (not just a
    straight line) -- reuses the same real-shaped chain as the collision
    test above (each step's own angle delta stays under W3's collinear-
    grouping tolerance, so it survives assembly as one multi-point chain,
    exactly like the real Baghau data), traversed in each direction."""
    segs_forward = [
        _seg("a1", 0.0, 0.0, 50.4, 16.8),
        _seg("a2", 50.4, 16.8, 75.2, 25.9),
        _seg("a3", 75.2, 25.9, 100.9, 36.6),
        _seg("sa1", 50.4, 16.8, 50.4, 40.0),
        _seg("sa2", 75.2, 25.9, 75.2, 50.0),
    ]
    segs_backward = [
        _seg("a1", 100.9, 36.6, 75.2, 25.9),
        _seg("a2", 75.2, 25.9, 50.4, 16.8),
        _seg("a3", 50.4, 16.8, 0.0, 0.0),
        _seg("sa1", 50.4, 16.8, 50.4, 40.0),
        _seg("sa2", 75.2, 25.9, 75.2, 50.0),
    ]
    forward, _ = _assemble(segs_forward)
    backward, _ = _assemble(segs_backward)
    diag_forward = next(w for w in forward if len(w.centerline_pts) >= 3)
    diag_backward = next(w for w in backward if len(w.centerline_pts) >= 3)
    assert diag_forward.candidate_id == diag_backward.candidate_id


# ---------------------------------------------------------------------------
# Property 3 (continued): translation/rotation/scale -- the algorithm's own
# QUALITATIVE behaviour (same-shape-same-id, different-shape-different-id)
# must hold after a metamorphic transform of the whole fixture. Absolute id
# VALUES are correctly NOT invariant under translation/rotation (the id is
# content-derived from real position, exactly as the pre-existing
# test_10/test_11* suite already documents and asserts) -- only the
# structural behaviour is required to transfer.
# ---------------------------------------------------------------------------


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


_COLLIDING_CHAIN_A = [
    _seg("a1", 0.0, 0.0, 50.4, 16.8),
    _seg("a2", 50.4, 16.8, 75.2, 25.9),
    _seg("a3", 75.2, 25.9, 100.9, 36.6),
    _seg("sa1", 50.4, 16.8, 50.4, 40.0),
    _seg("sa2", 75.2, 25.9, 75.2, 50.0),
]
_COLLIDING_CHAIN_B = [
    _seg("b1", 0.0, 0.0, 50.2, 18.8),
    _seg("b2", 50.2, 18.8, 75.1, 27.9),
    _seg("b3", 75.1, 27.9, 100.9, 36.6),
    _seg("sb1", 50.2, 18.8, 50.2, 40.0),
    _seg("sb2", 75.1, 27.9, 75.1, 50.0),
]


def _assert_still_distinguishes_after_transform(**transform_kwargs):
    walls_a, _ = _assemble(_transform(_COLLIDING_CHAIN_A, **transform_kwargs))
    walls_b, _ = _assemble(_transform(_COLLIDING_CHAIN_B, **transform_kwargs))
    diag_a = next(w for w in walls_a if len(w.centerline_pts) >= 3)
    diag_b = next(w for w in walls_b if len(w.centerline_pts) >= 3)
    assert diag_a.candidate_id != diag_b.candidate_id


def test_distinct_chains_still_distinguished_after_translation():
    _assert_still_distinguishes_after_transform(dx=500.0, dy=-300.0)


def test_distinct_chains_still_distinguished_after_rotation_90():
    _assert_still_distinguishes_after_transform(deg=90.0)


def test_distinct_chains_still_distinguished_after_rotation_41():
    _assert_still_distinguishes_after_transform(deg=41.0)


def test_distinct_chains_still_distinguished_after_scale_half():
    _assert_still_distinguishes_after_transform(scale=0.5)


def test_distinct_chains_still_distinguished_after_scale_double():
    _assert_still_distinguishes_after_transform(scale=2.0)


def _assert_same_wall_still_stable_after_transform(**transform_kwargs):
    one_piece_segs = _transform([_seg("a", 10.0, 5.0, 210.0, 105.0)], **transform_kwargs)
    split_segs = _transform(
        [
            _seg("a", 10.0, 5.0, 76.67, 38.33),
            _seg("b", 76.67, 38.33, 143.33, 71.67),
            _seg("c", 143.33, 71.67, 210.0, 105.0),
        ],
        **transform_kwargs,
    )
    one_piece, _ = _assemble(one_piece_segs)
    split, _ = _assemble(split_segs)
    assert one_piece[0].candidate_id == split[0].candidate_id


def test_same_wall_rechunk_invariance_still_holds_after_translation():
    _assert_same_wall_still_stable_after_transform(dx=-400.0, dy=900.0)


def test_same_wall_rechunk_invariance_still_holds_after_rotation():
    _assert_same_wall_still_stable_after_transform(deg=137.0)


def test_same_wall_rechunk_invariance_still_holds_after_scale():
    _assert_same_wall_still_stable_after_transform(scale=1.35)


# ---------------------------------------------------------------------------
# Property 4: deterministic repeated execution
# ---------------------------------------------------------------------------


def test_deterministic_repeated_execution_for_bent_chain():
    segments = _COLLIDING_CHAIN_A
    first, _ = _assemble(segments)
    second, _ = _assemble(segments)
    third, _ = _assemble(segments)
    ids_first = sorted(w.candidate_id for w in first)
    ids_second = sorted(w.candidate_id for w in second)
    ids_third = sorted(w.candidate_id for w in third)
    assert ids_first == ids_second == ids_third
