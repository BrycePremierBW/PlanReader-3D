"""W4 source-owned candidate addresses must not silently alias two walls."""
from copy import deepcopy
from dataclasses import replace

import pytest

from pb_geometry_takeoff_model import MeasurementAuthorityType
from pb_migration_contracts import EvidenceResolutionStatus
from pb_physical_wall_identity import collect_physical_wall_identities
from pb_wall_room_topology_contracts import JunctionType, WallCandidate
from pb_wall_room_topology_primitive_lineage import LINEAGE_KEY
from pb_wall_room_topology_wall_assembly import (
    W4SourceCandidateAddressCollision,
    _source_owned_collision_candidate_addresses,
)


def wall(edge, junction, *, candidate_id="wall_same_geometry",
         reverse=False, x=0.0, y=0.0):
    pts = ((x, y), (x + 10.0, y))
    return WallCandidate(
        candidate_id=candidate_id, viewport_id="source-owned-viewport",
        representation="single_line",
        centerline_pts=tuple(reversed(pts)) if reverse else pts,
        face_a_segment_ids=(edge,), face_b_segment_ids=None,
        is_curved=False, curve_control_pts=None,
        thickness_m=None, thickness_authority=MeasurementAuthorityType.PROVISIONAL,
        length_m=None, end_node_ids=(junction, "junction_common"),
        junction_types=(JunctionType.AMBIGUOUS, JunctionType.ENDPOINT),
        interior_exterior="unresolved", level_id=None,
        status=EvidenceResolutionStatus.CANDIDATE,
        confidence=0.5,
    )


def edges():
    return {
        "source-edge-a": {"id": "source-edge-a", "x1": 0., "y1": 0.,
                          "x2": 10., "y2": 0.,
                          LINEAGE_KEY: {"source_primitive_ids": ("native-a",)}},
        "source-edge-b": {"id": "source-edge-b", "x1": 10., "y1": 0.,
                          "x2": 0., "y2": 0.,
                          LINEAGE_KEY: {"source_primitive_ids": ("native-b",)}},
        "unrelated": {"id": "unrelated", "x1": 0., "y1": 10.,
                      "x2": 10., "y2": 10.,
                      LINEAGE_KEY: {"source_primitive_ids": ("native-c",)}},
    }


def test_collision_rekeys_both_competing_addresses_and_preserves_unrelated_candidate():
    a = wall("source-edge-a", "junction-a")
    b = wall("source-edge-b", "junction-b", reverse=True)
    other = wall("unrelated", "junction-c", candidate_id="wall_other", y=10.)
    original = deepcopy(([a, b, other], edges()))
    indexed = {w.face_a_segment_ids[0]: w.candidate_id for w in (a, b, other)}
    revised, mapping = _source_owned_collision_candidate_addresses(
        (a, b, other), edges(), indexed)
    assert original == ([a, b, other], edges())
    assert len({w.candidate_id for w in revised}) == 3
    assert revised[2] is other
    assert mapping["unrelated"] == other.candidate_id
    for w in revised[:2]:
        assert w.candidate_id != a.candidate_id
        assert w.metadata["precollision_w4_candidate_id"] == a.candidate_id
        assert "source_owned_w4_candidate_address_collision" in w.reason_codes
        assert mapping[w.face_a_segment_ids[0]] == w.candidate_id
    assert revised[0].candidate_id != revised[1].candidate_id
    assert len(collect_physical_wall_identities(revised, {"edges": list(edges().values())})) == 3


def test_collision_ids_are_invariant_to_input_order_and_raw_segment_direction():
    a, b = wall("source-edge-a", "junction-a"), wall("source-edge-b", "junction-b", reverse=True)
    initial, _ = _source_owned_collision_candidate_addresses(
        (a, b), edges(),
        {"source-edge-a": a.candidate_id, "source-edge-b": b.candidate_id})
    changed_edges = edges()
    for edge in changed_edges.values():
        edge["x1"], edge["x2"] = edge["x2"], edge["x1"]
        edge["y1"], edge["y2"] = edge["y2"], edge["y1"]
    reversed_rows, _ = _source_owned_collision_candidate_addresses(
        (b, a), changed_edges,
        {"source-edge-a": a.candidate_id, "source-edge-b": b.candidate_id})
    assert {x.face_a_segment_ids[0]: x.candidate_id for x in initial} == {
        x.face_a_segment_ids[0]: x.candidate_id for x in reversed_rows}


