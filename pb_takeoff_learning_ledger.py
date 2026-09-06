"""pb_takeoff_learning_ledger.py — PlanReader AI Takeoff, Error Taxonomy & Learning Ledger.

Implements:
  1. AI Draft Takeoff Flow: strictly provisional/draft takeoff candidates with explicit confidence,
     source region, uncertainty flags, and review requirements.
  2. Error Taxonomy: standardized taxonomy of 16 measurement and classification error reasons.
  3. Takeoff Learning Ledger: persistent audit trail of AI detections, app measurements,
     user corrections, and benchmark comparisons (future training dataset).
  4. Accuracy Report & Golden Plan Regression Matrix Generator.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pb_benchmark_runner import run_all_benchmarks


# ---------------------------------------------------------------------------
# Error Taxonomy
# ---------------------------------------------------------------------------

class ErrorTaxonomy(str, Enum):
    SCALE_ERROR = "scale_error"
    OCR_ERROR = "ocr_error"
    WRONG_DIMENSION_SELECTED = "wrong_dimension_selected"
    OPENING_MISSED = "opening_missed"
    OPENING_DOUBLE_COUNTED = "opening_double_counted"
    WALL_FALSE_POSITIVE = "wall_false_positive"
    WALL_MISSING = "wall_missing"
    FINISH_TAG_WRONG = "finish_tag_wrong"
    SCHEDULE_ROW_MISREAD = "schedule_row_misread"
    PROJECT_MISMATCH = "project_mismatch"
    WRONG_REVISION = "wrong_revision"
    HEIGHT_UNKNOWN = "height_unknown"
    RAKED_WALL_NOT_HANDLED = "raked_wall_not_handled"
    STAIR_AREA_COMPLEX = "stair_area_complex"
    FACTORY_FINISH_EXCLUDED = "factory_finish_excluded"
    SCOPE_RULE_WRONG = "scope_rule_wrong"


# ---------------------------------------------------------------------------
# AI Draft Takeoff Models
# ---------------------------------------------------------------------------

@dataclass
class AIDraftTakeoffRow:
    draft_id: str
    section: str
    location: str
    substrate: str
    finish_tag: str
    element: str
    unit: str
    detected_quantity: float
    confidence: float
    source_page: str
    source_region: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    reasoning_summary: str
    uncertainty_flags: List[str] = field(default_factory=list)
    requires_review: bool = True
    authority_status: str = "provisional"

    def __post_init__(self) -> None:
        if not math.isfinite(self.detected_quantity) or self.detected_quantity < 0.0:
            raise ValueError("Detected quantity must be non-negative finite number")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Takeoff Learning Ledger
# ---------------------------------------------------------------------------

@dataclass
class LearningLedgerEntry:
    entry_id: str
    benchmark_or_job_id: str
    object_id: str
    object_type: str  # "wall", "room", "opening", "surface", "ceiling", "gfa"
    ai_detected_value: Optional[float]
    planreader_measured_value: Optional[float]
    user_corrected_value: Optional[float]
    approved_final_value: Optional[float]
    source_page: str
    source_region: str
    error_reason: str  # from ErrorTaxonomy
    confidence_before: float
    confidence_after: float
    project_type: str  # "townhouse", "commercial", "high_rise", "tender"
    drawing_style: str  # "cad_vector", "raster_scan", "hybrid"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TakeoffLearningLedger:
    """Manages the correction ledger and accuracy metrics for model refinement."""

    def __init__(self, entries: Optional[List[LearningLedgerEntry]] = None):
        self.entries: List[LearningLedgerEntry] = list(entries or [])

    def record_correction(
        self,
        entry_id: str,
        benchmark_or_job_id: str,
        object_id: str,
        object_type: str,
        planreader_measured_value: Optional[float],
        user_corrected_value: float,
        source_page: str,
        error_reason: str,
        confidence_before: float = 0.60,
        confidence_after: float = 1.0,
        project_type: str = "townhouse",
        drawing_style: str = "cad_vector",
        ai_detected_value: Optional[float] = None,
        notes: str = "",
    ) -> LearningLedgerEntry:
        entry = LearningLedgerEntry(
            entry_id=entry_id,
            benchmark_or_job_id=benchmark_or_job_id,
            object_id=object_id,
            object_type=object_type,
            ai_detected_value=ai_detected_value,
            planreader_measured_value=planreader_measured_value,
            user_corrected_value=user_corrected_value,
            approved_final_value=user_corrected_value,
            source_page=source_page,
            source_region="",
            error_reason=error_reason,
            confidence_before=confidence_before,
            confidence_after=confidence_after,
            project_type=project_type,
            drawing_style=drawing_style,
            notes=notes,
        )
        self.entries.append(entry)
        return entry

    def get_top_error_reasons(self, limit: int = 5) -> List[Tuple[str, int]]:
        counts: Dict[str, int] = {}
        for e in self.entries:
            counts[e.error_reason] = counts.get(e.error_reason, 0) + 1
        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_counts[:limit]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_entries": len(self.entries),
            "top_error_reasons": self.get_top_error_reasons(),
            "entries": [e.to_dict() for e in self.entries],
        }

    def save_to_file(self, file_path: str | Path) -> None:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load_from_file(cls, file_path: str | Path) -> "TakeoffLearningLedger":
        path = Path(file_path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = []
        for d in data.get("entries", []):
            entries.append(LearningLedgerEntry(**d))
        return cls(entries)


# ---------------------------------------------------------------------------
# Golden Plan Accuracy Report Generator
# ---------------------------------------------------------------------------

def generate_golden_plan_accuracy_report(
    benchmark_dir: str | Path = "benchmarks/plans",
    output_dir: str | Path = "benchmark_results",
    ledger: Optional[TakeoffLearningLedger] = None,
    results: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Execute benchmark matrix and produce benchmark_results/accuracy_report.md."""
    b_dir = Path(benchmark_dir)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Run all benchmarks if results not pre-supplied
    if results is None:
        results = run_all_benchmarks(b_dir, out_dir)

    total_expected = 0
    total_exact = 0
    total_within_tol = 0
    total_outside_tol = 0
    total_missing = 0
    total_blocked = 0
    total_provisional = 0

    benchmark_summaries = []

    for r in results:
        b_id = r.benchmark_id
        matched = r.comparison_allowed
        summary = r.summary or {}

        q_count = summary.get("total_expected_quantities", len(r.quantities_compared))
        total_expected += q_count

        exact = summary.get("exact_match_count", 0)
        within = summary.get("within_tolerance_count", 0)
        outside = summary.get("outside_tolerance_count", 0)
        missing = summary.get("missing_count", 0)
        prov = summary.get("provisional_count", 0)

        total_exact += exact
        total_within_tol += within
        total_outside_tol += outside
        total_missing += missing
        total_provisional += prov

        if not matched:
            total_blocked += 1
            status_text = f"BLOCKED ({r.rejection_reason or 'Mismatch'})"
        else:
            status_text = "VERIFIED / BENCHMARKED"

        pname = r.project_identity.get("project_name") or b_id
        errs = [r.rejection_reason] if r.rejection_reason and r.rejection_reason != "project_identity_confirmed" else []

        benchmark_summaries.append({
            "benchmark_id": b_id,
            "project_name": pname,
            "status": status_text,
            "matched": matched,
            "expected_quantities_count": q_count,
            "exact_matches": exact,
            "within_tolerance": within,
            "provisional_count": prov,
            "error_reasons": errs,
        })

    # Accuracy percentage: percentage of non-blocked items within tolerance or exact
    evaluated_count = total_expected if total_expected > 0 else 1
    passed_count = total_exact + total_within_tol
    accuracy_pct = round((passed_count / evaluated_count) * 100.0, 1)
    readiness_pct = round(((total_expected - total_provisional) / evaluated_count) * 100.0, 1) if total_expected > 0 else 0.0

    top_errors = ledger.get_top_error_reasons() if ledger else [
        (ErrorTaxonomy.PROJECT_MISMATCH.value, total_blocked),
        (ErrorTaxonomy.SCALE_ERROR.value, 0),
        (ErrorTaxonomy.HEIGHT_UNKNOWN.value, 0),
    ]

    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_benchmarks_evaluated": len(results),
        "total_expected_quantities": total_expected,
        "exact_matches": total_exact,
        "within_tolerance": total_within_tol,
        "outside_tolerance": total_outside_tol,
        "missing": total_missing,
        "blocked": total_blocked,
        "provisional": total_provisional,
        "accuracy_percentage": accuracy_pct,
        "commercial_readiness_percentage": readiness_pct,
        "top_error_reasons": top_errors,
        "benchmarks": benchmark_summaries,
        "recommended_next_fixes": [
            "Maintain project identity matching gate to keep cross-project takeoffs blocked.",
            "Enforce AS 4041 opening deductions (>0.5 m2 deduct, <=0.5 m2 do not) across all wall takeoff paths.",
            "Promote provisional geometry to firm only upon explicit estimator approval.",
            "Publish only firm, verified quantities with non-stale preflight fingerprints to JobHub.",
        ],
    }

    # Format Markdown Report
    md_lines = [
        "# PlanReader Golden Plan Accuracy & Regression Report",
        "",
        f"**Generated**: {report_data['generated_at']}  ",
        f"**Benchmarks Evaluated**: {len(results)}  ",
        f"**Accuracy Score**: {accuracy_pct}%  ",
        f"**Commercial Readiness**: {readiness_pct}%  ",
        "",
        "---",
        "",
        "## Summary Metrics",
        "",
        "| Metric | Count | Description |",
        "|---|---|---|",
        f"| Total Expected Quantities | {total_expected} | Benchmark baseline items |",
        f"| Exact Matches | {total_exact} | 0% variance against benchmark |",
        f"| Within Tolerance | {total_within_tol} | Within acceptable tolerance threshold |",
        f"| Outside Tolerance | {total_outside_tol} | Variance exceeds tolerance |",
        f"| Missing Items | {total_missing} | Expected items not extracted |",
        f"| Blocked Benchmarks | {total_blocked} | Correctly rejected mismatched projects |",
        f"| Provisional Items | {total_provisional} | Reference/provisional quantities |",
        "",
        "---",
        "",
        "## Benchmark Manifest Matrix",
        "",
        "| Benchmark ID | Project Name | Status | Expected Items | Exact | Within Tol |",
        "|---|---|---|---|---|---|",
    ]

    for b in benchmark_summaries:
        md_lines.append(
            f"| `{b['benchmark_id']}` | {b['project_name']} | **{b['status']}** | {b['expected_quantities_count']} | {b['exact_matches']} | {b['within_tolerance']} |"
        )

    md_lines.extend([
        "",
        "---",
        "",
        "## Top Error Taxonomy Drivers",
        "",
    ])

    for err, count in top_errors:
        md_lines.append(f"- **`{err}`**: {count} occurrence(s)")

    md_lines.extend([
        "",
        "---",
        "",
        "## Recommended Next Fixes",
        "",
    ])
    for fix in report_data["recommended_next_fixes"]:
        md_lines.append(f"1. {fix}")

    md_content = "\n".join(md_lines) + "\n"

    # Write files
    (out_dir / "accuracy_report.md").write_text(md_content, encoding="utf-8")
    (out_dir / "accuracy_report.json").write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    return report_data
