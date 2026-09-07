# PR D.7 — Raked Wall / Stair Wall Accurate Area Engine: Module Map

Scratch working notes. Not part of the shipped contract.

## Discovery

D.5 added a guard (`_enforce_height_authority`) preventing a `raked`/`stair` wall
from silently claiming `FIRM` authority, because both wall types use the exact same
flat rectangular formula (`length_m * height_m`) as a standard wall — which is
simply wrong for a raked wall (height varies along its length) and unverified for a
stair wall. The guard was deliberately a safety net, not a fix: D.5's own docs said
"A proper raked-wall area formula ... is future work." This PR is that work.

## Scope decision: raked walls get a real formula, stair walls do not

**Raked wall**: a wall under a sloped roof/ceiling, height varying linearly from
one end to the other. The correct area is a **trapezoid**:
`area = length * (height_start + height_end) / 2`. This is a real, well-defined,
implementable formula — `WallModel` just never had the two endpoint heights to
compute it with (only a single `height_m`).

**Stair wall**: the area of a wall following a stair stringer/soffit depends on
stair geometry this codebase has no model for at all (going, rise, riser count,
stringer profile) — nothing here to build a real formula from. Per the original
D.5 mission text itself ("stair wall: special geometry/manual review **until
properly supported**"), staying in the manual-review guard is the intended state,
not a shortcut. Inventing a stair formula from data the codebase doesn't have would
violate the fail-closed, no-guessed-numbers principle every PR in this series has
followed. Stair walls are **unchanged** by this PR.

## The key distinction this PR draws

Two different situations currently look identical (`wall_type="raked"`, guard
always applies) but are not:

1. A raked wall with only a single `height_m` (no endpoint data) — this really is
   just an approximation. **The D.5 guard still applies** (forced to
   `REVIEW_REQUIRED` unless `approved_by` is set).
2. A raked wall with **both** `height_start_m` and `height_end_m` documented/
   figured/section-derived — this is now a **real, correct trapezoid calculation**,
   not a guess. **It is governed by `height_authority` normally**, the same as any
   standard wall — the D.5 wall-type guard no longer force-downgrades it, because
   there's nothing left to be suspicious of; the formula matches the geometry.

Stair walls always keep the D.5 guard regardless of any fields present, since no
formula exists for them yet.

## Fix scope

`pb_editable_3d_model.WallModel` (continuing D.2/D.5's precedent of working in this
file for wall-specific geometry concerns):

1. Add `height_start_m: Optional[float] = None` / `height_end_m: Optional[float] = None`
   (additive, optional).
2. `recalculate_areas()`: when `wall_type == "raked"` and both endpoint heights are
   present and valid (finite, positive), compute gross area via the trapezoid
   average height, reusing the existing, already-tested
   `calculate_wall_takeoff()` (passing the average as its `height_m` — that
   function's opening-deduction logic uses each opening's own `area_m2` directly,
   not derived from `height_m`, so this is a safe, correct reuse, not a
   reimplementation).
3. `_enforce_height_authority()`: skip the raked/stair force-downgrade specifically
   for the "raked wall with both endpoint heights known" case.
4. Malformed endpoint heights (NaN/inf/negative/zero, or only one of the two
   provided) fail closed — treated exactly like the old single-`height_m`
   approximation case (guard still applies), never silently guessed at.

## Tests covering it

`tests/editable_3d/test_wall_height_authority_hardening.py` already covers the
existing raked/stair guard (D.5) — those tests are unaffected since none of them
supply `height_start_m`/`height_end_m`. New coverage:
`tests/editable_3d/test_raked_wall_area_engine.py`.
