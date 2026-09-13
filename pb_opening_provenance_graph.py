"""Fail-closed opening provenance graph (shadow / diagnostics only).

This module represents evidence relationships among physical hosted openings,
plan tags, schedule rows, and dimension callouts. It never mints W1/W2/D1
from repetition, nearest text, width similarity, or benchmark expectation.
It never invents opening height. bound_wall_id is not assigned here.

A swing, a schedule row, or a callout cannot create a physical instance.
Identity is accepted only from a defensible geometric relationship
(contained tag or an explicit leader endpoint). Schedule binding requires
that identity first.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import hypot
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pb_opening_tag_normalization import normalize_opening_tag

STATUS_RESOLVED = "RESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_CONFLICT = "CONFLICT"
STATUS_UNBOUND = "UNBOUND"

PHYSICAL_HOSTED_SPAN = "physical_hosted_span"
PLAN_TYPE_MARK = "plan_type_mark"
PLAN_INSTANCE_MARK = "plan_instance_mark"
DIMENSION_CALLOUT = "dimension_callout"
SCHEDULE_ROW = "schedule_row"
ELEVATION_MARK = "elevation_mark"
DOOR_SWING = "door_swing"
OCR_ANNOTATION = "ocr_annotation"

REL_CONTAINED_TAG = "contained_tag"
REL_DIRECT_LEADER = "direct_leader"
REL_SCHEDULE_TYPE_MATCH = "schedule_type_match"
REL_DIMENSION_BOUND_TO_TAG = "dimension_bound_to_tag"
REL_CONFLICT = "conflict"
REL_AMBIGUOUS = "ambiguous"

SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY = "BLOCKED_ON_VIEWPORT_AUTHORITY"

BBox = Tuple[float, float, float, float]
ViewportKey = Optional[Tuple[float, float, float, float]]


@dataclass(frozen=True)
class OpeningEvidenceNode:
    node_id: str
    evidence_type: str
    page: int
    viewport: ViewportKey
    bbox: Optional[BBox]
    raw_token: Optional[str] = None
    normalized_value: Optional[str] = None
    width_m: Optional[float] = None
    height_m: Optional[float] = None
    provenance: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if payload["viewport"] is not None:
            payload["viewport"] = list(payload["viewport"])
        if payload["bbox"] is not None:
            payload["bbox"] = list(payload["bbox"])
        return payload


@dataclass(frozen=True)
class BindingEdge:
    from_node: str
    to_node: str
    relation_type: str
    authority: str
    reason: str
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpeningProvenanceResolution:
    status: str
    physical_opening: Optional[str]
    resolved_type_mark: Optional[str]
    width_m: Optional[float]
    height_m: Optional[float]
    schedule_row: Optional[str]
    evidence_chain: Tuple[str, ...]
    reasons: Tuple[str, ...]
    bound_wall_id: None = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["evidence_chain"] = list(self.evidence_chain)
        payload["reasons"] = list(self.reasons)
        payload["bound_wall_id"] = None
        return payload


def empty_opening_provenance_shadow(
    *,
    reason: str,
    viewport_census: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "status": "abstained",
        "reason": reason,
        "physical_openings": [],
        "nodes": [],
        "edges": [],
        "resolutions": [],
        "conflicts": [],
    }
    if viewport_census is not None:
        payload["viewport_census"] = viewport_census
    return payload


def local_opening_bbox(
    jamb_start: Sequence[float],
    jamb_end: Sequence[float],
    wall_thickness_pt: Optional[float],
) -> BBox:
    """Axis-aligned box of the wall-band rectangle around the jamb segment."""
    x0, y0 = float(jamb_start[0]), float(jamb_start[1])
    x1, y1 = float(jamb_end[0]), float(jamb_end[1])
    dx, dy = x1 - x0, y1 - y0
    length = hypot(dx, dy)
    half = float(wall_thickness_pt or 0.0) / 2.0
    if length <= 0.0:
        return (x0 - half, y0 - half, x1 + half, y1 + half)
    nx, ny = -dy / length, dx / length
    corners = (
        (x0 + nx * half, y0 + ny * half),
        (x0 - nx * half, y0 - ny * half),
        (x1 + nx * half, y1 + ny * half),
        (x1 - nx * half, y1 - ny * half),
    )
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_contains_point(bbox: BBox, x: float, y: float) -> bool:
    x0, y0, x1, y1 = bbox
    return min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)


def _bbox_contains_bbox(outer: BBox, inner: BBox) -> bool:
    return _bbox_contains_point(outer, inner[0], inner[1]) and _bbox_contains_point(
        outer, inner[2], inner[3]
    )


def _same_viewport(a: ViewportKey, b: ViewportKey) -> bool:
    if a is None or b is None:
        return False
    return tuple(float(v) for v in a) == tuple(float(v) for v in b)


def _widths_conflict(left: Optional[float], right: Optional[float]) -> bool:
    if left is None or right is None:
        return False
    return round(float(left), 2) != round(float(right), 2)


def _heights_conflict(left: Optional[float], right: Optional[float]) -> bool:
    if left is None or right is None:
        return False
    return round(float(left), 2) != round(float(right), 2)


def physical_node_from_hosted_record(record: Dict[str, Any]) -> OpeningEvidenceNode:
    jamb_start = record["jamb_start"]
    jamb_end = record["jamb_end"]
    thickness = record.get("wall_thickness_pt")
    return OpeningEvidenceNode(
        node_id=str(record["span_id"]),
        evidence_type=PHYSICAL_HOSTED_SPAN,
        page=int(record["page"]),
        viewport=tuple(record["viewport"]) if record.get("viewport") else None,
        bbox=local_opening_bbox(jamb_start, jamb_end, thickness),
        raw_token=None,
        normalized_value=None,
        width_m=record.get("width_m"),
        height_m=None,
        provenance="hosted_opening_shadow",
    )


def tag_node(
    *,
    page: int,
    viewport: ViewportKey,
    bbox: BBox,
    raw_token: str,
    node_id: Optional[str] = None,
    evidence_type: str = PLAN_INSTANCE_MARK,
    provenance: str = "explicit_plan_tag",
) -> Optional[OpeningEvidenceNode]:
    normalized = normalize_opening_tag(raw_token)
    if normalized is None:
        return None
    ident = node_id or (
        f"tag-p{page}-{normalized.tag}-"
        f"{bbox[0]:.2f}-{bbox[1]:.2f}-{bbox[2]:.2f}-{bbox[3]:.2f}"
    )
    return OpeningEvidenceNode(
        node_id=ident,
        evidence_type=evidence_type,
        page=page,
        viewport=viewport,
        bbox=bbox,
        raw_token=raw_token,
        normalized_value=normalized.tag,
        provenance=provenance,
    )


def schedule_node(
    *,
    page: int,
    viewport: ViewportKey,
    tag: str,
    width_m: Optional[float],
    height_m: Optional[float],
    bbox: Optional[BBox] = None,
    raw_token: Optional[str] = None,
    node_id: Optional[str] = None,
    provenance: str = "schedule_row",
) -> Optional[OpeningEvidenceNode]:
    normalized = normalize_opening_tag(tag)
    if normalized is None:
        return None
    ident = node_id or (
        f"sched-p{page}-{normalized.tag}-"
        f"{width_m}-{height_m}"
    )
    return OpeningEvidenceNode(
        node_id=ident,
        evidence_type=SCHEDULE_ROW,
        page=page,
        viewport=viewport,
        bbox=bbox,
        raw_token=raw_token or tag,
        normalized_value=normalized.tag,
        width_m=width_m,
        height_m=height_m,
        provenance=provenance,
    )


def callout_node(
    *,
    page: int,
    viewport: ViewportKey,
    bbox: BBox,
    kind: str,
    width_m: float,
    height_m: float,
    raw_token: str,
    node_id: Optional[str] = None,
) -> OpeningEvidenceNode:
    ident = node_id or (
        f"callout-p{page}-{kind}-{width_m:.3f}x{height_m:.3f}-"
        f"{bbox[0]:.2f}-{bbox[1]:.2f}"
    )
    return OpeningEvidenceNode(
        node_id=ident,
        evidence_type=DIMENSION_CALLOUT,
        page=page,
        viewport=viewport,
        bbox=bbox,
        raw_token=raw_token,
        normalized_value=None,
        width_m=width_m,
        height_m=height_m,
        provenance=f"size_callout:{kind}",
    )


def contained_tag_edges(
    physical: Sequence[OpeningEvidenceNode],
    tags: Sequence[OpeningEvidenceNode],
) -> List[BindingEdge]:
    """Identity edges only when a tag bbox/point sits inside the opening box."""
    edges: List[BindingEdge] = []
    for phys in physical:
        if phys.bbox is None:
            continue
        hits: List[OpeningEvidenceNode] = []
        for tag in tags:
            if tag.normalized_value is None or tag.bbox is None:
                continue
            if phys.page != tag.page:
                continue
            if not _same_viewport(phys.viewport, tag.viewport):
                continue
            if _bbox_contains_bbox(phys.bbox, tag.bbox) or _bbox_contains_point(
                phys.bbox,
                (tag.bbox[0] + tag.bbox[2]) / 2.0,
                (tag.bbox[1] + tag.bbox[3]) / 2.0,
            ):
                hits.append(tag)
        if len(hits) == 1:
            tag = hits[0]
            edges.append(
                BindingEdge(
                    from_node=phys.node_id,
                    to_node=tag.node_id,
                    relation_type=REL_CONTAINED_TAG,
                    authority="identity",
                    reason="explicit tag contained in local opening bbox",
                    status="ACCEPTED",
                )
            )
        elif len(hits) > 1:
            for tag in hits:
                edges.append(
                    BindingEdge(
                        from_node=phys.node_id,
                        to_node=tag.node_id,
                        relation_type=REL_CONFLICT,
                        authority="identity",
                        reason="one physical opening overlaps two candidate tags",
                        status="CONFLICT",
                    )
                )
    tag_owners: Dict[str, List[str]] = {}
    for edge in edges:
        if edge.relation_type in {REL_CONTAINED_TAG, REL_CONFLICT}:
            tag_owners.setdefault(edge.to_node, []).append(edge.from_node)
    extra: List[BindingEdge] = []
    for tag_id, owners in tag_owners.items():
        unique_owners = sorted(set(owners))
        if len(unique_owners) > 1:
            for owner in unique_owners:
                extra.append(
                    BindingEdge(
                        from_node=owner,
                        to_node=tag_id,
                        relation_type=REL_CONFLICT,
                        authority="identity",
                        reason="one tag serves two physical openings",
                        status="CONFLICT",
                    )
                )
    return edges + extra


def leader_edges(
    physical: Sequence[OpeningEvidenceNode],
    tags: Sequence[OpeningEvidenceNode],
    leaders: Sequence[Dict[str, Any]],
) -> List[BindingEdge]:
    """Accept a leader only when its endpoint is inside exactly one opening."""
    by_id = {node.node_id: node for node in list(physical) + list(tags)}
    edges: List[BindingEdge] = []
    for leader in leaders:
        tag = by_id.get(str(leader.get("tag_node")))
        endpoint = leader.get("endpoint")
        viewport = leader.get("viewport")
        if tag is None or endpoint is None or len(endpoint) != 2:
            continue
        hits = []
        for phys in physical:
            if phys.bbox is None:
                continue
            if phys.page != tag.page:
                continue
            if not _same_viewport(phys.viewport, viewport or tag.viewport):
                continue
            if _bbox_contains_point(phys.bbox, float(endpoint[0]), float(endpoint[1])):
                hits.append(phys)
        if len(hits) == 1:
            edges.append(
                BindingEdge(
                    from_node=hits[0].node_id,
                    to_node=tag.node_id,
                    relation_type=REL_DIRECT_LEADER,
                    authority="identity",
                    reason="leader endpoint inside exactly one local opening bbox",
                    status="ACCEPTED",
                )
            )
        elif len(hits) > 1:
            for phys in hits:
                edges.append(
                    BindingEdge(
                        from_node=phys.node_id,
                        to_node=tag.node_id,
                        relation_type=REL_CONFLICT,
                        authority="identity",
                        reason="leader endpoint ambiguous across openings",
                        status="CONFLICT",
                    )
                )
    return edges


def schedule_edges(
    identity_edges: Sequence[BindingEdge],
    tags: Sequence[OpeningEvidenceNode],
    schedules: Sequence[OpeningEvidenceNode],
) -> List[BindingEdge]:
    """Bind a schedule row only after a proven type mark, and only if unique."""
    proven: Dict[str, str] = {}
    conflicted_physical: set[str] = set()
    for edge in identity_edges:
        if edge.status == "CONFLICT":
            conflicted_physical.add(edge.from_node)
            continue
        if edge.relation_type in {REL_CONTAINED_TAG, REL_DIRECT_LEADER}:
            proven[edge.from_node] = edge.to_node
    tags_by_id = {node.node_id: node for node in tags}
    edges: List[BindingEdge] = []
    for physical_id, tag_id in proven.items():
        if physical_id in conflicted_physical:
            continue
        tag = tags_by_id.get(tag_id)
        if tag is None or not tag.normalized_value:
            continue
        matches = [
            row
            for row in schedules
            if row.normalized_value == tag.normalized_value
        ]
        if not matches:
            continue
        widths = {round(row.width_m, 2) for row in matches if row.width_m is not None}
        heights = {round(row.height_m, 2) for row in matches if row.height_m is not None}
        if len(matches) > 1 and (len(widths) > 1 or len(heights) > 1):
            for row in matches:
                edges.append(
                    BindingEdge(
                        from_node=tag.node_id,
                        to_node=row.node_id,
                        relation_type=REL_CONFLICT,
                        authority="dimension",
                        reason="duplicate type marks with conflicting WxH",
                        status="CONFLICT",
                    )
                )
            continue
        if len(matches) > 1 and len(widths) <= 1 and len(heights) <= 1:
            edges.append(
                BindingEdge(
                    from_node=tag.node_id,
                    to_node=matches[0].node_id,
                    relation_type=REL_AMBIGUOUS,
                    authority="dimension",
                    reason="multiple identical schedule rows; not unique",
                    status="AMBIGUOUS",
                )
            )
            continue
        row = matches[0]
        edges.append(
            BindingEdge(
                from_node=tag.node_id,
                to_node=row.node_id,
                relation_type=REL_SCHEDULE_TYPE_MATCH,
                authority="dimension",
                reason="unique schedule row for already-proven type mark",
                status="ACCEPTED",
            )
        )
    return edges


def callout_dimension_edges(
    physical: Sequence[OpeningEvidenceNode],
    callouts: Sequence[OpeningEvidenceNode],
    identity_edges: Sequence[BindingEdge],
) -> List[BindingEdge]:
    """Bind a callout only when it sits in the same opening box or is unique after identity.

    A free-floating callout never creates identity and is never assigned by
    nearest-text or width similarity.
    """
    proven_physical = {
        edge.from_node
        for edge in identity_edges
        if edge.status == "ACCEPTED"
        and edge.relation_type in {REL_CONTAINED_TAG, REL_DIRECT_LEADER}
    }
    edges: List[BindingEdge] = []
    for phys in physical:
        if phys.bbox is None:
            continue
        contained = []
        for callout in callouts:
            if callout.bbox is None:
                continue
            if phys.page != callout.page:
                continue
            if not _same_viewport(phys.viewport, callout.viewport):
                continue
            if _bbox_contains_bbox(phys.bbox, callout.bbox) or _bbox_contains_point(
                phys.bbox,
                (callout.bbox[0] + callout.bbox[2]) / 2.0,
                (callout.bbox[1] + callout.bbox[3]) / 2.0,
            ):
                contained.append(callout)
        if len(contained) == 1:
            callout = contained[0]
            edges.append(
                BindingEdge(
                    from_node=phys.node_id,
                    to_node=callout.node_id,
                    relation_type=REL_DIMENSION_BOUND_TO_TAG,
                    authority="dimension",
                    reason="WxH callout contained in local opening bbox",
                    status="ACCEPTED",
                )
            )
        elif len(contained) > 1:
            widths = {round(c.width_m, 2) for c in contained if c.width_m is not None}
            heights = {round(c.height_m, 2) for c in contained if c.height_m is not None}
            relation = REL_CONFLICT if len(widths) > 1 or len(heights) > 1 else REL_AMBIGUOUS
            status = "CONFLICT" if relation == REL_CONFLICT else "AMBIGUOUS"
            reason = (
                "plan dimension conflicts inside the same opening"
                if relation == REL_CONFLICT
                else "multiple contained callouts without unique WxH"
            )
            for callout in contained:
                edges.append(
                    BindingEdge(
                        from_node=phys.node_id,
                        to_node=callout.node_id,
                        relation_type=relation,
                        authority="dimension",
                        reason=reason,
                        status=status,
                    )
                )
        elif phys.node_id not in proven_physical:
            continue
    return edges


def resolve_opening_provenance(
    nodes: Sequence[OpeningEvidenceNode],
    *,
    leaders: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    physical = [n for n in nodes if n.evidence_type == PHYSICAL_HOSTED_SPAN]
    tags = [
        n
        for n in nodes
        if n.evidence_type in {PLAN_TYPE_MARK, PLAN_INSTANCE_MARK, OCR_ANNOTATION}
        and n.normalized_value
    ]
    schedules = [n for n in nodes if n.evidence_type == SCHEDULE_ROW]
    callouts = [n for n in nodes if n.evidence_type == DIMENSION_CALLOUT]
    identity = contained_tag_edges(physical, tags) + leader_edges(physical, tags, leaders)
    sched = schedule_edges(identity, tags, schedules)
    dims = callout_dimension_edges(physical, callouts, identity)
    edges = identity + sched + dims

    nodes_by_id = {n.node_id: n for n in nodes}
    resolutions: List[OpeningProvenanceResolution] = []
    conflicts: List[Dict[str, Any]] = []
    for phys in physical:
        owned = [e for e in edges if e.from_node == phys.node_id]
        tag_ids = [
            e.to_node
            for e in owned
            if e.relation_type in {REL_CONTAINED_TAG, REL_DIRECT_LEADER}
            and e.status == "ACCEPTED"
        ]
        conflict_hits = [e for e in owned if e.status == "CONFLICT"]
        for tag_id in tag_ids:
            conflict_hits.extend(
                e for e in edges if e.from_node == tag_id and e.status == "CONFLICT"
            )
        ambiguous_hits = [
            e for e in owned + [e for e in edges if e.from_node in tag_ids]
            if e.status == "AMBIGUOUS"
        ]
        reasons: List[str] = []
        type_mark = None
        schedule_id = None
        width_m = phys.width_m
        height_m = None
        chain = [phys.node_id]
        status = STATUS_UNBOUND

        if conflict_hits:
            status = STATUS_CONFLICT
            reasons.extend(e.reason for e in conflict_hits)
            conflicts.extend(e.to_dict() for e in conflict_hits)
            if tag_ids:
                type_mark = nodes_by_id[tag_ids[0]].normalized_value
                chain.append(tag_ids[0])
        elif tag_ids:
            type_mark = nodes_by_id[tag_ids[0]].normalized_value
            chain.append(tag_ids[0])
            status = STATUS_RESOLVED
            for edge in sched:
                if edge.from_node != tag_ids[0]:
                    continue
                if edge.status == "ACCEPTED":
                    row = nodes_by_id[edge.to_node]
                    schedule_id = row.node_id
                    chain.append(row.node_id)
                    if _widths_conflict(width_m, row.width_m):
                        status = STATUS_CONFLICT
                        reasons.append("physical width disagrees with candidate schedule row")
                        conflicts.append(edge.to_dict())
                        schedule_id = None
                        break
                    if width_m is None:
                        width_m = row.width_m
                    if row.height_m is not None:
                        height_m = row.height_m
                elif edge.status == "AMBIGUOUS":
                    status = STATUS_AMBIGUOUS
                    reasons.append(edge.reason)
        else:
            reasons.append("no contained tag, leader, or unique local identity")

        if status != STATUS_CONFLICT:
            dim_accepted = [
                e
                for e in owned
                if e.relation_type == REL_DIMENSION_BOUND_TO_TAG and e.status == "ACCEPTED"
            ]
            dim_conflict = [
                e
                for e in owned
                if e.relation_type in {REL_DIMENSION_BOUND_TO_TAG, REL_CONFLICT}
                and e.status == "CONFLICT"
            ]
            if dim_conflict:
                status = STATUS_CONFLICT
                reasons.extend(e.reason for e in dim_conflict)
                conflicts.extend(e.to_dict() for e in dim_conflict)
            elif len(dim_accepted) == 1:
                callout = nodes_by_id[dim_accepted[0].to_node]
                chain.append(callout.node_id)
                if _widths_conflict(width_m, callout.width_m) or _heights_conflict(
                    height_m, callout.height_m
                ):
                    status = STATUS_CONFLICT
                    reasons.append("plan dimension conflicts with already-bound size")
                else:
                    if width_m is None:
                        width_m = callout.width_m
                    if height_m is None:
                        height_m = callout.height_m
                    if status == STATUS_UNBOUND:
                        status = STATUS_RESOLVED
                        reasons.append("authoritative contained WxH callout")
            if status == STATUS_RESOLVED and ambiguous_hits:
                status = STATUS_AMBIGUOUS
                reasons.extend(e.reason for e in ambiguous_hits)

        if status == STATUS_UNBOUND:
            type_mark = None
            schedule_id = None
            height_m = None
            width_m = phys.width_m

        resolutions.append(
            OpeningProvenanceResolution(
                status=status,
                physical_opening=phys.node_id,
                resolved_type_mark=type_mark,
                width_m=width_m,
                height_m=height_m,
                schedule_row=schedule_id,
                evidence_chain=tuple(dict.fromkeys(chain)),
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )

    found = any(item.status != STATUS_UNBOUND for item in resolutions)
    return {
        "status": "found" if physical and found else ("found" if physical else "abstained"),
        "reason": (
            f"{len(physical)} physical opening(s) examined"
            if physical
            else "no_physical_opening_nodes"
        ),
        "physical_openings": [n.to_dict() for n in physical],
        "nodes": [n.to_dict() for n in nodes],
        "edges": [e.to_dict() for e in edges],
        "resolutions": [item.to_dict() for item in resolutions],
        "conflicts": conflicts,
    }


def collect_opening_provenance_shadow(
    *,
    hosted_shadow: Optional[Dict[str, Any]] = None,
    extra_nodes: Sequence[OpeningEvidenceNode] = (),
    leaders: Sequence[Dict[str, Any]] = (),
    reason_if_empty: str = "no_physical_opening_nodes",
) -> Dict[str, Any]:
    """Build a diagnostic graph. Never mutates predictions or F.9 inputs."""
    if hosted_shadow and hosted_shadow.get("reason") == SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY:
        return empty_opening_provenance_shadow(
            reason=SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY,
            viewport_census=hosted_shadow.get("viewport_census"),
        )
    nodes: List[OpeningEvidenceNode] = []
    for record in (hosted_shadow or {}).get("evidence") or []:
        nodes.append(physical_node_from_hosted_record(record))
    nodes.extend(extra_nodes)
    if not any(n.evidence_type == PHYSICAL_HOSTED_SPAN for n in nodes):
        return empty_opening_provenance_shadow(reason=reason_if_empty)
    return resolve_opening_provenance(nodes, leaders=leaders)


def _text_blocks_with_bbox(page: Any) -> List[Tuple[str, BBox]]:
    blocks: List[Tuple[str, BBox]] = []
    raw = page.get_text("dict") if hasattr(page, "get_text") else {}
    for block in raw.get("blocks") or []:
        for line in block.get("lines") or []:
            parts = []
            xs: List[float] = []
            ys: List[float] = []
            for span in line.get("spans") or []:
                text = str(span.get("text") or "")
                if text.strip():
                    parts.append(text)
                bbox = span.get("bbox")
                if bbox and len(bbox) == 4:
                    xs.extend([float(bbox[0]), float(bbox[2])])
                    ys.extend([float(bbox[1]), float(bbox[3])])
            if parts and xs and ys:
                blocks.append(("".join(parts), (min(xs), min(ys), max(xs), max(ys))))
    return blocks


def _bbox_in_viewport(bbox: BBox, viewport: BBox) -> bool:
    cx = (bbox[0] + bbox[2]) / 2.0
    cy = (bbox[1] + bbox[3]) / 2.0
    return _bbox_contains_point(viewport, cx, cy)


def collect_opening_provenance_shadow_for_doc(
    doc: Any,
    pages: Sequence[int],
    hosted_shadow: Dict[str, Any],
) -> Dict[str, Any]:
    """Viewport-gated tag/callout harvest plus hosted physical nodes.

    Schedule rows are not inferred from the live commercial extractor.
    """
    from pb_hosted_opening_instance_adapter import authoritative_floor_plan_viewports
    from pb_opening_callout_dimension_binder import parse_opening_size_callouts

    if hosted_shadow.get("reason") == SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY:
        return empty_opening_provenance_shadow(
            reason=SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY,
            viewport_census=hosted_shadow.get("viewport_census"),
        )

    extra: List[OpeningEvidenceNode] = []
    had_viewport = False
    for page_index in pages:
        if page_index < 0 or page_index >= len(doc):
            continue
        page = doc[page_index]
        viewports = authoritative_floor_plan_viewports(page, page_number=page_index + 1)
        if not viewports:
            continue
        had_viewport = True
        for viewport in viewports:
            vbox = tuple(float(v) for v in viewport.bounding_box)
            for text, bbox in _text_blocks_with_bbox(page):
                if not _bbox_in_viewport(bbox, vbox):
                    continue
                node = tag_node(
                    page=page_index + 1,
                    viewport=vbox,
                    bbox=bbox,
                    raw_token=text,
                )
                if node is not None:
                    extra.append(node)
                for callout in parse_opening_size_callouts(text):
                    extra.append(
                        callout_node(
                            page=page_index + 1,
                            viewport=vbox,
                            bbox=bbox,
                            kind=callout.kind,
                            width_m=callout.width_mm / 1000.0,
                            height_m=callout.height_mm / 1000.0,
                            raw_token=callout.evidence_text,
                        )
                    )
    if not had_viewport and not (hosted_shadow.get("evidence") or []):
        return empty_opening_provenance_shadow(reason=SHADOW_BLOCKED_ON_VIEWPORT_AUTHORITY)
    records = []
    for item in hosted_shadow.get("evidence") or []:
        enriched = dict(item)
        if enriched.get("viewport") is None:
            start = enriched.get("jamb_start") or [0.0, 0.0]
            end = enriched.get("jamb_end") or start
            mid = ((float(start[0]) + float(end[0])) / 2.0, (float(start[1]) + float(end[1])) / 2.0)
            page_no = int(enriched.get("page") or 0)
            for page_index in pages:
                if page_index < 0 or page_index >= len(doc):
                    continue
                if page_index + 1 != page_no and page_index != page_no:
                    continue
                for viewport in authoritative_floor_plan_viewports(
                    doc[page_index], page_number=page_index + 1
                ):
                    vbox = tuple(float(v) for v in viewport.bounding_box)
                    if _bbox_contains_point(vbox, mid[0], mid[1]):
                        enriched["viewport"] = vbox
                        break
        records.append(enriched)
    return collect_opening_provenance_shadow(
        hosted_shadow={"evidence": records, "reason": hosted_shadow.get("reason")},
        extra_nodes=extra,
    )
