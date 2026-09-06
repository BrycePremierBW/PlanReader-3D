# PlanReader Golden Plan Accuracy & Regression Report

**Generated**: 2026-09-06T14:39:33.101047+00:00  
**Benchmarks Evaluated**: 4  
**Accuracy Score**: 84.2%  
**Commercial Readiness**: 94.7%  

---

## Summary Metrics

| Metric | Count | Description |
|---|---|---|
| Total Expected Quantities | 19 | Benchmark baseline items |
| Exact Matches | 16 | 0% variance against benchmark |
| Within Tolerance | 0 | Within acceptable tolerance threshold |
| Outside Tolerance | 1 | Variance exceeds tolerance |
| Missing Items | 1 | Expected items not extracted |
| Blocked Benchmarks | 0 | Correctly rejected mismatched projects |
| Provisional Items | 1 | Reference/provisional quantities |

---

## Benchmark Manifest Matrix

| Benchmark ID | Project Name | Status | Expected Items | Exact | Within Tol |
|---|---|---|---|---|---|
| `king_st_122_126` | 122-126 King St, Buderim - Construction Issue 4 (G) | **VERIFIED / BENCHMARKED** | 1 | 1 | 0 |
| `lago_britinya` | CUBE DEVELOPMENTS - LAGO DD | **VERIFIED / BENCHMARKED** | 4 | 4 | 0 |
| `school_rd_60_62` | 60-62 School Rd Maroochydore - Proposed Townhouse Development | **VERIFIED / BENCHMARKED** | 10 | 9 | 0 |
| `school_rd_92_94` | COX PROPERTY GROUP - ELISE | **VERIFIED / BENCHMARKED** | 4 | 2 | 0 |

---

## Top Error Taxonomy Drivers

- **`project_mismatch`**: 0 occurrence(s)
- **`scale_error`**: 0 occurrence(s)
- **`height_unknown`**: 0 occurrence(s)

---

## Recommended Next Fixes

1. Maintain project identity matching gate to keep cross-project takeoffs blocked.
1. Enforce AS 4041 opening deductions (>0.5 m2 deduct, <=0.5 m2 do not) across all wall takeoff paths.
1. Promote provisional geometry to firm only upon explicit estimator approval.
1. Publish only firm, verified quantities with non-stale preflight fingerprints to JobHub.
