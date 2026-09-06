# PlanReader → JobHub Publishing Contract & Preflight Gate (PR C)

## Overview

PR C defines the safe, attributable payload contract and fail-closed preflight gate for transmitting PlanReader measurement and takeoff datasets to JobHub.

The goal of this contract is not to inject raw numbers into JobHub, but to ensure that **every quantity entering JobHub is traceable, fingerprinted, authority-checked, and either safely publishable or explicitly blocked**.

---

## 1. Top-Level Payload Contract (`PlanReaderJobHubPayload`)

Every publishing payload emitted to JobHub contains:

| Field | Type | Description |
|---|---|---|
| `project_identity` | `dict` | Project metadata (`project_id`, `project_name`, `identity_confirmed`, etc.) |
| `drawing_revision` | `dict` | Drawing revision set (`revision_id`, `revision_hash`, `revision_date`) |
| `benchmark_status` | `dict \| None` | Baseline accuracy benchmark metrics if evaluated |
| `authority_summary` | `dict` | Readiness metrics (`total_count`, `publishable_count`, `commercial_readiness_pct`) |
| `quantities` | `List[PlanReaderJobHubQuantityRow]` | Attributable takeoff rows with individual SHA-256 fingerprints |
| `excluded_items` | `List[dict]` | Explicitly excluded scope items |
| `warnings` | `List[str]` | Non-blocking notices and draft advisories |
| `blocking_reasons` | `List[str]` | Blocking reasons preventing commercial release |
| `source_files` | `List[str]` | Drawing PDFs and takeoff source files |
| `created_at` | `str` | ISO 8601 UTC creation timestamp |
| `created_by` | `str` | Estimator attribution |
| `publish_mode` | `str` | `commercial_publish` or `draft_publish` |
| `payload_fingerprint` | `str` | SHA-256 hash across canonical payload fields |
| `is_commercial_ready` | `bool` | True only for passing commercial release packages |

---

## 2. Quantity Row Contract (`PlanReaderJobHubQuantityRow`)

Each takeoff row carries 21 fields:
1. `quantity_id`
2. `description`
3. `value`
4. `unit`
5. `trade`
6. `source_type`
7. `authority_status`
8. `confidence`
9. `source_page`
10. `source_sheet`
11. `geometry_ref`
12. `scale_id`
13. `dimension_text_id`
14. `benchmark_status`
15. `is_publishable`
16. `warnings`
17. `blocking_reasons`
18. `approved_by`
19. `approved_at`
20. `revision_hash`
21. `fingerprint` (SHA-256 hash over commercial fields)

---

## 3. Publish Modes & Fail-Closed Gate

### `commercial_publish`
- Only permits rows where `is_publishable == True`.
- Rejects unapproved AI / model-derived rows.
- Rejects provisional scaled geometry.
- Rejects stale revisions (`row.revision_hash != drawing_revision.revision_hash`).
- Rejects project identity mismatches or unknown project identities.
- Rejects missing authority metadata.
- Rejects excluded, reference-only, or blocked rows.
- Rejects non-finite (NaN, inf), negative, or invalid zero quantities.

### `draft_publish`
- Permits provisional, scaled, and AI rows.
- Stamped with explicit non-commercial warning: `contains non-commercial quantities; NOT approved JobHub cost data`.
- Sets `is_commercial_ready = False`.
- Preserves all row-level warnings and blocking reasons.
