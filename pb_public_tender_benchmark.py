"""pb_public_tender_benchmark.py — Public Tender Benchmark & BOQ Classification Framework.

PR F.1 / F.2: External Public Tender Benchmark Expansion.
Enables PlanReader to verify accuracy against independent third-party public tender
datasets (UNGM / UNOPS, UN-Habitat, IOM, UNDP, tenders.go.ke, commercial public tenders).

Provides:
- Standardized 9-category BOQ line taxonomy.
- Heuristic and keyword-based BOQ line classifier.
- Drawing traceability validator for measurable takeoff items.
- Fail-closed project identity matching between tender drawings and BOQ schedules.
- Benchmark discovery, loading, and non-penalization of preliminaries.
- Strict accuracy scoring: unscored/missing predictions yield accuracy_score=None.
- Integrity verification with actual SHA-256 validation.
- Fail-closed error recording during benchmark discovery.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


# Global registry of benchmark load errors for transparency
_LAST_BENCHMARK_LOAD_ERRORS: Dict[str, str] = {}


def get_benchmark_load_errors() -> Dict[str, str]:
    """Return dictionary of any benchmark directories that failed validation."""
    return dict(_LAST_BENCHMARK_LOAD_ERRORS)


class BOQLineCategory(str, Enum):
    """Standardized 9-category taxonomy for Bill of Quantities (BOQ) line items."""

    MEASURABLE_FROM_DRAWINGS = "measurable_from_drawings"
    SCHEDULE_EXTRACTABLE = "schedule_extractable"
    SCOPE_ALLOWANCE_ONLY = "scope_allowance_only"
    PROVISIONAL_SUM = "provisional_sum"
    RATE_ONLY = "rate_only"
    PRELIMINARIES = "preliminaries"
    NOT_ARCHITECTURAL = "not_architectural"
    NOT_APPLICABLE_TO_PLANREADER = "not_applicable_to_planreader"
    UNKNOWN_REQUIRES_REVIEW = "unknown_requires_review"


@dataclass
class BOQLineItem:
    """Represents a single classified line item in a tender BOQ or schedule."""

    line_id: str
    description: str
    quantity: float
    unit: Optional[str] = None
    category: BOQLineCategory = BOQLineCategory.UNKNOWN_REQUIRES_REVIEW
    drawing_sheet: Optional[str] = None
    drawing_page: Optional[int] = None
    rate_only: bool = False
    is_provisional_flag: bool = False

    @property
    def is_measurable(self) -> bool:
        """True only if this line item represents physical geometry or scheduled elements."""
        return self.category in (
            BOQLineCategory.MEASURABLE_FROM_DRAWINGS,
            BOQLineCategory.SCHEDULE_EXTRACTABLE,
        )

    @property
    def is_preliminary(self) -> bool:
        """True if line item is site overhead, supervision, scaffold, or preliminary."""
        return self.category == BOQLineCategory.PRELIMINARIES

    @property
    def is_provisional(self) -> bool:
        """True if item is a provisional sum or scope allowance."""
        if self.category in (BOQLineCategory.PROVISIONAL_SUM, BOQLineCategory.SCOPE_ALLOWANCE_ONLY):
            return True
        if self.unit and self.unit.strip().upper() in ("PS", "PROVISIONAL"):
            return True
        return bool(self.is_provisional_flag)


def classify_boq_line(
    description: str,
    unit: Optional[str] = None,
    rate_only: bool = False,
    is_provisional: bool = False,
) -> BOQLineCategory:
    """Classify a BOQ line item into the standardized 9-category taxonomy."""
    if rate_only:
        return BOQLineCategory.RATE_ONLY

    desc_lower = (description or "").lower().strip()
    unit_upper = (unit or "").strip().upper()

    # 1. Provisional Sums
    if is_provisional or unit_upper in ("PS", "PROVISIONAL"):
        return BOQLineCategory.PROVISIONAL_SUM

    if any(p in desc_lower for p in ["provisional sum", "(ps)", "provisional"]):
        return BOQLineCategory.PROVISIONAL_SUM

    # 2. Scope Allowances
    if "scope allowance" in desc_lower or "allowance for" in desc_lower:
        return BOQLineCategory.SCOPE_ALLOWANCE_ONLY

    # 3. Preliminaries and site overheads (must never penalize physical measurement)
    prelim_keywords = [
        "preliminar",
        "site establishment",
        "temporary facilities",
        "hoarding",
        "scaffold",
        "mobilis",
        "mobiliz",
        "supervision",
        "insurance",
        "contractual overhead",
        "site security",
        "cleaning",
        "labour camp",
        "clearing away",
    ]
    if any(k in desc_lower for k in prelim_keywords):
        return BOQLineCategory.PRELIMINARIES

    # 4. Non-architectural trades (MEP, electrical, civil, drainage)
    non_arch_keywords = [
        "sewer",
        "drainage pipe",
        "pipe in trench",
        "switchboard",
        "3-phase",
        "electrical distribution",
        "electrical works",
        "hvac",
        "ductwork",
        "substation",
        "civil works",
        "earthworks",
        "bulk excavation",
        "stormwater",
        "pvc pipe",
    ]
    if any(k in desc_lower for k in non_arch_keywords):
        return BOQLineCategory.NOT_ARCHITECTURAL

    # 5. Schedule extractable (doors, windows, hardware schedules)
    schedule_keywords = [
        "door schedule",
        "window schedule",
        "door type",
        "window type",
        "sliding window",
        "timber door",
        "solid core timber door",
        "aluminium sliding window",
        "acoustic timber door",
        "sliding hospital door",
        "glazed sliding entry door",
        "steel casement window",
        "mild steel pannelled door",
        "mild steel panelled door",
        "double door overall size",
        "window overall size",
        "ironmongery",
        "flyscreen",
    ]
    if any(k in desc_lower for k in schedule_keywords):
        return BOQLineCategory.SCHEDULE_EXTRACTABLE

    # 6. Measurable from drawings (architectural physical finishes and partitions)
    measurable_keywords = [
        "plasterboard",
        "lining",
        "render",
        "paint",
        "finishes",
        "finish",
        "tile",
        "tiling",
        "flooring",
        "vinyl",
        "carpet",
        "blockwork",
        "masonry",
        "brickwork",
        "drywall",
        "gypsum",
        "partition",
        "ceiling",
        "membrane",
        "waterproof",
        "skirting",
        "insulation",
        "epoxy",
        "coating",
        "concrete block",
        "external cement",
        "red oxide",
        "screed",
        "walling",
        "chalkboard",
        "blackboard",
        "blockboard",
        "plaster to",
        "pointing externally",
        "pillars",
    ]
    if any(k in desc_lower for k in measurable_keywords):
        return BOQLineCategory.MEASURABLE_FROM_DRAWINGS

    # Default fallback
    return BOQLineCategory.UNKNOWN_REQUIRES_REVIEW


def evaluate_boq_measurement_traceability(items: Sequence[BOQLineItem]) -> Dict[str, Any]:
    """Evaluate drawing traceability across a sequence of BOQ line items."""
    total_items = len(items)
    measurable_items = [it for it in items if it.is_measurable]
    traced_measurable = [
        it for it in measurable_items if it.drawing_sheet is not None or it.drawing_page is not None
    ]
    missing_trace = [
        it for it in measurable_items if it.drawing_sheet is None and it.drawing_page is None
    ]

    return {
        "total_items": total_items,
        "measurable_items": len(measurable_items),
        "traced_measurable_items": len(traced_measurable),
        "missing_trace_items_count": len(missing_trace),
        "missing_trace_line_ids": [it.line_id for it in missing_trace],
    }


def compare_tender_drawings_and_boq(
    drawings_meta: Dict[str, Any],
    boq_meta: Dict[str, Any],
    manifest: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Ensure tender drawings and BOQ belong to the same project identity before comparison."""
    if not drawings_meta or not boq_meta:
        return False, "wrong_project_source_mismatch"

    # Check tender_reference
    d_ref = str(drawings_meta.get("tender_reference", "")).strip()
    b_ref = str(boq_meta.get("tender_reference", "")).strip()

    # Check project_name
    d_name = str(drawings_meta.get("project_name", "")).strip().lower()
    b_name = str(boq_meta.get("project_name", "")).strip().lower()

    # Check organization
    d_org = str(drawings_meta.get("organization", "")).strip().lower()
    b_org = str(boq_meta.get("organization", "")).strip().lower()

    # If both have tender_reference
    if d_ref and b_ref:
        if d_ref == b_ref:
            return True, "project_identity_confirmed"
        else:
            return False, "wrong_project_source_mismatch"

    if d_name and b_name:
        if d_name == b_name or (len(d_name) > 10 and d_name in b_name) or (len(b_name) > 10 and b_name in d_name):
            if d_org and b_org and d_org != b_org:
                return False, "wrong_project_source_mismatch"
            return True, "project_identity_confirmed"
        else:
            return False, "wrong_project_source_mismatch"

    return False, "wrong_project_source_mismatch"


