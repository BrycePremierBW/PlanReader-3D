# PlanReader Public Tender Benchmark Expansion

## 1. Overview and Rationale
PlanReader accuracy verification has historically relied on internal benchmark datasets (e.g. 60–62 School Rd, 92–94 School Rd, LAGO / Birtinya). While these benchmarks provide high-confidence ground truth from real-world projects, external public tender benchmarks provide independent proof that PlanReader is not tuned solely to internal estimating styles or single-contractor drafting practices.

Public tender packages published by international institutions (UNGM, UNOPS, UN-Habitat, IOM, UNDP) and commercial tender platforms feature:
- High-quality architectural drawing sets (PDF).
- Standardized Bills of Quantities (BOQ / Schedule of Rates) prepared by certified quantity surveyors.
- Publicly verifiable references and document hashes.

## 2. Standardized Directory and Manifest Structure
Public tender benchmarks are maintained under `benchmarks/public_tenders/`.

In accordance with repository policies, **large binary PDFs and spreadsheets are not checked into git**. Instead, each benchmark is registered as a metadata-only manifest suite:

```
benchmarks/public_tenders/
├── manifest.json                                # Top-level index of all registered public tender benchmarks
└── <benchmark_id>/
    ├── source_manifest.json                     # Metadata identity, allowed/rejected source files
    ├── download_manifest.json                   # Remote source URL, document roles, and SHA-256 hashes
    ├── expected_project.json                    # Normalised project attributes (levels, buildings, sheets)
    ├── expected_boq_summary.json                # Summary of BOQ line items and classified breakdowns
    └── benchmark_rules.json                     # Comparison tolerances and evaluation rules
```

### Manifest Roles & Requirements
1. **`source_manifest.json`**:
   - `benchmark_id`: Unique identifier string (e.g., `ungm_unops_wecc_torit`).
   - `project_name`: Formal project title.
   - `allowed_comparison_sources`: Whitelist of valid BOQ schedules for this tender.
   - `rejected_comparison_sources`: Explicit list of cross-project files known to cause invalid cross-comparison.
2. **`download_manifest.json`**:
   - `tender_reference`: Official tender reference code (e.g., `ITB/2023/45890`).
   - `publisher`: Issuing organization (e.g., `UNOPS`).
   - `source_url`: Public link to procurement notice.
   - `documents`: List of documents with roles (`architectural_drawings`, `bill_of_quantities`), descriptions, and SHA-256 integrity hashes.
3. **`expected_project.json`**:
   - High-level physical parameters (levels, building count, drawing issues).
4. **`expected_boq_summary.json`**:
   - Total line items count, measurable count, and category breakdown.
   - Sample measurable items with expected quantities and drawing page/sheet traces.
5. **`benchmark_rules.json`**:
   - Accuracy tolerances and scoring rules (e.g., ignore preliminaries in accuracy, require drawing trace).

## 3. BOQ Line Item Classification Taxonomy
A tender BOQ contains many items that are not physical geometric building elements. To measure PlanReader accuracy fairly, items are categorized into a 9-part taxonomy:

| Category | Description | Included in Physical Denominator |
| :--- | :--- | :--- |
| `measurable_from_drawings` | Direct physical measurements (wall linings, render, paint, flooring, tiling) | **Yes** |
| `schedule_extractable` | Counted or scheduled items (doors, windows, sanitary fixtures) | **Yes** |
| `scope_allowance_only` | Non-geometric trade allowances (e.g. mastic sealant allowance) | No |
| `provisional_sum` | Provisional budget allowances (e.g. PS for rock excavation) | No |
| `rate_only` | Unit rates for variations without commitment | No |
| `preliminaries` | Site establishment, supervision, scaffold, insurances | No (Excluded) |
| `not_architectural` | Civil works, drainage, plumbing, electrical switchboards | No |
| `not_applicable_to_planreader` | Out of scope contracts | No |
| `unknown_requires_review` | Unclassified items requiring user/estimator clarification | Flagged |

