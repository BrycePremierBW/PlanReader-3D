"""C15 ceiling-lining shadow quantity governance.

This module implements the *shadow-only* dependent ceiling-lining quantity
contract.  It deliberately does not mutate ``GenericPlanReaderExtractor``
predictions, does not project commercial takeoff rows, and does not calculate
roof, perimeter-trim, fixture-accessory, or wastage quantities.

A numeric shadow quantity exists only when BOTH prerequisites independently
resolve for the same physical scope and viewport coordinate frame:

1. an already-authoritative upstream floor/room/footprint ``QuantityEvidence``;
2. explicit ceiling-finish / ceiling-lining source evidence owned by the active
   document, page, viewport, revision context.

The area is copied exactly from the upstream authoritative quantity.  This
module never re-selects raw area candidates, repairs geometry, invents a scale,
or upgrades measurement authority.  Even when all prerequisites resolve, the
new quantity remains ``PROVISIONAL`` because AGENTS.md requires new extraction
work to begin in shadow mode and only existing authority seams may mint FIRM
measurement authority.
"""
from __future__ import annotations

import math
import re
from typing import Mapping, Optional, Sequence

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    QuantityEvidence,
    ViewportEvidence,
    ViewportResolutionStatus,
    stable_contract_id,
)
from pb_migration_provider_envelope import ProviderContext


CEILING_LINING_FAMILY = "ceiling_lining"
CEILING_LINING_FORMULA_VERSION = "1.0.0"

# Input families are existing/expected area quantity families only.  This list
# is a consumer gate, not an authority vocabulary: status/authority remain the
# existing QuantityEvidence + AuthorityStatus contracts.
_ACCEPTED_AREA_FAMILIES = frozenset(
    {
        "room_area",
        "floor_area",
        "footprint_area",
        "floor_footprint_area",
    }
)
_ACCEPTED_FINISH_KINDS = frozenset({"ceiling_finish", "ceiling_lining"})
_ACCEPTED_AREA_UNITS = frozenset({"m2", "m²", "sqm"})
_AUTHORITATIVE_AREA_STATUSES = frozenset(
    {AuthorityStatus.FIRM.value, AuthorityStatus.USER_APPROVED.value}
)

# Deliberately narrow.  Generic mentions such as "ceiling level", "ceiling
# height", or "RCP" are not finish evidence.  The source text must explicitly
# label a CEILING FINISH or CEILING LINING and include a non-empty descriptor.
_EXPLICIT_CEILING_FINISH_RE = re.compile(
    r"\bceiling\s+(?:finish|lining)\b"
    r"\s*(?::|=|-|–|—)?\s*"
    r"(?P<descriptor>[A-Za-z0-9][A-Za-z0-9 /.,()'\"+\-]{1,119})",
    re.IGNORECASE,
)
_UNRESOLVED_REFERENCE_RE = re.compile(
    r"^(?:as\s+specified|refer(?:\s+to)?\s+schedule|see\s+schedule|"
    r"to\s+architect(?:'s)?\s+detail)$",
    re.IGNORECASE,
)


def _clean(value: object) -> str:
    return str(value if value is not None else "").strip()


def _norm(value: object) -> str:
    return " ".join(_clean(value).replace("\u00a0", " ").split()).casefold()


