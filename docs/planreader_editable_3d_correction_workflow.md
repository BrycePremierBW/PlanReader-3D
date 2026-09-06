# PlanReader Editable 3D Correction Workflow (PR D.1)

## What "editable 3D" means here

Editable 3D is not about the picture. A 3D model the user can click and drag is only
commercially useful if a correction made in it flows back into quantity accuracy:

```
user correction -> model revision changes -> quantities become stale -> authority must be rechecked
```

This module (`pb_editable_3d_correction_model.py`) implements that chain as a standalone,
testable contract, independent of any rendering or UI concern.

## Why correction is separate from approval

A user dragging a wall, or typing a corrected height, is **not** the same act as an
estimator signing off that the corrected number is now commercially trustworthy. Conflating
the two — auto-approving a correction the moment it's made — means a typo or a bad drag
could become a firm, publishable quantity with no second set of eyes on it.

This module enforces the split explicitly:

- Every correction transitions the object's `authority_status` to `review_required`,
  never to `firm` or `user_approved`, regardless of who made the correction.
- Only `approve_corrected_geometry()` can promote an object to `user_approved`, and it
  requires its own attribution (`approved_by`, `approved_at`) and the exact revision
  hash being approved.
- Approving a revision that has since been superseded by a further correction fails
  closed (`ValueError`) rather than silently approving stale geometry.

(`pb_editable_3d_model.py` from #147 predates this rule and does not yet follow it —
its `apply_correction_event()` sets `authority_status=FIRM` and stamps `approved_by`
immediately on correction. That's a known, separate defect, out of scope for this PR;
see `scratch_pr_d1_editable_3d_module_map.md`.)

## How corrections invalidate quantities

Every `EditableGeometryObject` carries a `revision_hash`. A correction event
(`Editable3DCorrectionEvent`) always produces a **new** hash, computed as a pure
function of the previous hash plus the correction's own content:

```
new_hash = sha256(previous_hash : object_id : field : new_value)
```

This is a hash *chain*, not a random token — replaying the same sequence of events
from the same starting hash always reproduces the same final hash
(`Editable3DCorrectionLedger.replay()`), which is what makes the correction history
auditable rather than just a mutation log you have to trust.

`invalidate_stale_quantities_for_corrections()` is the bridge to PR B.4's
`TakeoffOutputRow`: given a set of corrected `object_id`s, any row whose
`geometry_ref` matches one is turned into a new, stale copy —
`is_publishable=False` and `"stale_after_geometry_correction"` appended to
`blocking_reasons` — leaving the original row object completely untouched.

## How revision hashes protect stale data

`TakeoffOutputRow.compute_fingerprint()` hashes only the row's core commercial
fields (`value`, `source_type`, `authority_status`, `source_page`, `revision_hash`,
`approved_by`, ...) — not `is_publishable`/`blocking_reasons`. So a staled row's
fingerprint is **identical** to its pre-correction fingerprint: that's what makes it
useful for audit. It proves the underlying measurement itself was not silently
altered — only its publishability was — and the old row is never deleted, so a
reviewer can always see exactly what was blocked and why.

## How this feeds JobHub preflight

PR C (`pb_planreader_jobhub_publish_contract.py`) is merged, and this module
integrates with it read-only — it does not call JobHub, does not publish live data,
and does not modify the publishing contract at all.

The integration is proven in
`tests/editable_3d/test_editable_3d_quantity_staleness.py::TestJobHubPreflightIntegration`:
a `TakeoffOutputRow` that passes `run_jobhub_publish_preflight()` cleanly (`is_valid=True`)
is turned stale by `invalidate_stale_quantities_for_corrections()` after a geometry
correction, and the **same, unmodified** preflight gate then correctly rejects it
(`is_valid=False`, `blocked_row_count=1`) — because PR C's gate already inspects
`is_publishable` and `blocking_reasons` on any `TakeoffOutputRow` it's given. No
compatibility hook was needed: the two modules were already shaped to compose.

## Approval and re-publication

A quantity staled by a correction cannot become firm again just because the
underlying `EditableGeometryObject` is later approved via
`approve_corrected_geometry()`. Approval updates the object's own
`authority_status`; it does not retroactively rewrite any `TakeoffOutputRow` that
was already staled. A new row must be created via `pb_takeoff_output_authority`
(e.g. `approve_takeoff_output_row()`) with a `revision_hash` matching the object's
new, approved revision before it can pass `run_jobhub_publish_preflight()` again.
This is deliberate: re-publication after a correction is a distinct, explicit act,
not an automatic side effect of approval.

## Known limitations

- This module is additive: it does not modify `pb_editable_3d_model.py`'s existing
  `WallModel`/`BuildingModel`/`apply_correction_event()`, so the auto-approval defect
  noted above still exists there. Bridging the two (or migrating callers) is future work.
- `EditableGeometryObject.coordinates_or_measurements` is an untyped bag rather than a
  per-object-type schema; validation is limited to the numeric physical-dimension
  fields the correction contract explicitly names.
- There is no persistence layer here (SQLite, etc.) — the ledger is in-memory, matching
  the scope of this PR (prove the model and the invalidation contract via tests).
- `approve_corrected_geometry()` updates the object's own `authority_status` but does
  not automatically re-create or re-approve any `TakeoffOutputRow`s derived from it;
  a caller must still create a new row via `pb_takeoff_output_authority` (e.g.
  `approve_takeoff_output_row()`) once corrected geometry is approved, per B.4's
  existing authority rules.
