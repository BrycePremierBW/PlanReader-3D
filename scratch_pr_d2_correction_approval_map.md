# PR D.2 — Correction vs Approval Separation: Module Map

Scratch working notes. Not part of the shipped contract.

## Discovery

`rg -n "apply_correction_event|CorrectionEvent|authority_status|FIRM|USER_APPROVED|approved_by|approved_at|review_required|user_corrected|publishable" .`
surfaced two independent correction/approval mechanisms that had drifted apart:

| File | Symbol | Current behaviour (before this PR) | Desired behaviour | Risk | Tests covering it |
|---|---|---|---|---|---|
| `pb_editable_3d_model.py` (#147) | `CorrectionEvent` | Structured event record: `correction_id`, `object_id`, `object_type`, `action`, `field_name`, `old_value`, `new_value`, `reason`, `actor`, `created_at`, `source` | Unchanged — the record itself was never the bug | — | `tests/editable_3d/test_correction_event_pipeline.py` |
| `pb_editable_3d_model.py` | `WallModel` | `authority_status`, `approved_by`; **no `approved_at` field at all** | Add `approved_at: Optional[str] = None`, included in `to_dict()` | Low (additive) | new tests |
| `pb_editable_3d_model.py` | `apply_correction_event()` — `CHANGE_HEIGHT`/`MOVE_WALL`/`ADD_OPENING` branches | **HIGH — the defect.** All three immediately set `wall.authority_status = AuthorityStatus.FIRM.value` and `wall.approved_by = event.actor`. A correction auto-approved itself. `ADD_OPENING` additionally created the new `OpeningModel` with `approval_status=FIRM`. | Every correction branch sets `authority_status = REVIEW_REQUIRED`, `approved_by = None`, `approved_at = None` — and clears any *prior* approval too, since a further correction to already-approved geometry must force re-review. | Fixed in this PR | `tests/editable_3d/test_correction_not_approval.py` (new), `test_correction_event_pipeline.py` (existing test's wrong assertions corrected) |
| `pb_editable_3d_model.py` | `apply_correction_event()` — `APPROVE_QUANTITY`/`REJECT_QUANTITY` branches | Already correctly separate from geometry corrections (a distinct `CorrectionAction`), but had no revision-hash gating at all — could approve any wall regardless of whether its geometry had moved on. | Left as the lightweight approve/reject path (unchanged behaviour, still un-gated) — a **new**, stricter `approve_corrected_geometry()` is the gated path this PR adds for anything that needs the safety guarantee. | Medium (two approval paths now coexist — see Known limitations) | `test_approve_and_reject_quantity` (existing, unaffected) |
| `pb_editable_3d_model.py` | `approve_corrected_geometry()` (new) | Did not exist | Standalone function: validates `object_id`/`approved_by`/`current_revision_hash` present, finds the wall, fails closed if `wall.revision_hash != current_revision_hash` (stale-revision approval) or `wall.source_sheet_label` is empty (untraceable geometry), then sets `FIRM`/`approved_by`/`approved_at` and recomputes the hash chain (level → building). | New, additive | `TestApprovalIsRevisionHashGated`, `TestSecondCorrectionAfterApprovalMakesQuantitiesStaleAgain`, `TestCorrectionAndApprovalActorsCanDiffer` |
| `pb_editable_3d_correction_model.py` (D.1, #153) | `Editable3DCorrectionLedger`, `approve_corrected_geometry()` | Already implements this exact separation correctly (fixed at D.1 time), for its own `EditableGeometryObject` model — a *different* object model from `WallModel`. | No change needed; this PR's fix brings `pb_editable_3d_model.py`'s older, separate object model up to the same standard. | Low | `tests/editable_3d/test_editable_3d_correction_model.py` (D.1) |
| `pb_takeoff_output_authority.py` (B.4, #150/#152) | `TakeoffOutputRow`, `create_takeoff_output_row()` | Already fail-closed and unrelated to this defect. | No change. | — | `tests/geometry/` |
| `pb_editable_3d_correction_model.py` | `invalidate_stale_quantities_for_corrections()` | Already correctly stales any `TakeoffOutputRow` whose `geometry_ref` matches a corrected object id. | Used directly in this PR's regression test to prove end-to-end: `pb_editable_3d_model.py` correction → D.1 staleness bridge → `TakeoffOutputRow.is_publishable=False`. | Low | `TestStaleLinkedQuantityRemainsBlockedAfterCorrection` (new) |

## Conclusion

The defect was narrowly scoped to three `CorrectionAction` branches inside one function. The fix is minimal: stop those three branches from writing approval fields, and add one new, revision-hash-gated approval function as the safe path for anything that needs the stronger guarantee test cases #11/#12 call for.

## Known limitations (see PR body)

- Two approval mechanisms now coexist in this file: the pre-existing `APPROVE_QUANTITY`/`REJECT_QUANTITY` `CorrectionEvent` actions (unchanged, still revision-unaware) and the new `approve_corrected_geometry()` (revision-hash-gated). Unifying them is a larger, separate change — out of scope for "keep this PR focused."
- `pb_editable_3d_model.py`'s `WallModel` and `pb_editable_3d_correction_model.py`'s `EditableGeometryObject` remain two separate object models with separate correction pipelines (D.1's own note from `scratch_pr_d1_editable_3d_module_map.md`, still true).
