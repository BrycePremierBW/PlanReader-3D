# PlanReader AI Takeoff & Learning Ledger

## Overview
The AI Takeoff & Learning Ledger subsystem (`pb_takeoff_learning_ledger.py`) provides:
1. **Strict AI Draft Flow**: AI-extracted quantities are treated strictly as preliminary drafts (`provisional` authority, explicit uncertainty flags, review required). No hidden, unreviewed AI numbers can ever bypass commercial review into JobHub.
2. **Standardized Error Taxonomy**: 16 categorized error drivers explaining why PlanReader was wrong on any measurement or classification.
3. **Takeoff Learning Ledger**: A structured audit log capturing AI detections, application measurements, user corrections, final approved quantities, confidence deltas, and project characteristics. This forms PlanReader's continuous model training dataset.
4. **Golden Plan Accuracy & Regression Report**: An automated benchmarking tool that scores all golden seeds (`school_rd_60_62`, `lago_britinya`, `school_rd_92_94`, `king_st_122_126`), verifies project mismatch gating, and outputs `benchmark_results/accuracy_report.md`.

---

## 1. AI Draft Takeoff Architecture

```text
Architectural PDF
   └── Page Classification
         └── AI / Model Linework & Tag Detection
               └── AIDraftTakeoffRow (provisional, confidence, source region, uncertainty flags)
                     └── Estimator Review / 3D Correction
                           └── TakeoffLearningLedger (records correction delta & error reason)
                                 └── Benchmark Validation
                                       └── Estimator Sign-Off (authority = firm)
                                             └── Preflight & JobHub Commercial Publish
```

### Invariants
- `detected_quantity`: Finite, non-negative number.
- `confidence`: Between `0.0` and `1.0`.
- `authority_status`: Default `provisional`; requires explicit user review.

---

## 2. Standardized Error Taxonomy (16 Categories)

| Category | Description |
|---|---|
| `scale_error` | Missing, unverified, or miscalculated drawing scale |
| `ocr_error` | Misread title block, room name, or schedule text |
| `wrong_dimension_selected` | Wrong string selected when multiple dimensions present |
| `opening_missed` | Window, door, or void opening omitted from wall deduction |
| `opening_double_counted` | Overlapping opening deducted multiple times |
| `wall_false_positive` | Non-wall linework (gridlines, boundaries) treated as wall |
| `wall_missing` | Wall segment undetected in room polygon |
| `finish_tag_wrong` | Misidentified material tag (e.g. EC01 vs EC02) |
| `schedule_row_misread` | Door/window schedule dimension table misread |
| `project_mismatch` | Attempted comparison of mismatched projects (rejected by gate) |
| `wrong_revision` | Outdated drawing issue or superseded revision |
| `height_unknown` | Unspecified wall height (fails closed to review required) |
| `raked_wall_not_handled` | Sloped or variable gable wall height |
| `stair_area_complex` | Double-height void or stair flight perimeter |
| `factory_finish_excluded` | Factory-finished joinery, powdercoat, or screed |
| `scope_rule_wrong` | Trade scope inclusion/exclusion rule error |

---

## 3. Learning Ledger & Training Dataset

Every correction records:
- `benchmark_or_job_id`: Target project identifier.
- `object_id` & `object_type`: Entity affected (`wall`, `opening`, `room`, `ceiling`, `gfa`).
- `planreader_measured_value`: App measurement before correction.
- `user_corrected_value`: Ground truth established by estimator.
- `error_reason`: Taxonomy category above.
- `confidence_before` & `confidence_after`: Confidence score delta.
- `project_type` & `drawing_style`: Project typology for stratified model training.

---

## 4. Golden Plan Accuracy Matrix

Run the automated accuracy matrix to evaluate regression health:

```python
from pb_takeoff_learning_ledger import generate_golden_plan_accuracy_report

report = generate_golden_plan_accuracy_report(
    benchmark_dir="benchmarks/plans",
    output_dir="benchmark_results",
)
```

Outputs:
- `benchmark_results/accuracy_report.md`: Markdown summary table for review.
- `benchmark_results/accuracy_report.json`: Machine-readable results and error distributions.