def test_unique_unrelated_walls_are_identity_pass_through_without_source_data():
    one = wall("source-edge-a", "junction-a")
    two = wall("source-edge-b", "junction-b", candidate_id="wall_other")
    remapped, owners = _source_owned_collision_candidate_addresses(
        (one, two), {}, {"source-edge-a": one.candidate_id,
                          "source-edge-b": two.candidate_id})
    assert remapped == [one, two]
    assert owners == {"source-edge-a": one.candidate_id, "source-edge-b": two.candidate_id}


@pytest.mark.parametrize("bad", ["missing_edge", "missing_source", "foreign_source", "nan", "same_edge",
                                  "same_identity", "wrong_owner"])
def test_unprovable_collision_never_rekeys_from_ambiguous_or_corrupt_source(bad):
    a, b = wall("source-edge-a", "junction-a"), wall("source-edge-b", "junction-b")
    inventory = edges()
    owners = {"source-edge-a": a.candidate_id, "source-edge-b": b.candidate_id}
    if bad == "missing_edge":
        del inventory["source-edge-b"]
    elif bad == "missing_source":
        inventory["source-edge-b"].pop(LINEAGE_KEY)
    elif bad == "foreign_source":
        inventory["source-edge-b"][LINEAGE_KEY]["source_primitive_ids"] = ()
    elif bad == "nan":
        inventory["source-edge-b"]["x1"] = float("nan")
    elif bad == "same_edge":
        b = replace(b, face_a_segment_ids=a.face_a_segment_ids)
    elif bad == "same_identity":
        b = replace(b, end_node_ids=a.end_node_ids)
        inventory["source-edge-b"][LINEAGE_KEY]["source_primitive_ids"] = ("native-a",)
    else:
        owners["source-edge-b"] = "foreign-owner"
    if bad == "same_identity":
        inventory["source-edge-b"]["x1"] = inventory["source-edge-a"]["x1"]
        inventory["source-edge-b"]["x2"] = inventory["source-edge-a"]["x2"]
    original = deepcopy((a, b, inventory, owners))
    with pytest.raises(W4SourceCandidateAddressCollision):
        _source_owned_collision_candidate_addresses((a, b), inventory, owners)
    assert (a, b, inventory, owners) == original


def test_collection_refuses_colliding_w4_id_before_last_writer_overwrite():
    a, b = wall("source-edge-a", "junction-a"), wall("source-edge-b", "junction-b")
    with pytest.raises(ValueError, match="duplicate W4 candidate id"):
        collect_physical_wall_identities((a, b), {"edges": list(edges().values())})


def test_shared_native_parents_with_distinct_split_edges_do_not_alias_w4_address():
    """Two adjacent W2 fragments can inherit exactly the same three U1 parents.

    Original-source shared ancestry is NOT sufficient to erase the different
    W2 split coordinates and W3 junction owners, nor to prove different
    physical walls.
    """
    a = wall("source-edge-a", "junction-a")
    b = wall("source-edge-b", "junction-b", reverse=True)
    graph_edges = edges()
    common = ["source-a", "source-b", "source-c"]
    for eid in ("source-edge-a", "source-edge-b"):
        graph_edges[eid][LINEAGE_KEY]["source_primitive_ids"] = common
    graph_edges["source-edge-a"].update({"x1": 1., "y1": 4., "x2": 1., "y2": 9.})
    graph_edges["source-edge-b"].update({"x1": 1., "y1": 9., "x2": 1., "y2": 12.})
    old = deepcopy((a, b, graph_edges))
    candidates, mapping = _source_owned_collision_candidate_addresses(
        (b, a), graph_edges,
        {"source-edge-a": a.candidate_id, "source-edge-b": b.candidate_id},
    )
    assert len(candidates) == len({c.candidate_id for c in candidates}) == 2
    assert candidates[0].candidate_id != candidates[1].candidate_id
    assert mapping["source-edge-a"] != mapping["source-edge-b"]
    assert all(c.metadata["precollision_w4_candidate_id"] == a.candidate_id
               for c in candidates)
    assert (a, b, graph_edges) == old


