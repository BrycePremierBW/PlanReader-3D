"""Independent characterization of #273 ranking. Does not change thresholds.

These nine tests lock the *current* ranking semantics and failure modes
found on real drawings. They are research evidence, not the desired
future wall-authority contract, and must not be merged to main as
permanent semantic expectations.
"""
from __future__ import annotations

from pb_migration_contracts import EvidenceResolutionStatus
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates
from pb_wall_room_topology_wall_evidence_ranking import (
    REASON_NO_EVIDENCE,
    REASON_PAIRED_FACE,
    REASON_ROOM_BOUNDARY,
    rank_wall_candidates,
)
from pb_wall_topology_diagnostics import collect_topology_from_segments, diagnose_wall_topology
from pb_wall_topology_ranking_validation import (
    BUCKET_ABSTAINED,
    BUCKET_AMBIGUOUS,
    BUCKET_CANDIDATE_SINGLE,
    BUCKET_CORROBORATED,
    BUCKET_W4_UNRANKED,
    apply_ranking_to_snapshot,
    ranking_bucket,
    ranking_signals,
    stratified_samples,
    summarize_ranking,
)


def _seg(seg_id, x1, y1, x2, y2):
    return {
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


def test_unranked_snapshot_is_w4_unranked_bucket() -> None:
    snapshot = collect_topology_from_segments(
        [_seg("a", 0, 0, 100, 0)],
        document_id="doc",
        page_id="page_1",
        page_number=1,
        viewport_id="vp_1",
    )
    report = diagnose_wall_topology(snapshot)
    assert report["distributions"]["evidence_ranking"]["buckets"][BUCKET_W4_UNRANKED] == 1
    assert report["wall_candidates"][0]["ranking_bucket"] == BUCKET_W4_UNRANKED


def test_apply_ranking_never_drops_or_renames_candidates() -> None:
    snapshot = collect_topology_from_segments(
        [_seg("a", 0, 0, 300, 0), _seg("b", 0, 15, 300, 15), _seg("g", 80, 80, 90, 80)],
        document_id="doc",
        page_id="page_1",
        page_number=1,
        viewport_id="vp_1",
    )
    ranked = apply_ranking_to_snapshot(snapshot, scale_pt_per_m=28.3)
    assert [wall.candidate_id for wall in ranked.walls] == [wall.candidate_id for wall in snapshot.walls]
    assert len(ranked.walls) == len(snapshot.walls)
    assert {ranking_bucket(wall) for wall in snapshot.walls} == {BUCKET_W4_UNRANKED}


def test_double_line_with_scale_is_corroborated_only_with_second_signal() -> None:
    snapshot = collect_topology_from_segments(
        [_seg("outer", 0, 0, 300, 0), _seg("inner", 0, 15, 300, 15)],
        document_id="doc",
        page_id="page_1",
        page_number=1,
        viewport_id="vp_1",
    )
    unscaled = apply_ranking_to_snapshot(snapshot)
    scaled = apply_ranking_to_snapshot(snapshot, scale_pt_per_m=28.3)
    # Paired-face alone is one signal: CANDIDATE, not CORROBORATED.
    assert all(ranking_bucket(wall) == BUCKET_CANDIDATE_SINGLE for wall in unscaled.walls)
    assert all(ranking_bucket(wall) == BUCKET_CANDIDATE_SINGLE for wall in scaled.walls)
    assert all(REASON_PAIRED_FACE in ranking_signals(wall) for wall in scaled.walls)


def test_furniture_loop_with_w5_rooms_is_single_signal_candidate() -> None:
    """Characterization, not a threshold change: an isolated furniture
    rectangle becomes its own W5 room, so ranking credits room-boundary
    and does not abstain. CANDIDATE therefore is not 'very likely a wall'.
    """
    segments = [
        _seg("f0", 500.0, 500.0, 520.0, 500.0),
        _seg("f1", 520.0, 500.0, 520.0, 515.0),
        _seg("f2", 520.0, 515.0, 500.0, 515.0),
        _seg("f3", 500.0, 515.0, 500.0, 500.0),
    ]
    snapshot = collect_topology_from_segments(
        segments,
        document_id="doc",
        page_id="page_1",
        page_number=1,
        viewport_id="vp_1",
        evaluate_opening_hosts=False,
    )
    ranked = apply_ranking_to_snapshot(snapshot)
    assert snapshot.rooms, "W5 built a room from the furniture loop"
    assert all(ranking_bucket(wall) == BUCKET_CANDIDATE_SINGLE for wall in ranked.walls)
    assert all(REASON_ROOM_BOUNDARY in ranking_signals(wall) for wall in ranked.walls)
    assert all(wall.status != EvidenceResolutionStatus.ABSTAINED for wall in ranked.walls)


def test_hatch_tick_touching_a_proved_wall_is_single_signal_candidate() -> None:
    """Characterization: a short tick that touches a paired-face wall
    inherits connected_component_participation. That is not enough to
    treat CANDIDATE as 'very likely a physical wall'.
    """
    segments = [
        _seg("outer", 0, 0, 300, 0),
        _seg("inner", 0, 15, 300, 15),
        _seg("tick", 150, 0, 156, 6),
    ]
    snapshot = collect_topology_from_segments(
        segments,
        document_id="doc",
        page_id="page_1",
        page_number=1,
        viewport_id="vp_1",
        evaluate_opening_hosts=False,
    )
    ranked = apply_ranking_to_snapshot(snapshot)
    tick = next(
        wall
        for wall in ranked.walls
        if {tuple(round(c, 3) for c in wall.centerline_pts[0]), tuple(round(c, 3) for c in wall.centerline_pts[-1])}
        == {(150.0, 0.0), (156.0, 6.0)}
    )
    assert ranking_bucket(tick) == BUCKET_CANDIDATE_SINGLE
    assert ranking_signals(tick) == ["connected_component_participation"]


def test_room_width_pairing_can_become_corroborated() -> None:
    """Characterization: detect_wall_pairs' 40pt max thickness is reused
    unchanged. At ~28 pt/m that is a ~1.4m band. A classroom-width
    parallel pair that also bounds a W5 room currently becomes
    CORROBORATED (~0.97m). That bucket is therefore not yet wall-precise.
    The pair is not a closed four-wall quad, so the furniture discard
    does not fire.
    """
    segments = [
        _seg("a", 0, 0, 200, 0),
        _seg("b", 0, 27.5, 200, 27.5),
        _seg("r1", 200, 0, 200, -80),
        _seg("r2", 200, -80, 0, -80),
        _seg("r3", 0, -80, 0, 0),
    ]
    snapshot = collect_topology_from_segments(
        segments,
        document_id="doc",
        page_id="page_1",
        page_number=1,
        viewport_id="vp_1",
        evaluate_opening_hosts=False,
    )
    ranked = apply_ranking_to_snapshot(snapshot, scale_pt_per_m=28.3)
    long_walls = [
        wall
        for wall in ranked.walls
        if ranking_bucket(wall) == BUCKET_CORROBORATED
    ]
    assert snapshot.rooms
    assert long_walls
    assert any(wall.thickness_m and wall.thickness_m > 0.8 for wall in long_walls)


def test_single_line_room_cannot_reach_corroborated() -> None:
    """False-negative lock: hatch-tick / single-line masonry has no
    paired face. A closed room plus caller scale still cannot become
    CORROBORATED. That bucket is unreachable on the very drawings this
    layer is trying to clean up.
    """
    segments = [
        _seg("s0", 0, 0, 400, 0),
        _seg("s1", 400, 0, 400, 220),
        _seg("s2", 400, 220, 0, 220),
        _seg("s3", 0, 220, 0, 0),
    ]
    snapshot = collect_topology_from_segments(
        segments,
        document_id="doc",
        page_id="page_1",
        page_number=1,
        viewport_id="vp_1",
        evaluate_opening_hosts=False,
    )
    ranked = apply_ranking_to_snapshot(snapshot, scale_pt_per_m=28.3)
    assert snapshot.rooms
    assert all(ranking_bucket(wall) != BUCKET_CORROBORATED for wall in ranked.walls)
    assert all(REASON_ROOM_BOUNDARY in ranking_signals(wall) for wall in ranked.walls)
    assert all(REASON_PAIRED_FACE not in ranking_signals(wall) for wall in ranked.walls)


def test_parallel_hatch_ladder_stays_ambiguous_not_corroborated() -> None:
    """Many parallel strokes at incompatible spacings must stay ambiguous."""
    segments = [_seg(f"r{index}", 0, index * 4.0, 80, index * 4.0) for index in range(8)]
    snapshot = collect_topology_from_segments(
        segments,
        document_id="doc",
        page_id="page_1",
        page_number=1,
        viewport_id="vp_1",
        evaluate_opening_hosts=False,
    )
    ranked = apply_ranking_to_snapshot(snapshot, scale_pt_per_m=28.3)
    assert any(ranking_bucket(wall) == BUCKET_AMBIGUOUS for wall in ranked.walls)
    assert all(ranking_bucket(wall) != BUCKET_CORROBORATED for wall in ranked.walls)


def test_stratified_samples_are_deterministic() -> None:
    graph = build_wall_graph_for_viewport(
        [_seg("a", 0, 0, 100, 0), _seg("b", 0, 15, 100, 15), _seg("c", 400, 400, 430, 400)]
    )
    junctions, relationships = classify_junctions(
        graph, document_id="doc", page_id="p1", viewport_id="vp"
    )
    walls, _ = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp")
    ranked = rank_wall_candidates(walls)
    first = stratified_samples(ranked, per_bucket=2)
    second = stratified_samples(ranked, per_bucket=2)
    assert first == second
    summary = summarize_ranking(ranked)
    assert summary["buckets"][BUCKET_ABSTAINED] >= 1
    assert REASON_NO_EVIDENCE in ranked[-1].reason_codes or any(
        ranking_bucket(wall) == BUCKET_ABSTAINED for wall in ranked
    )
