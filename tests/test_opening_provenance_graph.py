"""Fail-closed opening provenance graph: synthetic positives, negatives, metamorphic."""
from __future__ import annotations

from pb_opening_provenance_graph import (
    DIMENSION_CALLOUT,
    PHYSICAL_HOSTED_SPAN,
    PLAN_INSTANCE_MARK,
    REL_CONTAINED_TAG,
    REL_DIRECT_LEADER,
    REL_SCHEDULE_TYPE_MATCH,
    STATUS_AMBIGUOUS,
    STATUS_CONFLICT,
    STATUS_RESOLVED,
    STATUS_UNBOUND,
    OpeningEvidenceNode,
    callout_node,
    collect_opening_provenance_shadow,
    empty_opening_provenance_shadow,
    local_opening_bbox,
    resolve_opening_provenance,
    schedule_node,
    tag_node,
)

VP = (0.0, 0.0, 400.0, 400.0)
OTHER_VP = (500.0, 0.0, 900.0, 400.0)


def _physical(
    *,
    node_id: str = "span-a",
    page: int = 1,
    viewport=VP,
    jamb_start=(40.0, 80.0),
    jamb_end=(88.0, 80.0),
    thickness: float = 8.0,
    width_m: float | None = 1.50,
) -> OpeningEvidenceNode:
    return OpeningEvidenceNode(
        node_id=node_id,
        evidence_type=PHYSICAL_HOSTED_SPAN,
        page=page,
        viewport=viewport,
        bbox=local_opening_bbox(jamb_start, jamb_end, thickness),
        width_m=width_m,
        height_m=None,
        provenance="test",
    )


def test_local_opening_bbox_is_the_wall_band_not_a_padded_guess() -> None:
    box = local_opening_bbox((40.0, 80.0), (88.0, 80.0), 8.0)
    assert box[0] == 40.0
    assert box[2] == 88.0
    assert box[1] == 76.0
    assert box[3] == 84.0


def test_opening_plus_exact_local_tag_resolves_identity() -> None:
    phys = _physical()
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W-03")
    graph = resolve_opening_provenance([phys, tag])
    res = graph["resolutions"][0]
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] == "W3"
    assert res["height_m"] is None
    assert res["bound_wall_id"] is None
    assert any(e["relation_type"] == REL_CONTAINED_TAG for e in graph["edges"])


def test_exact_tag_plus_unique_schedule_row_binds_height() -> None:
    phys = _physical(width_m=1.50)
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W3")
    row = schedule_node(page=4, viewport=VP, tag="W3", width_m=1.50, height_m=1.50)
    graph = resolve_opening_provenance([phys, tag, row])
    res = graph["resolutions"][0]
    assert res["status"] == STATUS_RESOLVED
    assert res["schedule_row"] == row.node_id
    assert res["height_m"] == 1.50
    assert any(e["relation_type"] == REL_SCHEDULE_TYPE_MATCH for e in graph["edges"])


def test_exact_leader_binds_identity() -> None:
    phys = _physical()
    tag = tag_node(page=1, viewport=VP, bbox=(200.0, 40.0, 220.0, 52.0), raw_token="D2")
    graph = resolve_opening_provenance(
        [phys, tag],
        leaders=[{"tag_node": tag.node_id, "endpoint": (60.0, 80.0), "viewport": VP}],
    )
    res = graph["resolutions"][0]
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] == "D2"
    assert any(e["relation_type"] == REL_DIRECT_LEADER for e in graph["edges"])


def test_contained_wxh_callout_can_supply_height_without_minting_identity() -> None:
    phys = _physical(width_m=None)
    callout = callout_node(
        page=1,
        viewport=VP,
        bbox=(55.0, 77.0, 70.0, 83.0),
        kind="window",
        width_m=1.50,
        height_m=0.90,
        raw_token="1500mm x 900mm window",
    )
    graph = resolve_opening_provenance([phys, callout])
    res = graph["resolutions"][0]
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] is None
    assert res["width_m"] == 1.50
    assert res["height_m"] == 0.90
    assert "W1" not in {n["normalized_value"] for n in graph["nodes"]}


def test_type_mark_normalization_uses_shared_gate() -> None:
    phys = _physical()
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 70.0, 83.0), raw_token="WINDOW 07")
    graph = resolve_opening_provenance([phys, tag])
    assert graph["resolutions"][0]["resolved_type_mark"] == "W7"


def test_two_nearby_tags_conflict() -> None:
    phys = _physical()
    a = tag_node(page=1, viewport=VP, bbox=(42.0, 77.0, 50.0, 83.0), raw_token="W1")
    b = tag_node(page=1, viewport=VP, bbox=(70.0, 77.0, 80.0, 83.0), raw_token="W2")
    graph = resolve_opening_provenance([phys, a, b])
    assert graph["resolutions"][0]["status"] == STATUS_CONFLICT
    assert graph["conflicts"]


