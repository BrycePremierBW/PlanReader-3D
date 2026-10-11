"""Exact source-path hypotheses cannot supply wall or publication authority."""
from copy import deepcopy

import pytest

from pb_wall_room_topology_wall_identity_v2 import (
    canonical_path_fingerprint,
    canonical_wall_candidate_id_v2_from_components,
)
from tools.gptmax_terminal_source_span_shadow import preview_terminal_source_spans


def record(cid="wall_alpha", source="source_positive", lines=None):
    lines = lines or [(0., 0., 10., 0.)]
    identity = canonical_wall_candidate_id_v2_from_components(
        "source-page-one", canonical_path_fingerprint((lines[0][:2], lines[-1][2:])),
        (source,))
    return {
        "wall_candidate_id": cid,
        "physical_identity": {
            "status": "corroborated", "source_primitive_ids": [source],
            "candidate_identity_id": identity, "wall_candidate_id": cid,
            "viewport_id": "source-page-one",
        },
        "wall_candidate": {"viewport_id": "source-page-one", "candidate_id": cid},
        "source_edge_fragments": [{
            "edge_id": f"{cid}_edge_{i}", "geometry": list(line),
            "source_primitive_ids": [source],
        } for i, line in enumerate(lines)],
    }


def audit(coords=(10., 0., 11.25, 0.)):
    return {"original_positive_source_short_fragments": [{
        "source_split_fragment_id": "split_lost",
        "positive_source_primitive_id": "source_positive",
        "w2_observation": "SNAP_COLLAPSED",
        "snapped_endpoint_node_ids": [42, 42],
        "original_source_geometry_pt": list(coords),
    }]}


def test_exact_terminal_source_span_reconstructs_identity_without_authority_or_mutation():
    records, traced = [record()], audit()
    before = deepcopy((records, traced))
    result = preview_terminal_source_spans(records, traced)
    assert (records, traced) == before
    assert result["disposition_counts"] == {"unique_terminal_source_path_preview": 1}
    row = result["source_path_previews"][0]
    assert row["proposed_source_path_pt"] == ((0., 0.), (10., 0.), (11.25, 0.))
    assert row["proposed_source_candidate_identity_id"] == canonical_wall_candidate_id_v2_from_components(
        "source-page-one", ((0., 0.), (11.25, 0.)), ("source_positive",))
    assert row["proposed_source_candidate_identity_id"] != row["current_source_candidate_identity_id"]
    for output in (row, result):
        assert output["physical_equivalence_proven"] is False
        assert output["graph_mutation_allowed"] is False
        assert output["host_count_quantity_publication_allowed"] is False
    assert result["source_scope_association_authenticated_by_this_preview"] is False
    assert result["benchmark_accuracy"] is None


@pytest.mark.parametrize("coords", [
    (10., 0., 5., 0.),                 # overlap ending inside an existing edge
    (10., 0., 0., 0.),                 # duplicate the complete existing edge
    (10., 0., 10., 1.),                # turn rather than extend one source line
    (10.00000001, 0., 11.25, 0.),       # near endpoint is not an exact join
    (5., 0., 6., 0.),                  # interior subinterval
])
def test_overlap_turn_near_endpoint_and_internal_interval_never_make_preview(coords):
    assert not preview_terminal_source_spans([record()], audit(coords))["source_path_previews"]


@pytest.mark.parametrize("lines", [
    [(0., 0., 5., 0.), (6., 0., 10., 0.)],
    [(0., 0., 10., 0.), (10., 0., 12., 0.), (10., 0., 10., 2.)],
    [(0., 0., 10., 0.), (10., 0., 5., 0.)],
    [(0., 0., 5., 0.), (5., 0., 5., 5.)],
    [(0., 0., 10., 0.), (10., 0., 0., 0.)],
])
def test_disconnected_branched_backtracking_bent_and_cyclic_source_paths_fail_closed(lines):
    terminal = lines[-1][2:]
    traced = audit((*terminal, terminal[0] + 1., terminal[1]))
    assert not preview_terminal_source_spans([record(lines=lines)], traced)["source_path_previews"]


