# PlanReader Public Tender Benchmark — Executive Headline Accuracy Dashboard

**Generated**: `2026-09-07T10:34:58.322961+00:00`

> **Official Headline Accuracy**: **`28.6%`** across `2` headline-verified public tender benchmark(s).  
> **Strict Exact Accuracy** (zero-tolerance): **`28.6%`**.

## 1. Executive Headline Metrics (1:1 Material Scope Packages)

| Metric | Value | Description |
| :--- | :--- | :--- |
| **Headline Overall Accuracy (<= 5% tol)** | **`28.6%`** | Combined exact matches and <= 5% tolerance across headline benchmarks |
| **Headline Strict Exact Accuracy** | **`28.6%`** | Zero-tolerance exact numerical matches across headline benchmarks |
| Scored Headline Benchmarks | `2` | Verified packages with 1:1 physical drawing-to-BOQ scope match |
| Measurable Items Evaluated | `22` | Total expected architectural takeoff items |
| Total Items Compared (Denominator) | `28` | Expected items + hallucinated extra predictions across packages |
| Exact Matches | `8` | Exactly matched quantities |
| Within 5% Tolerance | `0` | Minor variations within 5% tolerance |
| Within 10% Tolerance | `0` | Minor variations (5% to 10%) |
| Within 20% Tolerance | `1` | Moderate variations (10% to 20%) |
| Gross Mismatches (> 20%) | `10` | Discrepancies exceeding 20% |
| Missed in Extraction | `3` | BOQ items missing from drawing predictions |
| Hallucinated Extra Predictions | `6` | Predictions with no counterpart in BOQ |

## 2. Headline Benchmark Breakdown (1:1 Physical Scope Match)

| Benchmark ID | Project Name | Scope | Expected | Compared | Exact | <= 5% | Gross | Missed | Halluc. | Accuracy | Strict % | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `tenders_ke_kstvet_cbc_classroom` | Proposed Construction of CBC Classroom and Integrated Resource Center | 1:1 Match | `12` | `12` | `4` | `0` | `6` | `1` | `0` | **`33.3%`** | `33.3%` | `verified_scored_benchmark` |
| `tenders_ke_murera_science_lab` | Proposed Construction of a Science Laboratory at Murera Senior School | 1:1 Match | `10` | `16` | `4` | `0` | `4` | `2` | `6` | **`25.0%`** | `25.0%` | `verified_scored_benchmark` |

## 3. Real-World Scope Divergence Stress Tests (Excluded from Headline)

> **Scope Divergence Stress Tests**: These packages represent authentic tender documents where the architectural drawing set and the Bill of Quantities cover different physical boundaries (e.g., drawings cover a whole facility while the BOQ covers a single wing). They are preserved as real-world stress tests and are excluded from primary headline accuracy scoring.

| Benchmark ID | Project Name | Scope Divergence | Total BOQ Items | Evaluated | Exact | Gross | Missed | Overall Acc | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `tenders_ke_mbagha_maternity_dispensary` | Proposed Construction of a Maternity Block at Mbagha Dispensary in Mwatate Sub-County | Facility drawings vs single-wing BOQ | `123` | `19` | `0` | `7` | `9` | `0.0%` | `verified_scope_mismatch` |

## 4. Candidate Seed Inventory (Unverified / Excluded)

> **Candidate Seeds**: Prospective tender references. They are strictly excluded from headline accuracy metrics until physical drawing and matching BOQ files are retrieved, verified, and scope-audited.

| Benchmark ID | Project Name | Organization | Reference | Status | Headline Eligible |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ungm_unops_wecc_torit` | UNOPS WECC Torit Vocational Training Centre | UNOPS | ITB/2023/45890 | `candidate_unverified` | **No** (Unverified) |
| `ungm_category_iv_housing_units` | UNGM Category IV Housing Units | UN-Habitat | ITB/2023/CAT4-H | `candidate_unverified` | **No** (Unverified) |
| `ungm_category_iv_shelters` | UNGM Category IV Shelters / House Units | IOM / UNGM | RFP/2024/CAT4-S | `candidate_unverified` | **No** (Unverified) |
| `ungm_fmns_faculty_building` | UNGM FMNS Faculty of Mathematical and Natural Sciences Building | UNDP / UNGM | ITB/2023/FMNS-08 | `candidate_unverified` | **No** (Unverified) |
| `ungm_al_qayarah_hospital_renovation` | UNGM Al Qayarah General Hospital Renovation | UNDP / UNGM | RFP/2024/78912 | `candidate_unverified` | **No** (Unverified) |
| `king_st_122_126` | 122-126 King St, Buderim - Construction Issue | Public Tender / Commercial Client | 23-060 | `candidate_unverified` | **No** (Unverified) |

## 5. Non-Penalized Denominator Exclusions

Contractor overheads, site preliminaries, and provisional budget allowances are transparently excluded from physical geometric accuracy:
- **Total Preliminaries Excluded**: `0`
- **Total Provisional Sums Excluded**: `0`
- **Total Non-Architectural Excluded**: `0`
