# PlanReader Wall Height Authority Hardening (PR D.5)

## Why height specifically

Height is one of the largest wall-area error sources: a wrong height doesn't just
throw off one number, it multiplies through gross area, net area, opening
deductions, and every finish quantity derived from that wall.

`pb_editable_3d_model.WallHeightAuthority` already existed (#147) as a descriptive
label — `documented_ceiling_height`, `section_derived`, `schedule_derived`,
`model_estimated`, `user_entered`, `raked_wall`, `stair_wall`, `unknown_height` —
but nothing read it. A wall with `height_authority=unknown_height` and a plausible
`height_m` could be marked `FIRM` and produce a normal computed area with nobody
stopping it. This PR closes that gap: `height_authority` is now enforced, not just
recorded.

## The rule: height authority sets a ceiling, never a floor

`WallModel._enforce_height_authority()` runs on every construction and every
`recalculate_areas()` call (including after a correction):

| `height_authority` | Enforcement |
|---|---|
| `unknown_height` | Area forced to `0.0`; `authority_status` forced to `blocked` — regardless of what the caller requested, and regardless of whether `height_m` itself looks like a plausible number. Not knowing where a height came from is disqualifying on its own. |
| `model_estimated` | A caller-requested `FIRM` is downgraded to `provisional`, **unless** `approved_by` is set (an explicit human approval can promote an estimate — that's the whole point of the approval gate). |
| `figured_dimension`, `documented_ceiling_height`, `section_derived`, `schedule_derived`, `user_approved` | No downgrade — these are trusted sources (added `figured_dimension` and `user_approved` as new enum members this PR; the existing ones were already trusted implicitly). |
| wall_type `raked` or `stair` (any height authority) | A caller-requested `FIRM` is downgraded to `review_required` **unless** `approved_by` is set. The flat rectangular formula is still computed and shown as an estimate — a raked or stair wall's true area needs a different formula or a human's eyes, so the flat-formula number can never silently become authoritative on its own. |

A caller can always request something *more* conservative than the ceiling (e.g.
`review_required` for a documented height) — the enforcement only ever pulls
`authority_status` down, never pushes it up.

## Figured-dimension height conversion

`resolve_wall_height_from_figured_dimension("2700mm")` → `2.7` (metres). This
reuses `pb_figured_dimension_authority.parse_figured_dimension_mm()` — the same
parser B.2 already validated for figured dimensions elsewhere in the codebase —
rather than reimplementing unit parsing. Malformed/negative/zero/non-finite text
raises the same `DimensionParseError` any other figured dimension would.

## Section height trace

`WallModel.height_source_sheet` / `height_source_level` (new, optional fields)
record *which* section/elevation sheet and level a `section_derived` height was
measured from — distinct from the wall's own plan `source_sheet_label`, since a
wall's height typically comes from a different drawing (a section or elevation)
than the floor plan it's drawn on.

## Corrected/approved height quantities

`WallModel` has no quantity-recalculation pipeline of its own (that's D.3's job,
built on the newer `EditableGeometryObject` model). So "corrected height
invalidates quantity" and "approved corrected height allows new quantity to
progress" are proven via that existing pipeline, framed around a height
correction specifically: `Editable3DCorrectionLedger.apply_correction()` (D.1/D.2)
→ `recalculate_quantities_for_correction()` (D.3) → `approve_corrected_geometry()`
(D.2) → `approve_takeoff_output_row()` (B.4). No new production code was needed for
these two behaviours — they were already correct as of D.1–D.4; this PR just adds
height-specific integration tests proving it.

## Known limitations

- `WallModel` and `EditableGeometryObject` remain separate models (the same
  documented limitation carried since D.1). Height authority enforcement lives on
  `WallModel` since that's the only place `WallHeightAuthority` exists;
  `EditableGeometryObject` has no equivalent height-provenance concept yet.
- The raked/stair "flat formula as estimate, never silently firm" guard doesn't
  compute a *better* formula for raked/stair geometry — it only prevents the wrong
  formula's result from being trusted uncritically. A proper raked-wall area
  formula (average height × length, or similar) is future work.
