"""pb_editable_3d_correction_model.py — Editable 3D Correction Model & Revision Invalidation.

The point of editable 3D is not the picture — it's that a user correction to geometry
must flow back into quantity accuracy: user correction -> model revision changes ->
quantities become stale -> authority must be rechecked.

This module is additive to pb_editable_3d_model.py (#147): it does not modify that
file's WallModel/BuildingModel classes, and does not touch PlanReader -> JobHub
publishing. It defines a standalone, append-only correction ledger and the bridge
that stales out pb_takeoff_output_authority.TakeoffOutputRow quantities whose
geometry_ref points at a corrected object.

Key invariant this module enforces (and pb_editable_3d_model.py's
apply_correction_event does not): a correction is never automatically an approval.
Correcting geometry always leaves it needing re-approval; only approve_corrected_geometry()
can promote it to a firm, publishable authority state, and only for the exact
revision it targets.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_output_authority import TakeoffOutputRow


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EditableObjectType(str, Enum):
    WALL = "wall"
    OPENING = "opening"
    DOOR = "door"
    WINDOW = "window"
    ROOM = "room"
    SURFACE = "surface"
    CEILING = "ceiling"
    FLOOR = "floor"
    SOFFIT = "soffit"
    STAIR = "stair"
    ROOF = "roof"
    UNKNOWN = "unknown"


class CorrectionField(str, Enum):
    LENGTH = "length"
    HEIGHT = "height"
    AREA = "area"
    PERIMETER = "perimeter"
    COORDINATES = "coordinates"
    OPENING_WIDTH = "opening_width"
    OPENING_HEIGHT = "opening_height"
    FINISH_TAG = "finish_tag"
    ROOM_ASSIGNMENT = "room_assignment"
    INCLUDE_EXCLUDE_STATUS = "include_exclude_status"
    SOURCE_SHEET = "source_sheet"
    SOURCE_PAGE = "source_page"
    GEOMETRY_REF = "geometry_ref"


class CorrectionSource(str, Enum):
    EDITOR_2D = "editor_2d"
    EDITOR_3D = "editor_3d"
    SCHEDULE_REVIEW = "schedule_review"
    BENCHMARK_REVIEW = "benchmark_review"
    MANUAL_ESTIMATOR_ENTRY = "manual_estimator_entry"
    AI_SUGGESTION_ACCEPTED = "ai_suggestion_accepted"


_KNOWN_OBJECT_TYPES = {t.value for t in EditableObjectType}
_KNOWN_FIELDS = {f.value for f in CorrectionField}
_KNOWN_SOURCES = {s.value for s in CorrectionSource}

# Fields that carry a physical dimension: must be finite, non-negative, and non-zero.
_NUMERIC_POSITIVE_FIELDS = {
    CorrectionField.LENGTH.value,
    CorrectionField.HEIGHT.value,
    CorrectionField.AREA.value,
    CorrectionField.PERIMETER.value,
    CorrectionField.OPENING_WIDTH.value,
    CorrectionField.OPENING_HEIGHT.value,
}

# Fields that correct an attribute of the geometry object itself rather than an
# entry in its coordinates_or_measurements bag.
_OBJECT_ATTRIBUTE_FIELDS = {
    CorrectionField.SOURCE_SHEET.value: "source_sheet",
    CorrectionField.SOURCE_PAGE.value: "source_page",
    CorrectionField.GEOMETRY_REF.value: "geometry_ref",
    CorrectionField.ROOM_ASSIGNMENT.value: "room_id",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_revision_hash(previous_revision_hash: Optional[str], object_id: str, field_name: str, new_value: Any) -> str:
    """Pure, deterministic hash chain: each revision is a function only of the prior
    hash and the correction applied. Replaying the same event sequence from the same
    genesis hash always reproduces the same final hash."""
    payload = f"{previous_revision_hash or 'GENESIS'}:{object_id}:{field_name}:{new_value!r}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Core Data Objects
# ---------------------------------------------------------------------------

@dataclass
class EditableGeometryObject:
    """A single correctable 3D/2D geometry object with full source traceability.

    Every commercially relevant object must be able to answer: what sheet/page/
    region created me (source_file_id/source_page/source_sheet/source_region), what
    scale and dimension evidence backs me (scale_id/dimension_text_ids), which
    original vector geometry I started from vs. what I currently point at
    (original_geometry_ref vs. geometry_ref), which corrections changed me
    (correction_ids), which quantities depend on me (dependent_quantity_ids), and
    who — if anyone — has approved me (approved_by/approved_at).
    """
    object_id: str
    object_type: str  # from EditableObjectType
    source_file_id: Optional[str] = None
    source_page: Optional[Union[int, str]] = None
    source_sheet: Optional[str] = None
    source_region: Optional[str] = None
    original_geometry_ref: Optional[str] = None
    geometry_ref: Optional[str] = None  # the *current* geometry reference
    scale_id: Optional[str] = None
    dimension_text_ids: List[str] = field(default_factory=list)
    level_id: Optional[str] = None
    room_id: Optional[str] = None
    coordinates_or_measurements: Dict[str, Any] = field(default_factory=dict)
    authority_status: str = AuthorityStatus.PROVISIONAL.value
    confidence: float = 1.0
    revision_hash: str = ""
    correction_ids: List[str] = field(default_factory=list)
    dependent_quantity_ids: List[str] = field(default_factory=list)
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EditableGeometryObject":
        return cls(
            object_id=str(data.get("object_id") or ""),
            object_type=str(data.get("object_type") or EditableObjectType.UNKNOWN.value),
            source_file_id=data.get("source_file_id"),
            source_page=data.get("source_page"),
            source_sheet=data.get("source_sheet"),
            source_region=data.get("source_region"),
            original_geometry_ref=data.get("original_geometry_ref"),
            geometry_ref=data.get("geometry_ref"),
            scale_id=data.get("scale_id"),
            dimension_text_ids=list(data.get("dimension_text_ids") or []),
            level_id=data.get("level_id"),
            room_id=data.get("room_id"),
            coordinates_or_measurements=dict(data.get("coordinates_or_measurements") or {}),
            authority_status=str(data.get("authority_status") or AuthorityStatus.PROVISIONAL.value),
            confidence=float(data.get("confidence") if data.get("confidence") is not None else 1.0),
            revision_hash=str(data.get("revision_hash") or ""),
            correction_ids=list(data.get("correction_ids") or []),
            dependent_quantity_ids=list(data.get("dependent_quantity_ids") or []),
            approved_by=data.get("approved_by"),
            approved_at=data.get("approved_at"),
            created_at=str(data.get("created_at") or _now_iso()),
            updated_at=str(data.get("updated_at") or _now_iso()),
        )


@dataclass
class Editable3DCorrectionEvent:
    """One immutable record of a single correction to a single object."""
    correction_id: str
    object_id: str
    object_type: str
    field: str  # from CorrectionField
    old_value: Any
    new_value: Any
    reason: str
    actor: str
    created_at: str
    source: str  # from CorrectionSource
    previous_revision_hash: Optional[str]
    new_revision_hash: Optional[str]
    affected_quantity_ids: List[str] = field(default_factory=list)
    requires_reapproval: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Editable3DRevision:
    """A snapshot of an object's measurements at the moment a correction produced it."""
    object_id: str
    revision_hash: str
    correction_id: Optional[str]
    created_at: str
    measurements_snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CorrectionOutcome:
    """Result of attempting to create a correction event: accepted, or rejected with reasons."""
    ok: bool
    event: Optional[Editable3DCorrectionEvent]
    blocking_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "event": self.event.to_dict() if self.event is not None else None,
            "blocking_reasons": list(self.blocking_reasons),
        }


