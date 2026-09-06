# PlanReader → JobHub Publishing Pipeline

## Overview
The PlanReader → JobHub Publishing Pipeline (`pb_jobhub_publishing_contract.py` and `pb_jobhub_publishing_pipeline.py`) establishes a stable, traceable, and fail-closed data contract for transferring measurement takeoffs, drawing revisions, and pricing data from PlanReader into JobHub commercial jobs.

---

## 1. Publishing Data Contract
A publishing package (`PublishingPackagePayload`) encapsulates the entire release context:

```json
{
  "workspace_id": 1,
  "mode": "commercial",
  "project_identity": {
    "job_no": "26-017",
    "job_name": "60-62 School Rd Maroochydore",
    "site_address": "60-62 School Rd, Maroochydore QLD 4558",
    "builder_client": "Balleo Pty Ltd",
    "estimator": "Bryce Curran",
    "target_jobhub_job_id": 501
  },
  "drawing_revision": {
    "drawing_issue": "BA Issue 1",
    "drawing_date": "2026-06-09",
    "sheet_count": 36,
    "source_files_hash": "a4f8e...",
    "file_names": ["Architectural_Plans_RevC.pdf"]
  },
  "benchmark_status": {
    "benchmark_id": "school_rd_60_62",
    "is_compatible": true,
    "match_status": "project_identity_confirmed",
    "tolerance_passed": true,
    "summary": "Verified against 60-62 School Rd golden manifest"
  },
  "quantities": [
    {
      "row_id": 1,
      "section": "Internal walls and ceilings",
      "location": "Level 1",
      "substrate": "Plasterboard",
      "finish_tag": "PB01",
      "element": "Internal Wall",
      "unit": "m2",
      "quantity": 150.0,
      "rate": 22.0,
      "total_price": 3300.0,
      "authority_type": "documented_dimension",
      "authority_status": "firm",
      "confidence": 1.0,
      "approved_by": "Bryce Curran"
    }
  ],
  "excluded_items": [
    {
      "item_code": "ALUM",
      "description": "Aluminium Window Frame",
      "reason": "Factory powdercoated joinery non-paint trade scope"
    }
  ],
  "preflight_fingerprint": "fp_9b83a...",
  "payload_hash": "sha256_d1e8..."
}
```

---

## 2. Publishing Modes

| Mode | Purpose | Provisional Quantities | AI / Model Derivations | Resulting JobHub Status |
|---|---|---|---|---|
| `DRAFT` | Estimator draft reviews, preliminary costing | Allowed (marked with warning notices) | Allowed provisionally | `Draft` |
| `COMMERCIAL` | Contractual tenders, formal quotation, subcontracts | **STRICTLY BLOCKED** | **BLOCKED** unless explicitly approved by estimator | `Published` |

---

## 3. Fail-Closed Publishing Gate Invariants

1. **Project Identity Gating**:
   - `job_no` and `job_name` are strictly required.
   - Cross-project conflicts (e.g. 60-62 School Rd vs 92-94 School Rd, or LAGO Birtinya vs School Rd) strictly block publishing.
   - If a benchmark match status is `wrong_project_source_mismatch`, publishing is blocked.

2. **Commercial Authority Enforcement**:
   - Any row marked `provisional` or `review_required` blocks commercial release.
   - Any row derived from `ai_detected` or `model_derived` requires explicit `approved_by` estimator attribution.

3. **Numeric Sanity & Non-Negative Invariants**:
   - Zero-quantity packages are blocked.
   - Negative quantities, rates, or totals are strictly blocked.
   - Non-finite numbers (`NaN`, `Inf`, `-Inf`) are strictly blocked.

4. **TOCTOU & Duplicate Protection**:
   - `payload_hash` is computed deterministically across all line items and identities.
   - If the preflight fingerprint or payload hash has mutated since calculation, publishing is blocked.
   - Re-publishing an identical package to the same JobHub job is rejected as a duplicate.
