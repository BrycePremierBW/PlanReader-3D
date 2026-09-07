# PlanReader Corrected Quantity Recalculation (PR D.3)

## What this closes

D.1 proved a correction stales the old quantity. D.2 proved correction is not
approval. Neither actually computed a *new* number. PR D.3 is the missing step:
when geometry changes, PlanReader recalculates the affected quantity from the
corrected geometry and produces a new, separate `TakeoffOutputRow` — never
auto-published, never replacing the old row's audit trail.

```
Wall: length 5.8m, height 2.7m, gross area 15.66m²
Estimator corrects length: 5.8m -> 6.0m

1. old 15.66m² row is preserved (never deleted)
2. old row is marked stale (D.1's invalidate_stale_quantities_for_corrections)
3. new gross area calculated: 16.20m² (real formula, pb_geometry_takeoff_model.calculate_wall_takeoff)
4. opening deductions recalculated as part of the same formula
5. new net area calculated
6. a new TakeoffOutputRow is created
7. it carries the corrected geometry's revision_hash
8. its source_type is USER_CORRECTED -> authority_status REVIEW_REQUIRED
9. is_publishable is False
10. approval (PR D.2's approve_corrected_geometry, or B.4's approve_takeoff_output_row)
    is a separate, later, explicit act
```

## Dependency graph

`get_affected_targets(object_type, field)` is the explicit, deterministic mapping
from a corrected geometry field to the derived quantities it affects:

| Object type | Corrected field | Affected targets |
|---|---|---|
| `wall` | `length` | wall_length, wall_gross_area, wall_net_area |
| `wall` | `height` | wall_gross_area, wall_net_area |
| `opening` | `opening_width` / `opening_height` | opening_area |
| `room` | `coordinates` | room_floor_area, room_perimeter |
| `ceiling` / `surface` / `soffit` | `area` | ceiling_area / surface_area / soffit_area |
| *(any)* | `finish_tag` | finish_quantity |
| anything else | — | `manual_review_required` |

An opening's own width/height only recalculates its own `opening_area` here — it
does **not** cascade into the host wall's net area, because a bare `EditableGeometryObject`
for an opening carries no reference back to its host wall's geometry. That cascade
needs the host wall's own correction (its `openings` list) to be recalculated
directly; recalculating a stray opening in isolation deliberately does not guess
at a wall it can't see.

## Real formulas only — no guessed numbers

Every recalculated target reuses existing, already-tested formulas rather than
reimplementing geometry math:

- Wall areas: `pb_geometry_takeoff_model.calculate_wall_takeoff()` (AS 4041 opening
  deduction rules, unchanged).
- Room floor area/perimeter: shoelace formula over the corrected polygon.
- Finish quantity: `pb_geometry_takeoff_model.classify_finish_tag()` (unchanged) to
  validate/reclassify the tag; the area itself is not invented.

Anything that doesn't have a real formula mapped (`get_affected_targets` returns
`manual_review_required`) or that fails validation (`NaN`/`inf`/zero/negative
geometry, a degenerate polygon, a missing measurement) never produces a
`TakeoffOutputRow` — the `QuantityRecalculationResult.status` is
`"manual_review_required"` with a `reason`, and `new_row` is `None`.

## Old row matching

A correction can affect multiple targets (e.g. correcting a wall's length affects
its length, gross area, *and* net area) while typically only one existing row is
supplied per correction call. Rows are matched to targets by a description keyword
(`"gross area"`, `"net area"`, `"length"`, ...) rather than by list position, so a
single "gross area" row is never mistakenly treated as the "length" quantity just
because it happened to be first in the list.

## Old value without an existing row

When no existing row is supplied at all, `old_value` is still computed — not left
blank — by rolling the corrected object's state back to `event.old_value` for just
the field that changed, then re-running the same formula against that reconstructed
"before" state. This is a real recalculation of the previous value, not a guess.

## Audit trail

Every new row carries `correction_id` (a new field added to `TakeoffOutputRow` in
this PR) linking it back to the exact `Editable3DCorrectionEvent` that produced it,
and `revision_hash` matching the corrected object's new hash. `correction_id` is
deliberately excluded from `TakeoffOutputRow.compute_fingerprint()` — it's audit
metadata, not a core commercial field, matching how `blocking_reasons`/`warnings`
are already excluded.

## Known limitations

- Opening-width/height corrections don't cascade into the host wall's net area (see
  above) — recalculating that cascade requires host-wall context this module isn't
  given in isolation.
- Old-row-to-target matching is description-keyword based, not a structural link;
  a row whose description doesn't contain a recognizable keyword won't be matched
  and the recalculation proceeds with `old_row=None` (still correct, just without
  audit linkage to a specific prior row).
- Finish quantity recalculation reclassifies scope/paintable status but does not
  itself compute a rate or cost — that remains downstream pricing logic's job.
