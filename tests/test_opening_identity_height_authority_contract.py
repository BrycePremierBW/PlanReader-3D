"""Generic fail-closed identity/height authority for hosted opening spans.

These cases prove the existing provenance graph contract. They do not add
nearest-neighbour identity, typical construction heights, or live F.9 wiring.
"""
from __future__ import annotations

from pb_opening_callout_dimension_binder import parse_opening_size_callouts
from pb_opening_provenance_graph import (
    PHYSICAL_HOSTED_SPAN,
    STATUS_CONFLICT,
    STATUS_RESOLVED,
    STATUS_UNBOUND,
    OpeningEvidenceNode,
    callout_node,
    local_opening_bbox,
    resolve_opening_provenance,
    schedule_node,
    tag_node,
)
from pb_opening_tag_normalization import find_explicit_opening_tags, normalize_opening_tag

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
    width_m: float | None = 1.70,
    provenance: str = "hosted_opening_shadow",
) -> OpeningEvidenceNode:
    return OpeningEvidenceNode(
        node_id=node_id,
        evidence_type=PHYSICAL_HOSTED_SPAN,
        page=page,
        viewport=viewport,
        bbox=local_opening_bbox(jamb_start, jamb_end, thickness),
        width_m=width_m,
        height_m=None,
        provenance=provenance,
    )


def _resolution(graph: dict, node_id: str = "span-a") -> dict:
    return next(item for item in graph["resolutions"] if item["physical_opening"] == node_id)


def test_contained_w1_resolves_identity_only() -> None:
    phys = _physical()
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W1")
    res = _resolution(resolve_opening_provenance([phys, tag]))
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] == "W1"
    assert res["height_m"] is None
    assert res["bound_wall_id"] is None


def test_contained_d1_resolves_identity_only() -> None:
    phys = _physical(width_m=1.20)
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="D1")
    res = _resolution(resolve_opening_provenance([phys, tag]))
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] == "D1"
    assert res["height_m"] is None
    assert res["bound_wall_id"] is None


def test_one_mark_equally_plausible_for_two_spans_stays_unresolved() -> None:
    left = _physical(node_id="span-l", jamb_start=(40.0, 80.0), jamb_end=(88.0, 80.0))
    right = _physical(node_id="span-r", jamb_start=(40.0, 80.0), jamb_end=(88.0, 80.0))
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W1")
    graph = resolve_opening_provenance([left, right, tag])
    assert {item["status"] for item in graph["resolutions"]} == {STATUS_CONFLICT}
    assert all(item["height_m"] is None for item in graph["resolutions"])


def test_two_conflicting_marks_for_one_span_stay_unresolved() -> None:
    phys = _physical()
    a = tag_node(page=1, viewport=VP, bbox=(42.0, 77.0, 50.0, 83.0), raw_token="W1")
    b = tag_node(page=1, viewport=VP, bbox=(70.0, 77.0, 80.0, 83.0), raw_token="D1")
    res = _resolution(resolve_opening_provenance([phys, a, b]))
    assert res["status"] == STATUS_CONFLICT
    assert res["height_m"] is None


def test_window_like_geometry_without_mark_mints_no_w_identity() -> None:
    phys = _physical(node_id="window-like-span", provenance="window_like_geometry")
    res = _resolution(resolve_opening_provenance([phys]), "window-like-span")
    assert res["status"] == STATUS_UNBOUND
    assert res["resolved_type_mark"] is None
    assert all(n.get("normalized_value") not in {"W1", "W2"} for n in [phys.to_dict()])


def test_door_like_geometry_without_mark_mints_no_d_identity() -> None:
    phys = _physical(
        node_id="door-like-span",
        jamb_start=(40.0, 80.0),
        jamb_end=(74.0, 80.0),
        width_m=1.20,
        provenance="door_like_swing_geometry",
    )
    res = _resolution(resolve_opening_provenance([phys]), "door-like-span")
    assert res["status"] == STATUS_UNBOUND
    assert res["resolved_type_mark"] is None
    assert res["height_m"] is None


def test_repeated_identical_spans_do_not_invent_identity() -> None:
    spans = [
        _physical(
            node_id=f"span-{index}",
            jamb_start=(40.0 + index * 70.0, 80.0),
            jamb_end=(88.0 + index * 70.0, 80.0),
        )
        for index in range(6)
    ]
    graph = resolve_opening_provenance(spans)
    assert {item["status"] for item in graph["resolutions"]} == {STATUS_UNBOUND}
    assert all(item["resolved_type_mark"] is None for item in graph["resolutions"])


