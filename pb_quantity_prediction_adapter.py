"""Project graph QuantityEvidence into the existing prediction compatibility shape.

This adapter is deliberately generic and gold-free.  It does not know benchmark
IDs, expected quantities, item mappings, or tolerance rules.  It exists only so
new graph quantities can be consumed by legacy callers while migration remains
family-by-family and reversible.

No source page is guessed.  Dict projection may carry ``source_page=None`` for
callers that accept an unlocated prediction.  Construction of the legacy
``ExtractedPrediction`` object requires an explicit positive source-page trace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Any, Mapping, Optional, Sequence

from pb_migration_contracts import QuantityEvidence, canonical_contract_json


PREDICTION_ADAPTER_VERSION = "1.0.0"


class PredictionProjectionAmbiguityError(RuntimeError):
    """Raised when more than one emitted quantity claims one semantic key."""


_CANONICAL_TO_LEGACY_UNIT = {
    "ea": "NO",
    "each": "NO",
    "no": "NO",
    "nr": "NO",
    "m2": "SM",
    "m²": "SM",
    "sqm": "SM",
    "m": "M",
    "lm": "M",
    "m3": "M3",
    "m³": "M3",
}


def prediction_unit(unit: str) -> str:
    """Map only unambiguous generic unit aliases into the legacy output vocabulary."""
    clean = str(unit or "").strip()
    if not clean:
        raise ValueError("quantity unit must be non-empty")
    return _CANONICAL_TO_LEGACY_UNIT.get(clean.lower().replace(" ", ""), clean)


def _finite_tuple(
    values: Optional[Sequence[float]],
    *,
    field_name: str,
    exact_length: Optional[int] = None,
) -> Optional[tuple[float, ...]]:
    if values is None:
        return None
    if exact_length is not None and len(values) != exact_length:
        raise ValueError(f"{field_name} must contain exactly {exact_length} values")
    converted = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in converted):
        raise ValueError(f"{field_name} values must be finite")
    return converted


def _json_copy(value: Any) -> Any:
    return json.loads(canonical_contract_json(value))


@dataclass(frozen=True)
class PredictionSourceTrace:
    """Explicit legacy source-location trace supplied by an evidence resolver."""

    source_page: Optional[int] = None
    sheet_number: Optional[str] = None
    dimensions: Optional[tuple[float, ...]] = None
    bounding_box: Optional[tuple[float, float, float, float]] = None
    description: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_page is not None:
            if isinstance(self.source_page, bool) or int(self.source_page) <= 0:
                raise ValueError("source_page must be a positive 1-based integer when supplied")
            object.__setattr__(self, "source_page", int(self.source_page))
        object.__setattr__(
            self,
            "dimensions",
            _finite_tuple(self.dimensions, field_name="dimensions"),
        )
        bbox = _finite_tuple(
            self.bounding_box,
            field_name="bounding_box",
            exact_length=4,
        )
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            if x1 < x0 or y1 < y0:
                raise ValueError("bounding_box must satisfy x1 >= x0 and y1 >= y0")
        object.__setattr__(self, "bounding_box", bbox)
        object.__setattr__(self, "metadata", _json_copy(self.metadata))


def _description(quantity: QuantityEvidence, trace: Optional[PredictionSourceTrace]) -> str:
    if trace is not None and str(trace.description or "").strip():
        return str(trace.description).strip()
    metadata_description = quantity.metadata.get("description") if isinstance(quantity.metadata, Mapping) else None
    if str(metadata_description or "").strip():
        return str(metadata_description).strip()
    return quantity.semantic_key


def _trade_type(quantity: QuantityEvidence) -> str:
    metadata_trade = quantity.metadata.get("trade_type") if isinstance(quantity.metadata, Mapping) else None
    if str(metadata_trade or "").strip():
        return str(metadata_trade).strip()
    return quantity.family


def quantity_evidence_to_prediction_dict(
    quantity: QuantityEvidence,
    *,
    trace: Optional[PredictionSourceTrace] = None,
) -> Optional[dict[str, Any]]:
    """Project one quantity into the legacy prediction dict shape.

    Abstentions emit no prediction: downstream evaluation may then treat a
    benchmark-expected item as missed, rather than receiving an invented zero.
    """
    if not isinstance(quantity, QuantityEvidence):
        raise TypeError("quantity must be a QuantityEvidence record")
    if quantity.abstained:
        return None

    source_page = trace.source_page if trace is not None else None
    sheet_number = trace.sheet_number if trace is not None else None
    dimensions = list(trace.dimensions) if trace is not None and trace.dimensions is not None else None
    bounding_box = (
        list(trace.bounding_box)
        if trace is not None and trace.bounding_box is not None
        else None
    )

    projection_metadata: dict[str, Any] = {
        "migration_adapter_version": PREDICTION_ADAPTER_VERSION,
        "quantity_id": quantity.quantity_id,
        "quantity_family": quantity.family,
        "quantity_authority": quantity.authority,
        "quantity_status": quantity.status,
        "formula": quantity.formula,
        "formula_version": quantity.formula_version,
        "input_entity_ids": list(quantity.input_entity_ids),
        "evidence_ids": list(quantity.evidence_ids),
        "reason_codes": list(quantity.reason_codes),
        "quantity_metadata": _json_copy(quantity.metadata),
    }
    if trace is not None and trace.metadata:
        projection_metadata["source_trace_metadata"] = _json_copy(trace.metadata)

    return {
        "tag": quantity.semantic_key,
        "trade_type": _trade_type(quantity),
        "description": _description(quantity, trace),
        "quantity": float(quantity.value),
        "unit": prediction_unit(quantity.unit),
        "confidence": float(quantity.confidence),
        "source_page": source_page,
        "sheet_number": sheet_number,
        "dimensions": dimensions,
        "bounding_box": bounding_box,
        "metadata": projection_metadata,
    }


def quantities_to_prediction_dicts(
    quantities: Sequence[QuantityEvidence],
    *,
    traces_by_quantity_id: Optional[Mapping[str, PredictionSourceTrace]] = None,
) -> list[dict[str, Any]]:
    """Project a quantity bundle, failing closed on duplicate emitted semantic keys."""
    traces = traces_by_quantity_id or {}
    seen_semantic_keys: set[str] = set()
    output: list[dict[str, Any]] = []
    for quantity in quantities:
        if not isinstance(quantity, QuantityEvidence):
            raise TypeError("quantities must contain only QuantityEvidence records")
        projected = quantity_evidence_to_prediction_dict(
            quantity,
            trace=traces.get(quantity.quantity_id),
        )
        if projected is None:
            continue
        semantic_key = quantity.semantic_key
        if semantic_key in seen_semantic_keys:
            raise PredictionProjectionAmbiguityError(
                f"multiple emitted quantities claim semantic key {semantic_key!r}"
            )
        seen_semantic_keys.add(semantic_key)
        output.append(projected)
    return output


def quantity_evidence_to_extracted_prediction(
    quantity: QuantityEvidence,
    *,
    trace: PredictionSourceTrace,
):
    """Construct the legacy ExtractedPrediction only with real page trace.

    Import is intentionally local: the migration core does not depend on the
    legacy extractor module merely to represent QuantityEvidence.
    """
    if trace is None or trace.source_page is None:
        raise ValueError(
            "an explicit positive source_page trace is required to construct ExtractedPrediction"
        )
    projected = quantity_evidence_to_prediction_dict(quantity, trace=trace)
    if projected is None:
        return None

    from pb_planreader_pdf_extractor import ExtractedPrediction

    return ExtractedPrediction(
        tag=projected["tag"],
        trade_type=projected["trade_type"],
        description=projected["description"],
        quantity=projected["quantity"],
        unit=projected["unit"],
        confidence=projected["confidence"],
        source_page=projected["source_page"],
        sheet_number=projected["sheet_number"],
        dimensions=projected["dimensions"],
        bounding_box=projected["bounding_box"],
        metadata=projected["metadata"],
    )
