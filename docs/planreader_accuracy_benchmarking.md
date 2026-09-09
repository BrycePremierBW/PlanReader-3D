# PlanReader Accuracy Benchmarking Framework

## Overview
The PlanReader Accuracy Benchmarking Framework provides an independent, reproducible, ground-truth-backed evaluation system for architectural plan interpretation, quantity takeoff, and project validation.

Its primary mission is to prevent **project identity hallucination**, **mismatched comparison laundering**, and **unauthorized commercial claims** by strictly enforcing:
1. **Explicit Project Identity Matching**: Every plan and takeoff must match verified project identifiers (project number, address, client) before comparisons are permitted.
2. **Fail-Closed Mismatch Gating**: Comparing mismatched sets (e.g. 60-62 School Rd against 92-94 School Rd, or LAGO Birtinya against residential takeoffs) fails closed with `wrong_project_source_mismatch`.
3. **Provisional Authority Discipline**: Unverified AI detections, model surface estimates, and uncalibrated geometry remain classified as `provisional` or `reference_only` and are prohibited from firm commercial claims.

---

## Directory Structure
Benchmark configurations live in declarative JSON files under `benchmarks/plans/`:

```text
benchmarks/
  plans/
    school_rd_60_62/
      source_manifest.json          # Project metadata, source file names, allowed/rejected lists
      expected_project.json         # Documented project identity (GFA, units, levels, sheets)
      expected_quantities.json      # Ground truth quantities with source references & tolerances
      expected_schedules.json       # Door, window, and finish schedule expectations
      expected_render_pages.json    # Architectural render / 3D sheet references
      tolerances.json               # Absolute & percentage tolerance policies
      notes.md                      # Engineering context & notes

    lago_britinya/
      ...

    school_rd_92_94/
      ...

    king_st_122_126/
      ...
```

---

## Source Manifest Specification
Every benchmark contains a `source_manifest.json` adhering to `SOURCE_MANIFEST_SCHEMA`:

```json
{
  "benchmark_id": "school_rd_60_62",
  "project_name": "60-62 School Rd Maroochydore - Proposed Townhouse Development",
  "project_number": "26-017",
  "client": "Balleo Pty Ltd",
  "drawing_issue": "BA Issue",
  "drawing_date": "09.06.2026",
  "source_pdf": "26-017 - 60-62 School Rd Maroochydore - BA Issue (1) - 09.06.26.pdf",
  "source_takeoff": "Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx",
  "allowed_comparison_sources": [
    "Premier_Brushworks_60-62_School_Rd_Maroochydore_Revised.xlsx"
  ],
  "rejected_comparison_sources": [
    "Premier_Brushworks_92-94_School_Rd_Full_Painting_Takeoff.xlsx"
  ],
  "status": "benchmark_seed"
}
```

---

## Project Identity Matching Policy
The matching engine (`pb_project_identity.py`) extracts title block data from PDFs and summary worksheets from workbooks, checking:
1. **Manifest Restrictions**: If `takeoff_filename` matches an entry in `rejected_comparison_sources`, comparison is blocked immediately (`wrong_project_source_mismatch`).
2. **Project Number**: Strict match required (e.g. `26-017` vs `26-017`). Conflicting project numbers trigger immediate failure.
3. **Site Address**: Validates street number and locality (e.g. `60-62 School Rd` vs `92-94 School Rd` triggers failure).
4. **Project / Client Name**: Verified against known aliases.
5. **Ambiguous Metadata**: Missing identity fails closed with `manual_review_required`.

---

## Authority & Scope Disposition
Every quantity record carries an explicit authority type:
- `documented`: Documented on the drawing or in written specifications.
- `schedule_extracted`: Extracted from door/window/finish schedules.
- `pdf_scaled`: Derived from verified pixel/vector linework with calibrated scale.
- `provisional`: Estimated or AI-derived without geometric verification.
- `excluded`: Explicitly excluded from quote / commercial total (e.g. internal doors in revised multi-unit takeoff).
- `reference_only`: Used for audit, QA, or cross-checks, not billed quantities.

---

## Running Benchmarks

### CLI Usage
```bash
# Run a specific benchmark
python scripts/run_planreader_benchmarks.py --benchmark school_rd_60_62

# Run all benchmarks
python scripts/run_planreader_benchmarks.py --all

# Run with file overrides
python scripts/run_planreader_benchmarks.py --benchmark school_rd_60_62 --pdf "path/to/plan.pdf" --takeoff "path/to/takeoff.xlsx"
```

### Output Reports
Internal golden-plan results are written to `benchmark_results/<benchmark_id>_results.json` containing:
- `project_identity`: Extracted identity details.
- `comparison_allowed`: Boolean status and rejection reason.
- `pages_classified`: Breakdown of page roles and detected render sheets.
- `quantities_compared`: Detailed line-by-line comparison with diff, diff %, status, confidence, and source trace.
- `summary`: Overall accuracy, pass/fail counts, and readiness scores.

Public-tender suite evaluation (`python pb_benchmark_accuracy_engine.py --all`) publishes an atomic report set under `benchmark_results/runs/<run_id>/` and points `benchmark_results/current.json` at that run only after every project report and the combined summary are complete. Compatibility dashboard and per-project files are copied from that same run. Do not compare a newly regenerated combined dashboard against project reports from an earlier commit or run ID.
