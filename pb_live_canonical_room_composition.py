"""Live canonical room/space projection from source-authenticated room faces.

This module preserves producer-owned physical room identity and exact page-space
geometry for downstream canonical-building consumers. It does not mint metric
geometry, names, levels, finishes, quantities, or commercial authority.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Collection, Mapping, Optional

from pb_drawing_evidence_binding import DrawingViewType
from pb_live_wall_opening_authority_composition import (
    LiveWallOpeningAuthorityComposition,
)
from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_physical_wall_candidate_authority import (
    PhysicalWallCandidateProducer,
    PhysicalWallCandidateSelector,
)
from pb_source_room_face_authority import (
    SourceRoomFaceAuthority,
    SourceRoomFaceSelector,
    build_source_room_face_authority,
)
from pb_source_composite_room_face_authority import (
    SOURCE_COMPOSITE_ROOM_FACE_RESOLVED,
    compose_grid_separated_room_faces,
)
from pb_source_visibility_authority import SourceVisibilityProducer
from pb_source_room_label_authority import (
    SourceRoomLabelProducer,
    SourceRoomLabelRecord,
    SourceRoomLabelSelector,
)


LIVE_CANONICAL_ROOM_SCHEMA_VERSION = "1.2.0"
LIVE_PHYSICAL_ROOM_IDENTITY_SCHEMA_VERSION = "1.0.0"
LIVE_CANONICAL_ROOM_RESOLVED = "live_canonical_room_composition_resolved"
LIVE_CANONICAL_ROOM_PARTIAL = "live_canonical_room_composition_partial"
LIVE_CANONICAL_ROOM_FACE_UNIVERSE_PARTIAL = "live_canonical_room_face_universe_partial"
LIVE_CANONICAL_ROOM_UNAVAILABLE = "live_canonical_room_composition_unavailable"
LIVE_CANONICAL_ROOM_VIEWPORT_FALLBACK_RESOLVED = (
    "live_canonical_room_viewport_fallback_resolved"
)
LIVE_CANONICAL_ROOM_GRID_COMPOSITE_RESOLVED = (
    "live_canonical_room_grid_composite_resolved"
)

_ROOM_FACE_AUTHORITY_BINDING_SEAL = object()


@dataclass(frozen=True)
class _RoomFaceAuthorityBinding:
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    source_room_face_record_ids: tuple[str, ...]
    viewport_id: Optional[str]
    viewport_bbox: Optional[tuple[float, float, float, float]]
    viewport_view_type: Optional[str]
    authority: SourceRoomFaceAuthority = field(repr=False, compare=False)
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._seal is not _ROOM_FACE_AUTHORITY_BINDING_SEAL
            or type(self.authority) is not SourceRoomFaceAuthority
        ):
            raise TypeError("room-face authority binding is producer-owned")


@dataclass(frozen=True)
class LiveCanonicalRoomObject:
    """Stable physical room identity with source-owned page-space geometry."""

    canonical_room_id: str
    physical_room_id: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    viewport_id: Optional[str]
    decision_scope_id: str
    polygon_pdf_pts: tuple[tuple[float, float], ...]
    bounding_wall_ids: tuple[str, ...]
    canonical_bounding_wall_ids: tuple[str, ...]
    wall_relationships_complete: bool
    area_page_pts2: float
    source_room_face_record_id: str
    evidence_ids: tuple[str, ...]
    geometry_complete: bool
    metric_geometry_complete: bool
    room_label: Optional[str] = None
    room_label_binding_record_id: Optional[str] = None
    room_label_evidence_ids: tuple[str, ...] = ()
    room_label_reason_codes: tuple[str, ...] = ()
    coordinate_unit: str = "pdf_pt"
    schema_version: str = LIVE_CANONICAL_ROOM_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "canonical_room_id": self.canonical_room_id,
            "physical_room_id": self.physical_room_id,
            "document_id": self.document_id,
            "revision_id": self.revision_id,
            "source_sha256": self.source_sha256,
            "snapshot_id": self.snapshot_id,
            "page_id": self.page_id,
            "viewport_id": self.viewport_id,
            "decision_scope_id": self.decision_scope_id,
            "polygon_pdf_pts": [list(point) for point in self.polygon_pdf_pts],
            "bounding_wall_ids": list(self.bounding_wall_ids),
            "canonical_bounding_wall_ids": list(self.canonical_bounding_wall_ids),
            "wall_relationships_complete": self.wall_relationships_complete,
            "area_page_pts2": self.area_page_pts2,
            "source_room_face_record_id": self.source_room_face_record_id,
            "evidence_ids": list(self.evidence_ids),
            "geometry_complete": self.geometry_complete,
            "metric_geometry_complete": self.metric_geometry_complete,
            "room_label": self.room_label,
            "room_label_binding_record_id": self.room_label_binding_record_id,
            "room_label_evidence_ids": list(self.room_label_evidence_ids),
            "room_label_reason_codes": list(self.room_label_reason_codes),
            "coordinate_unit": self.coordinate_unit,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LiveCanonicalRoomComposition:
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    rooms: tuple[LiveCanonicalRoomObject, ...]
    source_pages: tuple[int, ...]
    schema_version: str = LIVE_CANONICAL_ROOM_SCHEMA_VERSION
    _room_face_authority_bindings: tuple[_RoomFaceAuthorityBinding, ...] = field(
        default_factory=tuple,
        repr=False,
        compare=False,
    )

    def room_face_authority_binding_for(
        self,
        room: LiveCanonicalRoomObject,
    ) -> Optional[_RoomFaceAuthorityBinding]:
        """Return the exact sealed room-face authority that published the room.

        This runtime-only handoff prevents downstream consumers from rebuilding
        a page-wide authority when a room was recovered from an authenticated
        viewport scope. Manual/caller-created compositions carry no bindings.
        """
        if type(room) is not LiveCanonicalRoomObject:
            return None
        owned = [
            candidate
            for candidate in self.rooms
            if (
                candidate.canonical_room_id == room.canonical_room_id
                and candidate.source_room_face_record_id == room.source_room_face_record_id
                and candidate.snapshot_id == room.snapshot_id
                and candidate.page_id == room.page_id
                and candidate.decision_scope_id == room.decision_scope_id
            )
        ]
        if len(owned) != 1:
            return None

        # This binding was minted only after the exact producer-owned room-face
        # scope resolved CORROBORATED + complete. Replaying that immutable
        # authority scope once per room is redundant on dense CAD plans; exact
        # membership remains sealed below.
        matches = [
            binding
            for binding in self._room_face_authority_bindings
            if (
                binding._seal is _ROOM_FACE_AUTHORITY_BINDING_SEAL
                and binding.snapshot_id == room.snapshot_id
                and binding.page_id == room.page_id
                and binding.decision_scope_id == room.decision_scope_id
                and room.source_room_face_record_id in binding.source_room_face_record_ids
            )
        ]
        if len(matches) != 1:
            return None
        binding = matches[0]
        if room.viewport_id:
            if (
                binding.viewport_id != room.viewport_id
                or binding.viewport_bbox is None
            ):
                return None
        return binding

    def room_face_authority_for(
        self,
        room: LiveCanonicalRoomObject,
    ) -> Optional[SourceRoomFaceAuthority]:
        binding = self.room_face_authority_binding_for(room)
        return None if binding is None else binding.authority


def _authority_binding(
    authority: object,
    selector: SourceRoomFaceSelector,
    records: Collection[object],
    *,
    viewport_id: Optional[str] = None,
    viewport_bbox: Optional[Collection[float]] = None,
    viewport_view_type: Optional[str] = None,
) -> Optional[_RoomFaceAuthorityBinding]:
    if type(authority) is not SourceRoomFaceAuthority:
        return None
    record_ids = tuple(
        sorted(
            {
                str(getattr(record, "record_id", "") or "").strip()
                for record in records
                if str(getattr(record, "record_id", "") or "").strip()
            }
        )
    )
    if not record_ids:
        return None
    normalized_bbox: Optional[tuple[float, float, float, float]] = None
    if viewport_id is not None:
        if viewport_bbox is None:
            return None
        try:
            candidate_bbox = tuple(float(value) for value in viewport_bbox)
        except (TypeError, ValueError):
            return None
        if (
            len(candidate_bbox) != 4
            or candidate_bbox[2] <= candidate_bbox[0]
            or candidate_bbox[3] <= candidate_bbox[1]
        ):
            return None
        normalized_bbox = candidate_bbox
    return _RoomFaceAuthorityBinding(
        snapshot_id=str(selector.snapshot_id),
        page_id=str(selector.page_id),
        decision_scope_id=str(selector.decision_scope_id),
        source_room_face_record_ids=record_ids,
        viewport_id=(None if viewport_id is None else str(viewport_id)),
        viewport_bbox=normalized_bbox,
        viewport_view_type=(
            None if viewport_view_type is None else str(viewport_view_type)
        ),
        authority=authority,
        _seal=_ROOM_FACE_AUTHORITY_BINDING_SEAL,
    )


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _canonical_polygon_identity(
    polygon: Collection[Collection[float]],
) -> tuple[tuple[float, float], ...]:
    """Normalize page-space room geometry before physical identity hashing.

    Source room faces already use this six-decimal cyclic/reversal-invariant
    geometry contract. Repeating it at the canonical identity boundary prevents
    representation-order churn from changing a physical room id if another
    trusted producer supplies the same polygon with a different start vertex or
    winding.
    """

    points = tuple(
        (round(float(point[0]), 6), round(float(point[1]), 6))
        for point in polygon
    )
    if len(points) < 3:
        return ()
    variants: list[tuple[tuple[float, float], ...]] = []
    for start in range(len(points)):
        variants.append(
            tuple(points[(start + offset) % len(points)] for offset in range(len(points)))
        )
        variants.append(
            tuple(points[(start - offset) % len(points)] for offset in range(len(points)))
        )
    return min(variants)


def _physical_room_id(record, *, viewport_id: Optional[str]) -> str:
    """Physical room identity separate from revision/evidence fingerprints.

    SourceRoomFace record ids deliberately remain revision/snapshot specific for
    reproducibility. A canonical physical room is instead scoped by the logical
    document, source page/view and the already-canonical source-room polygon.
    Producer version, revision SHA, snapshot id, source-face record id and wall
    evidence ids therefore cannot churn the physical room id when geometry is
    unchanged.
    """
    return stable_contract_id(
        "live_physical_room",
        {
            "identity_schema_version": LIVE_PHYSICAL_ROOM_IDENTITY_SCHEMA_VERSION,
            "document_id": str(record.document_id),
            "page_id": str(record.page_id),
            "viewport_id": str(viewport_id or ""),
            "polygon_pdf_pts": _canonical_polygon_identity(
                record.polygon_pdf_pts
            ),
        },
        digest_chars=32,
    )


def _unique_source_room_labels_by_face(
    labels: Collection[SourceRoomLabelRecord],
) -> dict[str, SourceRoomLabelRecord]:
    """Retain only uniquely source-owned face labels; never last-write-wins.

    Exact repeated publication of one immutable label receipt is idempotent.
    Competing records for one physical face revoke the semantic label only,
    never the producer-authenticated physical room geometry.
    """
    owned: dict[str, SourceRoomLabelRecord] = {}
    conflicted: set[str] = set()
    for label in labels:
        if type(label) is not SourceRoomLabelRecord:
            continue
        face_id = str(label.face_id or "").strip()
        if not face_id or face_id in conflicted:
            continue
        previous = owned.get(face_id)
        if previous is not None and previous != label:
            owned.pop(face_id, None)
            conflicted.add(face_id)
        elif previous is None:
            owned[face_id] = label
    return owned


def _verified_source_room_label_for_face(
    record: object,
    label: Optional[SourceRoomLabelRecord],
) -> Optional[SourceRoomLabelRecord]:
    """At canonical publication, prove the semantic label owns this exact face.

    Face id alone is insufficient: a stale or unrelated scope must not
    relabel valid source geometry. Physical rooms remain publishable unlabeled.
    """
    if type(label) is not SourceRoomLabelRecord:
        return None
    if label.status is not EvidenceResolutionStatus.CORROBORATED:
        return None
    if any(
        str(getattr(record, attr, "") or "") != str(getattr(label, attr, "") or "")
        for attr in (
            "document_id", "revision_id", "source_sha256", "snapshot_id",
            "page_id", "decision_scope_id", "face_id",
        )
    ):
        return None
    if str(getattr(record, "record_id", "") or "") != str(label.source_room_face_record_id or ""):
        return None
    if not str(label.record_id or "").strip() or not label.observation_ids or not label.word_evidence:
        return None
    return label


def _room_object_from_record(
    record,
    *,
    viewport_id: Optional[str],
    canonical_wall_ids_by_candidate: Optional[Mapping[str, str]],
    unresolved_wall_candidate_ids: Optional[Collection[str]],
    room_label_record: Optional[SourceRoomLabelRecord] = None,
) -> LiveCanonicalRoomObject:
    canonical_boundary_ids: tuple[str, ...] = ()
    wall_relationships_complete = False
    if canonical_wall_ids_by_candidate is not None:
        mapped = [
            str(canonical_wall_ids_by_candidate.get(wall_id) or "")
            for wall_id in record.bounding_wall_ids
        ]
        if mapped and all(mapped):
            canonical_boundary_ids = tuple(dict.fromkeys(mapped))
            unresolved_ids = {
                str(value)
                for value in (unresolved_wall_candidate_ids or ())
                if str(value)
            }
            wall_relationships_complete = not any(
                wall_id in unresolved_ids for wall_id in record.bounding_wall_ids
            )

    physical_room_id = _physical_room_id(record, viewport_id=viewport_id)
    room_label_record = _verified_source_room_label_for_face(record, room_label_record)
    label_evidence_ids: tuple[str, ...] = ()
    label_reason_codes: tuple[str, ...] = ()
    if room_label_record is not None:
        label_evidence_ids = _dedupe(
            [
                *[str(value) for value in room_label_record.observation_ids],
                *[
                    str(word.authority_record_id)
                    for word in room_label_record.word_evidence
                ],
            ]
        )
        label_reason_codes = tuple(room_label_record.reason_codes)

    return LiveCanonicalRoomObject(
        canonical_room_id=physical_room_id,
        physical_room_id=physical_room_id,
        document_id=record.document_id,
        revision_id=record.revision_id,
        source_sha256=record.source_sha256,
        snapshot_id=record.snapshot_id,
        page_id=record.page_id,
        viewport_id=viewport_id,
        decision_scope_id=record.decision_scope_id,
        polygon_pdf_pts=record.polygon_pdf_pts,
        bounding_wall_ids=record.bounding_wall_ids,
        canonical_bounding_wall_ids=canonical_boundary_ids,
        wall_relationships_complete=wall_relationships_complete,
        area_page_pts2=float(record.area_page_pts2),
        source_room_face_record_id=record.record_id,
        evidence_ids=(record.record_id,),
        geometry_complete=True,
        metric_geometry_complete=False,
        room_label=(
            str(room_label_record.label)
            if room_label_record is not None
            else None
        ),
        room_label_binding_record_id=(
            str(room_label_record.record_id)
            if room_label_record is not None
            else None
        ),
        room_label_evidence_ids=label_evidence_ids,
        room_label_reason_codes=label_reason_codes,
    )


def _canonical_composite_supersedence(
    source_room_face_records,
    composite_records,
):
    """Project non-overlapping authenticated room composites, never their cells.

    Original producer-owned SourceRoomFace records remain available for audit.
    The canonical projection must not expose the same physical area as both
    its component cells and a larger authenticated composite room: doing so
    would duplicate canonical floors and downstream takeoff candidates.
    Any unexpected missing or duplicate constituent reference fails closed
    for the affected composite, preserving its original source-room cells.
    """
    originals = tuple(source_room_face_records)
    composites = tuple(composite_records)
    # The original physical face universe must itself be unique. Otherwise
    # retiring an identity could erase multiple source faces with one claim.
    source_id_counts = Counter(str(record.face_id) for record in originals)
    known = set(source_id_counts)
    originals_by_face = {str(record.face_id): record for record in originals}
    claimed = Counter(
        str(face_id)
        for composite in composites
        for face_id in composite.constituent_face_ids
    )
    accepted = []
    suppressed = set()
    for composite in composites:
        ids = tuple(str(value) for value in composite.constituent_face_ids)
        if (
            len(ids) < 2
            or len(ids) != len(set(ids))
            or any(
                face_id not in known
                or source_id_counts[face_id] != 1
                or claimed[face_id] != 1
                for face_id in ids
            )
        ):
            continue
        # A physical face identity is insufficient by itself: the composite
        # must cite each *exact* authenticated producer-owned source receipt.
        # Otherwise an older/stale witness could retire an unrelated face.
        actual_receipts = tuple(
            str(value)
            for value in (
                getattr(composite, "constituent_source_room_face_record_ids", ()) or ()
            )
        )
        expected_receipts = tuple(
            str(originals_by_face[face_id].record_id)
            for face_id in ids
        )
        if actual_receipts != expected_receipts:
            continue
        accepted.append(composite)
        suppressed.update(ids)
    return (
        tuple(record for record in originals if str(record.face_id) not in suppressed),
        tuple(accepted),
    )


def _room_object_from_composite_record(
    record,
    *,
    viewport_id: Optional[str],
    canonical_wall_ids_by_candidate: Optional[Mapping[str, str]],
    unresolved_wall_candidate_ids: Optional[Collection[str]],
) -> LiveCanonicalRoomObject:
    canonical_boundary_ids: tuple[str, ...] = ()
    wall_relationships_complete = False
    if canonical_wall_ids_by_candidate is not None:
        mapped = [
            str(canonical_wall_ids_by_candidate.get(wall_id) or "")
            for wall_id in record.bounding_wall_ids
        ]
        if mapped and all(mapped):
            canonical_boundary_ids = tuple(dict.fromkeys(mapped))
            unresolved_ids = {
                str(value)
                for value in (unresolved_wall_candidate_ids or ())
                if str(value)
            }
            wall_relationships_complete = not any(
                wall_id in unresolved_ids for wall_id in record.bounding_wall_ids
            )

    physical_room_id = _physical_room_id(record, viewport_id=viewport_id)
    return LiveCanonicalRoomObject(
        canonical_room_id=physical_room_id,
        physical_room_id=physical_room_id,
        document_id=record.document_id,
        revision_id=record.revision_id,
        source_sha256=record.source_sha256,
        snapshot_id=record.snapshot_id,
        page_id=record.page_id,
        viewport_id=viewport_id,
        decision_scope_id=record.decision_scope_id,
        polygon_pdf_pts=record.polygon_pdf_pts,
        bounding_wall_ids=record.bounding_wall_ids,
        canonical_bounding_wall_ids=canonical_boundary_ids,
        wall_relationships_complete=wall_relationships_complete,
        area_page_pts2=float(record.area_page_pts2),
        source_room_face_record_id=record.record_id,
        evidence_ids=tuple(record.evidence_ids),
        geometry_complete=True,
        metric_geometry_complete=False,
        room_label=str(record.label),
        room_label_binding_record_id=str(record.label_candidate_record_id),
        room_label_evidence_ids=tuple(record.label_evidence_ids),
        room_label_reason_codes=(SOURCE_COMPOSITE_ROOM_FACE_RESOLVED,),
    )


def compose_live_canonical_rooms(
    *,
    source_visibility_producer: SourceVisibilityProducer,
    wall_opening_composition: LiveWallOpeningAuthorityComposition,
    canonical_wall_ids_by_candidate: Optional[Mapping[str, str]] = None,
    unresolved_wall_candidate_ids: Optional[Collection[str]] = None,
) -> LiveCanonicalRoomComposition:
    """Project sealed room-face authority into persistent canonical room objects."""

    if type(source_visibility_producer) is not SourceVisibilityProducer:
        raise TypeError("source_visibility_producer must be producer-owned")
    if type(wall_opening_composition) is not LiveWallOpeningAuthorityComposition:
        raise TypeError("wall_opening_composition must be live producer-owned composition")

    published = source_visibility_producer.published_snapshot_for_revision(
        wall_opening_composition.revision_id
    )
    if published is None:
        return LiveCanonicalRoomComposition(
            status=EvidenceResolutionStatus.ABSTAINED,
            reason_codes=(LIVE_CANONICAL_ROOM_UNAVAILABLE,),
            rooms=(),
            source_pages=(),
        )

    authority = build_source_room_face_authority(
        wall_opening_composition.physical_wall_candidate_authority
    )

    # Resolve the cheap sealed room-face scopes before constructing any
    # semantic label producer. Pages that cannot publish a page-wide room scope
    # are handled by the authenticated viewport fallback below; OCR/text
    # corroboration for those pages must not be performed once here and then
    # repeated again against the fallback authority.
    page_room_results = {}
    page_room_selectors = {}
    page_label_ids: list[str] = []
    for page_id in wall_opening_composition.page_ids:
        selector = SourceRoomFaceSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            page_id=page_id,
            decision_scope_id=f"wall-source:page-{page_id}",
        )
        result = authority.resolve_scope(selector)
        page_room_selectors[page_id] = selector
        page_room_results[page_id] = result
        if (
            result.status is EvidenceResolutionStatus.CORROBORATED
            and result.scope_complete
            and result.records
            and result.face_universe_complete
        ):
            # Never build a page-wide label authority for an incomplete face
            # universe. Its source scope must instead use the authenticated
            # FLOOR_PLAN viewport fallback below.
            page_label_ids.append(str(page_id))

    page_label_authority = None
    if page_label_ids:
        try:
            page_label_authority = SourceRoomLabelProducer.from_authorities(
                source_visibility_producer,
                authority,
                page_ids=tuple(page_label_ids),
            ).authority()
        except Exception:
            # Room labels are semantic annotation only. A label-authority failure
            # must never destroy already-proven room geometry.
            page_label_authority = None

    rooms: list[LiveCanonicalRoomObject] = []
    reasons: list[str] = []
    resolved_pages: set[int] = set()
    room_pages: set[int] = set()
    unresolved_pages: list[str] = []
    viewport_fallback_used = False
    authority_bindings: list[_RoomFaceAuthorityBinding] = []

    for page_id in wall_opening_composition.page_ids:
        selector = page_room_selectors[page_id]
        result = page_room_results[page_id]
        if (
            result.status is EvidenceResolutionStatus.CORROBORATED
            and result.scope_complete
            and result.records
            and result.face_universe_complete
        ):
            # A page-wide incomplete face universe cannot establish persistent
            # physical identities: missing faces can change room ownership,
            # adjacency and downstream area/surface quantities. It falls back
            # to separately authenticated FLOOR_PLAN viewports, not page faces.
            if str(page_id).isdigit():
                room_pages.add(int(page_id))
                resolved_pages.add(int(page_id))
            label_records_by_face: dict[str, SourceRoomLabelRecord] = {}
            label_result = None
            if page_label_authority is not None:
                label_result = page_label_authority.resolve_scope(
                    SourceRoomLabelSelector(
                        document_id=selector.document_id,
                        revision_id=selector.revision_id,
                        source_sha256=selector.source_sha256,
                        snapshot_id=selector.snapshot_id,
                        page_id=selector.page_id,
                        decision_scope_id=selector.decision_scope_id,
                    )
                )
                label_records_by_face = _unique_source_room_labels_by_face(
                    label_result.records
                )

            composite_records = ()
            if label_result is not None and label_result.split_face_candidates:
                wall_scope = (
                    wall_opening_composition.physical_wall_candidate_authority.resolve_scope(
                        PhysicalWallCandidateSelector(
                            document_id=selector.document_id,
                            revision_id=selector.revision_id,
                            source_sha256=selector.source_sha256,
                            snapshot_id=selector.snapshot_id,
                            page_id=selector.page_id,
                            decision_scope_id=selector.decision_scope_id,
                        )
                    )
                )
                composite_result = compose_grid_separated_room_faces(
                    wall_scope=wall_scope,
                    room_scope=result,
                    label_scope=label_result,
                )
                composite_records = composite_result.records
                if composite_records:
                    reasons.append(LIVE_CANONICAL_ROOM_GRID_COMPOSITE_RESOLVED)

            binding = _authority_binding(authority, selector, result.records)
            if binding is not None:
                authority_bindings.append(binding)

            canonical_source_records, composite_records = (
                _canonical_composite_supersedence(result.records, composite_records)
            )
            rooms.extend(
                _room_object_from_record(
                    record,
                    viewport_id=None,
                    canonical_wall_ids_by_candidate=canonical_wall_ids_by_candidate,
                    unresolved_wall_candidate_ids=unresolved_wall_candidate_ids,
                    room_label_record=label_records_by_face.get(str(record.face_id)),
                )
                for record in canonical_source_records
            )
            rooms.extend(
                _room_object_from_composite_record(
                    record,
                    viewport_id=None,
                    canonical_wall_ids_by_candidate=canonical_wall_ids_by_candidate,
                    unresolved_wall_candidate_ids=unresolved_wall_candidate_ids,
                )
                for record in composite_records
            )
        else:
            if (
                result.status is EvidenceResolutionStatus.CORROBORATED
                and result.scope_complete
                and result.records
                and not result.face_universe_complete
            ):
                reasons.append(LIVE_CANONICAL_ROOM_FACE_UNIVERSE_PARTIAL)
            reasons.extend(result.reason_codes)
            unresolved_pages.append(str(page_id))

    # Page-wide ownership can abstain when unrelated reference furniture shares
    # the sheet with a physical drawing. Only for those pages, ask the existing
    # producer-owned viewport wall authority for authenticated floor-plan scopes.
    # No caller-supplied title, bbox, geometry, wall list, or completeness flag
    # enters this fallback.
    if unresolved_pages:
        viewport_wall_producer = (
            PhysicalWallCandidateProducer.from_authenticated_viewports(
                source_visibility_producer,
                page_ids=tuple(unresolved_pages),
            )
        )
        viewport_wall_authority = viewport_wall_producer.authority()
        viewport_published = source_visibility_producer.published_snapshot_for_revision(
            wall_opening_composition.revision_id
        )
        if (
            viewport_published is not None
            and viewport_published.revision.document_id
            == published.revision.document_id
            and viewport_published.revision.revision_id
            == published.revision.revision_id
            and viewport_published.revision.source_sha256
            == published.revision.source_sha256
        ):
            viewport_room_authority = build_source_room_face_authority(
                viewport_wall_authority
            )
            try:
                viewport_label_authority = SourceRoomLabelProducer.from_authorities(
                    source_visibility_producer,
                    viewport_room_authority,
                    page_ids=tuple(unresolved_pages),
                ).authority()
            except Exception:
                viewport_label_authority = None

            for page_id in unresolved_pages:
                # Canonical room geometry is topology authority. Semantic/support
                # plans must not mint or replace physical room faces merely
                # because they contain linework.
                selectors = (
                    viewport_wall_authority.selectors_for_authenticated_viewports(
                        document_id=viewport_published.revision.document_id,
                        revision_id=viewport_published.revision.revision_id,
                        source_sha256=viewport_published.revision.source_sha256,
                        snapshot_id=viewport_published.snapshot.snapshot_id,
                        page_id=page_id,
                        view_type=DrawingViewType.FLOOR_PLAN.value,
                    )
                )
                page_resolved = False
                page_face_universe_complete = True
                for wall_selector in selectors:
                    wall_scope = viewport_wall_authority.resolve_scope(wall_selector)
                    if (
                        wall_scope.status is not EvidenceResolutionStatus.CORROBORATED
                        or not wall_scope.records
                    ):
                        reasons.extend(wall_scope.reason_codes)
                        continue

                    room_result = viewport_room_authority.resolve_scope(
                        SourceRoomFaceSelector(
                            document_id=wall_selector.document_id,
                            revision_id=wall_selector.revision_id,
                            source_sha256=wall_selector.source_sha256,
                            snapshot_id=wall_selector.snapshot_id,
                            page_id=wall_selector.page_id,
                            decision_scope_id=wall_selector.decision_scope_id,
                        )
                    )
                    if (
                        room_result.status is not EvidenceResolutionStatus.CORROBORATED
                        or not room_result.scope_complete
                        or not room_result.records
                    ):
                        reasons.extend(room_result.reason_codes)
                        continue

                    label_records_by_face: dict[str, SourceRoomLabelRecord] = {}
                    label_result = None
                    if viewport_label_authority is not None:
                        label_result = viewport_label_authority.resolve_scope(
                            SourceRoomLabelSelector(
                                document_id=wall_selector.document_id,
                                revision_id=wall_selector.revision_id,
                                source_sha256=wall_selector.source_sha256,
                                snapshot_id=wall_selector.snapshot_id,
                                page_id=wall_selector.page_id,
                                decision_scope_id=wall_selector.decision_scope_id,
                            )
                        )
                        label_records_by_face = _unique_source_room_labels_by_face(
                            label_result.records
                        )

                    composite_records = ()
                    if label_result is not None and label_result.split_face_candidates:
                        composite_result = compose_grid_separated_room_faces(
                            wall_scope=wall_scope,
                            room_scope=room_result,
                            label_scope=label_result,
                        )
                        composite_records = composite_result.records
                        if composite_records:
                            reasons.append(
                                LIVE_CANONICAL_ROOM_GRID_COMPOSITE_RESOLVED
                            )

                    room_selector = SourceRoomFaceSelector(
                        document_id=wall_selector.document_id,
                        revision_id=wall_selector.revision_id,
                        source_sha256=wall_selector.source_sha256,
                        snapshot_id=wall_selector.snapshot_id,
                        page_id=wall_selector.page_id,
                        decision_scope_id=wall_selector.decision_scope_id,
                    )
                    binding = _authority_binding(
                        viewport_room_authority,
                        room_selector,
                        room_result.records,
                        viewport_id=(
                            None
                            if wall_scope.viewport_id is None
                            else str(wall_scope.viewport_id)
                        ),
                        viewport_bbox=getattr(wall_scope, "viewport_bbox", None),
                        viewport_view_type=getattr(
                            wall_scope,
                            "viewport_view_type",
                            None,
                        ),
                    )
                    if binding is not None:
                        authority_bindings.append(binding)

                    canonical_source_records, composite_records = (
                        _canonical_composite_supersedence(
                            room_result.records, composite_records
                        )
                    )
                    rooms.extend(
                        _room_object_from_record(
                            record,
                            viewport_id=wall_scope.viewport_id,
                            canonical_wall_ids_by_candidate=canonical_wall_ids_by_candidate,
                            unresolved_wall_candidate_ids=unresolved_wall_candidate_ids,
                            room_label_record=label_records_by_face.get(str(record.face_id)),
                        )
                        for record in canonical_source_records
                    )
                    rooms.extend(
                        _room_object_from_composite_record(
                            record,
                            viewport_id=wall_scope.viewport_id,
                            canonical_wall_ids_by_candidate=canonical_wall_ids_by_candidate,
                            unresolved_wall_candidate_ids=unresolved_wall_candidate_ids,
                        )
                        for record in composite_records
                    )
                    page_resolved = True
                    if not room_result.face_universe_complete:
                        page_face_universe_complete = False
                        reasons.append(LIVE_CANONICAL_ROOM_FACE_UNIVERSE_PARTIAL)
                    viewport_fallback_used = True

                if page_resolved and str(page_id).isdigit():
                    room_pages.add(int(page_id))
                    if page_face_universe_complete:
                        resolved_pages.add(int(page_id))

    rooms.sort(key=lambda room: (room.page_id, room.canonical_room_id))
    if rooms and len(resolved_pages) == len(wall_opening_composition.page_ids):
        return LiveCanonicalRoomComposition(
            status=EvidenceResolutionStatus.CORROBORATED,
            reason_codes=(
                (LIVE_CANONICAL_ROOM_RESOLVED,)
                if not viewport_fallback_used
                else (
                    LIVE_CANONICAL_ROOM_RESOLVED,
                    LIVE_CANONICAL_ROOM_VIEWPORT_FALLBACK_RESOLVED,
                )
            ),
            rooms=tuple(rooms),
            source_pages=tuple(sorted(room_pages)),
            _room_face_authority_bindings=tuple(authority_bindings),
        )
    if rooms:
        return LiveCanonicalRoomComposition(
            status=EvidenceResolutionStatus.CANDIDATE,
            reason_codes=(
                LIVE_CANONICAL_ROOM_PARTIAL,
                *(
                    (LIVE_CANONICAL_ROOM_VIEWPORT_FALLBACK_RESOLVED,)
                    if viewport_fallback_used
                    else ()
                ),
                *_dedupe(reasons),
            ),
            rooms=tuple(rooms),
            source_pages=tuple(sorted(room_pages)),
            _room_face_authority_bindings=tuple(authority_bindings),
        )
    return LiveCanonicalRoomComposition(
        status=EvidenceResolutionStatus.ABSTAINED,
        reason_codes=(LIVE_CANONICAL_ROOM_UNAVAILABLE, *_dedupe(reasons)),
        rooms=(),
        source_pages=(),
    )


__all__ = [
    "LIVE_CANONICAL_ROOM_PARTIAL",
    "LIVE_CANONICAL_ROOM_FACE_UNIVERSE_PARTIAL",
    "LIVE_CANONICAL_ROOM_RESOLVED",
    "LIVE_CANONICAL_ROOM_SCHEMA_VERSION",
    "LIVE_CANONICAL_ROOM_UNAVAILABLE",
    "LIVE_CANONICAL_ROOM_VIEWPORT_FALLBACK_RESOLVED",
    "LIVE_CANONICAL_ROOM_GRID_COMPOSITE_RESOLVED",
    "LIVE_PHYSICAL_ROOM_IDENTITY_SCHEMA_VERSION",
    "LiveCanonicalRoomComposition",
    "LiveCanonicalRoomObject",
    "compose_live_canonical_rooms",
]
