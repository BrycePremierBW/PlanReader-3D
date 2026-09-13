# AI Engineering Playbook — PlanReader-3D

Short, high-signal reference for an AI session before it touches wall,
room, opening, or quantity-authority code. Pairs with `AGENTS.md` (the
rules) — this is the map. Verified by reading the actual modules listed
below, not from memory; a stale claim here should be re-checked against the
code, not trusted on its own (see "Confidence" markers).

## The one trace worth understanding first

One physical quantity's real path through this codebase, module-level,
**[VERIFIED: module exists, docstring confirms role — function-level
call chain not fully traced here, confirm before relying on it]**:

```
PDF evidence (native vector / raster)
  -> pb_viewport_segmentation.py            (F.07: title text -> spatial
                                              viewport ownership; states
                                              RESOLVED / DERIVED / AMBIGUOUS /
                                              UNSUPPORTED — never guesses an
                                              owner)
  -> pb_viewport_scale_binding.py           (scale calibration SCOPED to one
                                              owned viewport, for mixed-scale
                                              sheets; reuses the one page-scale
                                              authority, never a second one)
  -> W2-W4 topology                          (pb_wall_room_topology_stage_a /
     (candidate geometry)                    _junction_classifier /
                                              _wall_assembly -> WallCandidate,
                                              PROVISIONAL thickness by default)
  -> pb_migration_contracts.py               (EntityEvidence / EvidenceAtom —
     (EntityEvidence)                        the ONE evidence-fusion shape)
  -> pb_measurement_input_authority.py       (binds one physical-entity
                                              measurement to document/source/
                                              revision/page/viewport/evidence
                                              identity; only AuthorityStatus.
                                              FIRM returns a value)
  -> pb_wall_length_quantity.py /            (QuantityEvidence — deterministic,
     pb_wall_height_authority.py /           fail-closed; e.g. wall height
     pb_wall_gross_area_quantity.py /        NEVER defaults to the historical
     pb_opening_deduction_readiness.py /     2.8m assumption; opening deduction
     pb_wall_net_area_quantity.py            blocks on any unresolved W7 host)
  -> pb_gold_free_shadow_runner.py           (M3: runs legacy + new engine on
     (shadow comparison)                     the SAME bytes, freezes both,
                                              compares with NO gold loaded)
  -> pb_migration_gold_join_boundary.py      (gold/evaluator stage receives a
                                              SEALED artifact; cannot invoke
                                              extract() itself — the boundary
                                              is the missing callback, not a
                                              flag)
  -> commercial publishing gate              (out of this trace's verified
                                              scope this pass — locate the
                                              actual gate before touching
                                              anything downstream of the seal)
```

**Why this matters**: every one of these modules' own docstrings
independently states the same discipline — one evidence vocabulary, one
scale authority, fail-closed on anything not FIRM/RESOLVED, no gold until
sealed. That repetition across ten-plus independently-authored modules is
the strongest evidence in the repository that this discipline is load-
bearing, not decorative. Do not route around any of these seams to get a
result faster.

## Module map (wall/room/opening topology specifically)

`pb_wall_room_topology_*.py`, W1 through W10, one file per stage:
contracts (W1) -> Stage A segment prep (W2) -> junction classification (W3)
-> wall-chain assembly / `WallCandidate` identity (W4) -> room-face
reconstruction via directed half-edge tracing (W5) -> room/wall
relationships, `interior_exterior` resolution (W6) -> opening-host
dangling-gap detection, `ambiguous_host`-only by design (W7) -> room label
binding (W8) -> reconciliation / referential-integrity reporting, no
promotion (W9) -> canonical-graph adapter, `takeoff_eligible=False`
unconditionally (W10). **[VERIFIED: read in full this session]**.

`pb_hosted_opening_geometry.py` (real door-swing/fill/jamb opening
evidence) and `pb_hosted_opening_wall_binding.py` (binds an opening span to
W4 walls) are a SEPARATE, more evidence-rich opening pipeline from W7's own
dangling-gap detector — they are not yet connected to each other.
`pb_opening_provenance_graph.py` is a third, still-separate opening
authority surface (Cursor-owned, F.07-era). Confirm current state before
assuming any of the three call into another.

