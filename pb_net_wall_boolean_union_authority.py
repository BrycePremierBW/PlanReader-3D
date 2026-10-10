"""Producer-owned Net-wall Boolean Union Authority.

This module proves one proposition only: the authenticated net wall-local
geometry and net wall area for an exact physical wall under an exact trade scope.

Downstream of:
1. Authenticated gross wall geometry (GrossWallGeometryAuthority);
2. Authenticated physical opening voids (PhysicalOpeningVoidAuthority);
3. Authenticated opening-deduction applicability (OpeningDeductionAuthority);
4. Complete opening universe (OpeningUniverseCompletenessAuthority).

Geometry Rule:
For wall-local gross domain G and authorized void geometries V_i:
U = unary_union(V_i)
N = G.difference(U)

Net area is measured geometrically from N in metres squared.
No scalar double subtraction, caller polygons, caller opening lists, or
precomputed areas can mint authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import math
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Sequence
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_opening_deduction_authority import (
    OPENING_DEDUCTION_AUTHORIZED,
    OpeningDeductionAuthority,
    OpeningDeductionSelector,
)
from pb_opening_universe_completeness_authority import (
    OpeningUniverseCompletenessAuthority,
    OpeningUniverseSelector,
)
from pb_physical_opening_void_authority import (
    PHYSICAL_OPENING_VOID_RESOLVED,
    PhysicalOpeningVoidAuthority,
    PhysicalOpeningVoidRecord,
    PhysicalOpeningVoidSelector,
)
from pb_gross_wall_geometry_authority import (
    GROSS_WALL_GEOMETRY_RESOLVED,
    GrossWallGeometryAuthority,
    GrossWallGeometryRecord,
    GrossWallGeometrySelector,
)


NET_WALL_BOOLEAN_UNION_SCHEMA_VERSION = "2.0.0"

NET_WALL_BOOLEAN_UNION_RESOLVED = "NET_WALL_BOOLEAN_UNION_RESOLVED"
NET_WALL_GROSS_UNRESOLVED = "NET_WALL_GROSS_UNRESOLVED"
NET_WALL_OPENING_UNIVERSE_INCOMPLETE = "NET_WALL_OPENING_UNIVERSE_INCOMPLETE"
NET_WALL_DEDUCTION_UNRESOLVED = "NET_WALL_DEDUCTION_UNRESOLVED"
NET_WALL_VOID_UNRESOLVED = "NET_WALL_VOID_UNRESOLVED"
NET_WALL_WRONG_WALL_VOID = "NET_WALL_WRONG_WALL_VOID"
NET_WALL_FRAME_MISMATCH = "NET_WALL_FRAME_MISMATCH"
NET_WALL_LINEAGE_MISMATCH = "NET_WALL_LINEAGE_MISMATCH"

NET_WALL_BOOLEAN_UNION_UPSTREAM_UNAVAILABLE = "net_wall_boolean_union_upstream_authorities_unavailable"
NET_WALL_BOOLEAN_UNION_RECORD_UNAVAILABLE = "net_wall_boolean_union_record_unavailable"
NET_WALL_BOOLEAN_UNION_INVALID_GEOMETRY = "net_wall_boolean_union_invalid_geometry"

_AUTHORITY_SEAL = object()
_PRODUCER_SEAL = object()
_Key = tuple[str, str, str, str, str, str, str, str]


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _has_consecutive_duplicates(coords: Sequence[tuple[float, float]]) -> bool:
    for i in range(len(coords) - 1):
        if coords[i] == coords[i + 1]:
            return True
    return False


def _valid_geometry(geometry: BaseGeometry) -> bool:
    if not isinstance(geometry, BaseGeometry) or geometry.is_empty or not geometry.is_valid:
        return False
    if geometry.geom_type not in ("Polygon", "MultiPolygon"):
        return False
    if not (geometry.area > 0 and math.isfinite(geometry.area)):
        return False
    bounds = tuple(float(v) for v in geometry.bounds)
    if not bounds or not all(math.isfinite(v) for v in bounds):
        return False
    polys = geometry.geoms if geometry.geom_type == "MultiPolygon" else (geometry,)
    for p in polys:
        if _has_consecutive_duplicates(list(p.exterior.coords)):
            return False
        for interior in p.interiors:
            if _has_consecutive_duplicates(list(interior.coords)):
                return False
    return True


def union_wall_local_void_polygons(void_polygons: Iterable[BaseGeometry]) -> BaseGeometry:
    """Return exact geometric union of already-authenticated wall-local voids.

    This helper performs geometry only. It does not establish opening identity,
    host binding, applicability, completeness or deduction permission.
    """
    items = tuple(void_polygons)
    for geometry in items:
        if not _valid_geometry(geometry):
            raise ValueError(NET_WALL_BOOLEAN_UNION_INVALID_GEOMETRY)
    if not items:
        return box(0.0, 0.0, 0.0, 0.0)
    merged = unary_union(items)
    if not _valid_geometry(merged):
        raise ValueError(NET_WALL_BOOLEAN_UNION_INVALID_GEOMETRY)
    return merged


def subtract_void_union_from_wall_polygon(
    gross_wall_polygon: BaseGeometry,
    void_polygons: Iterable[BaseGeometry],
) -> BaseGeometry:
    """Subtract the union of authenticated wall-local voids from gross geometry."""
    if not _valid_geometry(gross_wall_polygon):
        raise ValueError(NET_WALL_BOOLEAN_UNION_INVALID_GEOMETRY)
    items = tuple(void_polygons)
    if not items:
        return gross_wall_polygon
    for geometry in items:
        if not _valid_geometry(geometry):
            raise ValueError(NET_WALL_BOOLEAN_UNION_INVALID_GEOMETRY)
        if not gross_wall_polygon.covers(geometry):
            raise ValueError("Opening void is partially or completely outside gross wall")
    void_union = union_wall_local_void_polygons(items)
    result = gross_wall_polygon.difference(void_union)
    if result.is_empty:
        return result
    if not result.is_valid:
        raise ValueError(NET_WALL_BOOLEAN_UNION_INVALID_GEOMETRY)
    return result


@dataclass(frozen=True)
class NetWallBooleanUnionSelector:
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    physical_wall_id: str
    trade_scope_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "document_id",
            "revision_id",
            "source_sha256",
            "snapshot_id",
            "page_id",
            "decision_scope_id",
            "physical_wall_id",
            "trade_scope_id",
        ):
            _required(getattr(self, field_name), field_name)

    @property
    def key(self) -> _Key:
        return (
            self.document_id,
            self.revision_id,
            self.source_sha256,
            self.snapshot_id,
            self.page_id,
            self.decision_scope_id,
            self.physical_wall_id,
            self.trade_scope_id,
        )


@dataclass(frozen=True)
class NetWallBooleanUnionRecord:
    record_id: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    physical_wall_id: str
    gross_geometry_record_id: str
    opening_universe_record_id: str
    deduction_record_ids: tuple[str, ...]
    union_geometry_id: str
    net_area_m2: float | None = None
    gross_area_m2: float = 0.0
    void_union_area_m2: float = 0.0
    net_geometry_wkb_hex: str = ""
    physical_void_record_ids: tuple[str, ...] = ()
    trade_scope_id: str = ""
    gross_wall_record_id: str = ""
    opening_deduction_record_ids: tuple[str, ...] = ()
    schema_version: str = NET_WALL_BOOLEAN_UNION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.gross_wall_record_id and self.gross_geometry_record_id:
            object.__setattr__(self, "gross_wall_record_id", self.gross_geometry_record_id)
        if not self.opening_deduction_record_ids and self.deduction_record_ids:
            object.__setattr__(self, "opening_deduction_record_ids", self.deduction_record_ids)


NetWallBooleanUnionEvidence = NetWallBooleanUnionRecord


@dataclass(frozen=True)
class NetWallBooleanUnionResult:
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    record: NetWallBooleanUnionRecord | None = None
    evidence: NetWallBooleanUnionRecord | None = None
    schema_version: str = NET_WALL_BOOLEAN_UNION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.record is not None and self.evidence is None:
            object.__setattr__(self, "evidence", self.record)
        elif self.evidence is not None and self.record is None:
            object.__setattr__(self, "record", self.evidence)


def _blocked(
    status: EvidenceResolutionStatus,
    reason: str,
    *upstream_reasons: str,
) -> NetWallBooleanUnionResult:
    if status is EvidenceResolutionStatus.CORROBORATED:
        status = EvidenceResolutionStatus.ABSTAINED
    reasons = tuple(
        dict.fromkeys([reason, *(str(r) for r in upstream_reasons if str(r))])
    )
    return NetWallBooleanUnionResult(
        status=status,
        reason_codes=reasons or (NET_WALL_BOOLEAN_UNION_RECORD_UNAVAILABLE,),
        record=None,
    )


def _blocked_with_gross(
    status: EvidenceResolutionStatus,
    gross_record: GrossWallGeometryRecord,
    universe_record_id: str,
    reason: str,
    *upstream_reasons: str,
) -> NetWallBooleanUnionResult:
    if status is EvidenceResolutionStatus.CORROBORATED:
        status = EvidenceResolutionStatus.ABSTAINED
    reasons = tuple(
        dict.fromkeys([reason, *(str(r) for r in upstream_reasons if str(r))])
    )
    partial_record = NetWallBooleanUnionRecord(
        record_id=stable_contract_id("net_wall_boolean_union_blocked", {
            "gross": gross_record.record_id,
            "reasons": reasons,
        }),
        document_id=gross_record.document_id,
        revision_id=gross_record.revision_id,
        source_sha256=gross_record.source_sha256,
        snapshot_id=gross_record.snapshot_id,
        page_id=gross_record.page_id,
        decision_scope_id=gross_record.decision_scope_id,
        physical_wall_id=gross_record.physical_wall_id,
        gross_geometry_record_id=gross_record.record_id,
        gross_wall_record_id=gross_record.record_id,
        opening_universe_record_id=universe_record_id,
        deduction_record_ids=(),
        opening_deduction_record_ids=(),
        physical_void_record_ids=(),
        union_geometry_id="",
        net_area_m2=None,
        gross_area_m2=gross_record.gross_area_m2,
        void_union_area_m2=0.0,
        net_geometry_wkb_hex="",
    )
    return NetWallBooleanUnionResult(
        status=status,
        reason_codes=reasons,
        record=partial_record,
    )


def _lineage_matches(selector: NetWallBooleanUnionSelector, record: object) -> bool:
    return all(
        getattr(record, name, None) == getattr(selector, name)
        for name in ("document_id", "revision_id", "source_sha256", "snapshot_id")
    )


def deterministic_net_wall_record_id(
    selector: NetWallBooleanUnionSelector,
    *,
    gross_wall_record_id: str,
    opening_deduction_record_ids: tuple[str, ...],
    physical_void_record_ids: tuple[str, ...],
) -> str:
    """Addressing helper only; deterministic IDs never establish authority."""
    return stable_contract_id(
        "net_wall_boolean_union",
        {
            "selector": selector.key,
            "gross_wall_record_id": _required(gross_wall_record_id, "gross_wall_record_id"),
            "opening_deduction_record_ids": tuple(sorted(set(opening_deduction_record_ids))),
            "physical_void_record_ids": tuple(sorted(set(physical_void_record_ids))),
            "schema_version": NET_WALL_BOOLEAN_UNION_SCHEMA_VERSION,
        },
    )


class NetWallBooleanUnionAuthority:
    """Sealed selector-only lookup for published net-wall Boolean union results."""

    def __init__(
        self,
        results: Mapping[_Key, NetWallBooleanUnionResult],
        *,
        _seal: object = None,
    ) -> None:
        if _seal is not _AUTHORITY_SEAL:
            raise TypeError("NetWallBooleanUnionAuthority is producer-owned")
        self._results = MappingProxyType(dict(results))

    def resolve(self, selector: NetWallBooleanUnionSelector) -> NetWallBooleanUnionResult:
        if type(selector) is not NetWallBooleanUnionSelector:
            raise TypeError("selector must be NetWallBooleanUnionSelector")
        return self._results.get(
            selector.key,
            _blocked(
                EvidenceResolutionStatus.ABSTAINED,
                NET_WALL_BOOLEAN_UNION_RECORD_UNAVAILABLE,
            ),
        )


class NetWallBooleanUnionProducer:
    """Trusted writer over gross wall, physical void, deduction, and universe authorities."""

    def __init__(
        self,
        physical_void_authority: PhysicalOpeningVoidAuthority,
        opening_deduction_authority: OpeningDeductionAuthority,
        opening_universe_authority: OpeningUniverseCompletenessAuthority,
        gross_wall_authority: GrossWallGeometryAuthority,
        *,
        _seal: object = None,
    ) -> None:
        if _seal is not _PRODUCER_SEAL:
            raise TypeError("NetWallBooleanUnionProducer must be obtained from from_authorities()")
        self._void = physical_void_authority
        self._deduction = opening_deduction_authority
        self._universe = opening_universe_authority
        self._gross = gross_wall_authority
        self._results: dict[_Key, NetWallBooleanUnionResult] = {}

    @classmethod
    def from_authorities(
        cls,
        physical_void_authority: object,
        opening_deduction_authority: object,
        opening_universe_authority: object,
        gross_wall_authority: object,
    ) -> "NetWallBooleanUnionProducer":
        required = (
            ("pb_physical_opening_void_authority", "PhysicalOpeningVoidAuthority", physical_void_authority),
            ("pb_opening_deduction_authority", "OpeningDeductionAuthority", opening_deduction_authority),
            ("pb_opening_universe_completeness_authority", "OpeningUniverseCompletenessAuthority", opening_universe_authority),
            ("pb_gross_wall_geometry_authority", "GrossWallGeometryAuthority", gross_wall_authority),
        )
        for module_name, class_name, instance in required:
            try:
                module = importlib.import_module(module_name)
                expected = getattr(module, class_name)
            except (ImportError, AttributeError) as exc:
                raise RuntimeError(NET_WALL_BOOLEAN_UNION_UPSTREAM_UNAVAILABLE) from exc
            if type(instance) is not expected:
                raise TypeError(f"{class_name} instance required")
        return cls(
            physical_void_authority,  # type: ignore[arg-type]
            opening_deduction_authority,  # type: ignore[arg-type]
            opening_universe_authority,  # type: ignore[arg-type]
            gross_wall_authority,  # type: ignore[arg-type]
            _seal=_PRODUCER_SEAL,
        )

    def _store(
        self,
        selector: NetWallBooleanUnionSelector,
        result: NetWallBooleanUnionResult,
    ) -> NetWallBooleanUnionResult:
        existing = self._results.get(selector.key)
        if existing is not None and existing != result:
            result = _blocked(
                EvidenceResolutionStatus.CONFLICT,
                NET_WALL_LINEAGE_MISMATCH,
                "net_wall_producer_equivocation",
            )
        self._results[selector.key] = result
        return result

    def publish(self, selector: NetWallBooleanUnionSelector) -> NetWallBooleanUnionResult:
        if type(selector) is not NetWallBooleanUnionSelector:
            raise TypeError("selector must be NetWallBooleanUnionSelector")

        gross_selector = GrossWallGeometrySelector(
            document_id=selector.document_id,
            revision_id=selector.revision_id,
            source_sha256=selector.source_sha256,
            snapshot_id=selector.snapshot_id,
            page_id=selector.page_id,
            decision_scope_id=selector.decision_scope_id,
            physical_wall_id=selector.physical_wall_id,
        )
        gross_result = self._gross.resolve(gross_selector)
        gross_record = gross_result.record
        if (
            gross_result.status is not EvidenceResolutionStatus.CORROBORATED
            or gross_record is None
            or GROSS_WALL_GEOMETRY_RESOLVED not in gross_result.reason_codes
        ):
            return self._store(
                selector,
                _blocked(
                    gross_result.status,
                    NET_WALL_GROSS_UNRESOLVED,
                    *gross_result.reason_codes,
                ),
            )
        if gross_record.physical_wall_id != selector.physical_wall_id:
            return self._store(
                selector,
                _blocked(EvidenceResolutionStatus.ABSTAINED, NET_WALL_GROSS_UNRESOLVED),
            )
        if (
            not _lineage_matches(selector, gross_record)
            or gross_record.page_id != selector.page_id
            or gross_record.decision_scope_id != selector.decision_scope_id
        ):
            return self._store(
                selector,
                _blocked(EvidenceResolutionStatus.CONFLICT, NET_WALL_LINEAGE_MISMATCH),
            )

        universe_selector = OpeningUniverseSelector(
            document_id=selector.document_id,
            revision_id=selector.revision_id,
            source_sha256=selector.source_sha256,
            snapshot_id=selector.snapshot_id,
            decision_scope_id=selector.decision_scope_id,
        )
        universe_result = self._universe.resolve(universe_selector)
        universe_record = universe_result.record
        if (
            universe_result.status is not EvidenceResolutionStatus.CORROBORATED
            or universe_result.decision_scope_complete is not True
            or universe_record is None
            or universe_record.decision_scope_complete is not True
        ):
            return self._store(
                selector,
                _blocked_with_gross(
                    universe_result.status,
                    gross_record,
                    universe_record.record_id if universe_record else "",
                    NET_WALL_OPENING_UNIVERSE_INCOMPLETE,
                    *universe_result.reason_codes,
                ),
            )
        if (
            not _lineage_matches(selector, universe_record)
            or universe_record.decision_scope_id != selector.decision_scope_id
            or selector.page_id not in universe_record.page_ids
        ):
            return self._store(
                selector,
                _blocked_with_gross(
                    EvidenceResolutionStatus.CONFLICT,
                    gross_record,
                    universe_record.record_id,
                    NET_WALL_LINEAGE_MISMATCH,
                ),
            )

        # Do not let malformed replayed completeness records silently lose
        # duplicate or blank source members through set conversion.
        raw_member_ids = tuple(universe_record.accounted_member_ids)
        if (
            any(not str(member_id or "").strip() for member_id in raw_member_ids)
            or len(set(raw_member_ids)) != len(raw_member_ids)
        ):
            return self._store(
                selector,
                _blocked_with_gross(
                    EvidenceResolutionStatus.CONFLICT,
                    gross_record,
                    universe_record.record_id,
                    NET_WALL_OPENING_UNIVERSE_INCOMPLETE,
                ),
            )

        # Collect candidate opening identities within the scope
        candidate_opening_ids = set(raw_member_ids)
        if hasattr(self._void, "_results"):
            for key in self._void._results:
                if key[:6] == (
                    selector.document_id,
                    selector.revision_id,
                    selector.source_sha256,
                    selector.snapshot_id,
                    selector.page_id,
                    selector.decision_scope_id,
                ):
                    candidate_opening_ids.add(key[6])
        if hasattr(self._deduction, "_results"):
            for key in self._deduction._results:
                if key[:6] == (
                    selector.document_id,
                    selector.revision_id,
                    selector.source_sha256,
                    selector.snapshot_id,
                    selector.page_id,
                    selector.decision_scope_id,
                ):
                    candidate_opening_ids.add(key[6])

        applicable_voids: dict[str, PhysicalOpeningVoidRecord] = {}
        deduction_record_ids: dict[str, str] = {}
        tol = 1e-6

        for opening_id in sorted(candidate_opening_ids):
            void_selector = PhysicalOpeningVoidSelector(
                document_id=selector.document_id,
                revision_id=selector.revision_id,
                source_sha256=selector.source_sha256,
                snapshot_id=selector.snapshot_id,
                page_id=selector.page_id,
                decision_scope_id=selector.decision_scope_id,
                opening_identity_id=opening_id,
            )
            void_result = self._void.resolve(void_selector)
            if void_result.status is not EvidenceResolutionStatus.CORROBORATED or void_result.record is None:
                # If an opening was specifically registered for this wall or attempted for deduction, fail closed
                ded_selector = OpeningDeductionSelector(
                    document_id=selector.document_id,
                    revision_id=selector.revision_id,
                    source_sha256=selector.source_sha256,
                    snapshot_id=selector.snapshot_id,
                    page_id=selector.page_id,
                    decision_scope_id=selector.decision_scope_id,
                    opening_identity_id=opening_id,
                    target_scope_id=selector.trade_scope_id,
                )
                if hasattr(self._deduction, "_results") and ded_selector.key in self._deduction._results:
                    return self._store(
                        selector,
                        _blocked_with_gross(
                            void_result.status,
                            gross_record,
                            universe_record.record_id,
                            NET_WALL_VOID_UNRESOLVED,
                            *void_result.reason_codes,
                        ),
                    )
                continue

            void_record = void_result.record
            # Check whole-wall identity. Live composition addresses a physical
            # whole wall by the sealed wall_local_frame_id shared by all openings
            # on that wall. host_wall_id is opening-scoped legacy identity and
            # remains accepted only for backward-compatible producer fixtures.
            if (
                void_record.wall_local_frame_id != selector.physical_wall_id
                and void_record.host_wall_id != selector.physical_wall_id
            ):
                # Opening belongs to another physical wall/frame; ignore it.
                continue

            # Verify lineage
            if (
                not _lineage_matches(selector, void_record)
                or void_record.page_id != selector.page_id
                or void_record.decision_scope_id != selector.decision_scope_id
            ):
                return self._store(
                    selector,
                    _blocked_with_gross(
                        EvidenceResolutionStatus.CONFLICT,
                        gross_record,
                        universe_record.record_id,
                        NET_WALL_LINEAGE_MISMATCH,
                    ),
                )

            # Check coordinate frame
            if void_record.wall_local_frame_id != gross_record.wall_local_frame_id:
                return self._store(
                    selector,
                    _blocked_with_gross(
                        EvidenceResolutionStatus.CONFLICT,
                        gross_record,
                        universe_record.record_id,
                        NET_WALL_FRAME_MISMATCH,
                    ),
                )

            # Validate geometric bounds against gross wall
            u0 = float(void_record.u0)
            u1 = float(void_record.u1)
            z0 = float(void_record.z0)
            z1 = float(void_record.z1)
            if not (math.isfinite(u0) and math.isfinite(u1) and math.isfinite(z0) and math.isfinite(z1)):
                return self._store(
                    selector,
                    _blocked_with_gross(
                        EvidenceResolutionStatus.CONFLICT,
                        gross_record,
                        universe_record.record_id,
                        NET_WALL_VOID_UNRESOLVED,
                    ),
                )
            if u1 <= u0 + tol or z1 <= z0 + tol:
                return self._store(
                    selector,
                    _blocked_with_gross(
                        EvidenceResolutionStatus.CONFLICT,
                        gross_record,
                        universe_record.record_id,
                        NET_WALL_VOID_UNRESOLVED,
                    ),
                )
            if (
                u0 < -tol
                or u1 > gross_record.length_m + tol
                or z0 < -tol
                or z1 > gross_record.height_m + tol
            ):
                return self._store(
                    selector,
                    _blocked_with_gross(
                        EvidenceResolutionStatus.CONFLICT,
                        gross_record,
                        universe_record.record_id,
                        NET_WALL_VOID_UNRESOLVED,
                    ),
                )

            # Resolve deduction applicability for this trade scope
            ded_selector = OpeningDeductionSelector(
                document_id=selector.document_id,
                revision_id=selector.revision_id,
                source_sha256=selector.source_sha256,
                snapshot_id=selector.snapshot_id,
                page_id=selector.page_id,
                decision_scope_id=selector.decision_scope_id,
                opening_identity_id=opening_id,
                target_scope_id=selector.trade_scope_id,
            )
            ded_result = self._deduction.resolve(ded_selector)
            if (
                ded_result.status is EvidenceResolutionStatus.CORROBORATED
                and OPENING_DEDUCTION_AUTHORIZED in ded_result.reason_codes
                and ded_result.record is not None
            ):
                applicable_voids[opening_id] = void_record
                deduction_record_ids[opening_id] = ded_result.record.record_id
            elif ded_result.status is EvidenceResolutionStatus.CONFLICT:
                return self._store(
                    selector,
                    _blocked_with_gross(
                        EvidenceResolutionStatus.CONFLICT,
                        gross_record,
                        universe_record.record_id,
                        NET_WALL_DEDUCTION_UNRESOLVED,
                        *ded_result.reason_codes,
                    ),
                )
            else:
                # If reason indicates target/trade mismatch, it is non-applicable to this trade
                mismatch_tokens = (
                    "trade_scope_mismatch",
                    "finish_scope_mismatch",
                    "assembly_scope_mismatch",
                    "wall_scope_mismatch",
                    "scope_mismatch",
                )
                if any(
                    any(tok in reason_code.lower() for tok in mismatch_tokens)
                    for reason_code in ded_result.reason_codes
                ):
                    # Non-applicable opening for this trade scope; skip deduction safely
                    continue
                # Otherwise, applicability is unresolved: fail closed
                return self._store(
                    selector,
                    _blocked_with_gross(
                        EvidenceResolutionStatus.ABSTAINED,
                        gross_record,
                        universe_record.record_id,
                        NET_WALL_DEDUCTION_UNRESOLVED,
                        *ded_result.reason_codes,
                    ),
                )

        gross_polygon = box(0.0, 0.0, gross_record.length_m, gross_record.height_m)
        if not applicable_voids:
            void_union_area_m2 = 0.0
            net_area_m2 = gross_record.gross_area_m2
            net_polygon = gross_polygon
            union_geometry_id = stable_contract_id(
                "net_wall_union_geometry",
                {
                    "gross_record_id": gross_record.record_id,
                    "void_record_ids": (),
                    "net_area_m2": net_area_m2,
                },
            )
        else:
            void_polygons = [
                box(v.u0, v.z0, v.u1, v.z1)
                for v in applicable_voids.values()
            ]
            void_union = union_wall_local_void_polygons(void_polygons)
            void_union_area_m2 = round(float(void_union.area), 12)
            net_polygon = subtract_void_union_from_wall_polygon(gross_polygon, void_polygons)
            net_area_m2 = round(float(net_polygon.area), 12)
            union_geometry_id = stable_contract_id(
                "net_wall_union_geometry",
                {
                    "gross_record_id": gross_record.record_id,
                    "void_record_ids": tuple(sorted(v.record_id for v in applicable_voids.values())),
                    "net_area_m2": net_area_m2,
                },
            )

        ded_ids = tuple(sorted(deduction_record_ids.values()))
        void_ids = tuple(sorted(v.record_id for v in applicable_voids.values()))
        record_id = deterministic_net_wall_record_id(
            selector,
            gross_wall_record_id=gross_record.record_id,
            opening_deduction_record_ids=ded_ids,
            physical_void_record_ids=void_ids,
        )
        record = NetWallBooleanUnionRecord(
            record_id=record_id,
            document_id=selector.document_id,
            revision_id=selector.revision_id,
            source_sha256=selector.source_sha256,
            snapshot_id=selector.snapshot_id,
            page_id=selector.page_id,
            decision_scope_id=selector.decision_scope_id,
            physical_wall_id=selector.physical_wall_id,
            gross_geometry_record_id=gross_record.record_id,
            opening_universe_record_id=universe_record.record_id,
            deduction_record_ids=ded_ids,
            union_geometry_id=union_geometry_id,
            net_area_m2=net_area_m2,
            gross_area_m2=gross_record.gross_area_m2,
            void_union_area_m2=void_union_area_m2,
            net_geometry_wkb_hex=net_polygon.wkb_hex if hasattr(net_polygon, "wkb_hex") else "",
            physical_void_record_ids=void_ids,
            trade_scope_id=selector.trade_scope_id,
            gross_wall_record_id=gross_record.record_id,
            opening_deduction_record_ids=ded_ids,
            schema_version=NET_WALL_BOOLEAN_UNION_SCHEMA_VERSION,
        )
        return self._store(
            selector,
            NetWallBooleanUnionResult(
                status=EvidenceResolutionStatus.CORROBORATED,
                reason_codes=(NET_WALL_BOOLEAN_UNION_RESOLVED,),
                record=record,
            ),
        )

    publish_scope = publish

    def authority(self) -> NetWallBooleanUnionAuthority:
        return NetWallBooleanUnionAuthority(self._results, _seal=_AUTHORITY_SEAL)


__all__ = [
    "NET_WALL_BOOLEAN_UNION_SCHEMA_VERSION",
    "NET_WALL_BOOLEAN_UNION_RESOLVED",
    "NET_WALL_GROSS_UNRESOLVED",
    "NET_WALL_OPENING_UNIVERSE_INCOMPLETE",
    "NET_WALL_DEDUCTION_UNRESOLVED",
    "NET_WALL_VOID_UNRESOLVED",
    "NET_WALL_WRONG_WALL_VOID",
    "NET_WALL_FRAME_MISMATCH",
    "NET_WALL_LINEAGE_MISMATCH",
    "NET_WALL_BOOLEAN_UNION_UPSTREAM_UNAVAILABLE",
    "NET_WALL_BOOLEAN_UNION_RECORD_UNAVAILABLE",
    "NET_WALL_BOOLEAN_UNION_INVALID_GEOMETRY",
    "NetWallBooleanUnionSelector",
    "NetWallBooleanUnionRecord",
    "NetWallBooleanUnionEvidence",
    "NetWallBooleanUnionResult",
    "NetWallBooleanUnionAuthority",
    "NetWallBooleanUnionProducer",
    "union_wall_local_void_polygons",
    "subtract_void_union_from_wall_polygon",
    "deterministic_net_wall_record_id",
]
