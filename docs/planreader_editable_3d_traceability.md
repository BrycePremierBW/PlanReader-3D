# PlanReader Editable 3D Object Traceability (PR D.4)

## What every commercially relevant 3D object must answer

- What sheet created me? What page? What region of that page? → `source_file_id`, `source_page`, `source_sheet`, `source_region`
- What original 2D geometry did I start from, and what do I currently point at? → `original_geometry_ref` (immutable, captured once) vs. `geometry_ref` (the current pointer, correctable)
- What scale calibration and dimension evidence back me? → `scale_id`, `dimension_text_ids`
- What detection process, and how confident? → `confidence`
- Which corrections changed me? → `correction_ids` (append-only)
- Which quantities depend on me? → `dependent_quantity_ids`, resolvable via `resolve_dependent_quantities()`
- Which revision am I, and who — if anyone — approved me? → `revision_hash`, `approved_by`, `approved_at`

All of this lives on `pb_editable_3d_correction_model.EditableGeometryObject` — the
unified model D.1 introduced spanning every `EditableObjectType` (wall, opening,
door, window, room, surface, ceiling, floor, soffit, stair, roof, unknown).

## Why the unified model, not the legacy per-type classes

`pb_editable_3d_model.py` (#147) still has separate `WallModel`/`OpeningModel`/
`SurfaceModel`/etc. classes. D.1 and D.2 already documented (in their own scratch
maps) that these two models are deliberately not yet unified. Hardening the
traceability contract across 8+ separate legacy classes, on top of what
`EditableGeometryObject` already provides generically through `object_type`, would
duplicate the same contract twice and drift immediately. This PR hardens the one
model every later PR (D.2, D.3) actually builds on; the legacy classes are
untouched — the same deliberate, carried-forward scope decision.

## original_geometry_ref vs. geometry_ref

`geometry_ref` is the *current* pointer to underlying vector geometry — it's a
correctable field (`CorrectionField.GEOMETRY_REF`), since a page might genuinely
need to be re-linked to redrawn geometry. `original_geometry_ref` is captured once,
at `Editable3DCorrectionLedger.register_object()`, and is never touched by any
correction (it isn't in the ledger's `_OBJECT_ATTRIBUTE_FIELDS` map, so there's no
code path that can write to it after registration) — it always answers "what did
this object point at when it was first created," regardless of how many times its
current geometry reference has moved on since.

The same principle protects `source_file_id`/`source_page`/`source_sheet`/
`source_region`... except `source_page` and `source_sheet` remain intentionally
correctable (an estimator might genuinely need to fix a wrong page/sheet
attribution), matching D.1's original design. `source_file_id` and `source_region`
have no correction field at all, so they're structurally immutable once set.

## Approval requires source trace

`approve_corrected_geometry()` now fails closed (`ValueError`) if the object has no
recorded `source_page`/`source_sheet` — geometry that can't be traced back to
originating drawing evidence can never become commercial, no matter what revision
it's at. This mirrors the identical check already added to
`pb_editable_3d_model.approve_corrected_geometry()` in PR D.2, bringing the two
approval functions to parity without unifying them.

Approval now also **persists** `approved_by`/`approved_at` onto the object itself
(previously only returned in the transient `ApprovalResult`) — and a further
correction after approval clears both back to `None`, consistent with D.2's
"correction invalidates prior approval" rule.

## Dependent quantities

`ledger.link_dependent_quantities(object_id, quantity_ids)` records which
`TakeoffOutputRow.quantity_id`s currently derive from an object — additive and
deduplicating, never clearing existing links. `resolve_dependent_quantities(obj, rows)`
resolves those ids against a real candidate row set, proving the linkage points at
actual current quantities rather than dangling ids.

## Serialization

`EditableGeometryObject.to_dict()` (already existed) now naturally includes every
new traceability field, since it's a plain dataclass `asdict()`. Added
`EditableGeometryObject.from_dict()` for the reverse direction, with safe defaults
for every optional/list field so a partial payload (e.g. a minimal object with just
`object_id`/`object_type`/`revision_hash`) still reconstructs without error.

## Known limitations

- The legacy `pb_editable_3d_model.py` per-type classes are not separately
  hardened — see "Why the unified model" above.
- `dependent_quantity_ids` must be explicitly linked via `link_dependent_quantities()`;
  nothing currently auto-populates it from D.3's recalculation flow. Wiring that
  together is natural follow-up work, not done here to keep this PR focused on the
  object contract itself.
