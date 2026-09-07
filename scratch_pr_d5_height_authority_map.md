# PR D.5 — Wall Height Authority Hardening: Module Map

Scratch working notes. Not part of the shipped contract.

## Discovery

`pb_editable_3d_model.py` (#147) already has `WallHeightAuthority` (`documented_ceiling_height`,
`section_derived`, `schedule_derived`, `model_estimated`, `user_entered`,
`raked_wall`, `stair_wall`, `unknown_height`) and `WallModel.height_authority`.
`tests/editable_3d/test_wall_height_authority_rules.py` (#147) already exercises it
— but only as a **descriptive label the caller sets manually**. Nothing in
`WallModel` or `apply_correction_event` ever reads `height_authority` to actually
constrain `authority_status` or `gross_area_m2`/`net_area_m2`. Concretely:

| Symbol | Current behaviour | Gap vs. D.5 |
|---|---|---|
| `WallModel.recalculate_areas()` | Computes `length_m * height_m` (minus AS4041 opening deductions) for **every** wall, regardless of `height_authority` or `wall_type` | `height_authority=unknown_height` with an otherwise-valid positive `height_m` produces a normal computed area and, if the caller passes `authority_status=FIRM`, a fully firm/publishable wall — nothing blocks it. A `raked`/`stair` wall gets the exact same flat rectangular formula as a standard wall, and nothing stops a caller from marking it `FIRM` either. |
| `WallModel.__post_init__` | Only validates `height_m`/`length_m` are finite and non-negative | No connection at all between `height_authority` and `authority_status` — the two fields can disagree arbitrarily (e.g. `unknown_height` + `FIRM`) and nothing catches it |
| — | No mm→m figured-dimension conversion exists for wall height at all | D.5 explicitly wants "2700mm figured height converts to 2.7m" |
| — | No field records *which* section/elevation sheet a `section_derived` height was traced to (only the wall's own plan `source_sheet_label` exists, which is usually a different sheet) | D.5: "section-derived: trace to section sheet and relevant level" |
| `apply_correction_event` (fixed in D.2) | `CHANGE_HEIGHT` already sets `authority_status=REVIEW_REQUIRED`, clears `approved_by`/`approved_at`, and sets `height_authority=USER_ENTERED` | Already correct post-D.2; D.5 adds no new requirement here beyond proving it end-to-end for height specifically |

## Fix scope

`pb_editable_3d_model.py` (not `EditableGeometryObject`) is the right file for this
PR: wall height authority is a `WallModel`-specific concept that doesn't exist in
the newer unified model at all (which only has an untyped `height` measurement, no
provenance concept). D.2 already touched this same file for the auto-approval fix,
so continuing here is consistent, not scope creep into new territory.

1. Add `WallHeightAuthority.FIGURED_DIMENSION` and `.USER_APPROVED` (additive —
   `USER_ENTERED` is kept, unchanged, since `apply_correction_event` and an
   existing #147 test already depend on that exact value).
2. Add `WallModel.height_source_sheet` / `height_source_level` (both optional,
   additive) to carry the section-sheet trace.
3. `WallModel.__post_init__`/`recalculate_areas()` now enforces, rather than just
   describing:
   - `unknown_height` → area forced to `0.0`, `authority_status` forced to
     `BLOCKED`, regardless of what the caller requested.
   - `model_estimated` + a caller-requested `FIRM` → downgraded to `PROVISIONAL`.
   - `wall_type in ("raked", "stair")` + a caller-requested `FIRM` with no
     `approved_by` → downgraded to `REVIEW_REQUIRED` (an estimate can still be
     shown, but never silently treated as firm without going through explicit
     approval).
4. New `resolve_wall_height_from_figured_dimension(text)` reuses B.2's
   `pb_figured_dimension_authority.parse_figured_dimension_mm()` (not
   reimplemented) to convert e.g. `"2700mm"` → `2.7` m.

## Known limitation carried forward

`WallModel` and D.1's `EditableGeometryObject` remain separate models (same
documented limitation as D.1/D.2/D.4). The "corrected height invalidates
quantity" / "approved corrected height allows new quantity to progress" tests are
therefore proven via the `EditableGeometryObject`/ledger/D.3-recalculation pipeline
(already fully built and correct as of D.1–D.4), framed around a height correction
specifically — not via `WallModel`, which has no quantity-recalculation pipeline of
its own.
