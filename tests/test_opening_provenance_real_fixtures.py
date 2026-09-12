"""Provenance shadow against committed hosted-opening snapshots.

Fixture filenames identify the source drawings for reviewers. Production
code never branches on those names.
"""
from __future__ import annotations

from pathlib import Path

from pb_hosted_opening_geometry import resolve_hosted_opening_spans
from pb_hosted_opening_instance_adapter import hosted_span_to_shadow_record
from pb_opening_provenance_graph import (
    STATUS_CONFLICT,
    STATUS_RESOLVED,
    STATUS_UNBOUND,
    callout_node,
    collect_opening_provenance_shadow,
    local_opening_bbox,
    physical_node_from_hosted_record,
    resolve_opening_provenance,
    tag_node,
)
from tests.test_hosted_opening_geometry import (
    _BAGHAU_SNAPSHOT_PATH,
    _DUNGICHA_SNAPSHOT_PATH,
    _load_snapshot,
    _snapshot_page,
)

_FIXTURE_NORTH = (440.0, 440.0, 880.0, 500.0)
_FIXTURE_FULL = (440.0, 440.0, 880.0, 760.0)
_FIXTURE_FRONT = (60.0, 600.0, 800.0, 780.0)


def _physical_nodes(spans, viewport):
    nodes = []
    for span in spans:
        record = hosted_span_to_shadow_record(span)
        if record is None:
            continue
        record["viewport"] = list(viewport)
        nodes.append(physical_node_from_hosted_record(record))
    return nodes


def test_snapshot_physical_spans_are_unbound_without_local_tags() -> None:
    snapshot = _load_snapshot(_BAGHAU_SNAPSHOT_PATH)
    page = _snapshot_page(snapshot)
    ev = resolve_hosted_opening_spans(page, viewport_bbox=_FIXTURE_NORTH, scale_authority=28.3)
    nodes = _physical_nodes(ev.openings, _FIXTURE_NORTH)
    graph = resolve_opening_provenance(nodes)
    assert nodes
    assert all(item["status"] == STATUS_UNBOUND for item in graph["resolutions"])
    assert all(item["resolved_type_mark"] is None for item in graph["resolutions"])
    assert all(item["height_m"] is None for item in graph["resolutions"])
    assert all(item["bound_wall_id"] is None for item in graph["resolutions"])


def test_local_tag_inside_one_snapshot_span_resolves_only_that_span() -> None:
    snapshot = _load_snapshot(_BAGHAU_SNAPSHOT_PATH)
    page = _snapshot_page(snapshot)
    ev = resolve_hosted_opening_spans(page, viewport_bbox=_FIXTURE_NORTH, scale_authority=28.3)
    nodes = _physical_nodes(ev.openings, _FIXTURE_NORTH)
    first = nodes[0]
    tag = tag_node(
        page=first.page,
        viewport=_FIXTURE_NORTH,
        bbox=(
            (first.bbox[0] + first.bbox[2]) / 2.0 - 2.0,
            (first.bbox[1] + first.bbox[3]) / 2.0 - 1.0,
            (first.bbox[0] + first.bbox[2]) / 2.0 + 2.0,
            (first.bbox[1] + first.bbox[3]) / 2.0 + 1.0,
        ),
        raw_token="WD-01",
    )
    # WD-01 is not an accepted normalized opening tag; prove fail-closed.
    if tag is None:
        graph = resolve_opening_provenance(nodes)
        assert all(item["status"] == STATUS_UNBOUND for item in graph["resolutions"])
        return
    graph = resolve_opening_provenance([*nodes, tag])
    resolved = [item for item in graph["resolutions"] if item["status"] == STATUS_RESOLVED]
    assert len(resolved) == 1
    assert resolved[0]["physical_opening"] == first.node_id


