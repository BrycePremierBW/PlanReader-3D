"""Deterministic claim arbitration for family-scoped quantity identities.

Exactly one selected claim is allowed for:

    family + project + revision + semantic_key

This module detects collisions and conflicts.  It does not choose migration
authority — the family router does that after arbitration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from pb_migration_contracts import QuantityEvidence


class ClaimArbitrationError(RuntimeError):
    """Raised when two authoritative quantities claim the same scoped identity."""


@dataclass(frozen=True)
class ClaimKey:
    family: str
    project_id: str
    revision_id: str
    semantic_key: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.family, self.project_id, self.revision_id, self.semantic_key)


@dataclass(frozen=True)
class ArbitrationFinding:
    kind: str
    claim: ClaimKey
    detail: str
    quantity_ids: tuple[str, ...]


@dataclass(frozen=True)
class ArbitrationReport:
    findings: tuple[ArbitrationFinding, ...]
    blocking: bool

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(item.kind for item in self.findings)


_AGGREGATE_KEYS = frozenset({"door_total", "window_total"})
_BLOCKED_STATUSES = frozenset({"blocked", "rejected", "invalid"})


def is_accepted_quantity(item: QuantityEvidence) -> bool:
    return (
        not item.abstained
        and item.value is not None
        and str(item.status or "").strip().lower() not in _BLOCKED_STATUSES
    )


def is_blocked_quantity(item: QuantityEvidence) -> bool:
    return (
        not item.abstained
        and str(item.status or "").strip().lower() in _BLOCKED_STATUSES
    )


def claim_key(
    *,
    family: str,
    project_id: str,
    revision_id: Optional[str],
    semantic_key: str,
) -> ClaimKey:
    return ClaimKey(
        family=str(family),
        project_id=str(project_id),
        revision_id=str(revision_id or ""),
        semantic_key=str(semantic_key),
    )


def _by_key(items: Sequence[QuantityEvidence], *, family: str, project_id: str, revision_id: Optional[str]) -> dict[str, list[QuantityEvidence]]:
    grouped: dict[str, list[QuantityEvidence]] = {}
    for item in items:
        grouped.setdefault(item.semantic_key, []).append(item)
    return grouped


def arbitrate_claims(
    *,
    family: str,
    project_id: str,
    revision_id: Optional[str],
    new_quantities: Sequence[QuantityEvidence],
    legacy_keys: Sequence[str] = (),
) -> ArbitrationReport:
    findings: list[ArbitrationFinding] = []
    new_groups = _by_key(new_quantities, family=family, project_id=project_id, revision_id=revision_id)
    for key, rows in new_groups.items():
        claim = claim_key(family=family, project_id=project_id, revision_id=revision_id, semantic_key=key)
        accepted = [item for item in rows if is_accepted_quantity(item)]
        abstained = [item for item in rows if item.abstained]
        blocked = [item for item in rows if is_blocked_quantity(item)]
        if accepted and (abstained or blocked):
            findings.append(
                ArbitrationFinding(
                    kind="unresolved_mixed_claim",
                    claim=claim,
                    detail=(
                        f"semantic claim {key} mixes accepted rows with "
                        f"{len(abstained)} abstained and {len(blocked)} blocked"
                    ),
                    quantity_ids=tuple(item.quantity_id for item in rows),
                )
            )
        if len(accepted) > 1:
            values = {round(float(item.value), 9) for item in accepted}
            kind = "conflicting_new_claims" if len(values) > 1 else "duplicate_new_claim"
            findings.append(
                ArbitrationFinding(
                    kind=kind,
                    claim=claim,
                    detail=f"{len(accepted)} new quantities claim {key}",
                    quantity_ids=tuple(item.quantity_id for item in accepted),
                )
            )
        if key in set(legacy_keys) and accepted:
            findings.append(
                ArbitrationFinding(
                    kind="legacy_new_overlap",
                    claim=claim,
                    detail="legacy and new both emit this semantic key; router must pick exactly one",
                    quantity_ids=tuple(item.quantity_id for item in accepted),
                )
            )
        if key in _AGGREGATE_KEYS:
            instances = [
                other
                for other in new_quantities
                if other.semantic_key not in _AGGREGATE_KEYS and not other.abstained
            ]
            if instances:
                findings.append(
                    ArbitrationFinding(
                        kind="aggregate_instance_overlap",
                        claim=claim,
                        detail="family aggregate and type-instance keys both present; they are distinct claims",
                        quantity_ids=tuple(item.quantity_id for item in instances[:8]),
                    )
                )
    blocking = any(
        item.kind
        in {
            "duplicate_new_claim",
            "conflicting_new_claims",
            "semantic_key_collision",
            "unresolved_mixed_claim",
        }
        for item in findings
    )
    return ArbitrationReport(findings=tuple(findings), blocking=blocking)


def assert_exactly_one_selected(
    selected: Sequence[ClaimKey],
) -> None:
    seen: dict[tuple[str, str, str, str], int] = {}
    for claim in selected:
        key = claim.as_tuple()
        seen[key] = seen.get(key, 0) + 1
    collisions = [key for key, count in seen.items() if count > 1]
    if collisions:
        raise ClaimArbitrationError(
            f"double-selected claims: {collisions!r}"
        )