@dataclass
class ApprovalResult:
    """Result of approving a corrected object at a specific revision."""
    object_id: str
    approved_by: str
    approved_at: str
    revision_hash: str
    authority_status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuantityInvalidationResult:
    """Outcome of checking one TakeoffOutputRow against a set of corrected object ids."""
    quantity_id: str
    was_invalidated: bool
    old_row: TakeoffOutputRow
    new_row: TakeoffOutputRow
    old_fingerprint: str
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Correction Event Validation & Creation
# ---------------------------------------------------------------------------

def create_correction_event(
    correction_id: str,
    object_id: str,
    object_type: str,
    field: str,
    old_value: Any,
    new_value: Any,
    reason: str,
    actor: str,
    source: str,
    previous_revision_hash: Optional[str],
    affected_quantity_ids: Optional[List[str]] = None,
    manual_review: bool = False,
    created_at: Optional[str] = None,
) -> CorrectionOutcome:
    """Validate and construct a single correction event. Fails closed: every applicable
    violation is collected and returned rather than raising on the first one found."""
    blocking: List[str] = []

    if not object_id:
        blocking.append("Missing object_id")
    if not field:
        blocking.append("Missing field")
    elif field not in _KNOWN_FIELDS:
        blocking.append(f"Unsupported correction field: {field!r}")
    if not actor:
        blocking.append("Missing actor")
    if not reason:
        blocking.append("Missing reason")
    if not previous_revision_hash:
        blocking.append("Missing previous_revision_hash")

    obj_type_norm = str(object_type).lower() if object_type else EditableObjectType.UNKNOWN.value
    if obj_type_norm not in _KNOWN_OBJECT_TYPES:
        blocking.append(f"Unknown object_type: {object_type!r}")
        obj_type_norm = EditableObjectType.UNKNOWN.value
    if obj_type_norm == EditableObjectType.UNKNOWN.value and not manual_review:
        blocking.append("Unknown object_type requires manual_review=True")

    source_norm = str(source).lower() if source else ""
    if source_norm not in _KNOWN_SOURCES:
        blocking.append(f"Unknown correction source: {source!r}")

    if field in _NUMERIC_POSITIVE_FIELDS:
        try:
            numeric_value = float(new_value)
        except (TypeError, ValueError):
            blocking.append(f"New value for {field} must be numeric, got {new_value!r}")
            numeric_value = None
        if numeric_value is not None:
            if not math.isfinite(numeric_value):
                blocking.append(f"New value for {field} must be finite, got {numeric_value}")
            elif numeric_value < 0.0:
                blocking.append(f"New value for {field} cannot be negative, got {numeric_value}")
            elif numeric_value == 0.0:
                blocking.append(f"New value for {field} cannot be zero")

    if blocking:
        return CorrectionOutcome(ok=False, event=None, blocking_reasons=blocking)

    new_hash = _compute_revision_hash(previous_revision_hash, object_id, field, new_value)
    event = Editable3DCorrectionEvent(
        correction_id=correction_id,
        object_id=object_id,
        object_type=obj_type_norm,
        field=field,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        actor=actor,
        created_at=created_at or _now_iso(),
        source=source_norm,
        previous_revision_hash=previous_revision_hash,
        new_revision_hash=new_hash,
        affected_quantity_ids=list(affected_quantity_ids or []),
        requires_reapproval=True,
    )
    return CorrectionOutcome(ok=True, event=event)