@dataclass
class PublicTenderBenchmark:
    """Public tender benchmark definition loaded from standardized manifest suite."""

    benchmark_id: str
    project_name: str
    organization: str
    tender_reference: str
    status: str = "candidate_seed"
    source_manifest: Dict[str, Any] = field(default_factory=dict)
    download_manifest: Dict[str, Any] = field(default_factory=dict)
    expected_project: Dict[str, Any] = field(default_factory=dict)
    expected_boq_summary: Dict[str, Any] = field(default_factory=dict)
    benchmark_rules: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_verified(self) -> bool:
        """True only if benchmark is verified against real retrieved tender files."""
        return self.status == "verified_public_benchmark"

    @property
    def is_candidate_unverified(self) -> bool:
        """True if benchmark is an unverified candidate seed."""
        return self.status in ("candidate_unverified", "candidate_seed")

    @classmethod
    def load(
        cls,
        benchmark_id: str,
        base_dir: Path | str = "benchmarks/public_tenders",
    ) -> "PublicTenderBenchmark":
        """Load public tender benchmark from its manifest directory."""
        target_dir = Path(base_dir) / benchmark_id
        if not target_dir.exists():
            raise FileNotFoundError(f"Public tender benchmark '{benchmark_id}' not found at {target_dir}")

        source = json.loads((target_dir / "source_manifest.json").read_text(encoding="utf-8"))
        download = json.loads((target_dir / "download_manifest.json").read_text(encoding="utf-8"))
        project = json.loads((target_dir / "expected_project.json").read_text(encoding="utf-8"))
        boq = json.loads((target_dir / "expected_boq_summary.json").read_text(encoding="utf-8"))
        rules = json.loads((target_dir / "benchmark_rules.json").read_text(encoding="utf-8"))

        return cls(
            benchmark_id=benchmark_id,
            project_name=project.get("project_name", source.get("project_name", "")),
            organization=project.get("organization", source.get("client", "")),
            tender_reference=download.get("tender_reference", source.get("project_number", "")),
            status=source.get("status", "candidate_seed"),
            source_manifest=source,
            download_manifest=download,
            expected_project=project,
            expected_boq_summary=boq,
            benchmark_rules=rules,
        )

    def validate_source_files(self, drawings_filename: str, boq_filename: str) -> Tuple[bool, str]:
        """Validate that candidate drawings and BOQ are valid for this benchmark."""
        rejected = self.source_manifest.get("rejected_comparison_sources", [])
        for r in rejected:
            if r in boq_filename or boq_filename in r:
                return False, "wrong_project_source_mismatch"

        allowed = self.source_manifest.get("allowed_comparison_sources", [])
        doc_files = [d.get("filename") for d in self.download_manifest.get("documents", [])]
        known_valid = set(allowed + [d for d in doc_files if d])

        if not any(k in boq_filename or boq_filename in k for k in known_valid):
            return False, "wrong_project_source_mismatch"

        return True, "project_identity_confirmed"

    def validate_download_hash(
        self,
        filepath: Path | str,
        filename: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Compute SHA-256 of file and verify against download_manifest."""
        f_path = Path(filepath)
        if not f_path.exists() or not f_path.is_file():
            return False, f"file_not_found: {f_path}"

        h = hashlib.sha256(f_path.read_bytes()).hexdigest()
        lookup_name = filename or f_path.name

        docs = self.download_manifest.get("documents", [])
        matching_doc = next((d for d in docs if d.get("filename") == lookup_name), None)
        if not matching_doc:
            # Fallback to first document if single
            if len(docs) == 1:
                matching_doc = docs[0]
            else:
                return False, f"document_not_in_manifest: {lookup_name}"

        expected_sha = matching_doc.get("sha256", "")
        if h.lower() != expected_sha.lower():
            return False, f"sha256_mismatch: expected {expected_sha} got {h}"

        return True, "sha256_verified"

    def evaluate_accuracy_summary(
        self,
        predictions: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Evaluate accuracy score while strictly excluding preliminaries from scoring denominator.

        When no real predictions exist, accuracy_score is None and is_scored is False.
        Never awards 100% accuracy merely because predictions are absent.
        """
        boq = self.expected_boq_summary
        breakdown = boq.get("classified_breakdown", {})

        prelim_count = breakdown.get("preliminaries", boq.get("preliminaries_count", 0))
        provisional_count = breakdown.get("provisional_sum", boq.get("provisional_sums_count", 0))
        rate_only_count = breakdown.get("rate_only", boq.get("rate_only_count", 0))
        measurable_count = (
            breakdown.get("measurable_from_drawings", 0)
            + breakdown.get("schedule_extractable", 0)
        )
        total_items = boq.get("total_line_items", 0)

        # Fail-closed guard: Unverified candidate seeds cannot be scored in headline metrics
        if self.is_candidate_unverified and predictions is not None:
            return {
                "benchmark_id": self.benchmark_id,
                "status": self.status,
                "total_line_items": total_items,
                "measurable_items_count": measurable_count,
                "preliminaries_excluded_count": prelim_count,
                "provisional_sums_count": provisional_count,
                "rate_only_count": rate_only_count,
                "accuracy_score": None,
                "benchmark_status": "candidate_unverified",
                "is_scored": False,
                "is_valid": False,
                "error": "unverified_candidate_seed_cannot_contribute_to_accuracy_metrics",
            }

        # If no predictions provided, return candidate_unscored
        if predictions is None or len(predictions) == 0:
            return {
                "benchmark_id": self.benchmark_id,
                "status": self.status,
                "total_line_items": total_items,
                "measurable_items_count": measurable_count,
                "preliminaries_excluded_count": prelim_count,
                "provisional_sums_count": provisional_count,
                "rate_only_count": rate_only_count,
                "accuracy_score": None,
                "benchmark_status": "candidate_unscored" if not self.is_candidate_unverified else "candidate_unverified",
                "is_scored": False,
                "is_valid": True,
            }

        # Real predictions provided: compare against expected sample measurable items
        sample_items = boq.get("sample_measurable_items", [])
        if not sample_items:
            return {
                "benchmark_id": self.benchmark_id,
                "status": self.status,
                "total_line_items": total_items,
                "measurable_items_count": measurable_count,
                "accuracy_score": None,
                "benchmark_status": "no_sample_items_defined",
                "is_scored": False,
                "is_valid": False,
            }

        pred_map: Dict[str, float] = {}
        for p in predictions:
            pid = str(p.get("item_id", p.get("line_id", p.get("quantity_id", ""))))
            val = float(p.get("value", p.get("quantity", p.get("actual", 0.0))))
            if pid:
                pred_map[pid] = val

        item_results = []
        pass_count = 0
        fail_count = 0
        missing_count = 0

        tolerances = self.benchmark_rules.get("tolerances", {})

        for exp in sample_items:
            iid = exp.get("item_id", "")
            exp_val = float(exp.get("expected_quantity", 0.0))
            category = exp.get("category", "")

            # Preliminaries and provisional sums must never be penalized
            if category in (BOQLineCategory.PRELIMINARIES.value, BOQLineCategory.PROVISIONAL_SUM.value):
                continue

            if iid not in pred_map:
                item_results.append({
                    "item_id": iid,
                    "description": exp.get("description", ""),
                    "expected": exp_val,
                    "actual": None,
                    "status": "missing",
                    "drawing_sheet": exp.get("drawing_sheet"),
                    "drawing_page": exp.get("drawing_page"),
                })
                missing_count += 1
                fail_count += 1
                continue

            act_val = pred_map[iid]
            delta = act_val - exp_val
            pct_delta = (abs(delta) / exp_val * 100.0) if exp_val != 0 else 0.0

            # Determine tolerance
            is_exact = any(k in iid.lower() or k in exp.get("description", "").lower() for k in ["door", "window", "chalkboard", "pillar"])
            tol_pct = 5.0  # default 5% tolerance

            if is_exact:
                is_pass = abs(delta) < 1e-4
            else:
                is_pass = pct_delta <= tol_pct

            if is_pass:
                pass_count += 1
                status = "pass"
            else:
                fail_count += 1
                status = "fail"

            item_results.append({
                "item_id": iid,
                "description": exp.get("description", ""),
                "expected": exp_val,
                "actual": act_val,
                "delta": round(delta, 4),
                "pct_delta": round(pct_delta, 2),
                "tolerance": "exact" if is_exact else f"{tol_pct}%",
                "status": status,
                "drawing_sheet": exp.get("drawing_sheet"),
                "drawing_page": exp.get("drawing_page"),
            })

        total_compared = pass_count + fail_count
        score = (pass_count / total_compared) if total_compared > 0 else 0.0

        return {
            "benchmark_id": self.benchmark_id,
            "status": self.status,
            "total_line_items": total_items,
            "measurable_items_count": measurable_count,
            "compared_items_count": total_compared,
            "passed_items_count": pass_count,
            "failed_items_count": fail_count,
            "missing_items_count": missing_count,
            "preliminaries_excluded_count": prelim_count,
            "provisional_sums_count": provisional_count,
            "rate_only_count": rate_only_count,
            "accuracy_score": round(score, 4),
            "benchmark_status": "scored",
            "is_scored": True,
            "is_valid": True,
            "detailed_results": item_results,
        }


def list_available_public_tender_benchmarks(
    directory: Path | str = "benchmarks/public_tenders",
    strict: bool = False,
) -> List[PublicTenderBenchmark]:
    """Discover and load all registered public tender benchmarks.

    Records load failures in _LAST_BENCHMARK_LOAD_ERRORS rather than silently
    swallowing them.
    """
    global _LAST_BENCHMARK_LOAD_ERRORS
    _LAST_BENCHMARK_LOAD_ERRORS.clear()

    base = Path(directory)
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        return []

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmarks: List[PublicTenderBenchmark] = []

    for entry in data.get("benchmarks", []):
        b_id = entry.get("benchmark_id")
        if not b_id:
            continue
        try:
            bench = PublicTenderBenchmark.load(b_id, base_dir=base)
            benchmarks.append(bench)
        except Exception as err:
            _LAST_BENCHMARK_LOAD_ERRORS[b_id] = str(err)
            if strict:
                raise ValueError(f"Malformed public tender benchmark '{b_id}': {err}") from err

    return benchmarks
