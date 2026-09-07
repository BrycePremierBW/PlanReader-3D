# PR D.10 — Unify Approval Paths: Module Map

Scratch working notes. Not part of the shipped contract.

## Discovery: three geometry-approval paths exist

| # | Path | Model | Gating |
|---|---|---|---|
| 1 | `apply_correction_event(building, event)` with `CorrectionAction.APPROVE_QUANTITY` | `pb_editable_3d_model.WallModel` (#147) | **None** — sets `authority_status=FIRM`, `approved_by`, `approved_at` unconditionally. No revision-hash check, no source-trace check. |
| 2 | `pb_editable_3d_model.approve_corrected_geometry(building, object_id, current_revision_hash, approved_by, ...)` | `WallModel` (D.2) | Object exists; `approved_by`/`current_revision_hash` required; **revision-hash match required** (fails closed on stale approval); **source_sheet_label required** (D.4 parity check added later). |
| 3 | `pb_editable_3d_correction_model.approve_corrected_geometry(ledger, object_id, approved_by, current_revision_hash, ...)` | `EditableGeometryObject` (D.1/D.4) | Same as #2: object exists, required params, revision-hash match, `source_sheet`+`source_page` required. |

A fourth, related-but-distinct concept — `pb_takeoff_output_authority.approve_takeoff_output_row()`
(B.4) — approves a *commercial quantity* (`TakeoffOutputRow`), not a *geometry
object*. It's downstream of, not a duplicate of, paths 1–3, so it's out of scope
here.

Paths #2 and #3 were already independently designed to mirror each other (D.4's
commit message says so explicitly) — confirmed still true: same four checks, same
fail-closed behaviour, same field semantics. **The real gap is path #1**: the
original, still-live `APPROVE_QUANTITY` action has no gating at all, even though
it grants exactly the same `FIRM` authority the gated paths do.

## Why not delete path #1

`APPROVE_QUANTITY`/`REJECT_QUANTITY` are existing, tested `CorrectionAction`
members with an existing #147 test (`test_approve_and_reject_quantity`) and are
part of the `apply_correction_event()` single-call-does-everything API surface.
Removing them would be a breaking API change to an established path for no safety
gain proportionate to the risk — D.5's `_enforce_height_authority()` already
prevents `APPROVE_QUANTITY` from being commercially meaningful except as a genuine
approval act (a `wall_type="raked"`/`"stair"` wall's `FIRM` claim still gets
downgraded by the guard unless the format matches what D.5/D.7 consider trustworthy).

## The one structural difference worth keeping, not papering over

`approve_corrected_geometry()` (paths 2/3) exists specifically to guard against a
caller holding a *stale* revision hash across separate calls/time (e.g., an
estimator's browser tab open on an old revision while someone else corrects the
wall). `apply_correction_event()` always operates on the *live* `wall` object
passed into the same call — there's no "held a stale reference" risk within one
call, so a revision-hash parameter on `APPROVE_QUANTITY` wouldn't protect against
anything a caller couldn't already see by reading `wall.revision_hash` directly
before calling. Retrofitting revision-hash gating onto `CorrectionEvent` (which has
no field for a target hash today) is not a proportionate fix for a risk that
doesn't exist in this call shape — documented here rather than added.

## Fix scope

Close the one real, addressable gap: `APPROVE_QUANTITY` gets the same
source-trace requirement as paths #2/#3 (no revision-hash retrofit, per above).
`REJECT_QUANTITY` needs no change — it only ever downgrades, never grants
authority.

## Tests covering it

`tests/editable_3d/test_approval_path_parity.py` (new, this PR) — proves all three
paths now share the same source-trace floor, and documents/proves the
revision-hash structural difference explicitly rather than leaving it implicit.
