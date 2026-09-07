# PR D.8 — Automatic Geometry → Quantity Dependency Linking: Module Map

Scratch working notes. Not part of the shipped contract.

## Discovery

D.4 added `EditableGeometryObject.dependent_quantity_ids` and
`Editable3DCorrectionLedger.link_dependent_quantities(object_id, quantity_ids)`,
but flagged in its own "known limitations": *"nothing currently auto-populates it
from D.3's recalculation flow."* Confirmed still true: `recalculate_quantities_for_correction()`
(D.3, `pb_editable_3d_quantity_recalculation.py`) builds new `TakeoffOutputRow`s but
never calls `link_dependent_quantities()` — a caller has to remember to do it
separately, and nothing enforces that they do.

## Fix

Add an optional `ledger: Optional[Editable3DCorrectionLedger] = None` parameter to
`recalculate_quantities_for_correction()`. When provided, after building the
successfully-recalculated results, it calls
`ledger.link_dependent_quantities(object_id, [new row quantity_ids])` once,
covering every target recalculated by this correction in a single call — reusing
D.4's existing additive/deduplicating linking logic, not reimplementing it.
`manual_review_required` results (no `new_row`) are excluded, since there's no
quantity_id to link. Omitting `ledger` (the default) preserves the exact prior
behaviour — no auto-linking, no error — so every existing D.3/D.5/D.6 call site
that doesn't pass a ledger is unaffected.

## Tests covering it

`tests/editable_3d/test_auto_dependency_linking.py` (new, this PR).