def test_out_of_viewport_text_has_no_identity_authority() -> None:
    phys = _physical()
    tag = tag_node(page=1, viewport=OTHER_VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W1")
    res = _resolution(resolve_opening_provenance([phys, tag]))
    assert res["status"] == STATUS_UNBOUND
    assert res["resolved_type_mark"] is None
    assert res["height_m"] is None


def test_untagged_numeric_text_does_not_create_identity() -> None:
    for raw in (
        "1700",
        "1200",
        "CLASSROOM 01",
        "VERANDA",
        "overall size 1200 x 2400mm high",
        "850",
        "01",
        "02",
    ):
        assert normalize_opening_tag(raw) is None
        assert find_explicit_opening_tags(raw) == []
    phys = _physical()
    graph = resolve_opening_provenance([phys])
    assert graph["resolutions"][0]["resolved_type_mark"] is None


def test_nearby_but_uncontained_w1_is_not_nearest_neighbour_bound() -> None:
    phys = _physical()
    nearby = tag_node(page=1, viewport=VP, bbox=(40.0, 100.0, 60.0, 112.0), raw_token="W1")
    res = _resolution(resolve_opening_provenance([phys, nearby]))
    assert res["status"] == STATUS_UNBOUND
    assert res["resolved_type_mark"] is None


def test_tagged_w1_plus_unique_schedule_wxh_may_resolve_height() -> None:
    phys = _physical(width_m=1.70)
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W1")
    row = schedule_node(page=6, viewport=VP, tag="W1", width_m=1.70, height_m=1.50)
    res = _resolution(resolve_opening_provenance([phys, tag, row]))
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] == "W1"
    assert res["height_m"] == 1.50
    assert res["bound_wall_id"] is None


def test_tagged_d1_plus_unique_schedule_wxh_may_resolve_height() -> None:
    phys = _physical(width_m=1.20)
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="D1")
    row = schedule_node(page=5, viewport=VP, tag="D1", width_m=1.20, height_m=2.40)
    res = _resolution(resolve_opening_provenance([phys, tag, row]))
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] == "D1"
    assert res["height_m"] == 2.40
    assert res["bound_wall_id"] is None


def test_hosted_width_only_keeps_height_none() -> None:
    phys = _physical(width_m=1.70)
    res = _resolution(resolve_opening_provenance([phys]))
    assert res["width_m"] == 1.70
    assert res["height_m"] is None


def test_untagged_wxh_outside_opening_does_not_bind_height() -> None:
    phys = _physical(width_m=None)
    callout = callout_node(
        page=1,
        viewport=VP,
        bbox=(200.0, 200.0, 260.0, 220.0),
        kind="door",
        width_m=1.20,
        height_m=2.40,
        raw_token="1200mm x 2400mm door",
    )
    res = _resolution(resolve_opening_provenance([phys, callout]))
    assert res["status"] == STATUS_UNBOUND
    assert res["height_m"] is None
    assert res["resolved_type_mark"] is None


def test_conflicting_wxh_for_same_type_stays_unresolved() -> None:
    phys = _physical(width_m=1.70)
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W1")
    a = schedule_node(page=6, viewport=VP, tag="W1", width_m=1.70, height_m=1.50, node_id="sched-a")
    b = schedule_node(page=6, viewport=VP, tag="W1", width_m=1.70, height_m=1.20, node_id="sched-b")
    res = _resolution(resolve_opening_provenance([phys, tag, a, b]))
    assert res["status"] == STATUS_CONFLICT
    assert res["height_m"] is None


def test_explicit_w1_without_height_keeps_identity_and_none_height() -> None:
    phys = _physical(width_m=1.70)
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W1")
    res = _resolution(resolve_opening_provenance([phys, tag]))
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] == "W1"
    assert res["height_m"] is None


def test_explicit_height_with_ambiguous_identity_does_not_fabricate_type_mark() -> None:
    left = _physical(node_id="span-l", jamb_start=(40.0, 80.0), jamb_end=(88.0, 80.0))
    right = _physical(node_id="span-r", jamb_start=(130.0, 80.0), jamb_end=(178.0, 80.0))
    callout = callout_node(
        page=1,
        viewport=VP,
        bbox=(100.0, 77.0, 118.0, 83.0),
        kind="window",
        width_m=1.70,
        height_m=1.50,
        raw_token="1700mm x 1500mm window",
    )
    graph = resolve_opening_provenance([left, right, callout])
    assert {item["status"] for item in graph["resolutions"]} == {STATUS_UNBOUND}
    assert all(item["resolved_type_mark"] is None for item in graph["resolutions"])
    assert all(item["height_m"] is None for item in graph["resolutions"])