def test_one_tag_serving_two_openings_conflicts() -> None:
    left = _physical(node_id="span-l", jamb_start=(40.0, 80.0), jamb_end=(88.0, 80.0))
    right = _physical(node_id="span-r", jamb_start=(40.0, 80.0), jamb_end=(88.0, 80.0))
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W3")
    graph = resolve_opening_provenance([left, right, tag])
    assert {item["status"] for item in graph["resolutions"]} == {STATUS_CONFLICT}


def test_cross_view_tag_is_rejected() -> None:
    phys = _physical()
    tag = tag_node(page=1, viewport=OTHER_VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W3")
    graph = resolve_opening_provenance([phys, tag])
    assert graph["resolutions"][0]["status"] == STATUS_UNBOUND
    assert graph["resolutions"][0]["resolved_type_mark"] is None
    assert graph["edges"] == []


def test_schedule_row_without_physical_tag_does_not_mint_instance() -> None:
    phys = _physical()
    row = schedule_node(page=4, viewport=VP, tag="W3", width_m=1.50, height_m=1.50)
    graph = resolve_opening_provenance([phys, row])
    res = graph["resolutions"][0]
    assert res["status"] == STATUS_UNBOUND
    assert res["resolved_type_mark"] is None
    assert res["schedule_row"] is None
    assert res["height_m"] is None


def test_repeated_windows_with_no_tags_stay_unbound() -> None:
    spans = [
        _physical(node_id=f"span-{i}", jamb_start=(40.0 + i * 60, 80.0), jamb_end=(80.0 + i * 60, 80.0))
        for i in range(3)
    ]
    graph = resolve_opening_provenance(spans)
    assert {item["status"] for item in graph["resolutions"]} == {STATUS_UNBOUND}
    assert all(item["resolved_type_mark"] is None for item in graph["resolutions"])


def test_width_only_similarity_does_not_bind_schedule() -> None:
    phys = _physical(width_m=1.50)
    row = schedule_node(page=4, viewport=VP, tag="W9", width_m=1.50, height_m=1.20)
    graph = resolve_opening_provenance([phys, row])
    assert graph["resolutions"][0]["status"] == STATUS_UNBOUND
    assert graph["resolutions"][0]["height_m"] is None


def test_duplicate_schedule_mark_with_conflicting_heights_conflicts() -> None:
    phys = _physical(width_m=1.50)
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W3")
    a = schedule_node(page=4, viewport=VP, tag="W3", width_m=1.50, height_m=1.50, node_id="sched-a")
    b = schedule_node(page=4, viewport=VP, tag="W3", width_m=1.50, height_m=1.20, node_id="sched-b")
    graph = resolve_opening_provenance([phys, tag, a, b])
    assert graph["resolutions"][0]["status"] == STATUS_CONFLICT
    assert graph["resolutions"][0]["height_m"] is None


def test_conflicting_contained_callout_heights_conflict() -> None:
    phys = _physical(width_m=None)
    a = callout_node(
        page=1, viewport=VP, bbox=(42.0, 77.0, 52.0, 83.0),
        kind="window", width_m=2.90, height_m=0.90, raw_token="2900mm x 900mm window",
        node_id="c-a",
    )
    b = callout_node(
        page=1, viewport=VP, bbox=(70.0, 77.0, 82.0, 83.0),
        kind="window", width_m=3.00, height_m=1.20, raw_token="3000mm x 1200mm window",
        node_id="c-b",
    )
    graph = resolve_opening_provenance([phys, a, b])
    assert graph["resolutions"][0]["status"] == STATUS_CONFLICT
    assert graph["resolutions"][0]["height_m"] is None


def test_ocr_native_disagreement_is_not_auto_chosen() -> None:
    phys = _physical()
    native = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W3")
    ocr = OpeningEvidenceNode(
        node_id="ocr-w8",
        evidence_type="ocr_annotation",
        page=1,
        viewport=VP,
        bbox=(51.0, 77.0, 63.0, 83.0),
        raw_token="W8",
        normalized_value="W8",
        provenance="ocr",
    )
    graph = resolve_opening_provenance([phys, native, ocr])
    assert graph["resolutions"][0]["status"] == STATUS_CONFLICT


def test_text_near_wall_but_outside_opening_bbox_is_ignored() -> None:
    phys = _physical()
    nearby = tag_node(page=1, viewport=VP, bbox=(40.0, 100.0, 60.0, 112.0), raw_token="W3")
    graph = resolve_opening_provenance([phys, nearby])
    assert graph["resolutions"][0]["status"] == STATUS_UNBOUND
    assert graph["edges"] == []


def test_title_block_and_room_annotation_outside_opening_do_not_bind() -> None:
    phys = _physical()
    title = tag_node(page=1, viewport=VP, bbox=(10.0, 10.0, 40.0, 20.0), raw_token="W1")
    room = callout_node(
        page=1, viewport=VP, bbox=(200.0, 200.0, 260.0, 220.0),
        kind="window", width_m=1.20, height_m=1.20, raw_token="1200mm x 1200mm window",
    )
    graph = resolve_opening_provenance([phys, title, room])
    res = graph["resolutions"][0]
    assert res["status"] == STATUS_UNBOUND
    assert res["height_m"] is None
    assert res["resolved_type_mark"] is None


def test_kstvet_style_drawing_height_is_not_rewritten_to_1200() -> None:
    phys = _physical(width_m=3.00)
    callout = callout_node(
        page=1,
        viewport=VP,
        bbox=(50.0, 77.0, 80.0, 83.0),
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
    assert all(n.get("normalized_value") not in {"W1", "W2"} for n in graph["nodes"])


def test_physical_width_disagrees_with_schedule_row_conflicts() -> None:
    phys = _physical(width_m=2.00)
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W3")
    row = schedule_node(page=4, viewport=VP, tag="W3", width_m=1.20, height_m=1.20)
    graph = resolve_opening_provenance([phys, tag, row])
    assert graph["resolutions"][0]["status"] == STATUS_CONFLICT
    assert graph["resolutions"][0]["schedule_row"] is None


def test_leader_endpoint_ambiguous_across_openings_conflicts() -> None:
    left = _physical(node_id="span-l", jamb_start=(40.0, 80.0), jamb_end=(88.0, 80.0))
    right = _physical(node_id="span-r", jamb_start=(40.0, 80.0), jamb_end=(88.0, 80.0))
    tag = tag_node(page=1, viewport=VP, bbox=(200.0, 40.0, 220.0, 52.0), raw_token="D2")
    graph = resolve_opening_provenance(
        [left, right, tag],
        leaders=[{"tag_node": tag.node_id, "endpoint": (60.0, 80.0), "viewport": VP}],
    )
    assert {item["status"] for item in graph["resolutions"]} == {STATUS_CONFLICT}


def test_rotate90_metamorphic_preserves_resolution() -> None:
    phys = _physical()
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W3")
    baseline = resolve_opening_provenance([phys, tag])["resolutions"][0]

    def rot(x, y):
        return (-y, x)

    def rot_box(box):
        corners = [rot(box[0], box[1]), rot(box[2], box[1]), rot(box[0], box[3]), rot(box[2], box[3])]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    rotated_phys = OpeningEvidenceNode(
        node_id=phys.node_id,
        evidence_type=phys.evidence_type,
        page=phys.page,
        viewport=rot_box(phys.viewport),
        bbox=rot_box(phys.bbox),
        width_m=phys.width_m,
        provenance=phys.provenance,
    )
    rotated_tag = tag_node(
        page=1,
        viewport=rot_box(VP),
        bbox=rot_box((50.0, 77.0, 62.0, 83.0)),
        raw_token="W3",
        node_id=tag.node_id,
    )
    moved = resolve_opening_provenance([rotated_phys, rotated_tag])["resolutions"][0]
    assert moved["status"] == baseline["status"] == STATUS_RESOLVED
    assert moved["resolved_type_mark"] == baseline["resolved_type_mark"]


def test_translation_metamorphic_preserves_resolution() -> None:
    dx, dy = 125.0, -40.0

    def shift_box(box, x=dx, y=dy):
        return (box[0] + x, box[1] + y, box[2] + x, box[3] + y)

    def shift_vp(vp, x=dx, y=dy):
        return (vp[0] + x, vp[1] + y, vp[2] + x, vp[3] + y)

    phys = _physical()
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W3")
    baseline = resolve_opening_provenance([phys, tag])["resolutions"][0]
    moved_phys = OpeningEvidenceNode(
        node_id=phys.node_id,
        evidence_type=phys.evidence_type,
        page=phys.page,
        viewport=shift_vp(phys.viewport),
        bbox=shift_box(phys.bbox),
        width_m=phys.width_m,
        provenance=phys.provenance,
    )
    moved_tag = tag_node(
        page=1,
        viewport=shift_vp(VP),
        bbox=shift_box((50.0, 77.0, 62.0, 83.0)),
        raw_token="W3",
        node_id=tag.node_id,
    )
    moved = resolve_opening_provenance([moved_phys, moved_tag])["resolutions"][0]
    assert moved["status"] == baseline["status"] == STATUS_RESOLVED
    assert moved["resolved_type_mark"] == baseline["resolved_type_mark"]


def test_empty_shadow_envelope_is_diagnostic_only() -> None:
    shadow = empty_opening_provenance_shadow(reason="no_physical_opening_nodes")
    assert shadow["status"] == "abstained"
    assert shadow["nodes"] == []
    assert shadow["resolutions"] == []
    assert "pred_dict" not in shadow


def test_collect_from_hosted_shadow_does_not_invent_identity() -> None:
    hosted = {
        "status": "found",
        "reason": "1 hosted opening span(s) found",
        "evidence": [
            {
                "span_id": "hosted-span-p1-0-40.00-80.00-88.00-80.00",
                "page": 1,
                "jamb_start": [40.0, 80.0],
                "jamb_end": [88.0, 80.0],
                "wall_thickness_pt": 8.0,
                "width_m": None,
                "viewport": list(VP),
            }
        ],
    }
    shadow = collect_opening_provenance_shadow(hosted_shadow=hosted)
    assert shadow["resolutions"][0]["status"] == STATUS_UNBOUND
    assert shadow["resolutions"][0]["height_m"] is None
    assert shadow["resolutions"][0]["bound_wall_id"] is None