# ---------------------------------------------------------------------------
# Append-Only Correction Ledger
# ---------------------------------------------------------------------------

@dataclass
class Editable3DCorrectionLedger:
    """Tracks registered geometry objects and their append-only correction history.

    `events` is exposed as a read-only tuple: the only way to add to the ledger is
    through record()/apply_correction(), and rejected corrections are never appended.
    """
    _events: List[Editable3DCorrectionEvent] = field(default_factory=list)
    _objects: Dict[str, EditableGeometryObject] = field(default_factory=dict)
    _revisions: Dict[str, List[Editable3DRevision]] = field(default_factory=dict)

    @property
    def events(self) -> Tuple[Editable3DCorrectionEvent, ...]:
        return tuple(self._events)

    def register_object(self, obj: EditableGeometryObject) -> None:
        # Capture the original geometry reference exactly once, at first
        # registration — it must never change afterwards, even as geometry_ref
        # (the *current* pointer) is later corrected.
        if obj.original_geometry_ref is None and obj.geometry_ref is not None:
            obj = replace(obj, original_geometry_ref=obj.geometry_ref)
        self._objects[obj.object_id] = obj

    def link_dependent_quantities(self, object_id: str, quantity_ids: List[str]) -> None:
        """Record that the given TakeoffOutputRow quantity_ids are currently derived
        from this object. Additive and deduplicating — never clears existing links."""
        obj = self._objects.get(object_id)
        if obj is None:
            raise ValueError(f"Unknown object_id: {object_id!r} is not registered in this ledger")
        merged = list(obj.dependent_quantity_ids)
        for qid in quantity_ids:
            if qid not in merged:
                merged.append(qid)
        self._objects[object_id] = replace(obj, dependent_quantity_ids=merged, updated_at=_now_iso())

    def get_object(self, object_id: str) -> Optional[EditableGeometryObject]:
        return self._objects.get(object_id)

    def events_for_object(self, object_id: str) -> Tuple[Editable3DCorrectionEvent, ...]:
        return tuple(e for e in self._events if e.object_id == object_id)

    def revisions_for_object(self, object_id: str) -> Tuple[Editable3DRevision, ...]:
        return tuple(self._revisions.get(object_id, []))

    def corrected_object_ids(self) -> List[str]:
        seen: List[str] = []
        for e in self._events:
            if e.object_id not in seen:
                seen.append(e.object_id)
        return seen

    def apply_correction(
        self,
        correction_id: str,
        object_id: str,
        field: str,
        new_value: Any,
        reason: str,
        actor: str,
        source: str,
        affected_quantity_ids: Optional[List[str]] = None,
        manual_review: bool = False,
        created_at: Optional[str] = None,
    ) -> CorrectionOutcome:
        """Apply a correction to a registered object, updating its state only on success."""
        obj = self._objects.get(object_id)
        if obj is None:
            return CorrectionOutcome(
                ok=False, event=None,
                blocking_reasons=[f"Unknown object_id: {object_id!r} is not registered in this ledger"],
            )

        old_value = obj.coordinates_or_measurements.get(field)
        if field in _OBJECT_ATTRIBUTE_FIELDS:
            old_value = getattr(obj, _OBJECT_ATTRIBUTE_FIELDS[field], old_value)

        outcome = create_correction_event(
            correction_id=correction_id,
            object_id=object_id,
            object_type=obj.object_type,
            field=field,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            actor=actor,
            source=source,
            previous_revision_hash=obj.revision_hash or None,
            affected_quantity_ids=affected_quantity_ids,
            manual_review=manual_review,
            created_at=created_at,
        )

        if not outcome.ok or outcome.event is None:
            return outcome

        self._events.append(outcome.event)

        updated_measurements = dict(obj.coordinates_or_measurements)
        attr_overrides: Dict[str, Any] = {}
        if field in _OBJECT_ATTRIBUTE_FIELDS:
            attr_overrides[_OBJECT_ATTRIBUTE_FIELDS[field]] = new_value
        else:
            updated_measurements[field] = new_value

        updated_obj = replace(
            obj,
            coordinates_or_measurements=updated_measurements,
            revision_hash=outcome.event.new_revision_hash,
            # A correction is never automatically an approval — it always requires
            # re-review, regardless of what authority_status the object held before,
            # and it clears any prior approval attribution since that approval no
            # longer applies to the corrected geometry.
            authority_status=AuthorityStatus.REVIEW_REQUIRED.value,
            approved_by=None,
            approved_at=None,
            correction_ids=obj.correction_ids + [outcome.event.correction_id],
            updated_at=outcome.event.created_at,
            **attr_overrides,
        )
        self._objects[object_id] = updated_obj

        self._revisions.setdefault(object_id, []).append(
            Editable3DRevision(
                object_id=object_id,
                revision_hash=outcome.event.new_revision_hash,
                correction_id=outcome.event.correction_id,
                created_at=outcome.event.created_at,
                measurements_snapshot=dict(updated_measurements),
            )
        )
        return outcome

    def replay(self, object_id: str, genesis_hash: Optional[str] = None) -> Optional[str]:
        """Recompute the final revision hash for object_id purely from the recorded
        event log, independent of any live object state, proving replay determinism."""
        current_hash = genesis_hash
        result: Optional[str] = None
        for e in self.events_for_object(object_id):
            current_hash = _compute_revision_hash(current_hash, e.object_id, e.field, e.new_value)
            result = current_hash
        return result

    def invalidate_takeoff_rows(self, rows: Sequence[TakeoffOutputRow]) -> List[QuantityInvalidationResult]:
        return invalidate_stale_quantities_for_corrections(rows, self.corrected_object_ids())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self._events],
            "revisions": {
                object_id: [r.to_dict() for r in revs]
                for object_id, revs in self._revisions.items()
            },
        }