def _metadata(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _scope_id(atom: EvidenceAtom) -> str:
    return _clean(_metadata(atom.metadata).get("scope_entity_id"))


def _finish_descriptor(raw_text: str) -> Optional[str]:
    """Return canonical explicit finish descriptor, or None if not explicit."""
    text = " ".join(_clean(raw_text).replace("\u00a0", " ").split())
    match = _EXPLICIT_CEILING_FINISH_RE.search(text)
    if match is None:
        return None
    descriptor = match.group("descriptor").strip(" \t:;,.=-–—")
    # Stop common sentence/title delimiters from swallowing unrelated content.
    descriptor = re.split(r"\s{2,}|\s+\|\s+|\s+•\s+", descriptor, maxsplit=1)[0].strip()
    if len(descriptor) < 2 or _UNRESOLVED_REFERENCE_RE.fullmatch(descriptor):
        return None
    return _norm(descriptor)


def explicit_ceiling_finish_descriptor(raw_text: str) -> Optional[str]:
    """Public wrapper: canonical explicit finish descriptor, or None."""
    return _finish_descriptor(raw_text)


def iter_explicit_ceiling_finish_matches(page_text: str) -> tuple[str, ...]:
    """Return raw explicit ceiling-finish / lining match strings from page text."""
    text = " ".join(_clean(page_text).replace("\u00a0", " ").split())
    if not text:
        return ()
    matches: list[str] = []
    seen: set[str] = set()
    for match in _EXPLICIT_CEILING_FINISH_RE.finditer(text):
        raw = match.group(0)
        descriptor = _finish_descriptor(raw)
        if descriptor is None or descriptor in seen:
            continue
        seen.add(descriptor)
        matches.append(raw)
    return tuple(matches)


def _base_context_blockers(
    *,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    page_no: int,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not context.revision_id or not context.current_revision_id:
        blockers.append("revision_unbound")
    elif context.revision_id != context.current_revision_id:
        blockers.append("stale_revision")
    if document.document_id != context.document_id:
        blockers.append("document_id_mismatch")
    if document.source_sha256 != context.source_sha256:
        blockers.append("source_sha256_mismatch")
    if viewport.document_id != context.document_id:
        blockers.append("viewport_document_mismatch")
    if document.page_ids and viewport.page_id not in document.page_ids:
        blockers.append("viewport_page_not_owned_by_document")
    if viewport.viewport_id not in context.trusted_viewport_ids():
        blockers.append("viewport_not_owned")
    if viewport.status not in (
        ViewportResolutionStatus.RESOLVED,
        ViewportResolutionStatus.DERIVED,
    ):
        blockers.append("viewport_unresolved")
    if int(page_no) not in context.trusted_page_numbers():
        blockers.append("page_not_owned")
    mapped_page = context.page_for_viewport(viewport.viewport_id)
    if mapped_page is not None and int(mapped_page) != int(page_no):
        blockers.append("viewport_page_mismatch")
    return tuple(dict.fromkeys(blockers))


def resolve_ceiling_finish_entity(
    *,
    evidence_atoms: Sequence[EvidenceAtom],
    scope_entity_id: str,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    page_no: int,
) -> Optional[EntityEvidence]:
    """Recompute one same-scope explicit ceiling-finish entity from source atoms.

    Evidence bound to a different explicit ``scope_entity_id`` is unrelated and
    ignored, preserving unrelated-content / viewport-expansion invariance.
    Evidence claiming the requested scope but a different document/page/viewport
    is a conflict with the requested coordinate frame and therefore abstains.

    OCR-derived text is retained as evidence but cannot, by itself, corroborate
    the finish semantic in this first shadow slice.  At least one non-OCR source
    token with the same explicit descriptor is required.
    """
    scope = _clean(scope_entity_id)
    if not scope:
        return None

    scoped = tuple(atom for atom in evidence_atoms if _scope_id(atom) == scope)
    if not scoped:
        return None

    evidence_ids = tuple(sorted({atom.evidence_id for atom in scoped}))
    candidate_id = stable_contract_id(
        "ent",
        {
            "candidate_type": "ceiling_finish",
            "scope_entity_id": scope,
            "document_id": context.document_id,
            "page_id": viewport.page_id,
            "viewport_id": viewport.viewport_id,
            "evidence_ids": list(evidence_ids),
        },
    )

    blockers = list(
        _base_context_blockers(
            context=context,
            document=document,
            viewport=viewport,
            page_no=page_no,
        )
    )
    descriptors: dict[str, list[str]] = {}
    source_methods: set[str] = set()
    has_non_ocr_source = False

    for atom in sorted(scoped, key=lambda item: item.evidence_id):
        if atom.evidence_id not in document.evidence_ids:
            blockers.append("finish_evidence_not_owned_by_document")
        if atom.document_id != document.document_id:
            blockers.append("finish_document_mismatch")
        if atom.page_id != viewport.page_id:
            blockers.append("finish_page_mismatch")
        if atom.viewport_id != viewport.viewport_id:
            blockers.append("finish_coordinate_frame_mismatch")
        if _norm(atom.kind) not in _ACCEPTED_FINISH_KINDS:
            blockers.append("finish_evidence_kind_invalid")
        if atom.status in (
            EvidenceResolutionStatus.CONFLICT,
            EvidenceResolutionStatus.ABSTAINED,
        ):
            blockers.append("finish_evidence_already_blocked")

        descriptor = _finish_descriptor(atom.raw_text)
        if descriptor is None:
            blockers.append("ceiling_finish_not_explicit")
        else:
            descriptors.setdefault(descriptor, []).append(atom.evidence_id)

        method = _norm(atom.method)
        source_methods.add(method)
        if "ocr" not in method:
            has_non_ocr_source = True

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        return EntityEvidence(
            candidate_entity_id=candidate_id,
            candidate_type="ceiling_finish",
            evidence_ids=evidence_ids,
            status=EvidenceResolutionStatus.ABSTAINED,
            confidence=0.0,
            reason_codes=tuple(blockers),
            metadata={
                "scope_entity_id": scope,
                "viewport_id": viewport.viewport_id,
                "page_no": int(page_no),
            },
        )

    if len(descriptors) != 1:
        return EntityEvidence(
            candidate_entity_id=candidate_id,
            candidate_type="ceiling_finish",
            evidence_ids=evidence_ids,
            status=EvidenceResolutionStatus.CONFLICT,
            confidence=0.0,
            conflict_evidence_ids=evidence_ids,
            reason_codes=("conflicting_explicit_ceiling_finishes",),
            metadata={
                "scope_entity_id": scope,
                "viewport_id": viewport.viewport_id,
                "page_no": int(page_no),
                "finish_descriptors": tuple(sorted(descriptors)),
            },
        )

    descriptor = next(iter(descriptors))
    if not has_non_ocr_source:
        return EntityEvidence(
            candidate_entity_id=candidate_id,
            candidate_type="ceiling_finish",
            evidence_ids=evidence_ids,
            status=EvidenceResolutionStatus.ABSTAINED,
            confidence=0.0,
            reason_codes=("ocr_only_ceiling_finish_requires_secondary_authority",),
            metadata={
                "scope_entity_id": scope,
                "viewport_id": viewport.viewport_id,
                "page_no": int(page_no),
                "finish_descriptor": descriptor,
                "source_methods": tuple(sorted(source_methods)),
            },
        )

    return EntityEvidence(
        candidate_entity_id=candidate_id,
        candidate_type="ceiling_finish",
        evidence_ids=evidence_ids,
        status=EvidenceResolutionStatus.CORROBORATED,
        confidence=min(float(atom.confidence) for atom in scoped),
        reason_codes=("explicit_same_scope_ceiling_finish",),
        metadata={
            "scope_entity_id": scope,
            "viewport_id": viewport.viewport_id,
            "page_no": int(page_no),
            "finish_descriptor": descriptor,
            "source_methods": tuple(sorted(source_methods)),
        },
    )


def _validate_area_quantity(
    *,
    area_quantity: Optional[QuantityEvidence],
    scope_entity_id: str,
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    page_no: int,
) -> tuple[str, ...]:
    if area_quantity is None:
        return ("missing_authoritative_area_quantity",)

    blockers: list[str] = []
    if area_quantity.abstained or area_quantity.value is None:
        blockers.append("upstream_area_abstained")
    if _norm(area_quantity.family) not in _ACCEPTED_AREA_FAMILIES:
        blockers.append("upstream_quantity_not_floor_or_footprint_area")
    if _norm(area_quantity.unit).replace(" ", "") not in _ACCEPTED_AREA_UNITS:
        blockers.append("upstream_area_unit_not_m2")
    if _norm(area_quantity.status) not in _AUTHORITATIVE_AREA_STATUSES:
        blockers.append("upstream_area_not_authoritative")
    # FIRM is a status, not a measurement method: a guessed/model-derived
    # area cannot be laundered through provisional ceiling lining by copying
    # a FIRM status string from an unrelated quantity producer.
    if _norm(area_quantity.authority) not in {
        MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        MeasurementAuthorityType.PDF_SCALED.value,
        MeasurementAuthorityType.USER_APPROVED.value,
    }:
        blockers.append("upstream_area_measurement_authority_untrusted")
    if area_quantity.semantic_key != (
        f"{area_quantity.family}:{_clean(scope_entity_id)}"
    ):
        blockers.append("upstream_area_semantic_owner_mismatch")
    if area_quantity.blocking_reasons:
        blockers.append("upstream_area_carries_blockers")

    if tuple(area_quantity.input_entity_ids) != (_clean(scope_entity_id),):
        blockers.append("upstream_area_scope_mismatch")

    # This is only a PROVISIONAL ceiling handoff, but a false positive here
    # can be replayed as a future source-backed ceiling. Validate the actual
    # original area evidence instead of relying on an upstream status string.
    if area_quantity.value is not None:
        if type(area_quantity.value) not in (int, float):
            blockers.append("upstream_area_invalid")
        else:
            value = float(area_quantity.value)
            if not math.isfinite(value) or value <= 0.0:
                blockers.append("upstream_area_invalid")
    if (
        type(area_quantity.confidence) not in (int, float)
        or not math.isfinite(float(area_quantity.confidence))
        or not 0.0 <= float(area_quantity.confidence) <= 1.0
    ):
        blockers.append("upstream_area_confidence_invalid")
    if (
        not isinstance(area_quantity.evidence_ids, (tuple, list))
        or not area_quantity.evidence_ids
        or any(type(value) is not str or not value.strip() for value in area_quantity.evidence_ids)
        or len(set(area_quantity.evidence_ids)) != len(area_quantity.evidence_ids)
    ):
        blockers.append("upstream_area_source_receipts_invalid")

    if not set(area_quantity.evidence_ids).issubset(set(document.evidence_ids)):
        blockers.append("upstream_area_evidence_not_owned_by_document")

    meta = _metadata(area_quantity.metadata)
    if _clean(meta.get("source_sha256")).lower() != context.source_sha256:
        blockers.append("upstream_area_source_sha256_mismatch")
    if _clean(meta.get("revision_id")) != _clean(context.current_revision_id):
        blockers.append("upstream_area_revision_mismatch")
    if _clean(meta.get("viewport_id")) != viewport.viewport_id:
        blockers.append("upstream_area_coordinate_frame_mismatch")
    raw_area_page = meta.get("page_no")
    if type(raw_area_page) not in (int, str) or (
        isinstance(raw_area_page, str) and (
            not raw_area_page or raw_area_page != raw_area_page.strip()
            or not raw_area_page.isdecimal()
        )
    ):
        blockers.append("upstream_area_page_unbound")
    else:
        try:
            area_page = int(raw_area_page)
        except (TypeError, ValueError, OverflowError):
            blockers.append("upstream_area_page_unbound")
        else:
            if area_page != int(page_no):
                blockers.append("upstream_area_page_mismatch")

    blockers.extend(
        _base_context_blockers(
            context=context,
            document=document,
            viewport=viewport,
            page_no=page_no,
        )
    )
    return tuple(dict.fromkeys(blockers))


def _abstention(
    *,
    scope_entity_id: str,
    area_quantity: Optional[QuantityEvidence],
    finish_entity: Optional[EntityEvidence],
    context: ProviderContext,
    viewport: ViewportEvidence,
    page_no: int,
    blockers: Sequence[str],
) -> QuantityEvidence:
    reasons = tuple(dict.fromkeys(_clean(reason) for reason in blockers if _clean(reason)))
    if not reasons:
        reasons = ("ceiling_lining_unresolved",)
    payload = {
        "family": CEILING_LINING_FAMILY,
        "scope_entity_id": _clean(scope_entity_id),
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
        "viewport_id": viewport.viewport_id,
        "page_no": int(page_no),
        "area_quantity_id": area_quantity.quantity_id if area_quantity is not None else None,
        "finish_entity_id": finish_entity.candidate_entity_id if finish_entity is not None else None,
        "blockers": list(reasons),
    }
    evidence_ids = sorted(
        {
            *(() if area_quantity is None else area_quantity.evidence_ids),
            *(() if finish_entity is None else finish_entity.evidence_ids),
        }
    )
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=CEILING_LINING_FAMILY,
        semantic_key=f"ceiling_lining:{_clean(scope_entity_id) or 'unresolved'}",
        value=None,
        unit="m2",
        input_entity_ids=(_clean(scope_entity_id),) if _clean(scope_entity_id) else (),
        formula="reuse_same_scope_authoritative_area_with_explicit_ceiling_finish",
        formula_version=CEILING_LINING_FORMULA_VERSION,
        evidence_ids=tuple(evidence_ids),
        authority=MeasurementAuthorityType.MODEL_DERIVED.value,
        status=AuthorityStatus.BLOCKED.value,
        confidence=0.0,
        abstained=True,
        blocking_reasons=reasons,
        reason_codes=reasons,
        metadata={
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
            "page_no": int(page_no),
            "viewport_id": viewport.viewport_id,
            "shadow_only": True,
            "commercial_projection_allowed": False,
        },
    )


def build_ceiling_lining_quantity(
    *,
    scope_entity_id: str,
    area_quantity: Optional[QuantityEvidence],
    finish_evidence_atoms: Sequence[EvidenceAtom],
    context: ProviderContext,
    document: DocumentEvidence,
    viewport: ViewportEvidence,
    page_no: int,
) -> QuantityEvidence:
    """Build a shadow ceiling-lining quantity or an explicit BLOCKED abstention.

    The upstream area is consumed *as finalized*.  This function never compares
    candidate areas, never derives area from dimensions, and never changes its
    value.  Exact same-scope identity is enforced by ``input_entity_ids`` plus
    source/revision/page/viewport bindings.
    """
    scope = _clean(scope_entity_id)
    if not scope:
        return _abstention(
            scope_entity_id=scope,
            area_quantity=area_quantity,
            finish_entity=None,
            context=context,
            viewport=viewport,
            page_no=page_no,
            blockers=("scope_entity_id_missing",),
        )

    finish_entity = resolve_ceiling_finish_entity(
        evidence_atoms=finish_evidence_atoms,
        scope_entity_id=scope,
        context=context,
        document=document,
        viewport=viewport,
        page_no=page_no,
    )
    finish_blockers: list[str] = []
    if finish_entity is None:
        finish_blockers.append("missing_explicit_ceiling_finish")
    elif finish_entity.status == EvidenceResolutionStatus.CONFLICT:
        finish_blockers.extend(finish_entity.reason_codes or ("ceiling_finish_conflict",))
    elif finish_entity.status != EvidenceResolutionStatus.CORROBORATED:
        finish_blockers.extend(
            finish_entity.reason_codes or ("ceiling_finish_not_corroborated",)
        )

    area_blockers = _validate_area_quantity(
        area_quantity=area_quantity,
        scope_entity_id=scope,
        context=context,
        document=document,
        viewport=viewport,
        page_no=page_no,
    )
    blockers = tuple(dict.fromkeys([*finish_blockers, *area_blockers]))
    if blockers:
        return _abstention(
            scope_entity_id=scope,
            area_quantity=area_quantity,
            finish_entity=finish_entity,
            context=context,
            viewport=viewport,
            page_no=page_no,
            blockers=blockers,
        )

    assert area_quantity is not None
    assert area_quantity.value is not None
    assert finish_entity is not None
    value = float(area_quantity.value)
    evidence_ids = tuple(
        sorted({*area_quantity.evidence_ids, *finish_entity.evidence_ids})
    )
    finish_meta = _metadata(finish_entity.metadata)
    payload = {
        "family": CEILING_LINING_FAMILY,
        "scope_entity_id": scope,
        "value_m2": value,
        "upstream_area_quantity_id": area_quantity.quantity_id,
        "finish_entity_id": finish_entity.candidate_entity_id,
        "source_sha256": context.source_sha256,
        "revision_id": context.current_revision_id,
        "page_no": int(page_no),
        "viewport_id": viewport.viewport_id,
    }
    return QuantityEvidence(
        quantity_id=stable_contract_id("qty", payload),
        family=CEILING_LINING_FAMILY,
        semantic_key=f"ceiling_lining:{scope}",
        value=value,
        unit="m2",
        input_entity_ids=(scope,),
        formula="reuse_same_scope_authoritative_area_with_explicit_ceiling_finish",
        formula_version=CEILING_LINING_FORMULA_VERSION,
        evidence_ids=evidence_ids,
        authority=MeasurementAuthorityType.MODEL_DERIVED.value,
        # Shadow mode cannot mint FIRM authority.  A separate authority review
        # must explicitly promote this family later.
        status=AuthorityStatus.PROVISIONAL.value,
        confidence=min(float(area_quantity.confidence), float(finish_entity.confidence)),
        abstained=False,
        blocking_reasons=(),
        reason_codes=(
            "same_scope_authoritative_area_reused_exactly",
            "explicit_ceiling_finish_corroborated",
            "shadow_mode_no_firm_promotion",
        ),
        metadata={
            "source_sha256": context.source_sha256,
            "revision_id": context.current_revision_id,
            "page_no": int(page_no),
            "viewport_id": viewport.viewport_id,
            "scope_entity_id": scope,
            "upstream_area_quantity_id": area_quantity.quantity_id,
            "upstream_area_family": area_quantity.family,
            "upstream_area_authority": area_quantity.authority,
            "upstream_area_status": area_quantity.status,
            "finish_entity_id": finish_entity.candidate_entity_id,
            "finish_descriptor": finish_meta.get("finish_descriptor", ""),
            "finish_evidence_ids": tuple(finish_entity.evidence_ids),
            "finish_source_methods": finish_meta.get("source_methods", ()),
            "shadow_only": True,
            "commercial_projection_allowed": False,
            "dependent_claims_not_evaluated": (
                "ceiling_perimeter_trim",
                "recessed_fixture_accessories",
                "commercial_wastage",
                "roof_area",
            ),
        },
    )
