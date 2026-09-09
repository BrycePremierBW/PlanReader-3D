# PlanReader Accuracy Gap Ledger

This ledger records measured development-benchmark movements and rejected
accuracy candidates. It is engineering evidence, **not** proof of the final
>=99% target. KSTVET and Murera are development/diagnostic projects and can
never be represented as unseen holdout evidence.

## Measurement rules

- Never populate a measured result without an execution artifact or reproducible run.
- A rejected/regressing candidate remains visible rather than being rewritten away.
- Benchmark gold, mappings, tolerances, or denominators may not be changed to improve a candidate result.
- `null` / `NOT_RUN` means the current benchmark infrastructure did not measure that field.
- Final verified master accuracy remains `NOT_RUN` until a genuinely unseen frozen holdout exists and is scored under the master verification protocol.

## Current development headline

| Metric | Value |
|---|---:|
| Accepted within governing <=5% quantity criterion | 3 / 24 |
| Development accuracy | 12.50% |
| KSTVET | 2 / 13 = 15.38% |
| Murera | 1 / 11 = 9.09% |
| Coverage | NOT_RUN by current quantity benchmark |
| Abstentions | NOT_RUN by current quantity benchmark |
| Critical-error count | NOT_RUN by current quantity benchmark |
| Final unseen-holdout master accuracy | NOT_RUN |

## Gap entries

