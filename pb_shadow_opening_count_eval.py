"""Evaluator-side scoring for the shadow opening-count provider.

The provider and GoldFreeShadowRunner stay gold-free.  This module may load
expected BOQ files and item mappings only AFTER new QuantityEvidence has been
frozen.  It does not activate NEW_SELECTIVE or NEW_AUTHORITATIVE.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Optional, Sequence

from pb_benchmark_runner import resolve_file_path
from pb_gold_free_shadow_runner import GoldFreeShadowRunner
from pb_migration_contracts import QuantityEvidence
from pb_opening_tag_normalization import normalize_opening_tag
from pb_shadow_opening_count_gate import (
    OPENING_COUNT_AUTHORITY_RECOMMENDATION,
    OPENING_COUNT_AUTHORITY_STATE,
    OPENING_COUNT_FAMILIES,
    evaluate_opening_count_migration_gate,
)
from pb_shadow_opening_count_provider import (
    ShadowOpeningCountProvider,
    probe_opening_evidence_pages,
    resolve_opening_identity,
)


HEADLINE_DEVELOPMENT_BENCHMARKS = (
    "tenders_ke_kstvet_cbc_classroom",
    "tenders_ke_murera_science_lab",
    "tenders_ke_ghazi_science_lab",
    "tenders_ke_umma_hostels",
    "tenders_ke_lamu_ishakani_ecd_classrooms",
)

COUNT_UNITS = frozenset({"NO", "NO.", "NOS", "NOS.", "EA", "EACH", "NR"})
AGGREGATE_OPENING_KEYS = frozenset({"steel_casement_windows", "doors_complete"})
FAMILY_TOTAL_KEYS = frozenset({"door_total", "window_total"})
_HOLD_OUT_ID = "tenders_ke_olv_laboratory_complex"
_WD_KEY_RE = re.compile(r"^WD\d{1,3}$", re.IGNORECASE)


@dataclass(frozen=True)
class EligibleOpeningItem:
    benchmark_id: str
    item_id: str
    semantic_key: str
    expected_quantity: float
    unit: str
    description: str
    category: str


def _public_tender_dir(benchmark_id: str) -> Path:
    return Path("benchmarks/public_tenders") / benchmark_id


def _is_opening_identity(key: str) -> bool:
    if key in AGGREGATE_OPENING_KEYS:
        return True
    if key in FAMILY_TOTAL_KEYS:
        return False
    if normalize_opening_tag(key) is not None:
        return True
    return resolve_opening_identity(key, trade_type="windows") is not None or bool(_WD_KEY_RE.fullmatch(key))


def _is_well_formed_type_mark(key: str) -> bool:
    if key in AGGREGATE_OPENING_KEYS or key in FAMILY_TOTAL_KEYS:
        return False
    if normalize_opening_tag(key) is not None:
        return True
    return bool(_WD_KEY_RE.fullmatch(key))


def _is_family_aggregate(item: QuantityEvidence) -> bool:
    return (
        item.semantic_key in FAMILY_TOTAL_KEYS
        or item.metadata.get("count_kind") == "family_aggregate"
        or item.formula == "sum_of_authoritative_type_counts"
    )


def _looks_like_opening_count(description: str, unit: str, mapped: str) -> bool:
    if str(unit or "").strip().upper() not in COUNT_UNITS:
        return False
    if mapped and _is_opening_identity(mapped):
        return True
    text = (description or "").lower()
    if any(token in text for token in ("ironmongery", "hinge", "lockset", "butt hinge")):
        return False
    return bool(
        ("window" in text or "door" in text or "casement" in text)
        and "chalkboard" not in text
        and "pillar" not in text
    )


def load_eligible_opening_items(benchmark_id: str) -> tuple[EligibleOpeningItem, ...]:
    """Load gold opening-count items. Evaluator-only; never called by the provider."""
    if benchmark_id == _HOLD_OUT_ID:
        raise RuntimeError("sealed holdout scoring is out of scope for this shadow family")
    root = _public_tender_dir(benchmark_id)
    boq = json.loads((root / "expected_boq_summary.json").read_text(encoding="utf-8"))
    rules = json.loads((root / "benchmark_rules.json").read_text(encoding="utf-8"))
    mappings = dict(rules.get("item_mappings") or {})
    items: list[EligibleOpeningItem] = []
    for raw in boq.get("sample_measurable_items") or []:
        item_id = str(raw.get("item_id") or "")
        mapped = str(mappings.get(item_id) or "")
        if not _looks_like_opening_count(str(raw.get("description") or ""), str(raw.get("unit") or ""), mapped):
            continue
        key = mapped or item_id
        items.append(
            EligibleOpeningItem(
                benchmark_id=benchmark_id,
                item_id=item_id,
                semantic_key=key,
                expected_quantity=float(raw.get("expected_quantity")),
                unit=str(raw.get("unit") or "NO"),
                description=str(raw.get("description") or ""),
                category=str(raw.get("category") or ""),
            )
        )
    return tuple(items)


def _answered(quantities: Sequence[QuantityEvidence]) -> tuple[QuantityEvidence, ...]:
    return tuple(
        item
        for item in quantities
        if item.family in OPENING_COUNT_FAMILIES and not item.abstained and item.value is not None
    )


def _abstained(quantities: Sequence[QuantityEvidence]) -> tuple[QuantityEvidence, ...]:
    return tuple(
        item
        for item in quantities
        if item.family in OPENING_COUNT_FAMILIES and item.abstained
    )


def score_frozen_quantities(
    *,
    benchmark_id: str,
    frozen_quantities: Sequence[QuantityEvidence],
    eligible: Sequence[EligibleOpeningItem],
    conflicts: Sequence[Mapping[str, Any]] = (),
    ambiguous_marks: Sequence[str] = (),
    duplicate_observations: int = 0,
    comparisons: Sequence[Mapping[str, Any]] = (),
    source_status: str = "ok",
) -> dict[str, Any]:
    """Score already-frozen quantities against gold. Does not run extraction."""
    answered_all = _answered(frozen_quantities)
    abstained = _abstained(frozen_quantities)
    gold_by_key = {item.semantic_key: item for item in eligible}
    aggregates = [item for item in answered_all if _is_family_aggregate(item)]
    type_answers = [item for item in answered_all if not _is_family_aggregate(item)]
    answered_keys = [item.semantic_key for item in type_answers]
    duplicate_answered = len(answered_keys) - len(set(answered_keys))

    matched = [item for item in type_answers if item.semantic_key in gold_by_key]
    extra_valid = [
        item
        for item in type_answers
        if item.semantic_key not in gold_by_key and _is_well_formed_type_mark(item.semantic_key)
    ]
    hallucinations = [
        item
        for item in type_answers
        if item.semantic_key not in gold_by_key and not _is_well_formed_type_mark(item.semantic_key)
    ]
    answered = matched
    exact = [
        item
        for item in matched
        if math.isclose(float(item.value), gold_by_key[item.semantic_key].expected_quantity, abs_tol=1e-9)
    ]
    missing_provenance = [
        item
        for item in answered
        if not item.evidence_ids and not item.input_entity_ids
    ]
    conflict_leaks = [
        item
        for item in answered
        if any(
            str(conflict.get("tag")) == item.semantic_key
            for conflict in conflicts
        )
        or "conflict" in " ".join(item.reason_codes).lower()
    ]
    fake_identities = [
        item
        for item in answered
        if item.metadata.get("count_kind") == "dimension_only_identity"
        or item.formula == "dimension_inferred_identity"
    ]

    eligible_n = len(eligible)
    answered_n = len(answered)
    exact_n = len(exact)
    identity_n = len(matched)
    precision_den = identity_n + len(hallucinations)
    precision = (identity_n / precision_den) if precision_den else 0.0
    exact_rate = (exact_n / answered_n) if answered_n else 0.0
    recall = (exact_n / eligible_n) if eligible_n else 0.0
    coverage = (answered_n / eligible_n) if eligible_n else 0.0

    opening_comparisons = [
        row
        for row in comparisons
        if str(row.get("semantic_key") or "") not in FAMILY_TOTAL_KEYS
        and (
            _is_opening_identity(str(row.get("semantic_key") or ""))
            or str(row.get("family") or "") in OPENING_COUNT_FAMILIES
        )
    ]
    agree = sum(1 for row in opening_comparisons if row.get("status") == "agree")
    compared = len(opening_comparisons)
    by_authority: dict[str, int] = {}
    by_formula: dict[str, int] = {}
    for item in answered:
        by_authority[item.authority] = by_authority.get(item.authority, 0) + 1
        by_formula[item.formula] = by_formula.get(item.formula, 0) + 1

    return {
        "benchmark_id": benchmark_id,
        "source_status": source_status,
        "eligible_opening_count_items": eligible_n,
        "answered": answered_n,
        "abstained": len(abstained),
        "coverage": coverage,
        "precision_on_answered_identities": precision,
        "exact_correctness_on_answered_counts": exact_rate,
        "recall": recall,
        "hallucinations": len(hallucinations),
        "duplicate_counts": duplicate_answered,
        "critical_duplicate_counts": duplicate_answered,
        "conflicts": len(conflicts),
        "ambiguous_identities": len(tuple(ambiguous_marks)),
        "legacy_new_agreement": {
            "agree": agree,
            "compared": compared,
            "rate": (agree / compared) if compared else None,
        },
        "accepted_answered_count": answered_n,
        "accepted_missing_provenance": len(missing_provenance),
        "conflict_not_fail_closed": len(conflict_leaks),
        "dimension_derived_fake_identities": len(fake_identities),
        "by_authority": by_authority,
        "by_formula": by_formula,
        "answered_keys": [item.semantic_key for item in answered],
        "exact_keys": [item.semantic_key for item in exact],
        "hallucinated_keys": [item.semantic_key for item in hallucinations],
        "extra_valid_type_marks": len(extra_valid),
        "extra_valid_keys": [item.semantic_key for item in extra_valid],
        "family_aggregates": len(aggregates),
        "family_aggregate_keys": [item.semantic_key for item in aggregates],
        "eligible_keys": [item.semantic_key for item in eligible],
        "abstained_keys": [item.semantic_key for item in abstained],
        "duplicate_observations_suppressed": duplicate_observations,
    }


def _load_manifest_pdf(benchmark_id: str) -> Optional[Path]:
    manifest_path = _public_tender_dir(benchmark_id) / "source_manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return resolve_file_path(manifest.get("source_pdf"))


def run_project_shadow(
    benchmark_id: str,
    *,
    runner: Optional[GoldFreeShadowRunner] = None,
    provider: Optional[ShadowOpeningCountProvider] = None,
) -> dict[str, Any]:
    """Extract and freeze new quantities, then join gold evaluator-side only."""
    pdf_path = _load_manifest_pdf(benchmark_id)
    frozen: tuple[QuantityEvidence, ...] = ()
    bundle = None
    pages: Optional[list[int]] = None
    shadow = None
    source_status = "SOURCE_UNAVAILABLE"
    if pdf_path is not None:
        engine = provider or ShadowOpeningCountProvider()
        import fitz

        doc = fitz.open(pdf_path)
        try:
            pages = probe_opening_evidence_pages(doc)
        finally:
            doc.close()

        bundle = engine.extract_bundle(pdf_path, pages=pages or None)
        frozen = tuple(bundle.quantities)
        shadow = (runner or GoldFreeShadowRunner()).run(pdf_path, engine, pages=pages or None)
        source_status = "ok"

    eligible = load_eligible_opening_items(benchmark_id)
    metrics = score_frozen_quantities(
        benchmark_id=benchmark_id,
        frozen_quantities=frozen,
        eligible=eligible,
        conflicts=bundle.conflicts if bundle is not None else (),
        ambiguous_marks=bundle.ambiguous_marks if bundle is not None else (),
        duplicate_observations=bundle.duplicate_observations if bundle is not None else 0,
        comparisons=[row.to_dict() for row in shadow.comparisons] if shadow is not None else (),
        source_status=source_status,
    )
    if bundle is None:
        return {
            "benchmark_id": benchmark_id,
            "source_status": source_status,
            "frozen_quantities": [],
            "metrics": metrics,
        }
    return {
        "benchmark_id": benchmark_id,
        "source_status": source_status,
        "source_pdf": str(pdf_path),
        "pages": pages,
        "shadow_result_id": shadow.result_id if shadow is not None else None,
        "frozen_quantities": [item.to_dict() for item in frozen],
        "entity_evidence": [item.to_dict() for item in bundle.entity_evidence],
        "canonical_openings": [item.to_dict() for item in bundle.canonical_openings],
        "diagnostics": dict(bundle.diagnostics),
        "metrics": metrics,
    }


def _sum_int(rows: Sequence[Mapping[str, Any]], key: str) -> int:
    return sum(int(row.get(key) or 0) for row in rows)


def aggregate_development_metrics(project_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = _sum_int(project_rows, "eligible_opening_count_items")
    answered = _sum_int(project_rows, "answered")
    identity = 0
    exact = 0
    for row in project_rows:
        answered_n = int(row.get("answered") or 0)
        identity += int(round(float(row.get("precision_on_answered_identities") or 0.0) * answered_n))
        exact += int(round(float(row.get("exact_correctness_on_answered_counts") or 0.0) * answered_n))
    precision = (identity / answered) if answered else 0.0
    exact_rate = (exact / answered) if answered else 0.0
    recall = (exact / eligible) if eligible else 0.0
    coverage = (answered / eligible) if eligible else 0.0
    agree = sum(int((row.get("legacy_new_agreement") or {}).get("agree") or 0) for row in project_rows)
    compared = sum(int((row.get("legacy_new_agreement") or {}).get("compared") or 0) for row in project_rows)
    aggregated = {
        "eligible_opening_count_items": eligible,
        "answered": answered,
        "abstained": _sum_int(project_rows, "abstained"),
        "coverage": coverage,
        "precision_on_answered_identities": precision,
        "exact_correctness_on_answered_counts": exact_rate,
        "recall": recall,
        "hallucinations": _sum_int(project_rows, "hallucinations"),
        "extra_valid_type_marks": _sum_int(project_rows, "extra_valid_type_marks"),
        "family_aggregates": _sum_int(project_rows, "family_aggregates"),
        "duplicate_counts": _sum_int(project_rows, "duplicate_counts"),
        "critical_duplicate_counts": _sum_int(project_rows, "critical_duplicate_counts"),
        "conflicts": _sum_int(project_rows, "conflicts"),
        "ambiguous_identities": _sum_int(project_rows, "ambiguous_identities"),
        "legacy_new_agreement": {
            "agree": agree,
            "compared": compared,
            "rate": (agree / compared) if compared else None,
        },
        "accepted_answered_count": answered,
        "accepted_missing_provenance": _sum_int(project_rows, "accepted_missing_provenance"),
        "conflict_not_fail_closed": _sum_int(project_rows, "conflict_not_fail_closed"),
        "dimension_derived_fake_identities": _sum_int(project_rows, "dimension_derived_fake_identities"),
        "by_project": {row["benchmark_id"]: row for row in project_rows},
        "by_authority": {},
        "by_formula": {},
    }
    for row in project_rows:
        for key, value in (row.get("by_authority") or {}).items():
            aggregated["by_authority"][key] = aggregated["by_authority"].get(key, 0) + int(value)
        for key, value in (row.get("by_formula") or {}).items():
            aggregated["by_formula"][key] = aggregated["by_formula"].get(key, 0) + int(value)
    return aggregated


def run_development_shadow_report(
    *,
    benchmark_ids: Sequence[str] = HEADLINE_DEVELOPMENT_BENCHMARKS,
) -> dict[str, Any]:
    projects = [run_project_shadow(benchmark_id) for benchmark_id in benchmark_ids]
    metrics_rows = [project["metrics"] for project in projects]
    aggregated = aggregate_development_metrics(metrics_rows)
    gate = evaluate_opening_count_migration_gate(aggregated)
    return {
        "family": "opening_count",
        "authority_state": OPENING_COUNT_AUTHORITY_STATE,
        "authoritative_engine": "legacy",
        "gold_joined_after_freeze": True,
        "holdout_scored": False,
        "projects": projects,
        "metrics": aggregated,
        "migration_gate": gate,
        "recommendation": OPENING_COUNT_AUTHORITY_RECOMMENDATION,
    }