### Preliminary and Provisional Exclusions
- **Preliminaries Non-Penalization**: Contractor overheads, site hoardings, scaffolding, and supervision must never penalize PlanReader geometric accuracy. They are classified as `preliminaries` and excluded from the physical measurement scoring denominator.
- **Provisional Sums**: Items marked "PS", "Provisional", or generic scope allowances are flagged and excluded from firm physical measurement comparison.
- **Drawing Traceability**: Every item marked `measurable_from_drawings` strictly requires a drawing reference (`drawing_sheet` and/or `drawing_page`). Missing traces are flagged as unverified.

## 4. Project Identity Matching & Fail-Closed Guard
To ensure cross-project data contamination does not occur:
- PlanReader verifies `tender_reference`, `project_name`, and `organization` between drawings and BOQs.
- If a candidate comparison involves mismatched projects (e.g., comparing a UNGM hospital drawing set against a residential townhouse BOQ), the comparison fails closed immediately with:
  `wrong_project_source_mismatch`

## 5. Benchmark Verification Statuses and Registered Datasets

Public tender datasets fall strictly into two statuses:
- `verified_public_benchmark`: Real public tender documents have been retrieved, page counts and SHA-256 integrity hashes computed from actual files, project identity confirmed between drawings and BOQ, and measurable lines mapped to exact drawing sheets. Only verified benchmarks may contribute to headline accuracy metrics.
- `candidate_unverified`: Manifest seed metadata awaiting verified document retrieval. Candidate seeds are barred from contributing to headline accuracy metrics (`error="unverified_candidate_seed_cannot_contribute_to_accuracy_metrics"`).

### Verified Public Benchmarks (Tier 1)
1. **`tenders_ke_kstvet_cbc_classroom`**: Proposed Construction of CBC Classroom and Integrated Resource Center.
   - **Issuing Entity**: Ministry of Education / State Department of Basic Education, Republic of Kenya / Kenya School of TVET (KSTVET).
   - **Tender Reference**: `KSTVET/008/24` | Drawing No: `KSTVET/08/2024-AD01`, `E-1`.
   - **Source URL**: `https://tenders.go.ke/storage/Documents/1727358888238-bq-nd-drawing.pdf`.
   - **File Size / SHA-256**: 1,273,202 bytes | `6856bfa739aa136dd8e0bf17cb25fd43d0d31c9c3dfe3252525454f09d8fa4dc`.
   - **Structure**: 55-page combined document containing complete Bills of Quantities (pages 1–53) and verified architectural drawings (pages 54–55, 1:75 scale, ground floor plan, elevations E-02–E-05, sections S-02/S-03, electrical layout).
   - **Measurable Samples**: 12 verified items traced to page 54 (150mm block walling 58m², 150mm gable walling 13m², steel casement windows 3000x1200mm & 2900x1200mm, red oxide floor screed 97m², internal plaster/paint 69m², verandah pillars 4 NO).

### Candidate Seeds (Unverified)
The following candidate seeds remain registered for future retrieval and verification:
- `ungm_unops_wecc_torit`: UNOPS WECC Torit Vocational Training Centre (ITB/2023/45890).
- `ungm_category_iv_housing_units`: UN-Habitat Category IV Housing Units (ITB/2023/CAT4-H).
- `ungm_category_iv_shelters`: IOM Category IV Shelters / House Units (RFP/2024/CAT4-S).
- `ungm_fmns_faculty_building`: UNDP FMNS Faculty Building (ITB/2023/FMNS-08).
- `ungm_al_qayarah_hospital_renovation`: UNDP Al Qayarah General Hospital Renovation (RFP/2024/78912).
- `king_st_122_126`: 122-126 King St, Buderim Commercial/Residential Development (23-060).

## 6. Document Integrity Validation
PlanReader enforces file integrity via `validate_download_hash(benchmark_id, filename, file_path)`:
- Computes SHA-256 checksum of downloaded files outside git storage.
- Matches against the recorded SHA-256 in `download_manifest.json`.
- Mismatched hashes or missing files raise explicit validation errors and fail closed.