| Failure cluster | Frequency | Severity | Affected outputs | Suspected root cause | Generic fix / candidate | Measured before | Measured candidate/after | Confidence | Leakage risk | Status | Next action / evidence |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| F.13 raw dimension evidence / destructive anchor ambiguity | Initial candidate changed 3 KSTVET quantity outputs; 0 Murera | MAJOR | KSTVET floor finish and two internal wall-finish comparisons | A valid printed dimension row was discarded when dense vector linework made the graphical anchor ambiguous; downstream F.15 wall-thickness corroboration then disappeared | Preserve documented text constraints when vector anchoring is ambiguous/unsupported; use full witness binding only to add orientation/anchor authority | Main combined 5/24 = 20.83%; KSTVET 4/13; Murera 1/11 | Initial rejected candidate 4/24 = 16.67%; **post-fix candidate restored 5/24 = 20.83%, KSTVET 4/13, Murera 1/11, zero item deltas** | High | Low; generic authority separation plus synthetic mutation/metamorphic tests | RESOLVED IN F.13 CANDIDATE | Run 34241728461 exposed the regression. Post-fix run 34242384720 restored every compared item with unchanged hallucination/miss counts. Keep this regression test permanently. |
| F.22 compound footprint finish basis | 1 scored item crossed <=5% boundary | MODERATE | Internal floor finish | Enclosed finish area was measured on structural outer face while wall thickness was independently evidenced; open verandah required different measurement basis | Component-aware clear-face finish area while preserving structural bed footprint | Combined 4/24 = 16.67% | Combined 5/24 = 20.83%; KSTVET 23.08% -> 30.77%; Murera unchanged | High | Low; unchanged gold and same PDFs | MERGED | PR #206 / commit 774a61f. Preserve through F.13/F.07 work. |
| F.23A vertical datum authority | Quantity score unchanged; authority risk present | CRITICAL authority/safety risk | Wall height dependent wall/finish outputs | Missing/conflicting vertical evidence could inherit assumed default height; roof/floor datum conflicts could be collapsed | Fail closed on conflicting datums; expose provisional wall-height authority and demote confidence when height is assumed | Combined 5/24 = 20.83% | Combined 5/24 = 20.83%; zero quantity movements | High | Low | MERGED | PR #207 / commit 0d97b998. Remaining default-height behavior must remain visibly provisional until stronger evidence exists. |
| F.23 secondary-footprint (verandah) viewport evidence | 0 scored items moved | INFORMATIONAL | Murera substructure_surface_bed / substructure_bed_dpm / substructure_a142_mesh (root cause only, not fixed) | Murera's `partial_missing_components` footprint status traces to a real, un-evidenced verandah width; investigation found the building's only plan-view sheet with the verandah's width (page 229 of the real PDF) is a fully rasterized/scanned sheet with zero extractable vector text or vector geometry -- OCR was explicitly rejected as out of scope (fail-closed is correct, not a parser gap). Separately, KSTVET's existing page-wide verandah regex was found to have no viewport/adjacency scoping at all. | Add a same-F.07-viewport, adjacency-validated, ambiguity-fail-closed secondary-footprint width resolver (`pb_secondary_footprint_evidence.py`) as a stricter *preferred* path ahead of the legacy page-wide regex, which remains as fallback | Combined 5/24 = 20.83% | Combined 5/24 = 20.83%; zero item deltas on either project (KSTVET's composite sheet does not reach a RESOLVED/DERIVED plan viewport under F.07, so it still resolves via the unchanged legacy regex path; Murera has no vector plan evidence to anchor to either way) | High | Low; purely additive, no benchmark-defining file touched | MERGED (additive only) | Purely additive infrastructure, like F.21. Real payoff is conditional on a future document with a genuine vector-drawn floor plan; re-measure whenever a new development/holdout project is added. |
| F.24 opening-tag binding regression | 3 KSTVET items flipped exact/gross -> missed; 3 wall/finish items lost opening deduction | CRITICAL regression | KSTVET BOQ-C41-B, BOQ-C41-C, BOQ-C44-A (windows/door, now `missed_in_extraction`); BOQ-C36-A, BOQ-C46-A, BOQ-C46-C, BOQ-C47-A (wall/finish areas now the undeducted gross area, e.g. perimeter_walling 90.97 -> 103.60) | PR #211 ("F.24: replace dimension-shaped opening aliases with generic documented-tag binding", merged as commit 5d33fa5) no longer recognizes KSTVET's window/door tags, so no openings are extracted or deducted from wall area on that project | Not investigated by this entry -- F.24's opening/schedule-tag binding is actively owned by another concurrent agent (see open work on `codex/f24-*`, `codex/f25-portable-raster-ocr`); do not duplicate that work | Combined 5/24 = 20.83% (pre-F.24, i.e. state at the F.23 entry above) | Combined 3/24 = 12.50% (KSTVET 2/13 = 15.38%, Murera unchanged 1/11 = 9.09%) after F.24 merged | Certain (directly reproduced: `git stash` isolated this to F.24's own diff, not any change in this or the F.23 entry) | N/A -- this is a correctness regression, not a leakage question | OPEN | Whoever next touches opening/window/door tag binding (this codebase's own domain, currently F.24/F.25) should re-run the KSTVET benchmark before merging further changes there -- it is currently broken relative to pre-F.24 `main`. |
| F.8 raster-schedule PV/P.V drafting-legend overcount | 1 Murera item's error widened within the same gross-mismatch tier | MODERATE correctness defect | Murera `brick_vents` | `pb_raster_schedule_extractor._extract_callouts_from_page` matched the standalone abbreviation word "PV"/"P.V" as a vent callout, but real drawings also carry a once-per-sheet legend definition in the generic "<abbrev> denotes <meaning>" convention (this document has both "P.V denotes permanent vents." and "S.V.P denotes soil vent pipe."); that definition word matched the same pattern, adding one phantom vent per sheet carrying the note, then summed across sheets | Exclude a PV/P.V occurrence only when the immediately following word (same block/line, next word index) is "denotes" -- a generic grammatical exclusion, never a benchmark-specific count or page | Combined 3/24 = 12.50% (post-F.24 baseline above); Murera brick_vents extracted 9.0 (25.0% error, gross) | Combined 3/24 = 12.50%, unchanged -- both 9.0 and the corrected 6.0 are outside the <=5% acceptance band, so this item's accept/reject status does not change; Murera brick_vents now 6.0 (50.0% error, still gross) | High | Low; synthetic-only tests, no benchmark gold touched | MERGED | A genuine double-counting defect fixed on correctness grounds per this project's own authority-over-score-chasing precedent (F.23A); it does not by itself close the remaining gap to 12 (real evidence for the other 6 vents was not found within the reachable drawing pages during this investigation). |
| New development benchmark: Ghazi Primary School science lab | 3rd real project registered; 0/13 accepted on first score | INFORMATIONAL (benchmark acquisition, not a fix) | Entire pipeline generalization | KSTVET and Murera are both a single main room (or two adjoining rooms) plus one open verandah; no development benchmark previously tested a genuinely multi-room floor plan (this project has Laboratory + Office + Store + Preparation Room side by side) | Registered `tenders_ke_ghazi_science_lab` (real NG-CDF tender, tenders.go.ke, SHA-256-verified, 13 curated measurable items transcribed directly from the real BOQ with page-image cross-checks) as a new development benchmark, per this project's own precedent (F.1-F.5) of expanding beyond a single diagnostic pair | N/A (new benchmark, no prior baseline) | 0/13 = 0.0% on first score: `perimeter_walling` 151.20 vs 109.00 (38.7% over, gross); `substructure_bed_dpm`/floor_screed within 10-20%; the other 10 items (internal walling, gable walling, G.I. columns, DPC, both doors, the window, internal plaster, internal paint, ceiling lining) all `missed_in_extraction` -- nothing fired at all | High (real evidence, hand-verified against page images) | Low; new SHA-256-pinned source, not derived from or overlapping KSTVET/Murera | OPEN | This exposes that the pipeline is heavily fitted to a single-room-plus-verandah shape: outer-envelope/wall-area detection overshoots on a multi-room footprint, and most derived quantities (plaster, paint, ceiling, DPC, openings) never trigger at all outside that one shape. A genuinely general fix needs to handle multi-room footprints, not just add a per-document patch. `tenders.go.ke` search also turned up "proposed completion of laboratory at kamolo dispensary" and "Our Lady of Victory Girls High School-Kapnyeberai" laboratory complex as further untried candidates; the 6 pre-existing UNGM/tenders.net candidate seeds were checked and are genuinely inaccessible (UNGM requires a login; tenders.net returns 403) -- see `benchmarks/public_tenders/manifest.json` for per-candidate notes. No genuinely unseen frozen holdout has been registered yet (this project was read in full to build its expected values, so it cannot serve as one) -- acquiring one is still open. |
| Benchmark report-set freshness / atomicity | Combined `--all` dashboard could regenerate while project reports stayed on an older run | CRITICAL integrity (not a quantity-gap fix) | Combined dashboard vs per-project accuracy reports consumed by agents | `evaluate_suite` wrote only `headline_accuracy_dashboard.*`; individual `*_accuracy_report.json` files were left untouched, so consumers could mix commits | Publish one run directory (`runs/<run_id>/`) with a shared run ID, evaluated commit, source hashes, and scoring-policy identifier; replace `current.json` only after the set validates; copy compatibility aliases from that run | Unchanged quantity score: reporting-only path; synthetic report-set tests plus `evaluate_benchmark` before/after publication on identical predictions | Unchanged quantity score: no mappings, denominators, or tolerances were edited | High | Low; no gold files touched, public summaries omit expected quantities, holdout IDs stay opaque | OPEN pending merge | Reporting integrity only. Do not treat this as an accuracy movement. Re-run the canonical suite after merge and record the quantity score separately. |
| Final representative unseen holdout | 0 registered projects | CRITICAL verification gap | Entire final >=99% claim | No genuinely unseen frozen project-level holdout has been registered/scored | Acquire, seal, annotate and independently score representative holdout under frozen master metric | NOT_RUN | NOT_RUN | Certain | High if holdout identities/labels leak | OPEN | Do not claim VERIFIED >=99% from development benchmarks. |

## Required fields for future entries

Every new entry must preserve:

```text
failure cluster
frequency
severity
affected outputs
suspected root cause
generic fix
measured before/after effect
confidence
leakage risk
next action
execution evidence
coverage
abstentions
critical errors
project split
```

Fields absent from the evaluator remain `null` / `NOT_RUN`; they are never inferred from a quantity percentage.
