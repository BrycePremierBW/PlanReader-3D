"""Versioned contracts for the PlanReader legacy-to-graph migration.

This module is intentionally free of benchmark/gold dependencies.  It defines
small, immutable records that can be shared by the existing production reader,
new evidence/graph providers, shadow-mode comparison, and output adapters.

The contracts do not perform PDF extraction, semantic inference, geometry
reconstruction, or benchmark evaluation.  They only make ownership and
provenance boundaries explicit so those stages can evolve independently.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass, dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping, Optional, Sequence


MIGRATION_CONTRACT_SCHEMA_VERSION = "1.0.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MigrationAuthorityState(str, Enum):
    """Per-quantity-family migration authority state."""

    LEGACY_AUTHORITATIVE = "legacy_authoritative"
    NEW_SHADOW = "new_shadow"
    NEW_SELECTIVE = "new_selective"
    NEW_AUTHORITATIVE = "new_authoritative"
    LEGACY_RETIRED = "legacy_retired"


class EvidenceResolutionStatus(str, Enum):
    """Resolution state for evidence and candidate physical entities."""

    RAW = "raw"
    CANDIDATE = "candidate"
    CORROBORATED = "corroborated"
    CONFLICT = "conflict"
    ABSTAINED = "abstained"


class ViewportResolutionStatus(str, Enum):
    """Spatial ownership state for a drawing viewport."""

    RESOLVED = "resolved"
    DERIVED = "derived"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


def _require_nonempty(value: str, field_name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field_name} must be a non-empty string")
    return clean


def _require_confidence(value: float, field_name: str = "confidence") -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{field_name} must be finite and within [0, 1]")
    return numeric


def _require_bbox(
    bbox: Optional[Sequence[float]],
    *,
    field_name: str = "bbox",
) -> Optional[tuple[float, float, float, float]]:
    if bbox is None:
        return None
    if len(bbox) != 4:
        raise ValueError(f"{field_name} must contain exactly four coordinates")
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} coordinates must be numeric") from exc
    values = (x0, y0, x1, y1)
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"{field_name} coordinates must be finite")
    if x1 < x0 or y1 < y0:
        raise ValueError(f"{field_name} must satisfy x1 >= x0 and y1 >= y0")
    return values


def _plain(value: Any) -> Any:
    """Convert contract values into deterministic JSON-compatible primitives."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("contract payload contains a non-finite float")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def canonical_contract_json(value: Any) -> str:
    """Return a stable canonical JSON representation for hashing/artifacts."""
    return json.dumps(
        _plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def stable_contract_id(prefix: str, payload: Any, *, digest_chars: int = 20) -> str:
    """Create a deterministic content-derived ID for a migration artifact.

    ``prefix`` is semantic only (for example ``doc``, ``vp``, ``ev``, ``ent``
    or ``qty``); the digest is calculated solely from the canonical payload.
    """
    clean_prefix = re.sub(r"[^a-z0-9_]+", "_", str(prefix or "").strip().lower()).strip("_")
    if not clean_prefix:
        raise ValueError("prefix must contain at least one alphanumeric character")
    if not 8 <= int(digest_chars) <= 64:
        raise ValueError("digest_chars must be between 8 and 64")
    digest = hashlib.sha256(canonical_contract_json(payload).encode("utf-8")).hexdigest()
    return f"{clean_prefix}_{digest[:int(digest_chars)]}"


@dataclass(frozen=True)
class EvidenceAtom:
    """One immutable piece of source evidence before physical-entity fusion."""

    evidence_id: str
    document_id: str
    page_id: str
    kind: str
    method: str
    viewport_id: Optional[str] = None
    raw_text: str = ""
    bbox: Optional[tuple[float, float, float, float]] = None
    normalized_value: Optional[float] = None
    unit: Optional[str] = None
    confidence: float = 1.0
    status: EvidenceResolutionStatus = EvidenceResolutionStatus.RAW
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = MIGRATION_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.evidence_id, "evidence_id")
        _require_nonempty(self.document_id, "document_id")
        _require_nonempty(self.page_id, "page_id")
        _require_nonempty(self.kind, "kind")
        _require_nonempty(self.method, "method")
        _require_confidence(self.confidence)
        object.__setattr__(self, "bbox", _require_bbox(self.bbox))
        if self.normalized_value is not None:
            numeric = float(self.normalized_value)
            if not math.isfinite(numeric):
                raise ValueError("normalized_value must be finite when supplied")
            object.__setattr__(self, "normalized_value", numeric)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class DocumentEvidence:
    """Document-level immutable evidence manifest.

    Raw page/vector/text payloads may be stored as separate content-addressed
    artifacts.  This record owns the source identity and references the pages and
    evidence atoms that belong to that exact source hash.
    """

    document_id: str
    source_sha256: str
    page_count: int
    page_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    producer: str = ""
    producer_version: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = MIGRATION_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.document_id, "document_id")
        source_hash = str(self.source_sha256 or "").strip().lower()
        if not _SHA256_RE.fullmatch(source_hash):
            raise ValueError("source_sha256 must be a 64-character lowercase SHA-256 hex digest")
        object.__setattr__(self, "source_sha256", source_hash)
        if isinstance(self.page_count, bool) or int(self.page_count) < 0:
            raise ValueError("page_count must be a non-negative integer")
        object.__setattr__(self, "page_count", int(self.page_count))
        if self.page_ids and len(self.page_ids) != self.page_count:
            raise ValueError("page_ids length must equal page_count when page_ids are supplied")
        if len(set(self.page_ids)) != len(self.page_ids):
            raise ValueError("page_ids must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class ViewportEvidence:
    """Spatial ownership and scale context for one drawing viewport."""

    viewport_id: str
    document_id: str
    page_id: str
    bbox: tuple[float, float, float, float]
    view_type: str
    status: ViewportResolutionStatus
    evidence_ids: tuple[str, ...] = ()
    scale_evidence_ids: tuple[str, ...] = ()
    resolved_scale_id: Optional[str] = None
    confidence: float = 0.0
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = MIGRATION_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.viewport_id, "viewport_id")
        _require_nonempty(self.document_id, "document_id")
        _require_nonempty(self.page_id, "page_id")
        _require_nonempty(self.view_type, "view_type")
        object.__setattr__(self, "bbox", _require_bbox(self.bbox) or (0.0, 0.0, 0.0, 0.0))
        _require_confidence(self.confidence)
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")
        if len(set(self.scale_evidence_ids)) != len(self.scale_evidence_ids):
            raise ValueError("scale_evidence_ids must be unique")
        if self.status in (ViewportResolutionStatus.AMBIGUOUS, ViewportResolutionStatus.UNSUPPORTED):
            if self.resolved_scale_id is not None:
                raise ValueError("ambiguous/unsupported viewport cannot carry a resolved_scale_id")

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class EntityEvidence:
    """Evidence bundle for a candidate physical entity before graph commitment."""

    candidate_entity_id: str
    candidate_type: str
    evidence_ids: tuple[str, ...]
    status: EvidenceResolutionStatus = EvidenceResolutionStatus.CANDIDATE
    confidence: float = 0.0
    conflict_evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = MIGRATION_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.candidate_entity_id, "candidate_entity_id")
        _require_nonempty(self.candidate_type, "candidate_type")
        if not self.evidence_ids:
            raise ValueError("EntityEvidence requires at least one evidence_id")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")
        if len(set(self.conflict_evidence_ids)) != len(self.conflict_evidence_ids):
            raise ValueError("conflict_evidence_ids must be unique")
        _require_confidence(self.confidence)
        if self.status == EvidenceResolutionStatus.CORROBORATED and self.conflict_evidence_ids:
            raise ValueError("corroborated entity cannot retain unresolved conflict_evidence_ids")
        if self.status == EvidenceResolutionStatus.CONFLICT and not self.conflict_evidence_ids:
            raise ValueError("conflict status requires conflict_evidence_ids")

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class QuantityEvidence:
    """Deterministic quantity result with complete trace and abstention semantics."""

    quantity_id: str
    family: str
    semantic_key: str
    value: Optional[float]
    unit: str
    input_entity_ids: tuple[str, ...] = ()
    formula: str = ""
    formula_version: str = ""
    evidence_ids: tuple[str, ...] = ()
    authority: str = ""
    status: str = ""
    confidence: float = 0.0
    abstained: bool = False
    blocking_reasons: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = MIGRATION_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.quantity_id, "quantity_id")
        _require_nonempty(self.family, "family")
        _require_nonempty(self.semantic_key, "semantic_key")
        _require_nonempty(self.unit, "unit")
        _require_nonempty(self.authority, "authority")
        _require_nonempty(self.status, "status")
        _require_confidence(self.confidence)
        if len(set(self.input_entity_ids)) != len(self.input_entity_ids):
            raise ValueError("input_entity_ids must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")

        if self.abstained:
            if self.value is not None:
                raise ValueError("abstained QuantityEvidence must not carry a numeric value")
            if not self.blocking_reasons:
                raise ValueError("abstained QuantityEvidence requires at least one blocking reason")
            return

        if self.value is None:
            raise ValueError("non-abstained QuantityEvidence requires a numeric value")
        numeric = float(self.value)
        if not math.isfinite(numeric) or numeric < 0.0:
            raise ValueError("quantity value must be finite and non-negative")
        object.__setattr__(self, "value", numeric)
        if not self.input_entity_ids and not self.evidence_ids:
            raise ValueError("non-abstained QuantityEvidence requires entity or evidence traceability")

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class ShadowQuantityComparison:
    """Gold-free legacy/new comparison artifact.

    Expected benchmark values deliberately do not exist in this contract.  A
    benchmark harness may join gold only after both engine outputs are frozen.
    """

    family: str
    semantic_key: str
    legacy_quantity_id: Optional[str]
    new_quantity_id: Optional[str]
    legacy_value: Optional[float]
    new_value: Optional[float]
    unit: str
    absolute_delta: Optional[float]
    relative_delta: Optional[float]
    status: str
    new_engine_abstained: bool = False
    reason_codes: tuple[str, ...] = ()
    schema_version: str = MIGRATION_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.family, "family")
        _require_nonempty(self.semantic_key, "semantic_key")
        _require_nonempty(self.unit, "unit")
        _require_nonempty(self.status, "status")
        for name in ("legacy_value", "new_value", "absolute_delta", "relative_delta"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite when supplied")

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)