def test_accepted_local_w_tag_resolves_one_snapshot_span() -> None:
    snapshot = _load_snapshot(_DUNGICHA_SNAPSHOT_PATH)
    page = _snapshot_page(snapshot)
    ev = resolve_hosted_opening_spans(page, viewport_bbox=_FIXTURE_FRONT, scale_authority=28.35)
    nodes = _physical_nodes(ev.openings, _FIXTURE_FRONT)
    first = nodes[0]
    tag = tag_node(
        page=first.page,
        viewport=_FIXTURE_FRONT,
        bbox=(
            (first.bbox[0] + first.bbox[2]) / 2.0 - 2.0,
            (first.bbox[1] + first.bbox[3]) / 2.0 - 1.0,
            (first.bbox[0] + first.bbox[2]) / 2.0 + 2.0,
            (first.bbox[1] + first.bbox[3]) / 2.0 + 1.0,
        ),
        raw_token="W1",
    )
    graph = resolve_opening_provenance([*nodes, tag])
    resolved = [item for item in graph["resolutions"] if item["physical_opening"] == first.node_id][0]
    others = [item for item in graph["resolutions"] if item["physical_opening"] != first.node_id]
    assert resolved["status"] == STATUS_RESOLVED
    assert resolved["resolved_type_mark"] == "W1"
    assert all(item["status"] == STATUS_UNBOUND for item in others)
    assert all(item["resolved_type_mark"] is None for item in others)


def test_two_local_tags_in_one_snapshot_span_conflict() -> None:
    snapshot = _load_snapshot(_BAGHAU_SNAPSHOT_PATH)
    page = _snapshot_page(snapshot)
    ev = resolve_hosted_opening_spans(page, viewport_bbox=_FIXTURE_FULL, scale_authority=28.3)
    nodes = _physical_nodes(ev.openings, _FIXTURE_FULL)
    first = nodes[0]
    cx = (first.bbox[0] + first.bbox[2]) / 2.0
    cy = (first.bbox[1] + first.bbox[3]) / 2.0
    a = tag_node(page=first.page, viewport=_FIXTURE_FULL, bbox=(cx - 6, cy - 1, cx - 2, cy + 1), raw_token="W1")
    b = tag_node(page=first.page, viewport=_FIXTURE_FULL, bbox=(cx + 2, cy - 1, cx + 6, cy + 1), raw_token="W2")
    graph = resolve_opening_provenance([*nodes, a, b])
    target = next(item for item in graph["resolutions"] if item["physical_opening"] == first.node_id)
    assert target["status"] == STATUS_CONFLICT


def test_snapshot_shadow_collection_stays_unbound_and_anonymous() -> None:
    snapshot = _load_snapshot(_BAGHAU_SNAPSHOT_PATH)
    page = _snapshot_page(snapshot)
    ev = resolve_hosted_opening_spans(page, viewport_bbox=_FIXTURE_NORTH, scale_authority=None)
    evidence = []
    for span in ev.openings:
        record = hosted_span_to_shadow_record(span)
        if record is None:
            continue
        record["viewport"] = list(_FIXTURE_NORTH)
        evidence.append(record)
    shadow = collect_opening_provenance_shadow(
        hosted_shadow={"status": "found", "reason": "spans", "evidence": evidence}
    )
    assert shadow["resolutions"]
    assert all(item["status"] == STATUS_UNBOUND for item in shadow["resolutions"])
    assert all(not str(item["physical_opening"]).startswith("W") for item in shadow["resolutions"])
    assert all(item["height_m"] is None for item in shadow["resolutions"])


def test_kstvet_style_callouts_keep_900_height_and_do_not_mint_w1() -> None:
    """Drawing-side 3000x900 / 2900x900 must not become 1200 or W1/W2."""
    viewport = (0.0, 0.0, 200.0, 200.0)
    box = local_opening_bbox((20.0, 40.0), (80.0, 40.0), 8.0)
    from pb_opening_provenance_graph import OpeningEvidenceNode, PHYSICAL_HOSTED_SPAN

    phys = OpeningEvidenceNode(
        node_id="kstvet-like-span",
        evidence_type=PHYSICAL_HOSTED_SPAN,
        page=12,
        viewport=viewport,
        bbox=box,
        width_m=3.00,
        height_m=None,
        provenance="synthetic-drawing-span",
    )
    callout = callout_node(
        page=12,
        viewport=viewport,
        bbox=(40.0, 37.0, 70.0, 43.0),
        kind="window",
        width_m=3.00,
        height_m=0.90,
        raw_token="3000mm x 900mm window",
    )
    graph = resolve_opening_provenance([phys, callout])
    res = graph["resolutions"][0]
    assert res["height_m"] == 0.90
    assert res["height_m"] != 1.20
    assert res["resolved_type_mark"] is None
    assert all(n.get("normalized_value") not in {"W1", "W2", "D1"} for n in graph["nodes"])
