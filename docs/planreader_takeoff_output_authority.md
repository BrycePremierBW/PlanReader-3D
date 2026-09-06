# PlanReader Measurement Authority Output Integration (PR B.4)

## Overview

PlanReader no longer emits bare takeoff numbers. Every takeoff row output must carry complete authority metadata, source trace, confidence score, approval state, revision hash, warnings, blocking reasons, and publishability gating.

Downstream consumers (JobHub publishing, estimators, quotation pipelines) must be able to inspect each number and answer:
- **Where did it come from?** (`source_type`, `source_page`, `source_sheet`, `geometry_ref`, `scale_id`, `dimension_text_id`)
- **Was it figured, scaled, schedule-derived, AI-derived, user-corrected, or approved?**
- **Is it provisional?** (`authority_status == "provisional"`)
- **Is it stale?** (`revision_hash` vs current drawing revision)
- **Can it be commercially published?** (`is_publishable == True`)
- **Why is it blocked?** (`blocking_reasons`)

---

## The Takeoff Output Contract

Every takeoff item emitted conforms to the 20-field `TakeoffOutputRow` structure:

| Field | Type | Description |
|---|---|---|
| `quantity_id` | `str` | Unique item identifier (e.g. `QTY-W001`, `WALL-W104`) |
| `description` | `str` | Item scope description |
| `value` | `float` | Non-negative, strictly finite measurement value |
| `unit` | `str` | Unit of measure (`m`, `m²`, `m³`, `ea`) |
| `trade` | `str` | Trade or scope (`cladding`, `painting`, `plasterboard`, `glazing`, etc.) |
| `source_type` | `str` | Taxonomy source type (see below) |
| `authority_status` | `str` | `firm`, `provisional`, `review_required`, `user_approved`, `blocked`, `excluded`, `reference_only` |
| `confidence` | `float` | Measurement confidence score (0.0 to 1.0) |
| `source_page` | `int \| str \| None` | PDF page number or model source |
| `source_sheet` | `str \| None` | Drawing sheet label (e.g. `WD-03`, `A-101`) |
| `geometry_ref` | `str \| None` | Model element ID (`wall_id`, `surface_id`, `room_id`) |
| `scale_id` | `str \| None` | Associated scale calibration ID |
| `dimension_text_id` | `str \| None` | Figured dimension text annotation ID |
| `benchmark_status` | `str \| None` | Benchmark comparison status (`exact_match`, `within_tolerance`, etc.) |
| `is_publishable` | `bool` | Commercial publishability flag |
| `warnings` | `List[str]` | Non-blocking warnings or notices |
| `blocking_reasons` | `List[str]` | Reasons preventing commercial publication |
| `approved_by` | `str \| None` | Estimator attribution |
| `approved_at` | `str \| None` | ISO 8601 UTC timestamp of approval |
| `revision_hash` | `str \| None` | Revision hash at time of measurement |

---

## Authority & Publishability Matrix

| Source Type | Authority Status | Commercial Publishability Rule |
|---|---|---|
| `documented_dimension` | `firm` | Publishable **only** if current, valid, traceable (`source_page` or `source_sheet` present), **and** linked to a figured-dimension trace (`dimension_text_id`). |
| `schedule_extracted` | `firm` | Publishable **only** if project identity is explicitly confirmed (`project_identity_confirmed is True`) and source trace exists. Identity that was never verified (`None`) blocks the same as an explicit mismatch. |
| `pdf_scaled` | `provisional` | **Provisional / draft only**. Never commercially publishable. Requires a `scale_id` reference (missing scale reference is its own blocking reason), and blocks outright if the referenced scale calibration is `unknown`, `conflicting`, `manual_required`, or `blocked`. |
| `ai_detected` | `provisional` | **Provisional / draft only**. Never commercially publishable — this module has no approval override for AI-detected rows. |
| `model_derived` | `provisional` | Provisional unless user-approved. |
| `user_corrected` | `review_required` | `review_required` until approved by an estimator. |
| `user_approved` | `user_approved` | Publishable if current, non-stale, and valid. |
| `excluded` | `excluded` | **Never publishable**. Scope is explicitly excluded. |
| `reference_only` | `reference_only` | **Never publishable**. Informational reference only. |
| `blocked` | `blocked` | **Never publishable**. Fails closed on missing scale, bad geometry, or conflicts. |

---

## Fail-Closed Invariants

1. **Non-finite numbers**: `NaN`, `+inf`, `-inf` immediately fail closed with `ValueError` or `authority_status="blocked"`.
2. **Negative quantities**: Negative quantities fail closed with `ValueError` or `authority_status="blocked"`.
3. **Invalid zeroes**: Where `allow_zero=False`, a zero measurement is blocked from publication.
4. **Stale drawings**: If `revision_hash != current_revision_hash`, publication is blocked with a stale revision warning.
5. **Scale conflicts**: If referencing a scale calibration with status `unknown`, `conflicting`, `manual_required`, or `blocked`, the takeoff row fails closed to `blocked`.
6. **Tamper detection**: `compute_fingerprint()` calculates a SHA-256 hash across canonical commercial fields. Mutating quantity or status changes the hash.
7. **Unrecognized metadata**: An unrecognized `source_type` or `authority_status` string is not passed through — it fails closed to `authority_status="blocked"` with an explicit blocking reason naming the unrecognized value.
8. **Missing traces**: `documented_dimension` without a `dimension_text_id`, and `pdf_scaled` without a `scale_id`, each add their own specific blocking reason rather than merely being flagged as generically untraceable.
