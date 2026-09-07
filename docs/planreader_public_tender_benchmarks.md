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

## 5. Registered Seed Benchmarks
1. **`ungm_unops_wecc_torit`**: UNOPS WECC Torit Vocational Training Centre (ITB/2023/45890).
2. **`ungm_category_iv_housing_units`**: UN-Habitat Category IV Housing Units (ITB/2023/CAT4-H).
3. **`ungm_category_iv_shelters`**: IOM Category IV Shelters / House Units (RFP/2024/CAT4-S).
4. **`ungm_fmns_faculty_building`**: UNDP FMNS Faculty Building (ITB/2023/FMNS-08).
5. **`ungm_al_qayarah_hospital_renovation`**: UNDP Al Qayarah General Hospital Renovation (RFP/2024/78912).
6. **`king_st_122_126`**: 122-126 King St, Buderim Commercial/Residential Development (23-060).

## 6. How to Add a New Public Tender Benchmark
1. Create directory `benchmarks/public_tenders/<new_benchmark_id>/`.
2. Populate the 5 required JSON manifests conforming to schema.
3. Register the benchmark entry in `benchmarks/public_tenders/manifest.json`.
4. Run validation tests:
   ```bash
   python -m pytest -q tests/benchmarks/test_public_tender_manifest_schema.py
   python -m pytest -q tests/benchmarks/test_public_tender_project_matching.py
   python -m pytest -q tests/benchmarks/test_public_tender_benchmark_runner.py
   ```