def test_source_collision_rekey_is_independent_of_global_page_translation():
    """Candidate-address order cannot choose a winner after moving a viewport."""
    a, b = wall("source-edge-a", "junction-a"), wall("source-edge-b", "junction-b")
    inventory = edges()
    original_ids, _ = _source_owned_collision_candidate_addresses(
        (a, b), inventory,
        {"source-edge-a": a.candidate_id, "source-edge-b": b.candidate_id},
    )
    shifted = deepcopy(inventory)
    for edge in shifted.values():
        edge["x1"] += 500
        edge["x2"] += 500
        edge["y1"] -= 200
        edge["y2"] -= 200
    shifted_a, shifted_b = (
        replace(a, centerline_pts=tuple((x + 500, y - 200) for x, y in a.centerline_pts)),
        replace(b, centerline_pts=tuple((x + 500, y - 200) for x, y in b.centerline_pts)),
    )
    translated, _ = _source_owned_collision_candidate_addresses(
        (shifted_b, shifted_a), shifted,
        {"source-edge-a": a.candidate_id, "source-edge-b": b.candidate_id},
    )
    assert len({c.candidate_id for c in translated}) == 2
    assert {c.face_a_segment_ids[0] for c in translated} == {
        c.face_a_segment_ids[0] for c in original_ids}


def test_coincident_source_edges_with_shared_ancestry_and_distinct_junctions():
    """Coincident W2 source edges can still have different original W3 owners.

    Matching geometry and three shared native parents do not justify silently
    selecting the last row; distinct W4 candidate addresses remain separately
    subject to physical SAME/AMBIGUOUS equivalence review.
    """
    a = wall("source-edge-a", "junction-a")
    b = wall("source-edge-b", "junction-b", reverse=True)
    source_edges = edges()
    lineage = ("original-parent-one", "original-parent-two", "original-parent-three")
    for name in ("source-edge-a", "source-edge-b"):
        source_edges[name][LINEAGE_KEY]["source_primitive_ids"] = lineage
    originals = deepcopy((a, b, source_edges))
    candidates, owners = _source_owned_collision_candidate_addresses(
        (a, b), source_edges,
        {"source-edge-a": a.candidate_id, "source-edge-b": b.candidate_id})
    assert len(candidates) == 2
    assert candidates[0].candidate_id != candidates[1].candidate_id
    assert owners["source-edge-a"] == candidates[0].candidate_id
    assert owners["source-edge-b"] == candidates[1].candidate_id
    assert all("source_owned_w4_candidate_address_collision" in x.reason_codes
               and x.status is EvidenceResolutionStatus.CANDIDATE
               for x in candidates)
    assert (a, b, source_edges) == originals


def test_noncolliding_unchanged_id_is_never_reused_by_disambiguator(monkeypatch):
    import pb_wall_room_topology_wall_assembly as w4
    a = wall("source-edge-a", "junction-a")
    b = wall("source-edge-b", "junction-b")
    unrelated = wall("unrelated", "junction-c", candidate_id="wall_other", y=10.)
    original = w4.stable_contract_id
    def collide_with_unrelated(prefix, payload):
        if "geometric_candidate_id" in payload:
            return unrelated.candidate_id
        return original(prefix, payload)
    monkeypatch.setattr(w4, "stable_contract_id", collide_with_unrelated)
    with pytest.raises(ValueError, match="W4 collision not uniquely source-disambiguated"):
        _source_owned_collision_candidate_addresses(
            (a, b, unrelated), edges(),
            {"source-edge-a": a.candidate_id,
             "source-edge-b": b.candidate_id,
             "unrelated": unrelated.candidate_id})


