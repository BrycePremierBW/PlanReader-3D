# PlanReader Editable 3D Model Bridge (PR D.9)

## The two models

`pb_editable_3d_model.py` (#147) has one dataclass per object type — `WallModel`,
`OpeningModel`, `SurfaceModel`, `RoomModel`, `LevelModel`, `BuildingModel`,
`RoofModel`, `SoffitModel`, `UnitModel` — and hardened `WallModel` specifically
with real accuracy logic across D.2 (correction ≠ approval), D.5 (height-authority
enforcement) and D.7 (the raked-wall trapezoid formula).

`pb_editable_3d_correction_model.py` (D.1) has one unified `EditableGeometryObject`
spanning every `EditableObjectType`, with an append-only correction ledger,
hash-chained revisions, D.4's full traceability contract, D.8's automatic
dependency linking, and — proven in D.6 — a working path all the way to a JobHub
payload.

Every PR from D.1 through D.8 documented these as two separate models and
deliberately did not merge them.

## Why this PR doesn't merge them either

"Unify" could mean deleting one dataclass system in favour of the other. That would
require either re-deriving `WallModel`'s real, tested D.2/D.5/D.7 accuracy logic on
the generic `EditableGeometryObject` from scratch, or discarding it — either way
risking silently reintroducing exactly the fail-open bugs this whole series exists
to close, and it's the kind of large, high-risk architectural change every prior PR
here was explicitly told to avoid ("do not... broad editable 3D rewrites").

Instead, `pb_editable_3d_model_bridge.py` provides a **tested, bidirectional
conversion**: the two silos can now interoperate without either one's internals
changing.

## The bridge

- **`wall_model_to_editable_geometry_object(wall)`** — converts a `WallModel` (with
  its D.2/D.5/D.7-derived state already applied — `gross_area_m2`, `net_area_m2`,
  the enforced `authority_status`, `revision_hash`) into the unified shape, so it
  can be registered in a `Editable3DCorrectionLedger` and flow through D.1/D.3/D.6/
  D.8's ledger, recalculation, dependency-linking, and JobHub machinery.
- **`editable_geometry_object_to_wall_model(obj)`** — the inverse. Reconstruction
  runs `WallModel.__post_init__`, which **re-derives** gross/net area and
  **re-applies** D.5's height-authority enforcement and D.7's raked-wall trapezoid
  formula from the measurements. The round trip can never silently carry over an
  `authority_status` the reconstructed geometry doesn't actually support — proven
  directly: correcting a bridged wall via the ledger and converting back still
  shows `review_required`/`approved_by=None` (D.2's rule), and a raked wall's
  reconstructed area still uses the real trapezoid formula when endpoint heights
  are present, or still carries the D.5 guard when they aren't.
- Openings round-trip (`OpeningModel` ⇄ plain dicts inside
  `coordinates_or_measurements["openings"]`). Fields one model has that the other
  doesn't (`WallModel.start_pt`/`end_pt`, height-authority fields) are carried
  through via `coordinates_or_measurements` rather than silently dropped.
- Missing/partial data fails closed, not guessed: an `EditableGeometryObject` with
  no recorded `height_authority` reconstructs as `WallModel` with
  `height_authority="unknown_height"` — which D.5's enforcement then correctly
  blocks — never a trusted default.

## What this is not

- Not a replacement for either model. Both remain exactly as they were; this is an
  additive third file that depends on both without either depending on it.
- Not a migration path that's been wired into the application yet — this PR proves
  the conversion is correct and safe with tests; actually routing production code
  through the bridge (e.g. having the Streamlit editor persist through one model
  and read through the other) is separate, future work.

## Known limitations

- Only `WallModel` ⇄ `EditableGeometryObject` is bridged. `OpeningModel` converts
  as a nested structure within a wall's conversion, but has no *standalone*
  bridge function of its own (an opening doesn't independently correspond to an
  `EditableObjectType.OPENING`-typed `EditableGeometryObject` without also
  knowing its host wall). `SurfaceModel`/`RoomModel`/`LevelModel`/`BuildingModel`/
  `RoofModel`/`SoffitModel`/`UnitModel` are not bridged at all — `WallModel` was
  the one legacy class with real, load-bearing accuracy logic worth preserving
  across the bridge; the others are comparatively thin and can be bridged
  incrementally if/when they need it.