# ---------------------------------------------------------------------------
# Approval — separate from correction
# ---------------------------------------------------------------------------

def approve_corrected_geometry(
    ledger: Editable3DCorrectionLedger,
    object_id: str,
    approved_by: str,
    current_revision_hash: str,
    approved_at: Optional[str] = None,
) -> ApprovalResult:
    """Approve a geometry object at a specific revision.

    Approval is a distinct act from correction: it never mutates the correction
    history, and it only succeeds if the object is still exactly at the revision
    being approved (approving a superseded revision fails closed). It also fails
    closed if the object has no recorded source trace (source_page/source_sheet) —
    geometry that can't be traced back to originating drawing evidence can never
    become commercial, no matter how it was corrected.
    """
    if not object_id:
        raise ValueError("object_id is required to approve corrected geometry")
    if not approved_by:
        raise ValueError("approved_by is required to approve corrected geometry")
    if not current_revision_hash:
        raise ValueError("current_revision_hash is required to approve corrected geometry")

    obj = ledger.get_object(object_id)
    if obj is None:
        raise ValueError(f"Unknown object_id: {object_id!r} is not registered in this ledger")
    if obj.revision_hash != current_revision_hash:
        raise ValueError(
            f"Cannot approve stale revision for {object_id!r}: object is at "
            f"{obj.revision_hash!r}, approval targets {current_revision_hash!r}"
        )
    if not obj.source_sheet or obj.source_page is None:
        raise ValueError(
            f"Cannot approve {object_id!r}: missing source trace "
            f"(source_page={obj.source_page!r}, source_sheet={obj.source_sheet!r})"
        )

    stamp = approved_at or _now_iso()
    ledger._objects[object_id] = replace(
        obj,
        authority_status=AuthorityStatus.FIRM.value,
        approved_by=approved_by,
        approved_at=stamp,
        updated_at=stamp,
    )
    return ApprovalResult(
        object_id=object_id,
        approved_by=approved_by,
        approved_at=stamp,
        revision_hash=current_revision_hash,
        authority_status=AuthorityStatus.FIRM.value,
    )


