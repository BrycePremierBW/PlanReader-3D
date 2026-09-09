"""Compatibility adapter around the current GenericPlanReaderExtractor.

M2 of the graph-migration program deliberately does not change extraction
behaviour.  It freezes the legacy extractor behind a stable adapter so the
future graph engine can run beside it in shadow mode without either side
reading benchmark gold or silently mutating the other's results.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from pb_migration_contracts import canonical_contract_json, stable_contract_id
from pb_planreader_pdf_extractor import ExtractedPrediction, GenericPlanReaderExtractor


LEGACY_EXTRACTOR_ENGINE_ID = "generic_planreader_extractor"
LEGACY_EXTRACTOR_ADAPTER_VERSION = "1.0.0"


class SourceMutationDuringExtractionError(RuntimeError):
    """Raised when the source bytes change while one extraction is running."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_copy(value: Any) -> Any:
    """Detach mutable metadata from the live legacy prediction objects."""
    return json.loads(canonical_contract_json(value))


@dataclass(frozen=True)
class LegacyPredictionSnapshot:
    """Immutable compatibility snapshot of one legacy ExtractedPrediction."""

    tag: str
    trade_type: str
    description: str
    quantity: float
    unit: str
    confidence: float
    source_page: int
    sheet_number: Optional[str] = None
    dimensions: Optional[tuple[float, ...]] = None
    bounding_box: Optional[tuple[float, ...]] = None
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not str(self.tag or "").strip():
            raise ValueError("legacy prediction tag must be non-empty")
        if not str(self.trade_type or "").strip():
            raise ValueError("legacy prediction trade_type must be non-empty")
        if not str(self.unit or "").strip():
            raise ValueError("legacy prediction unit must be non-empty")
        if not math.isfinite(float(self.quantity)):
            raise ValueError("legacy prediction quantity must be finite")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("legacy prediction confidence must be within [0, 1]")
        if isinstance(self.source_page, bool) or int(self.source_page) <= 0:
            raise ValueError("legacy prediction source_page must be a positive integer")
        if self.dimensions is not None and not all(math.isfinite(float(v)) for v in self.dimensions):
            raise ValueError("legacy prediction dimensions must be finite")
        if self.bounding_box is not None and not all(math.isfinite(float(v)) for v in self.bounding_box):
            raise ValueError("legacy prediction bounding_box values must be finite")
        object.__setattr__(self, "quantity", float(self.quantity))
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "source_page", int(self.source_page))
        object.__setattr__(self, "metadata", _json_copy(self.metadata or {}))

    @classmethod
    def from_prediction(cls, prediction: ExtractedPrediction) -> "LegacyPredictionSnapshot":
        return cls(
            tag=prediction.tag,
            trade_type=prediction.trade_type,
            description=prediction.description,
            quantity=prediction.quantity,
            unit=prediction.unit,
            confidence=prediction.confidence,
            source_page=prediction.source_page,
            sheet_number=prediction.sheet_number,
            dimensions=tuple(prediction.dimensions) if prediction.dimensions is not None else None,
            bounding_box=tuple(prediction.bounding_box) if prediction.bounding_box is not None else None,
            metadata=prediction.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the exact public payload shape used by ExtractedPrediction.to_dict()."""
        return {
            "tag": self.tag,
            "trade_type": self.trade_type,
            "description": self.description,
            "quantity": self.quantity,
            "unit": self.unit,
            "confidence": self.confidence,
            "source_page": self.source_page,
            "sheet_number": self.sheet_number,
            "dimensions": list(self.dimensions) if self.dimensions is not None else None,
            "bounding_box": list(self.bounding_box) if self.bounding_box is not None else None,
            "metadata": _json_copy(self.metadata),
        }


@dataclass(frozen=True)
class LegacyExtractionResult:
    """Frozen result of one legacy extraction invocation."""

    result_id: str
    engine_id: str
    adapter_version: str
    source_sha256: str
    source_size_bytes: int
    pages: Optional[tuple[int, ...]]
    predictions: tuple[LegacyPredictionSnapshot, ...]

    def __post_init__(self) -> None:
        if len(self.source_sha256) != 64:
            raise ValueError("source_sha256 must be a SHA-256 hex digest")
        if isinstance(self.source_size_bytes, bool) or int(self.source_size_bytes) < 0:
            raise ValueError("source_size_bytes must be a non-negative integer")
        if self.pages is not None:
            if any(isinstance(page, bool) or int(page) < 0 for page in self.pages):
                raise ValueError("pages must contain zero-based non-negative page indices")
            if len(set(self.pages)) != len(self.pages):
                raise ValueError("pages must not contain duplicates")

    def to_prediction_dicts(self) -> list[dict[str, Any]]:
        return [prediction.to_dict() for prediction in self.predictions]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "engine_id": self.engine_id,
            "adapter_version": self.adapter_version,
            "source_sha256": self.source_sha256,
            "source_size_bytes": self.source_size_bytes,
            "pages": list(self.pages) if self.pages is not None else None,
            "predictions": self.to_prediction_dicts(),
        }


class LegacyExtractorAdapter:
    """Run the current GenericPlanReaderExtractor without changing its semantics."""

    def __init__(
        self,
        extractor_factory: Callable[[], GenericPlanReaderExtractor] = GenericPlanReaderExtractor,
    ) -> None:
        self._extractor_factory = extractor_factory

    def extract(
        self,
        pdf_path: Path | str,
        pages: Optional[Sequence[int]] = None,
    ) -> LegacyExtractionResult:
        source = Path(pdf_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"PDF file not found at: {source}")

        normalized_pages = tuple(int(page) for page in pages) if pages else None
        if normalized_pages is not None:
            if any(page < 0 for page in normalized_pages):
                raise ValueError("pages must use zero-based non-negative page indices")
            if len(set(normalized_pages)) != len(normalized_pages):
                raise ValueError("pages must not contain duplicates")

        before_hash = _sha256_file(source)
        before_size = source.stat().st_size

        extractor = self._extractor_factory()
        live_predictions = extractor.extract_from_pdf(
            source,
            pages=normalized_pages,
        )

        after_hash = _sha256_file(source)
        after_size = source.stat().st_size
        if before_hash != after_hash or before_size != after_size:
            raise SourceMutationDuringExtractionError(
                "source PDF changed while legacy extraction was running; result was discarded"
            )

        snapshots = tuple(
            LegacyPredictionSnapshot.from_prediction(prediction)
            for prediction in live_predictions
        )
        id_payload = {
            "engine_id": LEGACY_EXTRACTOR_ENGINE_ID,
            "adapter_version": LEGACY_EXTRACTOR_ADAPTER_VERSION,
            "source_sha256": before_hash,
            "pages": list(normalized_pages) if normalized_pages is not None else None,
            "predictions": [snapshot.to_dict() for snapshot in snapshots],
        }
        result_id = stable_contract_id("legacy_run", id_payload)

        return LegacyExtractionResult(
            result_id=result_id,
            engine_id=LEGACY_EXTRACTOR_ENGINE_ID,
            adapter_version=LEGACY_EXTRACTOR_ADAPTER_VERSION,
            source_sha256=before_hash,
            source_size_bytes=before_size,
            pages=normalized_pages,
            predictions=snapshots,
        )
