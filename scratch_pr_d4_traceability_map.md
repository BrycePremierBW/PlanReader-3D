# PR D.4 — Editable 3D Object Traceability: Module Map

Scratch working notes. Not part of the shipped contract.

## Discovery

Two object models exist for editable 3D, as already documented in D.1's and D.2's
own scratch maps:

1. `pb_editable_3d_model.py` (#147) — per-type legacy classes: `WallModel`,
   `OpeningModel`, `SurfaceModel`, `RoomModel`, `LevelModel`, `BuildingModel`,
   `RoofModel`, `SoffitModel`, `UnitModel`.
2. `pb_editable_3d_correction_model.py` (D.1, #153) — `EditableGeometryObject`, a
   single unified model spanning every `EditableObjectType` (wall, opening, door,
   window, room, surface, ceiling, floor, soffit, stair, roof, unknown), plus the
   append-only correction ledger D.2/D.3 build on.

## Decision: harden the unified model, not the legacy per-type classes

D.4 asks to "harden/extend `BuildingModel`, `LevelModel`, ..., `RoofModel`" — the
legacy per-type list. Duplicating the same traceability contract across 8+ separate
dataclasses in `pb_editable_3d_model.py`, on top of what `EditableGeometryObject`
already provides generically, would be exactly the kind of broad rewrite D.2/D.3
were told to avoid, and would leave two parallel, drifting traceability contracts
instead of one. `EditableGeometryObject` already covers every object type D.4 cares
about through `object_type`, and is the model every later PR (D.2, D.3) has actually
built on. This PR hardens that one model. The legacy classes are untouched — this is
the same deliberate, documented scope decision D.1/D.2 already made, carried forward.

## Gap analysis: D.4's object contract vs. current `EditableGeometryObject`

| Required field | Present before this PR? | Action |
|---|---|---|
| `object_id` | Yes | — |
| `object_type` | Yes | — |
| `source_file_id` | No | Add |
| `source_page` | Yes | — |
| `source_sheet` | Yes | — |
| `source_region` | No | Add |
| `original_geometry_ref` | No (only a single mutable `geometry_ref`) | Add — captured once at `register_object()`, never touched by any correction (not in `_OBJECT_ATTRIBUTE_FIELDS`, so structurally protected) |
| `current_geometry_ref` | Effectively `geometry_ref` (correctable via `CorrectionField.GEOMETRY_REF`) | Keep `geometry_ref` as the "current" pointer; document the naming explicitly rather than rename (renaming would break every D.1/D.2/D.3 caller and test) |
| `scale_id` | No | Add |
| `dimension_text_ids` | No | Add (list — an object may be justified by more than one figured dimension) |
| `authority_status` | Yes | — |
| `confidence` | No | Add |
| `revision_hash` | Yes | — |
| `correction_ids` | No | Add — appended (never replaced) by `apply_correction()` on every successful correction |
| `dependent_quantity_ids` | No | Add — populated via new `link_dependent_quantities()` |
| `approved_by` | No (only returned in `ApprovalResult`, never persisted on the object) | Add — set by `approve_corrected_geometry()` |
| `approved_at` | No (same gap) | Add |

## Real gaps found in existing approval logic

`pb_editable_3d_correction_model.approve_corrected_geometry()` (D.1) does **not**
check source trace before approving, and does **not** persist `approved_by`/
`approved_at` onto the object — both real gaps against D.4's explicit requirements
("model object without source trace blocks approval"; approval should be visible on
the object, not just in the returned `ApprovalResult`). This mirrors the same
source-trace check already added to `pb_editable_3d_model.approve_corrected_geometry()`
in D.2 — bringing the two approval functions to parity, without unifying them (still
a documented, deliberate limitation from D.2).

## Tests covering it

`tests/editable_3d/test_editable_3d_object_traceability.py` (new, this PR).
