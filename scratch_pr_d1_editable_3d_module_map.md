# PR D.1 — Editable 3D Correction Model + Revision Invalidation: Module Map

Scratch working notes. Not part of the shipped contract.

## Existing code surveyed

| File | Class/Function | Current responsibility | Supports correction? | Changes revision/hash? | Quantities become stale? | Risk | Test coverage |
|---|---|---|---|---|---|---|---|
| `pb_editable_3d_model.py` (#147) | `WallModel`, `OpeningModel`, `SurfaceModel`, `RoomModel`, `LevelModel`, `BuildingModel` | 2D-to-3D hierarchical domain model with per-object `authority_status`/`revision_hash` fields | Indirectly, via `apply_correction_event` | Yes — `WallModel.compute_revision_hash()`, `LevelModel.revision_hash`, `BuildingModel.compute_building_revision_hash()` all mutate in place | No — recalculates `gross_area_m2`/`net_area_m2` on the `WallModel` itself; never touches a `TakeoffOutputRow` (didn't exist yet — #147 predates #150) | **HIGH** — see defect below | `tests/editable_3d/test_2d_to_3d_data_model.py`, `test_wall_height_authority_rules.py`, `test_massing_model_generation.py` |
| `pb_editable_3d_model.py` | `CorrectionEvent` | Structured event record (`correction_id`, `object_id`, `object_type`, `action`, `field_name`, `old_value`, `new_value`, `reason`, `actor`, `created_at`, `source`) | N/A (it's the event itself) | No | No | Medium — missing `previous_revision_hash`/`new_revision_hash`/`affected_quantity_ids`/`requires_reapproval` fields the D.1 contract requires | `test_correction_event_pipeline.py` |
| `pb_editable_3d_model.py` | `apply_correction_event()` | Applies one `CorrectionEvent` to a `BuildingModel` wall, recalculates areas, mutates hashes | Yes | Yes (mutates in place, not append-only) | No | **HIGH — real defect**: `CHANGE_HEIGHT`, `MOVE_WALL`, and `ADD_OPENING` branches all immediately set `wall.authority_status = AuthorityStatus.FIRM.value` **and** `wall.approved_by = event.actor` — i.e. every correction is auto-approved by the person making it. This is exactly the failure mode D.1 rule 4/5 ("user correction is not automatically approved"; "approval is separate from correction") exists to prevent. | `test_correction_event_pipeline.py` (does not currently assert correction ≠ approval) |
| `pb_editable_3d_model.py` | `QuantityRecalculation` | Old/new gross/net area + `is_preflight_invalidated: bool` | N/A | No | Marks a boolean flag only; does not touch any `TakeoffOutputRow` | Medium | `test_correction_event_pipeline.py` |
| `pb_takeoff_output_authority.py` (#150) | `TakeoffOutputRow` | Canonical commercial takeoff row: `geometry_ref`, `revision_hash`, `is_publishable`, `blocking_reasons`, `quantity_id`, etc. | No correction concept at all | No | This is the thing that *should* become stale, but nothing currently marks it so | Low (module itself is solid; the gap is the missing bridge) | `tests/geometry/test_takeoff_output_authority_metadata.py`, `test_takeoff_publishability_flags.py` |
| `pb_geometry_takeoff_model.py` | `AuthorityStatus`, `MeasurementAuthorityType` | Shared enums reused across B.2/B.3/B.4 | N/A | N/A | N/A | Low | Covered indirectly by every dependent module's tests |
| `pb_takeoff_learning_ledger.py` (#148) | `TakeoffLearningLedger`, `AIDraftTakeoffRow` | AI draft ingestion + accuracy reporting | No | No | No | Low | `tests/learning_ledger/` |

## Conclusion

D.1 is **not** a duplicate of #147. It is the missing bridge:

1. #147 has no append-only correction ledger (mutates in place; not replayable).
2. #147 has no `Editable3DRevision` object — just a string field overwritten each time.
3. #147 has no `QuantityInvalidationResult` and never touches `TakeoffOutputRow` — the actual commercial-authority object introduced later in #150.
4. #147's `apply_correction_event` auto-approves corrections, violating the correction≠approval rule this PR is meant to establish.

Building a new, additive `pb_editable_3d_correction_model.py` (rather than modifying `pb_editable_3d_model.py`) avoids:
- touching PR C / publishing files (none of this lane's files intersect that surface),
- broad-refactor risk to the already-tested #147 model,
- collision with any concurrent process that might still be touching `pb_editable_3d_model.py` or PR C files.

The known #147 auto-approval defect is noted here but **not fixed in this PR** — out of scope for "one focused PR"; worth flagging separately.
