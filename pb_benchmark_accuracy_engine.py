"""pb_benchmark_accuracy_engine.py — Public Tender Benchmark Accuracy Evaluation Engine.

PR F.3: Independent Public Tender Accuracy Benchmarking Engine.
Executes PlanReader geometry/quantity extraction against external public tender packages,
compares extracted quantities against BOQ expected quantities across multiple tolerance tiers,
detects missed and hallucinated items, excludes non-physical preliminaries and provisional sums,
and outputs structured JSON and human-readable Markdown accuracy reports.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import fitz  # PyMuPDF

from pb_public_tender_benchmark import (
    BOQLineCategory,
    PublicTenderBenchmark,
    classify_boq_line,
    compare_tender_drawings_and_boq,
    list_available_public_tender_benchmarks,
)
from pb_benchmark_runner import resolve_file_path


from pb_planreader_pdf_extractor import (
    ExtractedPrediction,
    GenericPlanReaderExtractor,
)


class ItemMatchStatus(str, Enum):
    """Categorisation of comparison between extracted quantity and BOQ expected value."""

    EXACT_MATCH = "exact_match"
    WITHIN_5_PERCENT = "within_5_percent"
    WITHIN_10_PERCENT = "within_10_percent"
    WITHIN_20_PERCENT = "within_20_percent"
    GROSS_MISMATCH = "gross_mismatch"  # > 20% divergence
    MISSED_IN_EXTRACTION = "missed_in_extraction"  # In BOQ, not extracted
    HALLUCINATED_ITEM = "hallucinated_item"  # Extracted, not in BOQ
    EXCLUDED_PRELIMINARY = "excluded_preliminary"  # Overhead/preliminary
    EXCLUDED_PROVISIONAL = "excluded_provisional"  # Provisional sum
    EXCLUDED_NON_ARCHITECTURAL = "excluded_non_architectural"  # MEP/civil


@dataclass
class ItemComparisonResult:
    """Detailed comparison outcome for a single line item."""

    item_id: str
    description: str
    category: str
    expected_quantity: Optional[float]
    extracted_quantity: Optional[float]
    unit: Optional[str]
    delta: Optional[float]
    pct_error: Optional[float]
    status: ItemMatchStatus
    tolerance_tier: str  # "exact", "5%", "10%", "20%", "gross", "missed", "hallucinated", "excluded"
    drawing_sheet: Optional[str] = None
    drawing_page: Optional[int] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "description": self.description,
            "category": self.category,
            "expected_quantity": self.expected_quantity,
            "extracted_quantity": self.extracted_quantity,
            "unit": self.unit,
            "delta": self.delta,
            "pct_error": self.pct_error,
            "status": self.status.value,
            "tolerance_tier": self.tolerance_tier,
            "drawing_sheet": self.drawing_sheet,
            "drawing_page": self.drawing_page,
            "notes": self.notes,
        }


@dataclass
class BenchmarkAccuracyReport:
    """Comprehensive benchmark accuracy evaluation report."""

    benchmark_id: str
    timestamp: str
    project_name: str
    organization: str
    tender_reference: str
    status: str  # "scored", "candidate_unscored", "candidate_unverified", "verified_scope_mismatch", "failed_closed"
    is_scored: bool
    is_headline_eligible: bool = True
    source_pdf: Optional[str] = None
    total_boq_items: int = 0
    total_measurable_expected: int = 0
    total_items_compared: int = 0
    exact_matches: int = 0
    within_5_percent: int = 0
    within_10_percent: int = 0
    within_20_percent: int = 0
    gross_mismatches: int = 0
    missed_items: int = 0
    hallucinated_items: int = 0
    preliminaries_excluded: int = 0
    provisional_sums_excluded: int = 0
    non_architectural_excluded: int = 0
    overall_accuracy_percentage: Optional[float] = None
    strict_exact_accuracy_percentage: Optional[float] = None
    item_results: List[ItemComparisonResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "timestamp": self.timestamp,
            "project_name": self.project_name,
            "organization": self.organization,
            "tender_reference": self.tender_reference,
            "status": self.status,
            "is_scored": self.is_scored,
            "is_headline_eligible": self.is_headline_eligible,
            "source_pdf": self.source_pdf,
            "summary": {
                "total_boq_items": self.total_boq_items,
                "total_measurable_expected": self.total_measurable_expected,
                "total_items_compared": self.total_items_compared,
                "exact_matches": self.exact_matches,
                "within_5_percent": self.within_5_percent,
                "within_10_percent": self.within_10_percent,
                "within_20_percent": self.within_20_percent,
                "gross_mismatches": self.gross_mismatches,
                "missed_items": self.missed_items,
                "hallucinated_items": self.hallucinated_items,
                "preliminaries_excluded": self.preliminaries_excluded,
                "provisional_sums_excluded": self.provisional_sums_excluded,
                "non_architectural_excluded": self.non_architectural_excluded,
                "overall_accuracy_percentage": self.overall_accuracy_percentage,
                "strict_exact_accuracy_percentage": self.strict_exact_accuracy_percentage,
            },
            "item_results": [it.to_dict() for it in self.item_results],
            "errors": self.errors,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Render a formatted GitHub-Flavored Markdown report."""
        lines = []
        lines.append(f"# PlanReader Accuracy Evaluation Report: {self.project_name}")
        lines.append("")
        lines.append(f"- **Benchmark ID**: `{self.benchmark_id}`")
        lines.append(f"- **Organization**: {self.organization}")
        lines.append(f"- **Tender Reference**: `{self.tender_reference}`")
        lines.append(f"- **Evaluation Timestamp**: `{self.timestamp}`")
        lines.append(f"- **Evaluation Status**: `{self.status}`")
        lines.append(f"- **Source PDF**: `{self.source_pdf or 'None / Not supplied'}`")
        lines.append("")

        if not self.is_scored:
            lines.append("> [!WARNING]")
            if self.status == "candidate_unverified":
                lines.append(
                    "> **Evaluation Blocked**: This benchmark is an unverified candidate seed. "
                    "Unverified candidate seeds are barred from contributing to accuracy metrics."
                )
            else:
                lines.append(
                    "> **Unscored Benchmark**: No prediction inputs or source drawings were evaluated. "
                    "Accuracy score is undefined (`None`)."
                )
            if self.errors:
                lines.append("> ")
                for err in self.errors:
                    lines.append(f"> - Error: `{err}`")
            lines.append("")
            return "\n".join(lines)

        if not self.is_headline_eligible:
            lines.append("> [!NOTE]")
            lines.append(
                "> **Scope Divergence Stress Test**: This benchmark package represents a real-world scope divergence "
                "between drawing set and BOQ (e.g. facility-wide drawing vs single wing/unit). "
                "It is retained as an external stress test and is excluded from primary headline accuracy scoring."
            )
            lines.append("")

        lines.append("## 1. Executive Headline Metrics")
        lines.append("")
        acc_str = f"{self.overall_accuracy_percentage:.1f}%" if self.overall_accuracy_percentage is not None else "N/A"
        exact_str = f"{self.strict_exact_accuracy_percentage:.1f}%" if self.strict_exact_accuracy_percentage is not None else "N/A"

        lines.append("| Metric | Value | Description |")
        lines.append("| :--- | :--- | :--- |")
        lines.append(f"| **Overall Accuracy (<= 5% tol)** | **`{acc_str}`** | Combined exact matches and within 5% tolerance |")
        lines.append(f"| **Strict Exact Accuracy** | **`{exact_str}`** | Zero-tolerance exact numerical matches only |")
        lines.append(f"| Total BOQ Items | `{self.total_boq_items}` | Complete tender Bill of Quantities schedule lines |")
        lines.append(f"| Measurable Items Evaluated | `{self.total_measurable_expected}` | Physical architectural takeoff baseline |")
        lines.append(f"| Total Items Compared | `{self.total_items_compared}` | Measurable expected + hallucinated items |")
        lines.append(f"| Exact Matches | `{self.exact_matches}` | Exactly matched quantities |")
        lines.append(f"| Within 5% Tolerance | `{self.within_5_percent}` | Area/length finishes within 5% tolerance |")
        lines.append(f"| Within 10% Tolerance | `{self.within_10_percent}` | Minor variations (5% to 10%) |")
        lines.append(f"| Within 20% Tolerance | `{self.within_20_percent}` | Moderate variations (10% to 20%) |")
        lines.append(f"| Gross Mismatches (> 20%) | `{self.gross_mismatches}` | Severe discrepancy requiring investigation |")
        lines.append(f"| Missed Items | `{self.missed_items}` | Measurable items present in BOQ but missing in extraction |")
        lines.append(f"| Hallucinated Items | `{self.hallucinated_items}` | Items extracted but absent from drawing / BOQ |")
        lines.append("")

        lines.append("## 2. Non-Penalized Exclusions")
        lines.append("")
        lines.append(
            "Contractor overheads, site preliminaries, and provisional budget allowances "
            "are excluded from physical geometric accuracy denominators by design:"
        )
        lines.append(f"- **Preliminaries Excluded**: `{self.preliminaries_excluded}`")
        lines.append(f"- **Provisional Sums Excluded**: `{self.provisional_sums_excluded}`")
        lines.append(f"- **Non-Architectural Excluded**: `{self.non_architectural_excluded}`")
        lines.append("")

        lines.append("## 3. Detailed Item Comparison Breakdown")
        lines.append("")
        lines.append("| Item ID | Description | Category | Expected | Extracted | Unit | Delta | % Error | Status | Drawing Trace |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        for it in self.item_results:
            exp_s = f"{it.expected_quantity:.2f}" if it.expected_quantity is not None else "-"
            ext_s = f"{it.extracted_quantity:.2f}" if it.extracted_quantity is not None else "-"
            delta_s = f"{it.delta:+.2f}" if it.delta is not None else "-"
            pct_s = f"{it.pct_error:.1f}%" if it.pct_error is not None else "-"
            trace_s = f"Sheet {it.drawing_sheet or 'N/A'} (p. {it.drawing_page or '?'})" if it.drawing_sheet or it.drawing_page else "-"
            lines.append(
                f"| `{it.item_id}` | {it.description} | `{it.category}` | {exp_s} | {ext_s} | {it.unit or '-'} | {delta_s} | {pct_s} | `{it.status.value}` | {trace_s} |"
            )

        lines.append("")

        if self.gross_mismatches > 0:
            lines.append("## 4. Gross Mismatches (> 20%)")
            lines.append("")
            for it in self.item_results:
                if it.status == ItemMatchStatus.GROSS_MISMATCH:
                    lines.append(f"- **`{it.item_id}`** ({it.description}): Expected `{it.expected_quantity}`, Extracted `{it.extracted_quantity}` ({it.pct_error:.1f}% error). {it.notes}")
            lines.append("")

        if self.missed_items > 0:
            lines.append("## 5. Missed Items")
            lines.append("")
            for it in self.item_results:
                if it.status == ItemMatchStatus.MISSED_IN_EXTRACTION:
                    lines.append(f"- **`{it.item_id}`** ({it.description}): Expected `{it.expected_quantity} {it.unit}` on Sheet `{it.drawing_sheet}`.")
            lines.append("")

        if self.hallucinated_items > 0:
            lines.append("## 6. Hallucinated Items")
            lines.append("")
            for it in self.item_results:
                if it.status == ItemMatchStatus.HALLUCINATED_ITEM:
                    lines.append(f"- **`{it.item_id}`** ({it.description}): Extracted `{it.extracted_quantity} {it.unit}` with no corresponding BOQ entry.")
            lines.append("")

        return "\n".join(lines)


@dataclass
class HeadlineAccuracyDashboard:
    """Consolidated headline accuracy dashboard aggregating all public tender benchmarks.

    Enforces strict headline accuracy standards:
    - Only benchmarks with verified 1:1 physical scope match (verified_scored_benchmark)
      contribute to the official headline accuracy metrics.
    - Verified packages with scope divergence (verified_scope_mismatch) are isolated as
      real-world stress tests and never dilute headline accuracy.
    - Candidate seeds (candidate_unverified) are tracked as pipeline inventory but
      completely excluded from accuracy metrics.
    """

    timestamp: str
    headline_overall_accuracy: Optional[float]
    headline_strict_exact_accuracy: Optional[float]
    total_headline_benchmarks: int
    total_headline_measurable_expected: int
    total_headline_items_compared: int
    total_headline_exact_matches: int
    total_headline_within_5_percent: int
    total_headline_within_10_percent: int
    total_headline_within_20_percent: int
    total_headline_gross_mismatches: int
    total_headline_missed_items: int
    total_headline_hallucinated_items: int
    total_preliminaries_excluded: int
    total_provisional_sums_excluded: int
    total_non_architectural_excluded: int
    total_stress_test_benchmarks: int
    total_candidate_seeds: int
    headline_reports: List[BenchmarkAccuracyReport] = field(default_factory=list)
    stress_test_reports: List[BenchmarkAccuracyReport] = field(default_factory=list)
    candidate_seed_reports: List[BenchmarkAccuracyReport] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert dashboard to serializable dictionary."""
        return {
            "timestamp": self.timestamp,
            "headline_metrics": {
                "overall_accuracy_percentage": self.headline_overall_accuracy,
                "strict_exact_accuracy_percentage": self.headline_strict_exact_accuracy,
                "total_headline_benchmarks": self.total_headline_benchmarks,
                "total_measurable_expected": self.total_headline_measurable_expected,
                "total_items_compared": self.total_headline_items_compared,
                "exact_matches": self.total_headline_exact_matches,
                "within_5_percent": self.total_headline_within_5_percent,
                "within_10_percent": self.total_headline_within_10_percent,
                "within_20_percent": self.total_headline_within_20_percent,
                "gross_mismatches": self.total_headline_gross_mismatches,
                "missed_items": self.total_headline_missed_items,
                "hallucinated_items": self.total_headline_hallucinated_items,
            },
            "non_penalized_exclusions": {
                "preliminaries_excluded": self.total_preliminaries_excluded,
                "provisional_sums_excluded": self.total_provisional_sums_excluded,
                "non_architectural_excluded": self.total_non_architectural_excluded,
            },
            "summary_counts": {
                "headline_benchmarks": self.total_headline_benchmarks,
                "stress_test_benchmarks": self.total_stress_test_benchmarks,
                "candidate_seeds": self.total_candidate_seeds,
                "total_registered": (
                    self.total_headline_benchmarks
                    + self.total_stress_test_benchmarks
                    + self.total_candidate_seeds
                ),
            },
            "headline_reports": [r.to_dict() for r in self.headline_reports],
            "stress_test_reports": [r.to_dict() for r in self.stress_test_reports],
            "candidate_seed_reports": [r.to_dict() for r in self.candidate_seed_reports],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize dashboard to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Generate human-readable Markdown dashboard report."""
        lines = [
            "# PlanReader Public Tender Benchmark — Executive Headline Accuracy Dashboard",
            "",
            f"**Generated**: `{self.timestamp}`",
            "",
        ]

        acc_str = (
            f"{self.headline_overall_accuracy:.1f}%"
            if self.headline_overall_accuracy is not None
            else "N/A"
        )
        exact_str = (
            f"{self.headline_strict_exact_accuracy:.1f}%"
            if self.headline_strict_exact_accuracy is not None
            else "N/A"
        )

        lines.append(
            f"> **Official Headline Accuracy**: **`{acc_str}`** across `{self.total_headline_benchmarks}` headline-verified public tender benchmark(s).  \n"
            f"> **Strict Exact Accuracy** (zero-tolerance): **`{exact_str}`**."
        )
        lines.append("")

        lines.append("## 1. Executive Headline Metrics (1:1 Material Scope Packages)")
        lines.append("")
        lines.append("| Metric | Value | Description |")
        lines.append("| :--- | :--- | :--- |")
        lines.append(
            f"| **Headline Overall Accuracy (<= 5% tol)** | **`{acc_str}`** | Combined exact matches and <= 5% tolerance across headline benchmarks |"
        )
        lines.append(
            f"| **Headline Strict Exact Accuracy** | **`{exact_str}`** | Zero-tolerance exact numerical matches across headline benchmarks |"
        )
        lines.append(
            f"| Scored Headline Benchmarks | `{self.total_headline_benchmarks}` | Verified packages with 1:1 physical drawing-to-BOQ scope match |"
        )
        lines.append(
            f"| Measurable Items Evaluated | `{self.total_headline_measurable_expected}` | Total expected architectural takeoff items |"
        )
        lines.append(
            f"| Total Items Compared (Denominator) | `{self.total_headline_items_compared}` | Expected items + hallucinated extra predictions across packages |"
        )
        lines.append(
            f"| Exact Matches | `{self.total_headline_exact_matches}` | Exactly matched quantities |"
        )
        lines.append(
            f"| Within 5% Tolerance | `{self.total_headline_within_5_percent}` | Minor variations within 5% tolerance |"
        )
        lines.append(
            f"| Within 10% Tolerance | `{self.total_headline_within_10_percent}` | Minor variations (5% to 10%) |"
        )
        lines.append(
            f"| Within 20% Tolerance | `{self.total_headline_within_20_percent}` | Moderate variations (10% to 20%) |"
        )
        lines.append(
            f"| Gross Mismatches (> 20%) | `{self.total_headline_gross_mismatches}` | Discrepancies exceeding 20% |"
        )
        lines.append(
            f"| Missed in Extraction | `{self.total_headline_missed_items}` | BOQ items missing from drawing predictions |"
        )
        lines.append(
            f"| Hallucinated Extra Predictions | `{self.total_headline_hallucinated_items}` | Predictions with no counterpart in BOQ |"
        )
        lines.append("")

        lines.append("## 2. Headline Benchmark Breakdown (1:1 Physical Scope Match)")
        lines.append("")
        lines.append(
            "| Benchmark ID | Project Name | Scope | Expected | Compared | Exact | <= 5% | Gross | Missed | Halluc. | Accuracy | Strict % | Status |"
        )
        lines.append(
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        )
        for r in self.headline_reports:
            r_acc = (
                f"{r.overall_accuracy_percentage:.1f}%"
                if r.overall_accuracy_percentage is not None
                else "N/A"
            )
            r_strict = (
                f"{r.strict_exact_accuracy_percentage:.1f}%"
                if r.strict_exact_accuracy_percentage is not None
                else "N/A"
            )
            lines.append(
                f"| `{r.benchmark_id}` | {r.project_name} | 1:1 Match | `{r.total_measurable_expected}` | `{r.total_items_compared}` | `{r.exact_matches}` | `{r.within_5_percent}` | `{r.gross_mismatches}` | `{r.missed_items}` | `{r.hallucinated_items}` | **`{r_acc}`** | `{r_strict}` | `verified_scored_benchmark` |"
            )
        lines.append("")

        lines.append("## 3. Real-World Scope Divergence Stress Tests (Excluded from Headline)")
        lines.append("")
        lines.append(
            "> **Scope Divergence Stress Tests**: These packages represent authentic tender documents where the architectural "
            "drawing set and the Bill of Quantities cover different physical boundaries (e.g., drawings cover a whole facility while "
            "the BOQ covers a single wing). They are preserved as real-world stress tests and are excluded from primary headline accuracy scoring."
        )
        lines.append("")
        lines.append(
            "| Benchmark ID | Project Name | Scope Divergence | Total BOQ Items | Evaluated | Exact | Gross | Missed | Overall Acc | Status |"
        )
        lines.append(
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        )
        for r in self.stress_test_reports:
            r_acc = (
                f"{r.overall_accuracy_percentage:.1f}%"
                if r.overall_accuracy_percentage is not None
                else "N/A"
            )
            lines.append(
                f"| `{r.benchmark_id}` | {r.project_name} | Facility drawings vs single-wing BOQ | `{r.total_boq_items}` | `{r.total_items_compared}` | `{r.exact_matches}` | `{r.gross_mismatches}` | `{r.missed_items}` | `{r_acc}` | `{r.status}` |"
            )
        lines.append("")

        lines.append("## 4. Candidate Seed Inventory (Unverified / Excluded)")
        lines.append("")
        lines.append(
            "> **Candidate Seeds**: Prospective tender references. They are strictly excluded from headline accuracy "
            "metrics until physical drawing and matching BOQ files are retrieved, verified, and scope-audited."
        )
        lines.append("")
        lines.append(
            "| Benchmark ID | Project Name | Organization | Reference | Status | Headline Eligible |"
        )
        lines.append(
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        )
        for r in self.candidate_seed_reports:
            lines.append(
                f"| `{r.benchmark_id}` | {r.project_name} | {r.organization or '-'} | {r.tender_reference or '-'} | `{r.status}` | **No** (Unverified) |"
            )
        lines.append("")

        lines.append("## 5. Non-Penalized Denominator Exclusions")
        lines.append("")
        lines.append(
            "Contractor overheads, site preliminaries, and provisional budget allowances are transparently excluded from physical geometric accuracy:"
        )
        lines.append(f"- **Total Preliminaries Excluded**: `{self.total_preliminaries_excluded}`")
        lines.append(f"- **Total Provisional Sums Excluded**: `{self.total_provisional_sums_excluded}`")
        lines.append(f"- **Total Non-Architectural Excluded**: `{self.total_non_architectural_excluded}`")
        lines.append("")

        return "\n".join(lines)


class BenchmarkAccuracyEngine:
    """Engine for extracting quantities, evaluating accuracy, and generating reports."""

    def __init__(
        self,
        benchmarks_dir: Path | str = "benchmarks/public_tenders",
        output_dir: Path | str = "benchmark_results",
    ) -> None:
        self.benchmarks_dir = Path(benchmarks_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_quantities_from_pdf(
        self,
        pdf_path: Path | str,
        pages: Optional[Sequence[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Extract physical architectural quantities from drawing PDF via GenericPlanReaderExtractor.

        Maintains complete architectural decoupling from ground truth BOQs.
        """
        extractor = GenericPlanReaderExtractor()
        preds = extractor.extract_from_pdf(pdf_path, pages=pages)
        return [p.to_dict() for p in preds]

    def evaluate_benchmark(
        self,
        benchmark_id: str,
        pdf_path: Optional[Path | str] = None,
        predictions: Optional[Sequence[Dict[str, Any]]] = None,
        hallucinated_predictions: Optional[Sequence[Dict[str, Any]]] = None,
        strict_tolerance_pct: float = 5.0,
        auto_extract: bool = False,
    ) -> BenchmarkAccuracyReport:
        """Evaluate accuracy of extraction predictions or native PDF against benchmark BOQ.

        Follows fail-closed evaluation rules:
        - Unverified candidate seeds are strictly barred from scoring.
        - Unscored benchmarks (predictions=None, pdf_path=None, auto_extract=False) return is_scored=False.
        - Preliminaries and provisional sums are never penalized.
        - Identifies exact matches, tolerance tiers (5%, 10%, 20%), gross mismatches (>20%),
          missed items, and hallucinated items.
        """
        now_ts = datetime.now(timezone.utc).isoformat()

        # Load benchmark manifest suite
        try:
            bench = PublicTenderBenchmark.load(benchmark_id, base_dir=self.benchmarks_dir)
        except Exception as exc:
            return BenchmarkAccuracyReport(
                benchmark_id=benchmark_id,
                timestamp=now_ts,
                project_name="Unknown",
                organization="Unknown",
                tender_reference="Unknown",
                status="failed_closed",
                is_scored=False,
                source_pdf=str(pdf_path) if pdf_path else None,
                total_boq_items=0,
                total_measurable_expected=0,
                total_items_compared=0,
                exact_matches=0,
                within_5_percent=0,
                within_10_percent=0,
                within_20_percent=0,
                gross_mismatches=0,
                missed_items=0,
                hallucinated_items=0,
                preliminaries_excluded=0,
                provisional_sums_excluded=0,
                non_architectural_excluded=0,
                overall_accuracy_percentage=None,
                strict_exact_accuracy_percentage=None,
                errors=[f"Failed to load benchmark '{benchmark_id}': {exc}"],
            )

        # 1. Fail-closed: Unverified candidate seeds cannot be scored in headline metrics
        if bench.is_candidate_unverified:
            return BenchmarkAccuracyReport(
                benchmark_id=benchmark_id,
                timestamp=now_ts,
                project_name=bench.project_name,
                organization=bench.organization,
                tender_reference=bench.tender_reference,
                status="candidate_unverified",
                is_scored=False,
                is_headline_eligible=False,
                source_pdf=str(pdf_path) if pdf_path else None,
                total_boq_items=bench.expected_boq_summary.get("total_line_items", 0),
                total_measurable_expected=bench.expected_boq_summary.get("measurable_items_count", 0),
                total_items_compared=0,
                exact_matches=0,
                within_5_percent=0,
                within_10_percent=0,
                within_20_percent=0,
                gross_mismatches=0,
                missed_items=0,
                hallucinated_items=0,
                preliminaries_excluded=bench.expected_boq_summary.get("preliminaries_excluded_count", 0),
                provisional_sums_excluded=bench.expected_boq_summary.get("provisional_sums_count", 0),
                non_architectural_excluded=0,
                overall_accuracy_percentage=None,
                strict_exact_accuracy_percentage=None,
                errors=["unverified_candidate_seed_cannot_contribute_to_accuracy_metrics"],
            )

        # 2. Resolve PDF path if explicitly provided or auto_extract requested
        resolved_pdf = None
        if pdf_path:
            p_cand = Path(pdf_path)
            if p_cand.exists():
                resolved_pdf = p_cand.resolve()
        elif auto_extract:
            if bench.download_manifest.get("documents"):
                for doc in bench.download_manifest["documents"]:
                    doc_fn = doc.get("filename")
                    if doc_fn:
                        resolved_pdf = resolve_file_path(doc_fn)
                        if resolved_pdf:
                            break
            if not resolved_pdf and bench.source_manifest.get("source_pdf"):
                resolved_pdf = resolve_file_path(bench.source_manifest.get("source_pdf"))
            if not resolved_pdf and bench.source_manifest.get("allowed_comparison_sources"):
                for src in bench.source_manifest["allowed_comparison_sources"]:
                    if src.lower().endswith(".pdf"):
                        resolved_pdf = resolve_file_path(src)
                        if resolved_pdf:
                            break

        # 3. Resolve predictions: either supplied directly or extracted from PDF
        active_predictions: List[Dict[str, Any]] = []
        if predictions is not None:
            active_predictions.extend(predictions)
        elif (pdf_path or auto_extract) and resolved_pdf and resolved_pdf.exists():
            target_pages = None
            for doc in bench.download_manifest.get("documents", []):
                if doc.get("role") in ("architectural_drawings", "drawings", "tender_drawings"):
                    dp = doc.get("drawing_pages")
                    if dp and len(dp) == 2:
                        target_pages = list(range(dp[0] - 1, dp[1]))
                        break
            active_predictions.extend(self.extract_quantities_from_pdf(resolved_pdf, pages=target_pages))

        if hallucinated_predictions:
            active_predictions.extend(hallucinated_predictions)

        # If still no predictions, return candidate_unscored
        if not active_predictions:
            return BenchmarkAccuracyReport(
                benchmark_id=benchmark_id,
                timestamp=now_ts,
                project_name=bench.project_name,
                organization=bench.organization,
                tender_reference=bench.tender_reference,
                status="candidate_unscored",
                is_scored=False,
                is_headline_eligible=bench.is_headline_eligible,
                source_pdf=str(resolved_pdf) if resolved_pdf else None,
                total_boq_items=bench.expected_boq_summary.get("total_line_items", 0),
                total_measurable_expected=bench.expected_boq_summary.get("measurable_items_count", 0),
                total_items_compared=0,
                exact_matches=0,
                within_5_percent=0,
                within_10_percent=0,
                within_20_percent=0,
                gross_mismatches=0,
                missed_items=0,
                hallucinated_items=0,
                preliminaries_excluded=bench.expected_boq_summary.get("preliminaries_excluded_count", 0),
                provisional_sums_excluded=bench.expected_boq_summary.get("provisional_sums_count", 0),
                non_architectural_excluded=0,
                overall_accuracy_percentage=None,
                strict_exact_accuracy_percentage=None,
                errors=[],
            )

        # 4. Perform Comparison against expected sample measurable items
        sample_items = bench.expected_boq_summary.get("sample_measurable_items", [])
        expected_map: Dict[str, Dict[str, Any]] = {
            it.get("item_id"): it for it in sample_items if it.get("item_id")
        }

        # Build prediction mapping (by tag, item_id, line_id)
        pred_map: Dict[str, Dict[str, Any]] = {}
        for p in active_predictions:
            p_dict = p.to_dict() if hasattr(p, "to_dict") else dict(p)
            pid = str(p_dict.get("item_id", p_dict.get("tag", p_dict.get("line_id", p_dict.get("quantity_id", "")))))
            if pid:
                pred_map[pid] = p_dict
            tag = p_dict.get("tag")
            if tag:
                pred_map[tag] = p_dict

        item_mappings = bench.benchmark_rules.get("item_mappings", {})
        matched_pred_keys: Set[str] = set()

        item_results: List[ItemComparisonResult] = []
        exact_matches = 0
        within_5 = 0
        within_10 = 0
        within_20 = 0
        gross_mismatches = 0
        missed_items = 0
        hallucinated_items = 0
        prelim_excluded = 0
        provis_excluded = 0
        non_arch_excluded = 0

        # Evaluate all expected items
        for it in sample_items:
            iid = it.get("item_id", "")
            cat = it.get("category", "")
            exp_val = float(it.get("expected_quantity", 0.0))
            unit = it.get("unit")
            desc = it.get("description", "")
            dwg_sheet = it.get("drawing_sheet")
            dwg_page = it.get("drawing_page")

            # Check exclusions
            if cat == BOQLineCategory.PRELIMINARIES.value:
                prelim_excluded += 1
                item_results.append(
                    ItemComparisonResult(
                        item_id=iid,
                        description=desc,
                        category=cat,
                        expected_quantity=exp_val,
                        extracted_quantity=None,
                        unit=unit,
                        delta=None,
                        pct_error=None,
                        status=ItemMatchStatus.EXCLUDED_PRELIMINARY,
                        tolerance_tier="excluded",
                        drawing_sheet=dwg_sheet,
                        drawing_page=dwg_page,
                        notes="Preliminaries excluded from physical measurement denominator",
                    )
                )
                continue

            if cat in (BOQLineCategory.PROVISIONAL_SUM.value, BOQLineCategory.SCOPE_ALLOWANCE_ONLY.value):
                provis_excluded += 1
                item_results.append(
                    ItemComparisonResult(
                        item_id=iid,
                        description=desc,
                        category=cat,
                        expected_quantity=exp_val,
                        extracted_quantity=None,
                        unit=unit,
                        delta=None,
                        pct_error=None,
                        status=ItemMatchStatus.EXCLUDED_PROVISIONAL,
                        tolerance_tier="excluded",
                        drawing_sheet=dwg_sheet,
                        drawing_page=dwg_page,
                        notes="Provisional sum / scope allowance excluded from firm physical measurement",
                    )
                )
                continue

            if cat == BOQLineCategory.NOT_ARCHITECTURAL.value:
                non_arch_excluded += 1
                item_results.append(
                    ItemComparisonResult(
                        item_id=iid,
                        description=desc,
                        category=cat,
                        expected_quantity=exp_val,
                        extracted_quantity=None,
                        unit=unit,
                        delta=None,
                        pct_error=None,
                        status=ItemMatchStatus.EXCLUDED_NON_ARCHITECTURAL,
                        tolerance_tier="excluded",
                        drawing_sheet=dwg_sheet,
                        drawing_page=dwg_page,
                        notes="Non-architectural trade excluded",
                    )
                )
                continue

            # Look up prediction by item_id or mapped tag
            pred_key = None
            if iid in pred_map:
                pred_key = iid
            elif iid in item_mappings and item_mappings[iid] in pred_map:
                pred_key = item_mappings[iid]

            if pred_key is None:
                missed_items += 1
                item_results.append(
                    ItemComparisonResult(
                        item_id=iid,
                        description=desc,
                        category=cat,
                        expected_quantity=exp_val,
                        extracted_quantity=None,
                        unit=unit,
                        delta=None,
                        pct_error=None,
                        status=ItemMatchStatus.MISSED_IN_EXTRACTION,
                        tolerance_tier="missed",
                        drawing_sheet=dwg_sheet,
                        drawing_page=dwg_page,
                        notes="Item present in BOQ but absent from extraction predictions",
                    )
                )
                continue

            matched_pred_keys.add(pred_key)
            matched_pred_keys.add(iid)
            pred_obj = pred_map[pred_key]
            act_val = float(pred_obj.get("value", pred_obj.get("quantity", pred_obj.get("actual", 0.0))))
            delta = round(act_val - exp_val, 4)
            pct_err = round((abs(delta) / exp_val * 100.0) if exp_val != 0.0 else 0.0, 2)

            # Check if count-based (doors, windows, chalkboards, pillars)
            is_count_item = (
                unit in ("NO", "NR", "EA")
                or any(k in desc.lower() for k in ["door", "window", "chalkboard", "pillar"])
            )

            if abs(delta) < 1e-4:
                exact_matches += 1
                stat = ItemMatchStatus.EXACT_MATCH
                tier = "exact"
            elif is_count_item:
                # Count items require exact matching; any divergence is a gross mismatch
                gross_mismatches += 1
                stat = ItemMatchStatus.GROSS_MISMATCH
                tier = "gross"
            elif pct_err <= 5.0:
                within_5 += 1
                stat = ItemMatchStatus.WITHIN_5_PERCENT
                tier = "5%"
            elif pct_err <= 10.0:
                within_10 += 1
                stat = ItemMatchStatus.WITHIN_10_PERCENT
                tier = "10%"
            elif pct_err <= 20.0:
                within_20 += 1
                stat = ItemMatchStatus.WITHIN_20_PERCENT
                tier = "20%"
            else:
                gross_mismatches += 1
                stat = ItemMatchStatus.GROSS_MISMATCH
                tier = "gross"

            item_results.append(
                ItemComparisonResult(
                    item_id=iid,
                    description=desc,
                    category=cat,
                    expected_quantity=exp_val,
                    extracted_quantity=act_val,
                    unit=unit,
                    delta=delta,
                    pct_error=pct_err,
                    status=stat,
                    tolerance_tier=tier,
                    drawing_sheet=dwg_sheet,
                    drawing_page=dwg_page,
                    notes=f"Comparison evaluated against {exp_val} {unit or ''}",
                )
            )

        # 5. Detect Hallucinated Items (predictions with no match in expected sample items or mappings)
        logged_hallucinated_ids = set()
        for p in active_predictions:
            p_dict = p.to_dict() if hasattr(p, "to_dict") else dict(p)
            pid = str(p_dict.get("item_id", p_dict.get("tag", p_dict.get("line_id", p_dict.get("quantity_id", "")))))
            tag = p_dict.get("tag", "")

            if pid in matched_pred_keys or tag in matched_pred_keys or pid in expected_map:
                continue
            if pid in logged_hallucinated_ids:
                continue
            logged_hallucinated_ids.add(pid)

            hallucinated_items += 1
            act_val = float(p_dict.get("value", p_dict.get("quantity", p_dict.get("actual", 0.0))))
            unit = p_dict.get("unit")
            desc = p_dict.get("description", "Extracted quantity without BOQ counterpart")
            item_results.append(
                ItemComparisonResult(
                    item_id=pid,
                    description=desc,
                    category="hallucinated",
                    expected_quantity=None,
                    extracted_quantity=act_val,
                    unit=unit,
                    delta=None,
                    pct_error=None,
                    status=ItemMatchStatus.HALLUCINATED_ITEM,
                    tolerance_tier="hallucinated",
                    drawing_sheet=p_dict.get("sheet_number") or p_dict.get("drawing_sheet"),
                    drawing_page=p_dict.get("source_page") or p_dict.get("drawing_page"),
                    notes="Item present in extraction but absent from verified BOQ ground truth",
                )
            )

        # 6. Calculate Overall Metrics
        total_measurable_expected = (
            exact_matches + within_5 + within_10 + within_20 + gross_mismatches + missed_items
        )
        total_compared = total_measurable_expected + hallucinated_items

        # Accepted accuracy numerator: exact matches + within 5% tolerance
        accepted_count = exact_matches + within_5
        overall_acc = (
            round((accepted_count / total_compared) * 100.0, 2) if total_compared > 0 else 0.0
        )
        strict_exact_acc = (
            round((exact_matches / total_compared) * 100.0, 2) if total_compared > 0 else 0.0
        )

        report_status = "verified_scope_mismatch" if bench.is_scope_mismatch else "scored"
        return BenchmarkAccuracyReport(
            benchmark_id=benchmark_id,
            timestamp=now_ts,
            project_name=bench.project_name,
            organization=bench.organization,
            tender_reference=bench.tender_reference,
            status=report_status,
            is_scored=True,
            is_headline_eligible=bench.is_headline_eligible,
            source_pdf=str(resolved_pdf) if resolved_pdf else None,
            total_boq_items=bench.expected_boq_summary.get("total_line_items", len(sample_items)),
            total_measurable_expected=total_measurable_expected,
            total_items_compared=total_compared,
            exact_matches=exact_matches,
            within_5_percent=within_5,
            within_10_percent=within_10,
            within_20_percent=within_20,
            gross_mismatches=gross_mismatches,
            missed_items=missed_items,
            hallucinated_items=hallucinated_items,
            preliminaries_excluded=prelim_excluded,
            provisional_sums_excluded=provis_excluded,
            non_architectural_excluded=non_arch_excluded,
            overall_accuracy_percentage=overall_acc,
            strict_exact_accuracy_percentage=strict_exact_acc,
            item_results=item_results,
            errors=[],
        )

    def save_report(
        self,
        report: BenchmarkAccuracyReport,
        output_dir: Optional[Path | str] = None,
    ) -> Tuple[Path, Path]:
        """Save report as JSON and Markdown files in output directory."""
        target_dir = Path(output_dir or self.output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        json_path = target_dir / f"{report.benchmark_id}_accuracy_report.json"
        md_path = target_dir / f"{report.benchmark_id}_accuracy_report.md"

        json_path.write_text(report.to_json(indent=2), encoding="utf-8")
        md_path.write_text(report.to_markdown(), encoding="utf-8")

        return json_path, md_path

    def evaluate_suite(
        self,
        benchmarks_dir: Optional[Path | str] = None,
        auto_extract: bool = True,
        predictions_by_benchmark: Optional[Dict[str, Sequence[Dict[str, Any]]]] = None,
        output_dir: Optional[Path | str] = None,
    ) -> HeadlineAccuracyDashboard:
        """Evaluate all registered public tender benchmarks and generate headline dashboard.

        Rules:
        - Only benchmarks with verified 1:1 physical scope match (verified_scored_benchmark)
          contribute to the official headline accuracy metrics.
        - Verified packages with scope divergence (verified_scope_mismatch) are isolated as
          real-world stress tests and never dilute headline accuracy.
        - Candidate seeds (candidate_unverified) are tracked as pipeline inventory but
          completely excluded from accuracy metrics.
        """
        b_dir = Path(benchmarks_dir or self.benchmarks_dir)
        benchmarks = list_available_public_tender_benchmarks(b_dir)

        headline_reports: List[BenchmarkAccuracyReport] = []
        stress_test_reports: List[BenchmarkAccuracyReport] = []
        candidate_seed_reports: List[BenchmarkAccuracyReport] = []

        now_ts = datetime.now(timezone.utc).isoformat()

        for bench in benchmarks:
            preds = (
                predictions_by_benchmark.get(bench.benchmark_id)
                if predictions_by_benchmark
                else None
            )

            if bench.is_candidate_unverified:
                rep = self.evaluate_benchmark(
                    benchmark_id=bench.benchmark_id,
                    predictions=preds,
                    auto_extract=False,
                )
                candidate_seed_reports.append(rep)
            elif bench.is_scope_mismatch:
                rep = self.evaluate_benchmark(
                    benchmark_id=bench.benchmark_id,
                    predictions=preds,
                    auto_extract=auto_extract,
                )
                stress_test_reports.append(rep)
            elif bench.is_headline_eligible:
                rep = self.evaluate_benchmark(
                    benchmark_id=bench.benchmark_id,
                    predictions=preds,
                    auto_extract=auto_extract,
                )
                headline_reports.append(rep)
            else:
                rep = self.evaluate_benchmark(
                    benchmark_id=bench.benchmark_id,
                    predictions=preds,
                    auto_extract=auto_extract,
                )
                candidate_seed_reports.append(rep)

        # Aggregate headline metrics across headline-eligible benchmarks only
        tot_exact = sum(r.exact_matches for r in headline_reports)
        tot_w5 = sum(r.within_5_percent for r in headline_reports)
        tot_w10 = sum(r.within_10_percent for r in headline_reports)
        tot_w20 = sum(r.within_20_percent for r in headline_reports)
        tot_gross = sum(r.gross_mismatches for r in headline_reports)
        tot_missed = sum(r.missed_items for r in headline_reports)
        tot_halluc = sum(r.hallucinated_items for r in headline_reports)
        tot_expected = sum(r.total_measurable_expected for r in headline_reports)
        tot_compared = sum(r.total_items_compared for r in headline_reports)

        tot_prelim = sum(r.preliminaries_excluded for r in headline_reports) + sum(
            r.preliminaries_excluded for r in stress_test_reports
        )
        tot_provis = sum(r.provisional_sums_excluded for r in headline_reports) + sum(
            r.provisional_sums_excluded for r in stress_test_reports
        )
        tot_non_arch = sum(r.non_architectural_excluded for r in headline_reports) + sum(
            r.non_architectural_excluded for r in stress_test_reports
        )

        accepted = tot_exact + tot_w5
        overall_acc = (
            round((accepted / tot_compared) * 100.0, 2) if tot_compared > 0 else 0.0
        )
        strict_acc = (
            round((tot_exact / tot_compared) * 100.0, 2) if tot_compared > 0 else 0.0
        )

        dashboard = HeadlineAccuracyDashboard(
            timestamp=now_ts,
            headline_overall_accuracy=overall_acc,
            headline_strict_exact_accuracy=strict_acc,
            total_headline_benchmarks=len(headline_reports),
            total_headline_measurable_expected=tot_expected,
            total_headline_items_compared=tot_compared,
            total_headline_exact_matches=tot_exact,
            total_headline_within_5_percent=tot_w5,
            total_headline_within_10_percent=tot_w10,
            total_headline_within_20_percent=tot_w20,
            total_headline_gross_mismatches=tot_gross,
            total_headline_missed_items=tot_missed,
            total_headline_hallucinated_items=tot_halluc,
            total_preliminaries_excluded=tot_prelim,
            total_provisional_sums_excluded=tot_provis,
            total_non_architectural_excluded=tot_non_arch,
            total_stress_test_benchmarks=len(stress_test_reports),
            total_candidate_seeds=len(candidate_seed_reports),
            headline_reports=headline_reports,
            stress_test_reports=stress_test_reports,
            candidate_seed_reports=candidate_seed_reports,
        )

        out_d = Path(output_dir or self.output_dir)
        self.save_dashboard(dashboard, output_dir=out_d)
        return dashboard

    def save_dashboard(
        self,
        dashboard: HeadlineAccuracyDashboard,
        output_dir: Optional[Path | str] = None,
    ) -> Tuple[Path, Path]:
        """Save dashboard as JSON and Markdown files in output directory."""
        target_dir = Path(output_dir or self.output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        json_path = target_dir / "headline_accuracy_dashboard.json"
        md_path = target_dir / "headline_accuracy_dashboard.md"

        json_path.write_text(dashboard.to_json(indent=2), encoding="utf-8")
        md_path.write_text(dashboard.to_markdown(), encoding="utf-8")

        return json_path, md_path


def run_public_tender_benchmark(
    benchmark_id: str,
    pdf_path: Optional[Path | str] = None,
    predictions: Optional[Sequence[Dict[str, Any]]] = None,
    auto_extract: bool = False,
    benchmarks_dir: Path | str = "benchmarks/public_tenders",
    output_dir: Path | str = "benchmark_results",
) -> BenchmarkAccuracyReport:
    """Convenience function to evaluate a public tender benchmark and save reports."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=benchmarks_dir, output_dir=output_dir)
    report = engine.evaluate_benchmark(
        benchmark_id=benchmark_id,
        pdf_path=pdf_path,
        predictions=predictions,
        auto_extract=auto_extract,
    )
    engine.save_report(report, output_dir=output_dir)
    return report


def run_public_tender_benchmark_suite(
    benchmarks_dir: Path | str = "benchmarks/public_tenders",
    output_dir: Path | str = "benchmark_results",
    auto_extract: bool = True,
    predictions_by_benchmark: Optional[Dict[str, Sequence[Dict[str, Any]]]] = None,
) -> HeadlineAccuracyDashboard:
    """Convenience function to evaluate the full public tender suite and save headline dashboard."""
    engine = BenchmarkAccuracyEngine(benchmarks_dir=benchmarks_dir, output_dir=output_dir)
    return engine.evaluate_suite(
        benchmarks_dir=benchmarks_dir,
        auto_extract=auto_extract,
        predictions_by_benchmark=predictions_by_benchmark,
        output_dir=output_dir,
    )


def main() -> int:
    """CLI entrypoint for PlanReader Public Tender Benchmark Accuracy Engine."""
    parser = argparse.ArgumentParser(description="PlanReader Public Tender Benchmark Accuracy Engine")
    parser.add_argument("--benchmark", default="tenders_ke_kstvet_cbc_classroom", help="Public tender benchmark ID")
    parser.add_argument("--all", "--suite", action="store_true", help="Evaluate all registered benchmarks and produce headline dashboard")
    parser.add_argument("--pdf", help="Optional override path to source tender PDF")
    parser.add_argument("--auto-extract", action="store_true", default=True, help="Auto-extract from downloaded PDF if available")
    parser.add_argument("--benchmarks-dir", default="benchmarks/public_tenders", help="Path to public tender benchmarks directory")
    parser.add_argument("--output-dir", default="benchmark_results", help="Directory to save JSON/Markdown accuracy reports")
    args = parser.parse_args()

    engine = BenchmarkAccuracyEngine(benchmarks_dir=args.benchmarks_dir, output_dir=args.output_dir)

    if args.all:
        dashboard = engine.evaluate_suite(
            benchmarks_dir=args.benchmarks_dir,
            auto_extract=args.auto_extract,
            output_dir=args.output_dir,
        )
        j_path, m_path = engine.save_dashboard(dashboard, output_dir=args.output_dir)
        acc_s = (
            f"{dashboard.headline_overall_accuracy:.1f}%"
            if dashboard.headline_overall_accuracy is not None
            else "N/A"
        )
        exact_s = (
            f"{dashboard.headline_strict_exact_accuracy:.1f}%"
            if dashboard.headline_strict_exact_accuracy is not None
            else "N/A"
        )
        print("=" * 75)
        print("PLANREADER PUBLIC TENDER BENCHMARK — EXECUTIVE HEADLINE ACCURACY DASHBOARD")
        print("=" * 75)
        print(f"Official Headline Accuracy (<= 5% tol): {acc_s}")
        print(f"Strict Exact Accuracy:                  {exact_s}")
        print(f"Scored Headline Benchmarks:            {dashboard.total_headline_benchmarks}")
        print(f"Total Measurable Items Evaluated:       {dashboard.total_headline_measurable_expected}")
        print(f"Total Items Compared (Denominator):     {dashboard.total_headline_items_compared}")
        print(f"Exact Matches:                         {dashboard.total_headline_exact_matches}")
        print(f"Within 5% Tolerance:                   {dashboard.total_headline_within_5_percent}")
        print(f"Gross Mismatches (> 20%):              {dashboard.total_headline_gross_mismatches}")
        print(f"Missed Items:                          {dashboard.total_headline_missed_items}")
        print(f"Hallucinated Extra Predictions:        {dashboard.total_headline_hallucinated_items}")
        print(f"Scope Divergence Stress Tests:         {dashboard.total_stress_test_benchmarks}")
        print(f"Candidate Seeds (Unverified):          {dashboard.total_candidate_seeds}")
        print(f"Dashboard reports written to:          {j_path} and {m_path}")
        print("=" * 75)
        return 0

    report = engine.evaluate_benchmark(
        benchmark_id=args.benchmark,
        pdf_path=args.pdf,
        auto_extract=args.auto_extract,
    )
    j_path, m_path = engine.save_report(report, output_dir=args.output_dir)

    print("=" * 70)
    print(f"PlanReader Public Tender Accuracy Evaluation: {report.project_name}")
    print(f"Benchmark:            {report.benchmark_id} [{report.status}]")
    print(f"Overall Accuracy:     {report.overall_accuracy_percentage}%" if report.overall_accuracy_percentage is not None else "Overall Accuracy:     N/A")
    print(f"Exact Matches:        {report.exact_matches}")
    print(f"Within 5% Tolerance:  {report.within_5_percent}")
    print(f"Within 10% Tolerance: {report.within_10_percent}")
    print(f"Gross Mismatches:     {report.gross_mismatches}")
    print(f"Missed Items:         {report.missed_items}")
    print(f"Hallucinated Items:   {report.hallucinated_items}")
    print(f"Reports written to:   {j_path} and {m_path}")
    print("=" * 70)

    return 0 if report.is_scored else 1


if __name__ == "__main__":
    sys.exit(main())