def test_door_swing_geometry_does_not_create_height() -> None:
    phys = _physical(
        node_id="swing-span",
        width_m=1.20,
        provenance="jamb_anchored_door_swing",
    )
    res = _resolution(resolve_opening_provenance([phys]), "swing-span")
    assert res["height_m"] is None
    assert res["resolved_type_mark"] is None
    assert res["bound_wall_id"] is None


def test_untagged_boq_size_string_is_not_an_opening_identity_or_mm_x_mm_callout() -> None:
    raw = "50mm thick double panelled door faced and hardwood lipped all round, overall size 1200 x 2400mm high"
    assert normalize_opening_tag(raw) is None
    assert parse_opening_size_callouts(raw) == []


def test_figured_width_only_tokens_are_not_wxh_callouts() -> None:
    for raw in ("1700", "1200", "850", "650", "1600", "200"):
        assert parse_opening_size_callouts(raw) == []
        assert normalize_opening_tag(raw) is None


def test_contained_identity_is_translation_invariant() -> None:
    dx, dy = 80.0, -25.0

    def shift(box, x=dx, y=dy):
        return (box[0] + x, box[1] + y, box[2] + x, box[3] + y)

    phys = _physical()
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="D1")
    baseline = _resolution(resolve_opening_provenance([phys, tag]))
    moved_phys = OpeningEvidenceNode(
        node_id=phys.node_id,
        evidence_type=phys.evidence_type,
        page=phys.page,
        viewport=shift(phys.viewport),
        bbox=shift(phys.bbox),
        width_m=phys.width_m,
        provenance=phys.provenance,
    )
    moved_tag = tag_node(
        page=1,
        viewport=shift(VP),
        bbox=shift((50.0, 77.0, 62.0, 83.0)),
        raw_token="D1",
        node_id=tag.node_id,
    )
    moved = _resolution(resolve_opening_provenance([moved_phys, moved_tag]))
    assert moved["status"] == baseline["status"] == STATUS_RESOLVED
    assert moved["resolved_type_mark"] == baseline["resolved_type_mark"] == "D1"
    assert moved["height_m"] is None


def test_contained_identity_is_90deg_rotation_invariant() -> None:
    phys = _physical()
    tag_box = (50.0, 77.0, 62.0, 83.0)
    tag = tag_node(page=1, viewport=VP, bbox=tag_box, raw_token="W1")
    baseline = _resolution(resolve_opening_provenance([phys, tag]))

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
        bbox=rot_box(tag_box),
        raw_token="W1",
        node_id=tag.node_id,
    )
    moved = _resolution(resolve_opening_provenance([rotated_phys, rotated_tag]))
    assert moved["status"] == baseline["status"] == STATUS_RESOLVED
    assert moved["resolved_type_mark"] == "W1"


def test_contained_identity_is_scale_invariant_for_half_and_double() -> None:
    phys = _physical()
    tag_box = (50.0, 77.0, 62.0, 83.0)
    tag = tag_node(page=1, viewport=VP, bbox=tag_box, raw_token="W1")
    baseline = _resolution(resolve_opening_provenance([phys, tag]))

    def scale_box(box, factor):
        return (box[0] * factor, box[1] * factor, box[2] * factor, box[3] * factor)

    for factor in (0.5, 1.35, 2.0):
        scaled_phys = OpeningEvidenceNode(
            node_id=phys.node_id,
            evidence_type=phys.evidence_type,
            page=phys.page,
            viewport=scale_box(phys.viewport, factor),
            bbox=scale_box(phys.bbox, factor),
            width_m=phys.width_m,
            provenance=phys.provenance,
        )
        scaled_tag = tag_node(
            page=1,
            viewport=scale_box(VP, factor),
            bbox=scale_box(tag_box, factor),
            raw_token="W1",
            node_id=tag.node_id,
        )
        moved = _resolution(resolve_opening_provenance([scaled_phys, scaled_tag]))
        assert moved["status"] == baseline["status"] == STATUS_RESOLVED
        assert moved["resolved_type_mark"] == "W1"
        assert moved["height_m"] is None


def test_identity_and_height_are_independent_of_host_wall_binding() -> None:
    phys = _physical()
    tag = tag_node(page=1, viewport=VP, bbox=(50.0, 77.0, 62.0, 83.0), raw_token="W1")
    row = schedule_node(page=6, viewport=VP, tag="W1", width_m=1.70, height_m=1.50)
    res = _resolution(resolve_opening_provenance([phys, tag, row]))
    assert res["status"] == STATUS_RESOLVED
    assert res["resolved_type_mark"] == "W1"
    assert res["height_m"] == 1.50
    assert res["bound_wall_id"] is None
