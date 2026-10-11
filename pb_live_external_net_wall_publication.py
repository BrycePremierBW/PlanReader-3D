"""Source-owned publication contract for external whole-wall net area.

This module closes Item 21A's last semantic gap without weakening its wall-
identity firewall. Physical whole-wall identities remain the unit of authority
through gross geometry, role classification, opening deductions and net-wall
Boolean union. Only after those exact records are replayed successfully may
their source-proven EXTERNAL subset be aggregated into the extractor's
commercial perimeter-wall semantic quantity.

No caller-supplied wall list, role, area, completeness flag, perimeter value,
opening deduction, benchmark expectation or fallback may enter the numeric
path. target_scope_id is addressing only and must resolve an already published
net-wall record for every gross whole wall in the complete scope.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

from pb_gross_wall_geometry_authority import GrossWallGeometryAuthority
from pb_live_gross_wall_geometry_composition import LiveGrossWallGeometryComposition
from pb_live_net_wall_boolean_composition import LiveNetWallBooleanComposition
from pb_live_whole_wall_role_composition import LiveWholeWallRoleComposition
from pb_migration_contracts import (
    EvidenceResolutionStatus,
    QuantityEvidence,
    stable_contract_id,
)
from pb_net_wall_boolean_union_authority import NetWallBooleanUnionAuthority
from pb_wall_role_authority import WallRoleClassification
from pb_whole_wall_role_authority import WholeWallRoleAuthority


LIVE_EXTERNAL_NET_WALL_PUBLICATION_SCHEMA_VERSION = "1.0.0"

LIVE_EXTERNAL_NET_WALL_RESOLVED = "live_external_net_wall_publication_resolved"
LIVE_EXTERNAL_NET_WALL_UPSTREAM_INCOMPLETE = (
    "live_external_net_wall_publication_upstream_incomplete"
)
LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH = (
    "live_external_net_wall_publication_lineage_mismatch"
)
LIVE_EXTERNAL_NET_WALL_ROLE_UNRESOLVED = (
    "live_external_net_wall_publication_role_unresolved"
)
LIVE_EXTERNAL_NET_WALL_NET_UNRESOLVED = (
    "live_external_net_wall_publication_net_unresolved"
)
LIVE_EXTERNAL_NET_WALL_NO_EXTERNAL_WALLS = (
    "live_external_net_wall_publication_no_external_walls"
)
LIVE_EXTERNAL_NET_WALL_DUPLICATE_WALL = (
    "live_external_net_wall_publication_duplicate_wall"
)

PERIMETER_WALLING_SEMANTIC_KEY = "perimeter_walling"


@dataclass(frozen=True)
class LiveExternalNetWallPublication:
    revision_id: str
    target_scope_id: str
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    quantity_evidence: Optional[QuantityEvidence]
    external_wall_ids: tuple[str, ...]
    gross_geometry_record_ids: tuple[str, ...]
    whole_wall_role_record_ids: tuple[str, ...]
    net_wall_record_ids: tuple[str, ...]
    schema_version: str = LIVE_EXTERNAL_NET_WALL_PUBLICATION_SCHEMA_VERSION


def _clean(value: object) -> str:
    return str(value or "").strip()


def _reasons(*values: object) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if isinstance(value, (tuple, list)):
            result.extend(_clean(item) for item in value if _clean(item))
        elif _clean(value):
            result.append(_clean(value))
    return tuple(dict.fromkeys(result))


def _blocked(
    *,
    revision_id: str,
    target_scope_id: str,
    status: EvidenceResolutionStatus,
    reason: str,
    extra_reasons: tuple[str, ...] = (),
) -> LiveExternalNetWallPublication:
    if status is EvidenceResolutionStatus.CORROBORATED:
        status = EvidenceResolutionStatus.ABSTAINED
    return LiveExternalNetWallPublication(
        revision_id=revision_id,
        target_scope_id=target_scope_id,
        status=status,
        reason_codes=_reasons(reason, extra_reasons),
        quantity_evidence=None,
        external_wall_ids=(),
        gross_geometry_record_ids=(),
        whole_wall_role_record_ids=(),
        net_wall_record_ids=(),
    )


def _lineage_tuple(value) -> tuple[str, str, str, str, str, str, str]:
    return (
        _clean(value.document_id),
        _clean(value.revision_id),
        _clean(value.source_sha256),
        _clean(value.snapshot_id),
        _clean(value.page_id),
        _clean(value.decision_scope_id),
        _clean(value.physical_wall_id),
    )


def compose_live_external_net_wall_publication(
    *,
    gross_wall_composition: LiveGrossWallGeometryComposition,
    net_wall_composition: LiveNetWallBooleanComposition,
    whole_wall_role_composition: LiveWholeWallRoleComposition,
    target_scope_id: str,
) -> LiveExternalNetWallPublication:
    """Aggregate source-authenticated EXTERNAL whole-wall net areas.

    Publication requires complete corroboration of all three upstream
    compositions. Each gross selector is replayed through the sealed gross,
    whole-wall-role and net-wall authorities. The caller cannot select which
    walls are external or which walls participate; the complete gross-wall
    trace universe defines membership.
    """
    if type(gross_wall_composition) is not LiveGrossWallGeometryComposition:
        raise TypeError(
            "gross_wall_composition must be LiveGrossWallGeometryComposition"
        )
    if type(net_wall_composition) is not LiveNetWallBooleanComposition:
        raise TypeError(
            "net_wall_composition must be LiveNetWallBooleanComposition"
        )
    if type(whole_wall_role_composition) is not LiveWholeWallRoleComposition:
        raise TypeError(
            "whole_wall_role_composition must be LiveWholeWallRoleComposition"
        )

    target = _clean(target_scope_id)
    if not target:
        raise ValueError("target_scope_id must be a non-empty address")

    revision_id = _clean(gross_wall_composition.revision_id)
    if (
        _clean(net_wall_composition.revision_id) != revision_id
        or _clean(whole_wall_role_composition.revision_id) != revision_id
    ):
        return _blocked(
            revision_id=revision_id,
            target_scope_id=target,
            status=EvidenceResolutionStatus.CONFLICT,
            reason=LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH,
        )

    gross_authority = gross_wall_composition.gross_wall_geometry_authority
    role_authority = whole_wall_role_composition.whole_wall_role_authority
    if (
        type(gross_authority) is not GrossWallGeometryAuthority
        or type(role_authority) is not WholeWallRoleAuthority
        or gross_wall_composition.status is not EvidenceResolutionStatus.CORROBORATED
        or net_wall_composition.status is not EvidenceResolutionStatus.CORROBORATED
        or whole_wall_role_composition.status is not EvidenceResolutionStatus.CORROBORATED
        or not gross_wall_composition.traces
    ):
        return _blocked(
            revision_id=revision_id,
            target_scope_id=target,
            status=EvidenceResolutionStatus.ABSTAINED,
            reason=LIVE_EXTERNAL_NET_WALL_UPSTREAM_INCOMPLETE,
            extra_reasons=_reasons(
                gross_wall_composition.reason_codes,
                net_wall_composition.reason_codes,
                whole_wall_role_composition.reason_codes,
            ),
        )

    trace_ids = tuple(
        _clean(trace.physical_wall_id) for trace in gross_wall_composition.traces
    )
    if (
        any(not wall_id for wall_id in trace_ids)
        or len(set(trace_ids)) != len(trace_ids)
    ):
        return _blocked(
            revision_id=revision_id,
            target_scope_id=target,
            status=EvidenceResolutionStatus.CONFLICT,
            reason=LIVE_EXTERNAL_NET_WALL_DUPLICATE_WALL,
        )

    external_wall_ids: list[str] = []
    gross_record_ids: list[str] = []
    role_record_ids: list[str] = []
    net_record_ids: list[str] = []
    net_values: list[float] = []

    for trace in gross_wall_composition.traces:
        wall_id = _clean(trace.physical_wall_id)
        gross_selector = gross_wall_composition.gross_selectors.get(wall_id)
        role_selector = whole_wall_role_composition.role_selectors.get(wall_id)
        net_selector = net_wall_composition.net_wall_selectors.get((wall_id, target))

        if gross_selector is None or role_selector is None or net_selector is None:
            return _blocked(
                revision_id=revision_id,
                target_scope_id=target,
                status=EvidenceResolutionStatus.ABSTAINED,
                reason=LIVE_EXTERNAL_NET_WALL_UPSTREAM_INCOMPLETE,
            )

        expected = _lineage_tuple(gross_selector)
        if (
            _clean(trace.page_id) != _clean(gross_selector.page_id)
            or _clean(trace.decision_scope_id) != _clean(gross_selector.decision_scope_id)
            or _clean(trace.physical_wall_id) != _clean(gross_selector.physical_wall_id)
            or _lineage_tuple(role_selector) != expected
            or _lineage_tuple(net_selector) != expected
            or _clean(net_selector.trade_scope_id) != target
        ):
            return _blocked(
                revision_id=revision_id,
                target_scope_id=target,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH,
            )

        gross_result = gross_authority.resolve(gross_selector)
        role_result = role_authority.resolve(role_selector)
        page_net_authority = net_wall_composition.net_wall_authorities.get(
            _clean(net_selector.page_id)
        )
        if type(page_net_authority) is not NetWallBooleanUnionAuthority:
            return _blocked(
                revision_id=revision_id,
                target_scope_id=target,
                status=EvidenceResolutionStatus.ABSTAINED,
                reason=LIVE_EXTERNAL_NET_WALL_NET_UNRESOLVED,
            )
        net_result = page_net_authority.resolve(net_selector)

        gross_record = gross_result.record
        role_record = role_result.record
        net_record = net_result.record
        if (
            gross_result.status is not EvidenceResolutionStatus.CORROBORATED
            or gross_record is None
        ):
            return _blocked(
                revision_id=revision_id,
                target_scope_id=target,
                status=EvidenceResolutionStatus.ABSTAINED,
                reason=LIVE_EXTERNAL_NET_WALL_UPSTREAM_INCOMPLETE,
                extra_reasons=tuple(gross_result.reason_codes),
            )
        if (
            role_result.status is not EvidenceResolutionStatus.CORROBORATED
            or role_record is None
            or role_record.role is WallRoleClassification.UNRESOLVED
        ):
            return _blocked(
                revision_id=revision_id,
                target_scope_id=target,
                status=(
                    EvidenceResolutionStatus.CONFLICT
                    if role_result.status is EvidenceResolutionStatus.CONFLICT
                    else EvidenceResolutionStatus.ABSTAINED
                ),
                reason=LIVE_EXTERNAL_NET_WALL_ROLE_UNRESOLVED,
                extra_reasons=tuple(role_result.reason_codes),
            )
        if (
            net_result.status is not EvidenceResolutionStatus.CORROBORATED
            or net_record is None
            or net_record.net_area_m2 is None
            or type(net_record.net_area_m2) not in (int, float)
            or not math.isfinite(float(net_record.net_area_m2))
            or float(net_record.net_area_m2) < 0.0
        ):
            return _blocked(
                revision_id=revision_id,
                target_scope_id=target,
                status=(
                    EvidenceResolutionStatus.CONFLICT
                    if net_result.status is EvidenceResolutionStatus.CONFLICT
                    else EvidenceResolutionStatus.ABSTAINED
                ),
                reason=LIVE_EXTERNAL_NET_WALL_NET_UNRESOLVED,
                extra_reasons=tuple(net_result.reason_codes),
            )

        if (
            _lineage_tuple(gross_record) != expected
            or _lineage_tuple(role_record) != expected
            or _lineage_tuple(net_record) != expected
            or _clean(role_record.gross_geometry_record_id)
            != _clean(gross_record.record_id)
            or _clean(net_record.gross_geometry_record_id)
            != _clean(gross_record.record_id)
            or _clean(net_record.trade_scope_id) != target
        ):
            return _blocked(
                revision_id=revision_id,
                target_scope_id=target,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH,
            )

        # A source-backed net wall can only be the gross physical surface
        # minus its authenticated union of physical opening voids. Do not
        # publish values larger than the wall, negative voids, or a replay
        # whose net/gross/void arithmetic no longer agrees with the original
        # authority's record. This is a quantity integrity check, not a
        # substitute for the upstream physical opening-universe proof.
        gross_area = gross_record.gross_area_m2
        net_gross = net_record.gross_area_m2
        void_area = net_record.void_union_area_m2
        net_area = net_record.net_area_m2
        if (
            any(type(n) not in (int, float) for n in (
                gross_area, net_gross, void_area, net_area,
            ))
            or not all(math.isfinite(float(n)) for n in (
                gross_area, net_gross, void_area, net_area,
            ))
            or float(gross_area) <= 0.0
            or float(void_area) < 0.0
            or float(net_area) > float(gross_area) + 1e-6
            or float(void_area) > float(gross_area) + 1e-6
            or not math.isclose(
                float(net_gross), float(gross_area), rel_tol=1e-9, abs_tol=1e-6
            )
            or not math.isclose(
                float(net_area) + float(void_area), float(gross_area),
                rel_tol=1e-9, abs_tol=1e-6,
            )
            or _clean(trace.gross_record_id) != _clean(gross_record.record_id)
        ):
            return _blocked(
                revision_id=revision_id,
                target_scope_id=target,
                status=EvidenceResolutionStatus.CONFLICT,
                reason=LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH,
            )

        gross_record_ids.append(_clean(gross_record.record_id))
        if role_record.role is WallRoleClassification.EXTERNAL:
            external_wall_ids.append(wall_id)
            role_record_ids.append(_clean(role_record.record_id))
            net_record_ids.append(_clean(net_record.record_id))
            net_values.append(float(net_record.net_area_m2))

    if not external_wall_ids:
        return _blocked(
            revision_id=revision_id,
            target_scope_id=target,
            status=EvidenceResolutionStatus.ABSTAINED,
            reason=LIVE_EXTERNAL_NET_WALL_NO_EXTERNAL_WALLS,
        )

    value = round(math.fsum(net_values), 6)
    evidence = QuantityEvidence(
        quantity_id=stable_contract_id(
            "external_whole_wall_net_area",
            {
                "revision_id": revision_id,
                "target_scope_id": target,
                "physical_wall_ids": tuple(external_wall_ids),
                "gross_geometry_record_ids": tuple(gross_record_ids),
                "whole_wall_role_record_ids": tuple(role_record_ids),
                "net_wall_record_ids": tuple(net_record_ids),
                "value_m2": value,
            },
        ),
        family="wall_net_area",
        semantic_key=PERIMETER_WALLING_SEMANTIC_KEY,
        value=value,
        unit="m2",
        input_entity_ids=tuple(external_wall_ids),
        formula="sum(net_area_m2 for source-authenticated external whole walls)",
        formula_version="1.0.0",
        evidence_ids=tuple(dict.fromkeys((*role_record_ids, *net_record_ids))),
        authority=(
            "pb_live_external_net_wall_publication."
            "compose_live_external_net_wall_publication"
        ),
        status="corroborated",
        confidence=1.0,
        abstained=False,
        blocking_reasons=(),
        reason_codes=(LIVE_EXTERNAL_NET_WALL_RESOLVED,),
        metadata={
            "revision_id": revision_id,
            "target_scope_id": target,
            "external_wall_ids": tuple(external_wall_ids),
            "gross_geometry_record_ids": tuple(gross_record_ids),
            "whole_wall_role_record_ids": tuple(role_record_ids),
            "net_wall_record_ids": tuple(net_record_ids),
        },
    )
    return LiveExternalNetWallPublication(
        revision_id=revision_id,
        target_scope_id=target,
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=(LIVE_EXTERNAL_NET_WALL_RESOLVED,),
        quantity_evidence=evidence,
        external_wall_ids=tuple(external_wall_ids),
        gross_geometry_record_ids=tuple(gross_record_ids),
        whole_wall_role_record_ids=tuple(role_record_ids),
        net_wall_record_ids=tuple(net_record_ids),
    )


__all__ = [
    "LIVE_EXTERNAL_NET_WALL_DUPLICATE_WALL",
    "LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH",
    "LIVE_EXTERNAL_NET_WALL_NET_UNRESOLVED",
    "LIVE_EXTERNAL_NET_WALL_NO_EXTERNAL_WALLS",
    "LIVE_EXTERNAL_NET_WALL_PUBLICATION_SCHEMA_VERSION",
    "LIVE_EXTERNAL_NET_WALL_RESOLVED",
    "LIVE_EXTERNAL_NET_WALL_ROLE_UNRESOLVED",
    "LIVE_EXTERNAL_NET_WALL_UPSTREAM_INCOMPLETE",
    "PERIMETER_WALLING_SEMANTIC_KEY",
    "LiveExternalNetWallPublication",
    "compose_live_external_net_wall_publication",
]