def resolve_dependent_quantities(
    obj: EditableGeometryObject,
    rows: Sequence["TakeoffOutputRow"],
) -> List["TakeoffOutputRow"]:
    """Resolve an object's dependent_quantity_ids against a candidate set of rows,
    proving the linkage points at real, current quantities rather than dangling ids."""
    wanted = set(obj.dependent_quantity_ids)
    return [r for r in rows if r.quantity_id in wanted]


# ---------------------------------------------------------------------------
# Quantity Staleness Bridge (PR B.4 integration)
# ---------------------------------------------------------------------------

_STALE_REASON = "stale_after_geometry_correction"


def invalidate_stale_quantities_for_corrections(
    rows: Sequence[TakeoffOutputRow],
    corrected_object_ids: Iterable[str],
) -> List[QuantityInvalidationResult]:
    """For each row whose geometry_ref matches a corrected object, produce a stale copy:
    is_publishable=False and a 'stale_after_geometry_correction' blocking reason.

    Input rows are never mutated or dropped — old_row is the exact original object, so
    its fingerprint remains recoverable for audit even after the correction.
    """
    corrected = set(corrected_object_ids)
    results: List[QuantityInvalidationResult] = []

    for row in rows:
        old_fingerprint = row.compute_fingerprint()

        if row.geometry_ref is not None and row.geometry_ref in corrected:
            new_blocking = list(row.blocking_reasons)
            if _STALE_REASON not in new_blocking:
                new_blocking.append(_STALE_REASON)
            new_row = replace(row, is_publishable=False, blocking_reasons=new_blocking)
            results.append(QuantityInvalidationResult(
                quantity_id=row.quantity_id,
                was_invalidated=True,
                old_row=row,
                new_row=new_row,
                old_fingerprint=old_fingerprint,
                reason=_STALE_REASON,
            ))
        else:
            results.append(QuantityInvalidationResult(
                quantity_id=row.quantity_id,
                was_invalidated=False,
                old_row=row,
                new_row=row,
                old_fingerprint=old_fingerprint,
                reason=None,
            ))

    return results