## 7. Accuracy Scoring Rules & Fail-Closed Guardrails
When running `evaluate_accuracy_summary()` against a benchmark:
1. **Unscored Candidate State**: If no predictions are supplied (`predictions=None`), the evaluation returns `accuracy_score = None`, `benchmark_status = "candidate_unscored"`, and `is_scored = False`. PlanReader never awards 100% or synthetic scores when predictions have not been evaluated.
2. **Candidate Gate**: Candidate unverified benchmarks raise a blocked evaluation error if attempted in headline scoring.
3. **Physical Denominator**: Only items marked `measurable_from_drawings` or `schedule_extractable` form the accuracy denominator. Preliminaries, provisional sums, and rate-only items are completely excluded.
4. **Tolerance Matching**: Quantities within defined tolerances (e.g. ±5% for walling/render, exact count for doors/windows) pass; missing or out-of-tolerance items fail.

## 8. Benchmark Accuracy Engine (`pb_benchmark_accuracy_engine.py`)

PlanReader provides an independent evaluation engine (`pb_benchmark_accuracy_engine.py`) that compares native drawing extractions or candidate predictions against ground-truth public tender BOQs.

### Multi-Tier Tolerance Classification
Each item comparison is categorized into strict tolerance tiers:
- **`exact_match`**: Zero-tolerance match (`|actual - expected| < 1e-4`). Count items (doors, windows, chalkboards, pillars) strictly require exact matches.
- **`within_5_percent`**: Linear and area finishes within 5% tolerance (e.g. wall plaster, paint, floor screed).
- **`within_10_percent`**: Minor variations between 5% and 10%.
- **`within_20_percent`**: Moderate variations between 10% and 20%.
- **`gross_mismatch`**: Severe divergences exceeding 20% error, or any non-zero deviation on count-based fixtures. Flagged for commercial review.
- **`missed_in_extraction`**: Measurable items present in the BOQ but missing from the extraction output. Directly penalizes accuracy.
- **`hallucinated_item`**: Quantities generated by extraction that have no corresponding counterpart in the verified BOQ or drawings. Expands the comparison denominator and directly penalizes accuracy.
- **`excluded_preliminary` / `excluded_provisional`**: Non-geometric items excluded from the physical measurement denominator.

### Scoring Formulas
$$\text{Total Items Compared} = \text{Measurable Expected Items} + \text{Hallucinated Items}$$
$$\text{Overall Accuracy (\%)} = \frac{\text{Exact Matches} + \text{Within 5\% Matches}}{\text{Total Items Compared}} \times 100$$
$$\text{Strict Exact Accuracy (\%)} = \frac{\text{Exact Matches}}{\text{Total Items Compared}} \times 100$$

## 9. CLI Execution and Report Outputs

Evaluate a public tender benchmark and output JSON and Markdown reports:
```bash
# Direct engine invocation
python pb_benchmark_accuracy_engine.py --benchmark tenders_ke_kstvet_cbc_classroom

# Unified PlanReader benchmark script
python scripts/run_planreader_benchmarks.py --public-tender tenders_ke_kstvet_cbc_classroom
```

Reports are automatically generated under `benchmark_results/`:
- `<benchmark_id>_accuracy_report.json`: Machine-readable payload containing full summary metrics, itemized comparison records, deltas, percentage errors, and drawing trace citations.
- `<benchmark_id>_accuracy_report.md`: Formatted GitHub Markdown document with executive badges, exclusion disclosures, detailed item breakdown tables, and highlighted sections for gross mismatches, missed items, and hallucinations.

## 10. How to Add or Verify a Public Tender Benchmark
1. Search public procurement portals for packages containing both drawings and BOQ/takeoffs.
2. Download documents to external storage outside git and calculate SHA-256 and page counts.
3. Confirm project identity matches between drawing title blocks and BOQ cover/summary.
4. Create or update directory `benchmarks/public_tenders/<benchmark_id>/` with the 5 required JSON manifests.
5. Set `status: "verified_public_benchmark"` in `source_manifest.json` and `manifest.json`.
6. Trace measurable items to specific drawing sheets and page numbers.
7. Run validation tests:
   ```bash
   python -m pytest -q tests/benchmarks/test_public_tender_manifest_schema.py
   python -m pytest -q tests/benchmarks/test_public_tender_project_matching.py
   python -m pytest -q tests/benchmarks/test_public_tender_benchmark_runner.py
   python -m pytest -q tests/benchmarks/test_public_tender_verified_benchmark.py
   python -m pytest -q tests/benchmarks/test_benchmark_accuracy_engine.py
   ```