@pytest.mark.parametrize("status", ["unresolved", "contradicted", "corroborated"])
def test_competing_owner_blocks_preview_even_when_other_owner_is_unresolved(status):
    competing = record("wall_beta", lines=[(10., 0., 20., 0.)])
    competing["physical_identity"]["status"] = status
    result = preview_terminal_source_spans([record(), competing], audit())
    assert not result["source_path_previews"]
    assert result["disposition_counts"] == {"source_endpoint_owner_unavailable_or_ambiguous": 1}


@pytest.mark.parametrize("change", ["unresolved", "multi_parent", "fragment_parent", "other_source"])
def test_uncorroborated_or_conflicting_lineage_cannot_supply_unique_source_owner(change):
    r, traced = record(), audit()
    if change == "unresolved":
        r["physical_identity"]["status"] = "unresolved"
    elif change == "multi_parent":
        r["physical_identity"]["source_primitive_ids"].append("other")
    elif change == "fragment_parent":
        r["source_edge_fragments"][0]["source_primitive_ids"].append("other")
    else:
        traced["original_positive_source_short_fragments"][0]["positive_source_primitive_id"] = "other"
    assert not preview_terminal_source_spans([r], traced)["source_path_previews"]


@pytest.mark.parametrize("status", ["EDGE_ABSENT_UNRESOLVED", "PRODUCER_REPORTED_EDGE_ABSENT", "RETAINED_RAW_EDGE"])
def test_untraced_disappearance_or_surviving_fragment_cannot_supply_terminal_preview(status):
    traced = audit()
    traced["original_positive_source_short_fragments"][0]["w2_observation"] = status
    assert preview_terminal_source_spans([record()], traced)["disposition_counts"] == {"not_proven_collapsed": 1}


@pytest.mark.parametrize("nodes", [None, [], [42], [42, 43], [True, True], [42., 42.]])
def test_missing_or_invalid_actual_collapse_assignments_raise(nodes):
    traced = audit()
    traced["original_positive_source_short_fragments"][0]["snapped_endpoint_node_ids"] = nodes
    with pytest.raises(ValueError, match="endpoint assignment"):
        preview_terminal_source_spans([record()], traced)


@pytest.mark.parametrize("change", [
    "candidate", "edge", "primitive", "fragment", "viewport", "identity_candidate",
    "empty_source", "nonfinite", "huge_integer", "degenerate", "already_surviving",
])
def test_corrupt_source_identity_or_geometry_never_emits_partial_preview(change):
    records, traced = [record()], audit()
    r = records[0]
    if change == "candidate":
        records.append(deepcopy(r))
    elif change == "edge":
        r["source_edge_fragments"].append(deepcopy(r["source_edge_fragments"][0]))
    elif change == "primitive":
        r["physical_identity"]["source_primitive_ids"] *= 2
    elif change == "fragment":
        traced["original_positive_source_short_fragments"] *= 2
    elif change == "viewport":
        r["physical_identity"]["viewport_id"] = "other-page"
    elif change == "identity_candidate":
        r["physical_identity"]["wall_candidate_id"] = "other-wall"
    elif change == "empty_source":
        traced["original_positive_source_short_fragments"][0]["positive_source_primitive_id"] = ""
    elif change in {"nonfinite", "huge_integer", "degenerate"}:
        coords = traced["original_positive_source_short_fragments"][0]["original_source_geometry_pt"]
        if change == "degenerate":
            coords[2:] = coords[:2]
        else:
            coords[0] = float("nan") if change == "nonfinite" else 10 ** 1000
    else:
        traced["original_positive_source_short_fragments"][0]["source_split_fragment_id"] = r["source_edge_fragments"][0]["edge_id"]
    with pytest.raises(ValueError):
        preview_terminal_source_spans(records, traced)