## The one big architectural finding

**W4 commits a `WallCandidate`'s permanent identity from chaining rules
alone (junction type only), before any relational evidence (paired faces,
consistent thickness, connectivity) exists to inform that decision.**
Everything downstream inherits whatever W4 already decided. This is not a
wrong architecture — the ten-stage boundary maps onto real, separable
concerns and should not be collapsed into a from-scratch rewrite — but it
means evidence is computed in the wrong *order* relative to identity
commitment. See `pb_wall_room_topology_wall_assembly.py`'s own
`_canonical_wall_candidate_id`/`assemble_wall_candidates` for where this
lives. **[VERIFIED, with two concrete confirmed consequences below]**.

## Concrete, verified defects (not inference — reproduced directly)

- **Identity collision**: `_canonical_wall_candidate_id` hashed only a
  chain's two outer endpoints. Two geometrically distinct chains sharing
  both endpoints (confirmed on real Baghau p36 data) collided onto one id
  and crashed a downstream pass expecting per-object uniqueness. Fixed via
  a direction-canonical, arc-length-resampled shape fingerprint (see
  `claude/pre-w4-relational-wall-evidence-rd`) — re-chunking invariant,
  shape-sensitive.
- **No spatial indexing anywhere**: `pb_vector_geometry_v130.snap_geometry`'s
  node-locate is a linear scan against every existing node so far (O(n²)
  overall); `split_segments_at_intersections` is all-pairs (O(n²)). Directly
  observed: a full, un-scoped real page (Dungicha, ~37k raw segments) was
  impractical to process without scoping to its own viewport region first.
  Per-viewport scoping (matching W2's own naming) is the correct fix
  regardless of performance; a shared spatial index would let per-viewport
  processing itself scale further.
- **Evidence independence, proven unsound by direct construction, not
  merely argued**: a research pass (PR #273) counted W5 room-boundary
  participation and one-hop connectivity as independent corroborating
  signals. Room-boundary is circular (the face is built FROM the same
  candidate). One-hop connectivity promotes anything touching an evidenced
  neighbour regardless of its own evidence. Both were confirmed, by
  building the adversarial fixtures, to accept a furniture loop, a hatch
  tick, and an isolated room-width pair as strong evidence. The
  replacement model (`pb_wall_room_topology_wall_band_evidence.py`,
  research-only) requires either a thickness recurring at a spatially
  DISTINCT location elsewhere in the drawing, or a topologically-adjacent
  (real corner or opening-gap) neighbour independently showing the same
  thickness — neither producible by one candidate's own local geometry.

## Techniques already used correctly (do not re-derive from scratch)

- Directed half-edge / DCEL-style planar face tracing (`extract_planar_faces`
  in `pb_accuracy_v13_engines_v145.py`) for room reconstruction.
- Relative, drawing-derived tolerances everywhere a threshold is needed
  (never an absolute drawing-unit or benchmark-fitted constant) — W3's
  short-arm fraction, W5's tiny-face fraction, the wall-band model's
  relative thickness-consistency fraction.
- Fail-closed-to-ambiguous at every genuinely underdetermined geometric
  question, enforced by contract validation
  (`WallCandidate.__post_init__`'s CORROBORATED/PROVISIONAL rule), not just
  convention.

## Techniques that do NOT fit here (do not introduce them)

- Hough-transform line grouping and skeletonization/medial-axis — these
  solve *raster* line-extraction problems. PlanReader's vector-CAD pages
  already have native line geometry; these tools have no problem to solve
  there. They ARE the right family of tools for the confirmed-raster pages
  (Ghazi, Murera — near-zero real vector content) once that separate lane
  is built. Do not apply them to a vector-CAD page.

## Before writing any geometric hypothesis

Required test categories (see `AGENTS.md`): synthetic positive + synthetic
look-alike negative, ambiguity/conflict with an explicit expected
abstention, translation/rotation/scale metamorphic, input-order and
re-chunking invariance, deterministic replay, no-mutation, and — before any
wiring — proof that shadow-mode output does not change live predictions.
Real drawings surface failure modes worth fixing; the benchmark's own
expected numbers must never set a threshold.