@pytest.mark.parametrize("error_source,error_text", [
    ("w4", "W4 collision lacks positive source ancestry"),
    ("w4", "W4 collision has missing original source edge"),
    ("collector", "duplicate W4 candidate id before physical identity collection"),
    ("w4", "W4 collided wall lost source edge ownership"),
    ("w4", "W4 source edge owner unexpectedly changed"),
    ("w4", "W4 source candidate addresses remain duplicated"),
])
def test_production_w4_source_collision_returns_unavailable_not_unhandled(
    monkeypatch, error_source, error_text
):
    import pb_physical_wall_candidate_authority as authority

    def assemble(*args, **kwargs):
        if error_source == "w4":
            raise W4SourceCandidateAddressCollision(error_text)
        return ["positive-source-wall"], ["source-junction"]

    def collect(*args, **kwargs):
        if error_source == "collector":
            raise ValueError(error_text)
        return {"positive-source-wall": "verified-identity"}

    monkeypatch.setattr(authority, "assemble_wall_topology", assemble)
    monkeypatch.setattr(authority, "collect_physical_wall_identities", collect)
    outcome = authority._assemble_source_owned_w4_identities_or_unavailable(
        graph={"edges": []}, junctions=(), relationships=(),
        scope_id="original-source-only",
    )
    assert outcome is None


def test_production_w4_source_collision_guard_preserves_valid_walls(monkeypatch):
    import pb_physical_wall_candidate_authority as authority

    expected_walls = ["original-source-wall"]
    expected_junctions = ["original-junction"]
    expected_identities = {"original-source-wall": "original-source-identity"}
    def assemble(graph, junctions, relationships, *, viewport_id):
        assert viewport_id == "wall-source:page-3"
        return expected_walls, expected_junctions

    def collect(walls, graph):
        assert walls is expected_walls
        return expected_identities

    monkeypatch.setattr(authority, "assemble_wall_topology", assemble)
    monkeypatch.setattr(authority, "collect_physical_wall_identities", collect)
    result = authority._assemble_source_owned_w4_identities_or_unavailable(
        graph={"edges": []}, junctions=(), relationships=(),
        scope_id="wall-source:page-3",
    )
    assert result == (expected_walls, expected_junctions, expected_identities)
    assert result[0] is expected_walls and result[2] is expected_identities


def test_production_w4_scope_does_not_hide_unrelated_assembly_error(monkeypatch):
    import pb_physical_wall_candidate_authority as authority

    def fail_unexpected(*args, **kwargs):
        raise ValueError("unexpected source graph corruption")

    monkeypatch.setattr(authority, "assemble_wall_topology", fail_unexpected)
    with pytest.raises(ValueError, match="unexpected source graph corruption"):
        authority._assemble_source_owned_w4_identities_or_unavailable(
            graph={}, junctions=(), relationships=(),
            scope_id="wall-source:page-3",
        )


def test_production_guard_refuses_an_unrelated_value_error_with_collision_like_text(monkeypatch):
    import pb_physical_wall_candidate_authority as authority

    def malicious_untyped_failure(*args, **kwargs):
        raise ValueError("W4 collision is merely part of an unrelated error string")

    monkeypatch.setattr(authority, "assemble_wall_topology", malicious_untyped_failure)
    with pytest.raises(ValueError, match="unrelated error string"):
        authority._assemble_source_owned_w4_identities_or_unavailable(
            graph={}, junctions=(), relationships=(),
            scope_id="wall-source:page-3",
        )

@pytest.mark.parametrize("bad_parent", ("", " ", "\t"))
def test_w4_collision_refuses_whitespace_source_ancestry(bad_parent):
    a = wall("source-edge-a", "junction-a")
    b = wall("source-edge-b", "junction-b", reverse=True)
    source_edges = edges()
    source_edges["source-edge-a"][LINEAGE_KEY]["source_primitive_ids"] = (bad_parent,)
    original = deepcopy(source_edges)
    with pytest.raises(W4SourceCandidateAddressCollision, match="positive source ancestry"):
        _source_owned_collision_candidate_addresses(
            (a, b), source_edges,
            {"source-edge-a": a.candidate_id, "source-edge-b": b.candidate_id},
        )
    assert source_edges == original