def test_records_from_different_viewports_cannot_be_combined():
    other = record("wall_beta", "other_source")
    other["wall_candidate"]["viewport_id"] = "other-page"
    other["physical_identity"]["viewport_id"] = "other-page"
    with pytest.raises(ValueError, match="mixed"):
        preview_terminal_source_spans([record(), other], audit())


def test_orientation_order_and_exact_collinear_rechunking_leave_preview_identity_stable():
    r = record(lines=[(0., 0., 5., 0.), (5., 0., 10., 0.)])
    traced = audit()
    first = preview_terminal_source_spans([r], traced)
    for fragment in r["source_edge_fragments"]:
        coords = fragment["geometry"]
        fragment["geometry"] = coords[2:] + coords[:2]
    r["source_edge_fragments"].reverse()
    coords = traced["original_positive_source_short_fragments"][0]["original_source_geometry_pt"]
    traced["original_positive_source_short_fragments"][0]["original_source_geometry_pt"] = coords[2:] + coords[:2]
    assert preview_terminal_source_spans([r], traced) == first
    assert first["source_path_previews"][0]["proposed_source_candidate_identity_id"] == preview_terminal_source_spans(
        [record()], audit())["source_path_previews"][0]["proposed_source_candidate_identity_id"]


@pytest.mark.parametrize("transform", [
    lambda x, y: (y, -x),
    lambda x, y: (2 * x + 100, 2 * y - 80),
    lambda x, y: (-x + 30, y + 40),
])
def test_rotated_reflected_scaled_and_translated_terminal_ownership_is_source_derived(transform):
    r, traced = record(), audit()
    for coords in (r["source_edge_fragments"][0]["geometry"],
                   traced["original_positive_source_short_fragments"][0]["original_source_geometry_pt"]):
        coords[:] = [*transform(*coords[:2]), *transform(*coords[2:])]
    row = preview_terminal_source_spans([r], traced)["source_path_previews"][0]
    expected = canonical_wall_candidate_id_v2_from_components(
        "source-page-one", canonical_path_fingerprint((transform(0., 0.), transform(11.25, 0.))),
        ("source_positive",))
    assert row["proposed_source_candidate_identity_id"] == expected


def test_preview_order_is_deterministic_without_source_specific_selection():
    r1, r2 = record(), record("wall_beta", "source_beta", [(0., 5., 10., 5.)])
    traced = audit()
    second = deepcopy(traced["original_positive_source_short_fragments"][0])
    second.update(source_split_fragment_id="split_beta", positive_source_primitive_id="source_beta",
                  original_source_geometry_pt=[10., 5., 11.25, 5.])
    traced["original_positive_source_short_fragments"].append(second)
    expected = preview_terminal_source_spans([r1, r2], traced)
    traced["original_positive_source_short_fragments"].reverse()
    assert preview_terminal_source_spans([r2, r1], traced) == expected


def test_unrelated_content_and_viewport_expansion_do_not_change_owned_source_preview():
    owned, traced = record(), audit()
    expected = preview_terminal_source_spans([owned], traced)
    unrelated = record("wall_elsewhere", "source_elsewhere", [(100., 200., 120., 200.)])
    owned["wall_candidate"]["viewport_bbox"] = [-500., -500., 500., 500.]
    assert preview_terminal_source_spans([unrelated, owned], traced) == expected


def test_exact_terminal_extension_at_other_end_is_equally_eligible():
    result = preview_terminal_source_spans([record()], audit((-1.25, 0., 0., 0.)))
    assert result["source_path_previews"][0]["proposed_source_path_pt"] == (
        (-1.25, 0.), (0., 0.), (10., 0.))

@pytest.mark.parametrize("parent", ("", "   ", "\t"))
def test_missing_or_whitespace_terminal_source_parent_never_previews(parent):
    records = [record()]
    records[0]["physical_identity"]["source_primitive_ids"] = [parent]
    with pytest.raises(ValueError, match="invalid original source primitive identities"):
        preview_terminal_source_spans(records, audit())
