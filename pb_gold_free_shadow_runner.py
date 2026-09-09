"""Gold-free shadow runner for PlanReader legacy/new-engine migration.

M3 runs the current legacy extractor and an injected new quantity engine against
exactly the same source bytes, freezes both outputs, and compares them without
loading benchmark IDs, expected quantities, item mappings, or tolerance rules.

Benchmark evaluation may join gold only after this artifact has been written.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from pb_legacy_extractor_adapter import (
    LegacyExtractionResult,
    LegacyExtractorAdapter,
    LegacyPredictionSnapshot,
)
from pb_migration_contracts import (
    QuantityEvidence,
    ShadowQuantityComparison,
    stable_contract_id,
)


SHADOW_RUNNER_VERSION = "1.0.0"


class SourceMutationDuringShadowRunError(RuntimeError):
    """Raised when source bytes change between legacy and new-engine runs."""


class ShadowComparisonAmbiguityError(RuntimeError):
    """Raised when an engine emits multiple quantities for one semantic key."""


class ShadowQuantityEngine(Protocol):
    """Minimal interface required from a new graph/quantity engine in shadow mode."""

    engine_id: str
    engine_version: str

    def extract_quantities(
        self,
        pdf_path: Path | str,
        pages: Optional[Sequence[int]] = None,
    ) -> Sequence[QuantityEvidence]: ...


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_UNIT_ALIASES = {
    "NO": "ea",
    "NO.": "ea",
    "NOS": "ea",
    "NOS.": "ea",
    "NR": "ea",
    "EA": "ea",
    "EACH": "ea",
    "SM": "m2",
    "M2": "m2",
    "M²": "m2",
    "SQM": "m2",
    "SQ.M": "m2",
    "M": "m",
    "LM": "m",
    "L.M": "m",
    "M3": "m3",
    "M³": "m3",
}


def canonical_shadow_unit(unit: str) -> str:
    """Normalize only unambiguous unit aliases; never apply project-specific mapping."""
    clean = str(unit or "").strip().upper().replace(" ", "")
    if not clean:
        raise ValueError("unit must be non-empty")
    return _UNIT_ALIASES.get(clean, clean.lower())


def _legacy_by_semantic_key(
    predictions: Sequence[LegacyPredictionSnapshot],
) -> dict[str, LegacyPredictionSnapshot]:
    result: dict[str, LegacyPredictionSnapshot] = {}
    for prediction in predictions:
        key = str(prediction.tag or "").strip()
        if key in result:
            raise ShadowComparisonAmbiguityError(
                f"legacy engine emitted duplicate semantic key {key!r}"
            )
        result[key] = prediction
    return result


def _new_by_semantic_key(
    quantities: Sequence[QuantityEvidence],
) -> dict[str, QuantityEvidence]:
    result: dict[str, QuantityEvidence] = {}
    for quantity in quantities:
        key = str(quantity.semantic_key or "").strip()
        if key in result:
            raise ShadowComparisonAmbiguityError(
                f"new engine emitted duplicate semantic key {key!r}"
            )
        result[key] = quantity
    return result


def compare_shadow_quantities(
    legacy_result: LegacyExtractionResult,
    new_quantities: Sequence[QuantityEvidence],
) -> tuple[ShadowQuantityComparison, ...]:
    """Compare engines by generic semantic key only, with no benchmark mappings."""
    legacy = _legacy_by_semantic_key(legacy_result.predictions)
    new = _new_by_semantic_key(new_quantities)
    comparisons: list[ShadowQuantityComparison] = []

    for semantic_key in sorted(set(legacy) | set(new)):
        legacy_row = legacy.get(semantic_key)
        new_row = new.get(semantic_key)

        if legacy_row is None and new_row is not None:
            comparisons.append(
                ShadowQuantityComparison(
                    family=new_row.family,
                    semantic_key=semantic_key,
                    legacy_quantity_id=None,
                    new_quantity_id=new_row.quantity_id,
                    legacy_value=None,
                    new_value=None if new_row.abstained else new_row.value,
                    unit=canonical_shadow_unit(new_row.unit),
                    absolute_delta=None,
                    relative_delta=None,
                    status="new_abstained" if new_row.abstained else "new_only",
                    new_engine_abstained=new_row.abstained,
                    reason_codes=(
                        "new_engine_abstained",
                    ) if new_row.abstained else ("legacy_quantity_missing",),
                )
            )
            continue

        if legacy_row is not None and new_row is None:
            comparisons.append(
                ShadowQuantityComparison(
                    family=legacy_row.trade_type,
                    semantic_key=semantic_key,
                    legacy_quantity_id=f"legacy:{semantic_key}",
                    new_quantity_id=None,
                    legacy_value=legacy_row.quantity,
                    new_value=None,
                    unit=canonical_shadow_unit(legacy_row.unit),
                    absolute_delta=None,
                    relative_delta=None,
                    status="legacy_only",
                    new_engine_abstained=False,
                    reason_codes=("new_quantity_missing",),
                )
            )
            continue

        assert legacy_row is not None and new_row is not None
        legacy_unit = canonical_shadow_unit(legacy_row.unit)
        new_unit = canonical_shadow_unit(new_row.unit)

        if new_row.abstained:
            comparisons.append(
                ShadowQuantityComparison(
                    family=new_row.family,
                    semantic_key=semantic_key,
                    legacy_quantity_id=f"legacy:{semantic_key}",
                    new_quantity_id=new_row.quantity_id,
                    legacy_value=legacy_row.quantity,
                    new_value=None,
                    unit=new_unit,
                    absolute_delta=None,
                    relative_delta=None,
                    status="new_abstained",
                    new_engine_abstained=True,
                    reason_codes=("new_engine_abstained",),
                )
            )
            continue

        if legacy_unit != new_unit:
            comparisons.append(
                ShadowQuantityComparison(
                    family=new_row.family,
                    semantic_key=semantic_key,
                    legacy_quantity_id=f"legacy:{semantic_key}",
                    new_quantity_id=new_row.quantity_id,
                    legacy_value=legacy_row.quantity,
                    new_value=new_row.value,
                    unit=f"legacy:{legacy_unit}|new:{new_unit}",
                    absolute_delta=None,
                    relative_delta=None,
                    status="unit_mismatch",
                    new_engine_abstained=False,
                    reason_codes=("unit_mismatch",),
                )
            )
            continue

        legacy_value = float(legacy_row.quantity)
        new_value = float(new_row.value)
        absolute_delta = abs(new_value - legacy_value)
        if legacy_value == 0.0:
            relative_delta = 0.0 if new_value == 0.0 else None
        else:
            relative_delta = absolute_delta / abs(legacy_value)
        agrees = math.isclose(new_value, legacy_value, rel_tol=0.0, abs_tol=1e-9)
        comparisons.append(
            ShadowQuantityComparison(
                family=new_row.family,
                semantic_key=semantic_key,
                legacy_quantity_id=f"legacy:{semantic_key}",
                new_quantity_id=new_row.quantity_id,
                legacy_value=legacy_value,
                new_value=new_value,
                unit=legacy_unit,
                absolute_delta=absolute_delta,
                relative_delta=relative_delta,
                status="agree" if agrees else "differ",
                new_engine_abstained=False,
                reason_codes=(
                    "exact_numeric_match",
                ) if agrees else ("numeric_difference",),
            )
        )

    return tuple(comparisons)


@dataclass(frozen=True)
class ShadowRunResult:
    """Frozen, gold-free artifact containing both engine outputs and their comparison."""

    result_id: str
    runner_version: str
    source_sha256: str
    pages: Optional[tuple[int, ...]]
    legacy_output: LegacyExtractionResult
    new_engine_id: str
    new_engine_version: str
    new_bundle_id: str
    new_output: tuple[QuantityEvidence, ...]
    comparisons: tuple[ShadowQuantityComparison, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "runner_version": self.runner_version,
            "source_sha256": self.source_sha256,
            "pages": list(self.pages) if self.pages is not None else None,
            "legacy_output": self.legacy_output.to_dict(),
            "new_engine": {
                "engine_id": self.new_engine_id,
                "engine_version": self.new_engine_version,
                "bundle_id": self.new_bundle_id,
                "quantities": [quantity.to_dict() for quantity in self.new_output],
            },
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
        }


class GoldFreeShadowRunner:
    """Run legacy and new engines on one immutable source, then compare without gold."""

    def __init__(self, legacy_adapter: Optional[LegacyExtractorAdapter] = None) -> None:
        self._legacy_adapter = legacy_adapter or LegacyExtractorAdapter()

    def run(
        self,
        pdf_path: Path | str,
        new_engine: ShadowQuantityEngine,
        pages: Optional[Sequence[int]] = None,
    ) -> ShadowRunResult:
        source = Path(pdf_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"PDF file not found at: {source}")

        new_engine_id = str(getattr(new_engine, "engine_id", "") or "").strip()
        new_engine_version = str(getattr(new_engine, "engine_version", "") or "").strip()
        if not new_engine_id or not new_engine_version:
            raise ValueError("new shadow engine must expose non-empty engine_id and engine_version")

        source_hash = _sha256_file(source)
        legacy_output = self._legacy_adapter.extract(source, pages=pages)
        if legacy_output.source_sha256 != source_hash or _sha256_file(source) != source_hash:
            raise SourceMutationDuringShadowRunError(
                "source changed before the new engine could run; shadow result was discarded"
            )

        # Materialize the new engine output before the final source hash check so
        # a lazy generator cannot mutate the source after the integrity check.
        raw_new_output = new_engine.extract_quantities(source, pages=pages)
        new_output = tuple(raw_new_output)
        if _sha256_file(source) != source_hash:
            raise SourceMutationDuringShadowRunError(
                "source changed while the new engine was running; shadow result was discarded"
            )

        if not all(isinstance(quantity, QuantityEvidence) for quantity in new_output):
            raise TypeError("new shadow engine must return only QuantityEvidence records")
        new_output = tuple(
            sorted(
                new_output,
                key=lambda quantity: (
                    quantity.family,
                    quantity.semantic_key,
                    quantity.quantity_id,
                ),
            )
        )

        comparisons = compare_shadow_quantities(legacy_output, new_output)
        new_bundle_id = stable_contract_id(
            "new_bundle", [quantity.to_dict() for quantity in new_output]
        )
        normalized_pages = legacy_output.pages
        result_payload = {
            "runner_version": SHADOW_RUNNER_VERSION,
            "source_sha256": source_hash,
            "pages": list(normalized_pages) if normalized_pages is not None else None,
            "legacy_output": legacy_output.to_dict(),
            "new_engine_id": new_engine_id,
            "new_engine_version": new_engine_version,
            "new_bundle_id": new_bundle_id,
            "new_output": [quantity.to_dict() for quantity in new_output],
            "comparisons": [comparison.to_dict() for comparison in comparisons],
        }
        result_id = stable_contract_id("shadow_run", result_payload)

        return ShadowRunResult(
            result_id=result_id,
            runner_version=SHADOW_RUNNER_VERSION,
            source_sha256=source_hash,
            pages=normalized_pages,
            legacy_output=legacy_output,
            new_engine_id=new_engine_id,
            new_engine_version=new_engine_version,
            new_bundle_id=new_bundle_id,
            new_output=new_output,
            comparisons=comparisons,
        )


def save_shadow_run_json(result: ShadowRunResult, output_path: Path | str) -> Path:
    """Atomically persist one already-frozen shadow result."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    payload = json.dumps(result.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    return target
