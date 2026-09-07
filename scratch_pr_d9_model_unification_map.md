# PR D.9 — Unify Editable 3D Object Models: Module Map & Scope Decision

Scratch working notes. Not part of the shipped contract.

## The two models, and why they still exist separately

| | `pb_editable_3d_model.WallModel` (#147, D.2, D.5, D.7) | `pb_editable_3d_correction_model.EditableGeometryObject` (D.1, D.4, D.8) |
|---|---|---|
| Shape | One dataclass per object type (`WallModel`, `OpeningModel`, `SurfaceModel`, `RoomModel`, `LevelModel`, `BuildingModel`, `RoofModel`, `SoffitModel`, `UnitModel`) | One dataclass for every `EditableObjectType` |
| Correction | `apply_correction_event()` + `CorrectionEvent` (in-place mutation) | `Editable3DCorrectionLedger.apply_correction()` (append-only event log, hash-chained revisions, replayable) |
| Wall-specific accuracy logic | Height authority enforcement (D.5), raked-wall trapezoid formula (D.7), AS4041 opening deductions | None — a wall here is just `coordinates_or_measurements = {"length": ..., "height": ...}`, no height-authority or raked-wall concept at all |
| Quantity recalculation | None | `recalculate_quantities_for_correction()` (D.3), with auto dependency-linking (D.8) |
| Traceability contract | `source_page_no`/`source_sheet_label`/`height_source_sheet`/`height_source_level` | Full D.4 contract: `source_file_id`/`source_region`/`original_geometry_ref` vs. current `geometry_ref`/`scale_id`/`dimension_text_ids`/`correction_ids`/`dependent_quantity_ids` |
| JobHub integration | None | Proven end-to-end in D.6 |

Every PR from D.1 through D.8 documented this split as a known limitation and
deliberately did not merge the two — because each of `WallModel`'s D.2/D.5/D.7
accuracy fixes (auto-approval prevention, height-authority enforcement, the
trapezoid formula) is real, tested, load-bearing logic that would need to be
faithfully re-implemented on `EditableGeometryObject` to safely replace `WallModel`
outright, and none of `EditableGeometryObject`'s D.3/D.4/D.6/D.8 machinery
(recalculation, dependency linking, the full traceability contract, the proven
JobHub path) exists on `WallModel` at all.

## Scope decision for this PR

**"Unify" here means connect the two models with a tested, bidirectional bridge —
not delete or merge either dataclass system.**

A destructive merge (deprecating `WallModel` in favour of `EditableGeometryObject`,
or vice versa) would be exactly the kind of large, high-risk architectural change
every prior PR in this series was explicitly told to avoid ("do not... broad
editable 3D rewrites"), and it would require re-deriving D.5/D.7's wall-specific
enforcement logic on the generic object model from scratch, or discarding it —
either way risking silently reintroducing the exact fail-open bugs this whole
series exists to close. That is not a one-PR change to make safely without a much
larger, dedicated design pass.

Instead, `pb_editable_3d_model_bridge.py` (new file — neither core module needs to
import the other, avoiding any circularity) provides:

- `wall_model_to_editable_geometry_object(wall) -> EditableGeometryObject`: converts
  a `WallModel` (with all its D.2/D.5/D.7-derived state — `gross_area_m2`,
  `net_area_m2`, `authority_status` as already enforced, `revision_hash`) into the
  unified object shape, so it can be registered in a
  `Editable3DCorrectionLedger` and flow through D.1/D.3/D.6/D.8's ledger,
  recalculation, and JobHub machinery.
- `editable_geometry_object_to_wall_model(obj) -> WallModel`: the inverse — takes a
  wall-typed `EditableGeometryObject` and reconstructs an equivalent `WallModel`,
  which re-runs `__post_init__` and therefore re-applies D.5/D.7's real
  enforcement logic (height-authority ceiling, raked-wall trapezoid) on the
  reconstructed object — proving the round trip doesn't silently bypass either
  model's own safety logic.
- Both directions round-trip openings (`OpeningModel` ⇄ plain dicts inside
  `coordinates_or_measurements["openings"]`) and preserve every field either model
  actually has a place for; fields one model has that the other doesn't (e.g.
  `WallModel.start_pt`/`end_pt`, or `EditableGeometryObject.dimension_text_ids`)
  are carried through the conversion where a natural home exists
  (`coordinates_or_measurements` for the wall-only ones) rather than silently
  dropped.

This is a real, meaningful unification step — the two silos can now interoperate,
and a wall corrected via one pipeline can be inspected/continued via the other —
without the destructive risk of merging the underlying dataclasses.

## Tests covering it

`tests/editable_3d/test_model_bridge.py` (new, this PR).
