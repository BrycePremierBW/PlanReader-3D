# PlanReader v2 — Target Architecture for Generic Construction-Drawing Understanding

**Status:** Design document. No production code or benchmark gold changed by this document.
**Scope:** The accuracy/benchmark extraction subsystem (`pb_planreader_pdf_extractor.py` and the ~20
evidence/geometry helper modules it imports, `pb_raster_schedule_extractor.py`,
`pb_opening_deduction_pipeline.py`, `pb_benchmark_accuracy_engine.py`). The separate commercial
3D-viewer/BIM subsystem (`pb_planreader_3d_app.py`, `pb_canonical_building.py`,
`pb_editable_3d_*.py`, `pb_production_3d_adapter*.py`) is treated as an architectural boundary, not
audited file-by-file — see §1.2.
**Method:** Four parallel first-hand code audits (direct file reads, not inference) covering
dimension/scale authority, footprint/room geometry, openings/schedules/tags, and viewport
segmentation/canonical-graph wiring, plus direct reading of the central orchestrator
(`pb_planreader_pdf_extractor.py`). All file:line citations below were read directly, not guessed.
This document also reconciles an independent architecture/migration analysis received during
drafting (credited inline as "the migration analysis"); where the two disagree on a factual claim,
this document defers to the directly-verified code reading and says so explicitly.

---

## 1. Executive diagnosis

### 1.1 The core problem, in one sentence

PlanReader's accuracy pipeline computes quantities from **flat arithmetic over parsed numbers**
(the largest two dimensions on a page, a page-wide keyword match, a schedule-row count) rather
than from **a reconstructed building** (walls with junctions, room polygons, openings hosted by a
specific wall). Every feature added this session (F.7 through F.31) has made those arithmetic
heuristics more corroborated and more fail-closed — genuinely valuable, hard-won safety work — but
none of them has changed the fundamental shape: there is still no topology anywhere in the live
extraction path.

### 1.2 A second, load-bearing finding: two disconnected subsystems already exist

`pb_planreader_pdf_extractor.py` has **zero top-level imports of any other `pb_*` module** — it is
a 1,585-line monolith that does ~15 local (function-scoped) imports of specialized evidence
modules and wires them together procedurally inside one class. Tracing those imports and their
own dependents produced a second finding that reshapes the whole design: this monolith plus its
~20 helper modules form one closed subsystem (call it **the 2D accuracy pipeline**), and a
completely separate ~140-file subsystem exists (`pb_planreader_3d_app.py`,
`pb_canonical_building.py`, `pb_geometry_services.py`, `pb_editable_3d_*.py`,
`pb_production_3d_adapter*.py`, `pb_bim_viewer.py`, the `pb_opening_*_v17x.py` family, and dozens
of version-suffixed files) — call it **the 3D/BIM subsystem**. A repo-wide grep confirms neither
`pb_planreader_pdf_extractor.py` nor `pb_benchmark_accuracy_engine.py` imports
`pb_canonical_building` or `pb_canonical_persistence` at all, in either direction.

This matters enormously for the design, because **the 3D/BIM subsystem already contains almost
exactly the canonical building graph this document was asked to design**:
`pb_canonical_building.py` defines `CanonicalProject → CanonicalBuilding → CanonicalLevel →
{CanonicalWall (with nested CanonicalOpening), CanonicalSpace, CanonicalFloor, CanonicalCeiling,
CanonicalRoof, CanonicalSoffit, CanonicalBalcony, CanonicalParapet, CanonicalColumn,
CanonicalBalustrade, CanonicalScreen, CanonicalFinishSurface}`, every element carrying a
`Provenance` record (source PDF, page, drawing id, coordinate space, producer module/version,
contributing evidence) and fail-closed defaults (`confidence: Optional[float] = None`,
`review_state = REVIEW_REQUIRED`, `takeoff_eligible: bool = False`,
`deduction_authority: bool = False`, with a strict-bool parser that refuses to let a string
`"true"` grant authority). `pb_geometry_services.py` sits on top of it doing exactly the kind of
deterministic, PDF-agnostic geometry computation (`wall_gross_area`, `potential_net_wall_area`
with opening-overlap detection, `space_floor_area` via the shoelace formula, `level_extents`) that
a target quantity engine should do. This is not aspirational or dead code — it is actively
imported by a dozen files in the 3D subsystem.

**One important caveat verified directly, not assumed:** the v170–v175 opening-evidence pipeline
files (`pb_opening_deduction_v174.py`, `pb_opening_evidence_v170.py`, `pb_opening_production_v175.py`)
each import only the single utility function `parse_strict_bool` from `pb_canonical_building.py` —
none of them was found constructing `CanonicalWall`/`CanonicalOpening`/`CanonicalSpace` instances
from real PDF evidence in the files this audit read. The only files that actually instantiate
these dataclasses are `pb_canonical_building.py` itself and `pb_synthetic_3d_fixture.py`. This
means the schema is right, but **its automated population from real drawing evidence is thin or
absent** — plausibly the 3D subsystem's model is populated substantially through the
"editable 3D correction" (user-edited) workflow rather than automated extraction. The
recommendation below is therefore not "wire the existing pipeline into the existing schema" (that
wiring barely exists) but "**target the existing schema as the destination**, and build the
missing automated population path as new work" — a smaller, more honest task than inventing a new
schema from nothing, but real new engineering nonetheless.

### 1.3 Top five concrete findings (all directly verified, file:line cited)

1. **No wall/room topology anywhere in the live path.**
   `GenericPlanReaderExtractor._detect_outer_envelope()` (`pb_planreader_pdf_extractor.py:205-289`)
   selects "the two largest orthogonal dimensions whose product falls in a plausible building-area
   range" from a flat list of numbers parsed off the page. F.30's newer
   `pb_orthogonal_envelope_evidence.py` is a real improvement (requires oriented dimension text
   plus independent floor-area corroboration before it fires) but is architecturally the same
   shape: it still resolves to exactly **one** `(length, width)` pair for "the building" — never a
   room-by-room polygon set. `MultiSpaceFootprintBuilder` (`pb_multi_space_footprint_geometry.py`)
   *can* hold arbitrary polygons and genuinely computes shared-edge/perimeter geometry, but the
   only caller (`pb_planreader_pdf_extractor.py:617-634`) ever constructs exactly one main
   rectangle plus at most one verandah, hard-coded to `adjacency="front"`. The generic engine
   exists; the caller never exercises its generality.

2. **Openings are bound to one synthetic wall, not to real wall segments.**
   `pb_planreader_pdf_extractor.py:1518-1568` constructs a single `WallInstance(wall_id=
   "perimeter_walling", ...)` and attaches **every** detected door/window to that one object before
   calling the deduction pipeline. `pb_opening_deduction_pipeline.py`'s own `bind_openings_to_walls`
   is more sophisticated in isolation (bbox-overlap binding, or "if there's exactly one wall, bind
   everything to it with zero spatial check") — but the production caller only ever gives it one
   wall, so the sophistication is unreachable. There is no per-instance placement along a wall, no
   room-pair adjacency, no swing/thickness geometry.

3. **A rich, unused canonical building graph already exists** (§1.2) — the target schema for Part
   2 of this brief should extend `pb_canonical_building.py`, not invent a parallel one.

4. **Two independent, disagreeing wall/room-height resolvers, plus a third default.**
   `pb_dimension_graph_constraint_engine.resolve_wall_height()` is strict (`UNRESOLVED` on missing
   evidence, `CONFLICT_MANUAL_REVIEW` on disagreement, never guesses). `pb_height_evidence_v150.
   resolve_height()` is a completely independent regex pipeline that **always** returns a number,
   defaulting to **2.70 m** in multiple places (including a second, separately-hardcoded 2.70 in
   `get_default_height()`'s exception handler). `pb_planreader_pdf_extractor.py:68-69` has its own
   third default, **2.80 m** (`default_ceiling_height_m`). Three sources of truth for the same
   physical quantity, two of which are silent numeric defaults that a caller reading only the
   float (not the accompanying status string) cannot distinguish from a real measurement.

5. **Three independently-maintained "bare number = millimetres" parsers**
   (`pb_dimension_graph_constraint_engine.parse_dimension_tokens_from_text` — confirmed unused in
   production wiring, only referenced by its own test; `pb_figured_dimension_evidence.
   classify_dimension_token`; `pb_figured_dimension_authority.parse_figured_dimension_mm`), each
   with independently maintained regex. Not currently causing a known defect, but exactly the kind
   of duplicated-evidence risk that produces silent drift.

### 1.4 What is genuinely already good and must not be thrown away

The fail-closed discipline in the *individual* evidence modules is consistently strong and should
be the model for everything new:

- `pb_explicit_floor_area_evidence.py`, `pb_secondary_footprint_evidence.py`,
  `pb_secondary_area_support_evidence.py`, `pb_slab_classification_geometry.py`,
  `pb_structural_bay_pillar_count.py`, `pb_page_scale_calibration_authority.py`,
  `pb_viewport_dimension_binding.py`, `pb_contextual_wd_card_evidence.py`, and
  `pb_explicit_item_count_extractor.py` all fail closed to `None`/`UNRESOLVED`/an empty result on
  ambiguity, multiple disagreeing candidates, or missing spatial corroboration — never guessing.
- `pb_viewport_segmentation.py` is a genuine, spatially-grounded viewport system (native vector
  frame detection, RESOLVED/DERIVED/AMBIGUOUS states, per-viewport view-type classification) and
  is **already transitively live-wired** into the production path via
  `pb_dimension_chain_evidence_extractor.py` and `pb_secondary_footprint_evidence.py`. This is
  the one piece of "spatial viewport segmentation" infrastructure the parallel Cursor workstream
  should extend rather than duplicate.
- `pb_geometry_takeoff_model.py`'s `MeasurementAuthorityType`/`AuthorityStatus` enums and its
  `reconcile_figured_and_scaled()` precedence rule (figured beats scaled, escalates to review on
  disagreement) are exactly the right authority primitive and are already reused by several other
  evidence modules.
- `pb_raster_schedule_extractor.py`'s multiple schedule-layout detectors (structured tables,
  row/column-aligned, callouts, card-style, contextual WD-fragment reconstruction) represent real,
  hard-won support for distinct real-world drafting conventions and should be kept as pluggable
  evidence providers, not replaced by a single model call.
- The benchmark integrity infrastructure — `scripts/check_benchmark_gold_separation.py` (blocks
  benchmark-gold and production-code changes in the same PR), the leakage-audit tests, and the
  frozen-holdout registry (`pb_holdout_suite_registry.py`) — is sound and should be extended, not
  replaced.

---

## 2. Current architecture map

```
                         GenericPlanReaderExtractor.extract_from_pdf()
                         (pb_planreader_pdf_extractor.py, 1585 lines, one class)
                                            │
        ┌───────────────────────────────────┼───────────────────────────────────────┐
        │ cross-page pre-scan (per drawing   │ per-page extraction                    │ post-pass
        │ page, in document order)           │                                        │
        ▼                                    ▼                                        ▼
 explicit floor area          figured dimension parsing              opening deduction
 (pb_explicit_floor_area_      (regex over page text; feeds          (pb_opening_deduction_
  evidence.py)                 _detect_outer_envelope OR             pipeline.py — binds every
 secondary footprint width     pb_orthogonal_envelope_evidence.py    opening to ONE synthetic
  (pb_secondary_footprint_     when explicit floor area exists)      "perimeter_walling" wall)
  evidence.py, viewport-              │
  scoped via pb_viewport_            ▼
  segmentation.py)             MultiSpaceFootprintBuilder
 level datums (pb_level_       (pb_multi_space_footprint_
  datum_extraction.py —         geometry.py) — ALWAYS: one
  page-wide, NOT viewport-      main rectangle + at most one
  scoped)                       frontal verandah, in practice
 dimension chains / wall              │
  thickness (pb_dimension_            ▼
  chain_evidence_extractor.py,  component-aware floor finish
  pb_dimension_graph_           (pb_component_floor_finish_
  constraint_engine.py)         geometry.py) — requires exactly
 corroborated support counts   ONE main-building component
  (pb_secondary_area_support_
  evidence.py, pb_structural_
  bay_pillar_count.py)
 DPC/DPM/mesh/surface-bed
  keyword flags (regex,
  page-wide)
 roof pitch / span

        │
        ▼
 GenericScheduleTableExtractor (pb_raster_schedule_extractor.py)
   ├── native table grid detection (page.find_tables())
   ├── row-aligned / column-aligned word clustering
   ├── callout counting (pb_explicit_item_count_extractor.py)
   ├── card-style "Overall Quantity" resolver
   └── contextual WD-fragment reconstruction (pb_contextual_wd_card_evidence.py)
        │
        ▼
 OCR evidence fallback + native/OCR reconciliation (pb_drawing_ocr_evidence_layer.py)
   — reconciles by TAG STRING MATCH only, not spatially; own regex tag parser,
     independent of pb_opening_tag_normalization.py
        │
        ▼
 dict[tag -> ExtractedPrediction]  (flat: tag, trade_type, quantity, unit, confidence,
                                     source_page, dimensions, bounding_box, metadata)
```

**Separate, disconnected subsystem** (not modified or extended by anything above):

```
pb_planreader_3d_app.py (7,412 lines)
  → pb_editable_3d_*.py, pb_bim_viewer.py, pb_production_3d_adapter*.py
        → pb_canonical_building.py  (CanonicalProject/Building/Level/Wall/Opening/Space/...,
                                      Provenance, fail-closed defaults — NO PDF evidence reading
                                      anywhere in this file)
        → pb_geometry_services.py   (deterministic geometry over supplied canonical objects only,
                                      explicitly refuses to become "another PDF extraction engine")
        → pb_canonical_persistence.py (versioned JSON persistence, source fingerprinting,
                                        staleness detection)
  → pb_opening_evidence_v170.py / pb_opening_production_v175.py / pb_opening_deduction_v174.py
        (import only `parse_strict_bool` from pb_canonical_building — do not construct its
         dataclasses from PDF evidence in the code paths read for this audit)
```

Two other things worth naming precisely, because they will matter for the roadmap:

- `pb_viewport_dimension_binding.py` implements the *correct* pattern (a dimension observation is
  only assigned to a viewport when it is fully spatially contained, with RESOLVED viewports
  required by default) but **is not imported by `pb_planreader_pdf_extractor.py` at all** — built,
  tested, and unwired.
- `pb_level_datum_extraction.find_level_markers()` runs its regex over the **whole page text**
  with `scope_id` always `None` (`pb_level_datum_extraction.py:80-111`), and the call site
  (`pb_planreader_pdf_extractor.py:401-402`) passes whole-page text with no viewport filtering —
  a real page-wide-regex anti-pattern sitting right next to the properly viewport-scoped dimension
  chain call a few lines later in the same function.

---

## 3. Architectural weaknesses, organized by the anti-pattern taxonomy requested

| Anti-pattern | Where (file:line) | Concrete consequence |
|---|---|---|
| Page-wide regex, no spatial scoping | `pb_level_datum_extraction.py:94-99` and its call site `pb_planreader_pdf_extractor.py:401-402`; `pb_height_evidence_v150.py`'s plain-text fallback path | A level marker or height keyword on one viewport of a multi-viewport sheet is silently treated as belonging to the whole page. |
| Largest-dimension / envelope assumption | `pb_planreader_pdf_extractor.py:205-289` (`_detect_outer_envelope`); `pb_orthogonal_envelope_evidence.py:248-257,291-292` (same shape, stricter gating) | Cannot represent two disconnected wings; already documented in `ACCURACY_GAP_LEDGER.md` as the root cause of Ghazi's multi-room failures this session. |
| Single-room assumption | `pb_component_floor_finish_geometry.py:67-72` (hard-requires exactly one `MAIN_BUILDING` component, returns `None` otherwise — safe but not general); `pb_planreader_pdf_extractor.py:617-634` (production caller of the generic multi-space builder only ever adds one main room + one frontal verandah) | A genuinely multi-wing building's finish areas cannot be computed even though the underlying geometry engine could represent it. |
| Benchmark-shape sensitivity | `pb_secondary_area_support_evidence.py` (module docstring self-describes the "verandah between two repeated-bay chains with an adjacent pole/column spec" pattern as a specific scenario fingerprint); `add_verandah(..., adjacency="front")` hard-coded at the only call site | Correctly and honestly documented as scenario-specific in its own comments — good practice, but confirms the general engine is under-exercised. |
| Schedule-layout-specific logic | `pb_raster_schedule_extractor.py:437` (`x < 600` title-block cutoff), `:446` (`>80pt` column-gap threshold), `:357-363` (requires literal words "schedule" + "window(s)/door(s)" on the page) | A schedule titled "Fenestration Schedule" or "Joinery Schedule", or laid out on a non-standard page size, silently produces zero rows via these paths (other paths may still catch it). |
| Implicit geometry from text without spatial grounding | `pb_height_evidence_v150.py` `_classify_dimension_orientation()`/`_find_paired_rls()` (nearest-keyword-within-±50-characters, even in the code path that has real word bounding boxes available) | Two vertically-stacked but unrelated numbers on a section drawing can be paired as if measuring the same thing. |
| Default dimensions/heights becoming silently authoritative | `pb_height_evidence_v150.py` defaults to 2.70 m in `resolve_height()` and again independently in `get_default_height()`'s exception handler; `pb_planreader_pdf_extractor.py:68-69` defaults to 2.80 m | Two different silent fallback constants for the same physical quantity, and a caller reading only the returned float cannot tell a default from a measurement without also inspecting a separate status string. |
| Duplicated evidence, no reconciliation | Wall/room height (item above); three independent "bare number = mm" parsers (`pb_dimension_graph_constraint_engine.parse_dimension_tokens_from_text` — unused in production, `pb_figured_dimension_evidence.classify_dimension_token`, `pb_figured_dimension_authority.parse_figured_dimension_mm`) | Any future change to the mm-assumption convention must be made in three places or silently drifts. |
| Order-dependent logic | `pb_opening_deduction_pipeline.bind_openings_to_walls` (bbox-overlap case takes the *first* overlapping wall via `break`, order depending on wall list order — currently unreachable because production only ever supplies one wall, but latent); `pb_raster_schedule_extractor.deduplicate_schedule_rows`'s explicit priority-tuple tie-break (this one is fine — documented as intentional, not a flag) | Currently masked by finding #2 above (single synthetic wall means the order-dependent branch is never exercised) — will become a real bug the moment per-wall binding is implemented without also fixing the tie-break. |
| Hard-coded drawing conventions | `pb_orthogonal_envelope_evidence.py:226-229,300` (secondary strip assumed to run along the main envelope's *length*, not its width — a site convention, not a geometric derivation); `pb_secondary_footprint_evidence._SECONDARY_SPACE_LABELS = ("verandah", "veranda")` (a carport, patio, or porch is invisible to this module by design) | Correctly fails closed rather than misfiring, but silently produces "missed" on any document using a different convention/vocabulary. |
| Fragile tag normalization | `pb_drawing_ocr_evidence_layer.py`'s own tag regex (`[WwDd]\s*[-_]?\s*[A-Za-z0-9]+`, line 240) is broader and less guarded than the canonical `pb_opening_tag_normalization._TAG_RE`, and does **not** call `normalize_opening_tag` at all — a token like `D8-03` could become tag `D8-03` here while the rest of the pipeline would produce `D8`, silently splitting one physical opening's evidence into two tag identities. | A real, currently-latent double-counting or missed-reconciliation risk whenever OCR evidence and native evidence for the same opening are both present. |
| Geometry calculated before topology is established | `pb_planreader_pdf_extractor.py:637,674` — `derived_footprint_area_m2`/`perimeter_m` are computed directly from the two scalar `(length_m, width_m)` values the moment they're resolved, before (and instead of) any wall/room graph exists | This is the single largest structural gap this document exists to close — see §5. |

**Duplicated-implicit-authority risk (not in the requested taxonomy but found directly and worth
flagging):** `DimensionObservation.authority` defaults to `MeasurementAuthorityType.
DOCUMENTED_DIMENSION` and `confidence` defaults to `1.0` in the dataclass itself
(`pb_dimension_graph_constraint_engine.py:123-124`). Every current call site passes explicit
values, so this is not an active bug, but it means the *safe default* for this dataclass is
"trust completely," not "fail closed" — a real risk for whoever adds the next call site without
reading this closely.

---

## 4. Proposed target architecture

### 4.1 Pipeline shape

```
PDF (or image set)
        │
        ▼
┌─────────────────────────────┐
│ 1. DocumentEvidence          │  immutable raw facts: source hash, per-page native words/
│                               │  vector primitives/embedded images/tables, no semantics
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 2. ViewportEvidence          │  spatial region + view-type + scale, per page
│  (pb_viewport_segmentation.py │  — EXTEND this existing module, do not replace it
│   already does most of this) │
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 3. EntityEvidence             │  NEW LAYER — candidate physical objects with supporting/
│                               │  conflicting evidence references, before identity is decided
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 4. CanonicalBuildingGraph     │  EXTEND pb_canonical_building.py's existing schema —
│                               │  do not invent a second one (see §1.2, §5)
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 5. SemanticBuildingModel      │  ontology classification bound to graph entities
│                               │  (room type, finish type, substructure type)
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 6. QuantityEvidence           │  deterministic formulas over resolved entities only,
│                               │  each result carrying a full evidence/derivation trace
└─────────────────────────────┘
        │
   ┌────┴─────┐
   ▼          ▼
Production   Benchmark
DB adapter   adapter → ExtractedPrediction (compatibility shape only)
```

**Why the `EntityEvidence` layer is added on top of the brief's original five-layer sketch:**
without it, viewport evidence tends to mutate directly into a wall/room/opening the moment it is
observed — which is exactly today's failure mode (a dimension pair becomes "the envelope" the
instant two numbers are found). `EntityEvidence` is where multiple independent signals about the
*same physical thing* — a native plan rectangle, a schedule row, an elevation callout, an OCR
mark — get bundled as competing/corroborating evidence for one candidate entity, and where
conflicts get resolved or explicitly left unresolved, **before** anything is promoted into the
canonical graph. This is the direct fix for finding #1 and #2 in §1.3: an opening becomes a
`CanonicalOpening` only after its `EntityEvidence` bundle has been reconciled against candidate
wall segments, not the instant a tag+quantity pair is parsed.

### 4.2 Geometry reconstruction (Part 3 of the original brief)

**Wall reconstruction.** Native vector evidence is the highest-priority source, following the
existing `pb_vector_geometry_v130.py` pattern (`extract_native_page`, `snap_geometry` — a
node/edge graph built by snapping nearby endpoints within a point tolerance, `detect_wall_pairs`
— parallel-line wall-face candidate detection) which **already exists but is wired only into
`pb_planreader_v126_app.py`, a different entry point from the benchmark pipeline.** The target
design reuses this module's algorithms (snap-to-graph, parallel-pair detection) rather than
re-implementing them, extended with:
- junction classification (T/L/X) from the snapped node graph's degree and incident-angle pattern;
- wall thickness from the parallel-pair spacing, cross-checked against
  `pb_dimension_chain_evidence_extractor.resolve_corroborated_wall_thickness_m()` (already
  requires ≥2 independent chain candidates to agree — reuse this corroboration requirement, don't
  weaken it);
- fragmented/curved-wall handling as an explicit `UNRESOLVED` state, not a silent straight-line
  approximation.

**Room reconstruction.** Build closed planar faces from the wall graph's cycles (standard
planar-graph face extraction over the snapped node/edge graph), *not* from "the two largest
dimensions." `MultiSpaceFootprintBuilder`'s shoelace-area and shared-edge-detection code
(`pb_multi_space_footprint_geometry.py:113-175,221-240`) is directly reusable once given real
polygons instead of one synthetic rectangle — this is the concrete mechanism by which "genuinely
general" room reconstruction connects to code that already exists and is already tested.
Disconnected wings, courtyards, and corridors fall out naturally once faces come from a real graph
instead of a caller-constructed rectangle list.

**Opening reconstruction.** A door/window becomes a `CanonicalOpening` hosted by a specific
`CanonicalWall` (the schema already supports this nesting) only when its `EntityEvidence` bundle
resolves to: (a) a wall segment whose centerline the opening's bbox is spatially close to
(replacing bbox-overlap-with-first-match, fixing the order-dependence flagged in §3), and (b) a
schedule/tag identity via the *existing* `pb_opening_tag_normalization.normalize_opening_tag` (used
consistently everywhere, closing the OCR-layer's independent, less-guarded tag regex gap flagged
in §3). Deduction then runs per-instance, per-host-wall — never against one synthetic aggregate.

### 4.3 Scale and dimension authority

Adopt the *existing* `MeasurementAuthorityType`/`AuthorityStatus` ladder
(`pb_geometry_takeoff_model.py`) as the single authority vocabulary for the whole pipeline,
replacing `pb_height_evidence_v150.py`'s independent, disagreeing status strings
(`"Measured"`/`"Provisional measured"`/`"Default/fallback"`/`"Review"`). Concretely:

| Tier | Source | Existing code that already implements this tier correctly |
|---|---|---|
| 1 | Explicit figured dimension, spatially bound to geometry | `pb_figured_dimension_evidence.DimensionEvidenceTier.WITNESS_BOUND` |
| 2 | Dimension chain (multiple witnesses reconciled) | `pb_dimension_chain_evidence_extractor.py` |
| 3 | Drawing scale verified against a figured dimension | `pb_page_scale_calibration_authority.py` (already implements "TITLE_BLOCK-only reading is VALID but capped at PROVISIONAL, never FIRM") |
| 4 | Derived geometry corroborated by independent evidence | `pb_orthogonal_envelope_evidence.py` (already requires independent floor-area corroboration within 1.5% before it fires) |
| 5 | Assumption/default | Must be visibly and permanently marked provisional; **never** flows into a `firm`/`CONFIRMED` quantity |

The concrete fix for finding #4 (§1.3): `resolve_wall_height()`'s strict behavior
(`pb_dimension_graph_constraint_engine.py`) becomes the *only* wall-height resolver.
`pb_height_evidence_v150.py`'s always-succeeds behavior is either retired or explicitly demoted to
populate Tier 5 only, and the 2.70/2.80 discrepancy is deleted by having exactly one named
constant, owned by one module, used everywhere a provisional height is genuinely needed for a
non-authoritative UX estimate.

### 4.4 Evidence fusion

A generic fusion function takes an `EntityEvidence` bundle and produces one of:
`CONFIRMED` (≥2 independent, agreeing evidence sources spatially bound to the same candidate),
`SUPPORTED` (one strong evidence source, no conflicts), `PROVISIONAL` (weak/single low-confidence
source), `AMBIGUOUS` (multiple candidates score within a small margin of each other — this pattern
already exists and works well in `pb_contextual_wd_card_evidence.py:251-253`, which explicitly
drops a match when two candidates are too close in score rather than picking the nearer one; reuse
this exact rule generically), or `CONFLICTING` (disagreeing values from sources that should agree
— e.g., a schedule count vs. a plan count that disagree by more than a specified tolerance). This
maps directly onto `pb_drawing_evidence_binding.ReconciliationStatus`
(`CONFIRMED`/`PROVISIONAL`/`CONFLICT_MANUAL_REVIEW`), which already exists and already handles
cross-view (plan/elevation/section/schedule) reconciliation with fail-closed conflict handling —
extend this enum with `AMBIGUOUS` and `SUPPORTED` rather than building a new one.

### 4.5 Semantic construction ontology

Separate geometry from construction semantics explicitly. A resolved `CanonicalSpace` polygon
(37.42 m²) plus a semantic classification (`room_type=laboratory`, `floor_finish=ceramic_tile`,
`wall_finish=plaster_and_paint`, `ceiling=gypsum_board`) should let the quantity engine emit
`floor_finish_area = 37.42 m²` from one generic rule ("floor finish area = the room's own floor
polygon area, when a floor-finish specification is bound to that room") instead of the current
approach of a bespoke keyword regex per finish type scattered through
`pb_planreader_pdf_extractor.py` (`_has_dpm_specification`, `_has_surface_bed_specification`,
`_has_internal_plaster_finish`, etc. — each a hand-written page-wide keyword detector). Start the
ontology with the trade categories the current schema already names in
`pb_canonical_building.ObjectType` and `pb_geometry_takeoff_model.KNOWN_FINISH_TAGS`
(excavation/hardcore/blinding/concrete/reinforcement/formwork/masonry/DPC/DPM/wall
finishes/floor finishes/ceilings/roofing/doors/windows/painting/fixtures) — do not try to encode
every trade on day one; the mechanism (bind a specification to an entity, derive quantity from
entity geometry) is the reusable part, not the initial vocabulary size.

### 4.6 Quantity engine

Every quantity becomes a deterministic formula over *resolved* entities, always carrying a full
trace, in the shape already partially implemented by
`pb_geometry_takeoff_model.calculate_wall_takeoff()` (generic `gross = length × height`, deducts
openings above a named threshold under a named standard, is already agnostic to how many
walls/rooms exist) — generalize this pattern to floor/ceiling/DPC/DPM instead of leaving it
wall-only:

```
floor_finish_area  = Σ room.polygon_area for rooms bound to that finish spec
wall_length        = wall.centerline_length_m  (from resolved topology, not a dimension guess)
gross_wall_area     = wall_length × wall_height_authority
net_wall_finish     = gross_wall_area − Σ hosted_opening.area for openings actually hosted by this wall
dpc_length          = Σ length of wall segments whose specification includes a DPC callout
dpm_area            = ground-bearing slab polygon area, only for slabs classified as ground-bearing
doors/windows       = resolved physical instance count, or schedule-authoritative quantity when
                      instance-level resolution is not (yet) achieved — never both summed
```

Each result should carry a trace equivalent to:

```
Quantity: internal_plaster = 142.8 m2
Derived from: 12 wall surfaces (entity ids listed)
Gross: 158.4 m2   Opening deductions: 15.6 m2 (4 openings, listed)
Height authority: dimension chain #142, Tier 2
Geometry source: sheet A03, viewport vp_2
Confidence: 0.96   Status: firm
```

---

## 5. Canonical schemas

**Recommendation, stated once, unambiguously: extend `pb_canonical_building.py` and
`pb_geometry_services.py`. Do not create a parallel `CanonicalBuildingGraphV2`.** The existing
schema already has the right entity list, the right relationships (via `parent_id`/`children_ids`
and per-level aggregation in `CanonicalLevel`), the right provenance object, and the right
fail-closed defaults. The gap is not the schema — it is that nothing in the accuracy pipeline
populates it from real evidence yet (§1.2's caveat).

Concrete extensions needed on top of the existing schema:

- Add an explicit `authority: MeasurementAuthorityType` and `confidence_tier` field to
  `CanonicalElement` (currently only a bare `Optional[float] confidence`), so the pipeline can
  reuse the single authority vocabulary from §4.3 uniformly across every entity type, not just
  dimensions.
- Add `supporting_evidence_ids: List[str]` and `conflicting_evidence_ids: List[str]` to
  `CanonicalElement.metadata` (or promote to real fields) so an entity's derivation is fully
  auditable back through `EntityEvidence` to `DocumentEvidence` — the existing `Provenance` object
  already carries `contributing_evidence: List[str]`, which is most of this; it just needs to
  distinguish supporting from conflicting.
- Add a `wall_id` reference on `CanonicalOpening` (host-wall binding) if not already present in the
  full class body (not fully verified in this pass — confirm before implementing M8/M12 in the
  roadmap below).

`EntityEvidence` (new, sits between `ViewportEvidence` and the canonical graph):

```json
{
  "candidate_entity_id": "opening_candidate_842",
  "candidate_type": "window",
  "evidence_ids": ["ev_plan_441", "ev_sched_091", "ev_elev_212"],
  "conflicts": [],
  "resolution": "confirmed",
  "confidence": 0.99
}
```

`QuantityEvidence` (new, replaces `ExtractedPrediction` as the internal representation;
`ExtractedPrediction` becomes a compatibility/export shape only):

```json
{
  "quantity_id": "q_wall_finish_0091",
  "family": "internal_wall_finish",
  "semantic_key": "internal_plaster",
  "value": 203.4,
  "unit": "m2",
  "input_entity_ids": ["wall_11", "wall_12"],
  "formula": "SUM(net_face_area_m2)",
  "formula_version": "wall_finish_v1",
  "evidence_ids": ["..."],
  "authority": "documented_dimension",
  "confidence": 0.97,
  "status": "firm",
  "abstained": false,
  "blocking_reasons": []
}
```

---

## 6. Evidence-authority model

Adopt the five-tier ladder in §4.3 as the one authority vocabulary. Concretely:

- **Tier 1-2 (documented/chain) is never overridden by Tier 4-5 (derived/default).** This is
  already the rule `reconcile_figured_and_scaled()` implements for the figured-vs-scaled case
  (`pb_geometry_takeoff_model.py:300-344`); generalize it to every tier pair.
- **A default (Tier 5) may populate a UX-visible provisional estimate but must never set
  `status="firm"` or `deduction_authority=True`.** This directly fixes finding #4: the 2.7/2.8
  disagreement is not really about which number is "more correct" — it's about the fact that both
  numbers are currently allowed to become authoritative silently. Under this rule, neither can.
- **Conflicting evidence is preserved, not resolved by preference.** `CONFLICT_MANUAL_REVIEW` /
  `CONFLICTING` states already exist in `pb_dimension_graph_constraint_engine.ConstraintStatus` and
  `pb_slab_classification_geometry.SlabResolutionState` — reuse these states in the new
  `EntityEvidence` fusion layer rather than inventing another status enum.
- **Ambiguity fails closed by default.** The existing near-tie abstention pattern in
  `pb_contextual_wd_card_evidence.py:251-253` (drop the match if two candidates score within
  `max(2.0, 0.15×score)` of each other) is the concrete template — generalize this exact numeric
  discipline (a relative-margin threshold, not just "pick the best") into the generic fusion
  function in §4.4.

---

## 7. Building-graph design

Entity types (mapped directly onto the existing `pb_canonical_building.ObjectType` enum — no new
names needed for the initial scope): `Level`, `Space` (room/zone), `Wall` (with `WallAssembly`
metadata: thickness, material, both-face finish bindings), `Opening` → `Door`/`Window`, `Column`,
`Beam` (not yet in the existing enum — add), `Slab`/`Floor`, `Roof`, `Ceiling`, `FinishSurface`,
plus non-physical `Grid`, `Dimension`, `Annotation`, `Schedule`, `Specification` evidence types
that live in `EntityEvidence`/`DocumentEvidence`, not the physical graph (the existing
`CanonicalEvidenceObservation` class already models exactly this "evidence that must never gain
deduction authority" concept for elevation-only observations — extend its use rather than
reinventing it).

Relationships, using the existing `parent_id`/`children_ids`/`level_id` fields plus new named
edges where the current schema is silent: `contains` (Level→Space, existing via `CanonicalLevel`
aggregation), `bounds`/`bounded_by` (Wall↔Space, new), `adjacent_to` (Space↔Space, derived from
shared-edge detection already implemented in `MultiSpaceFootprintGeometry`), `hosted_by`
(Opening→Wall, new — the direct fix for finding #2), `corresponds_to_schedule_entry`
(Opening→ScheduleSpecification, new — replaces today's flat tag-string matching with a real
relationship), `dimensioned_by` (any physical entity → DimensionEvidence, new), `derived_from`
(any entity → its `EntityEvidence` bundle, new).

Every entity and relationship retains provenance via the existing `Provenance` dataclass — no new
provenance schema is needed, only consistent population of the one that exists.

---

## 8. Multi-modal perception strategy

Recommendation: **do not reach for an end-to-end multimodal LLM as the first move.** The existing
pipeline's strength is deterministic, auditable, cheap evidence extraction (native text/vector),
and that should stay the default path for the large majority of drawings that are native-vector
PDFs (every benchmark project registered this session — KSTVET, Murera, Ghazi, Umma, Lamu — has
been native-vector with real extractable text and geometry, not scanned raster). Reserve
model-based perception for the genuinely hard remainder: scanned/rasterized sheets, hand-drawn
annotations, and symbol detection where no native evidence exists at all.

| Task | Candidate approach | Accuracy | Latency | GPU | Training needed | Windows/offline | Verdict |
|---|---|---|---|---|---|---|---|
| Wall segmentation from raster/scanned plans | CubiCasa5K-style CNN segmentation, or classical line-clustering (Hough/LSD) on binarized raster | Moderate-high on clean scans, degrades on noisy/low-res | Low (classical) to moderate (CNN) | Optional for classical, required for CNN | None for classical; fine-tuning for CNN | Classical works fully offline/Windows; CNN needs an inference runtime | Start with classical line-clustering reusing `pb_vector_geometry_v130.snap_geometry`'s approach generalized to raster-extracted lines; escalate to a small fine-tuned segmentation model only for the raster-only residual. |
| Room/floor-plan structure | RoomFormer / FloorPlanCAD-style structured prediction | High on in-distribution CAD exports | Moderate | Required | Substantial (needs FloorPlanCAD-scale data) | Requires a training pipeline this repo doesn't have | Defer; not justified until the deterministic graph path is built and its failure rate on native-vector drawings is actually measured. |
| Door/window symbol detection | Modern object detection (YOLO-class) fine-tuned on architectural symbols | High if trained on genuinely similar drafting conventions | Low at inference | Required for training, optional at inference (CPU-viable for small models) | Real annotation effort | CPU inference is Windows-viable | Reserve for raster-only sheets after native/vector paths are exhausted — most of the current benchmark set doesn't need this at all. |
| OCR | Windows OCR (`winocr`, already integrated in `pb_drawing_ocr_evidence_layer.py`) or Tesseract | Adequate for clean CAD-exported raster text; degrades on handwriting | Low | No | No | Already Windows-native | Keep the existing native-first/OCR-second architecture; it's already correctly designed (fail-closed on low image quality, downgrades to `PROVISIONAL`). |
| Schedule/table understanding | PyMuPDF native table detection (already used) + layout heuristics; document-layout models (LayoutLM-class) only for raster schedules | High for native tables, moderate for raster | Low (native) to moderate (model) | Optional | Fine-tuning needed for model path | Native path already Windows-native | Keep native-first; add a model-based fallback only after measuring how often raster-only schedules actually occur in the target document population. |
| Rasterized/scanned plan processing generally | Cascaded: rasterize → classical line/text extraction → escalate to CV/OCR only for unresolved regions | Depends heavily on scan quality | Variable | Depends on stage reached | Depends on stage reached | Fully controllable | This is the general strategy — see §12 in the companion migration analysis (staged, cheap-first cascade) for the concrete stage design; do not raster-OCR every page by default. |

The system should remain capable of deterministic verification at every stage — a model's output
becomes `EntityEvidence` like any other source, subject to the same fusion/confidence rules, never
a privileged "AI said so" override of a conflicting native-vector or figured-dimension source.

---

## 9. Dataset and training strategy

### 9.1 Splits and leakage prevention

`TRAIN` / `VALIDATION` / `FROZEN HOLDOUT`, with **project-family leakage** prevented explicitly:
KSTVET and the "Kirudi Junior School" candidate rejected earlier this session for being a
byte-identical reused standard-design template are the concrete cautionary example already in
`ACCURACY_GAP_LEDGER.md` — the same discipline (SHA-256 + architect/consultant identity + plan
geometry cross-check against every other registered project) that this session already applies
manually to benchmark acquisition should become an automated pre-registration check as the
dataset grows past what one person can eyeball.

- **Development** (KSTVET, Murera, Ghazi, Umma, Lamu currently): failures here are allowed to
  directly influence implementation. Never call this "unseen."
- **Validation**: independent projects used to decide whether a migration gate (§ below, adapted
  from the migration analysis's per-family gates) is met — used to gate readiness decisions, not
  repeatedly hand-tuned against at the individual-item level, or it silently becomes development
  data.
- **Frozen holdout**: `tenders_ke_olv_laboratory_complex`, already sealed this session with only a
  `source_manifest.json` (no gold, no `.holdout_lock.json`, correctly excluded from all scoring
  paths per `pb_holdout_suite_registry.list_registered_holdout_projects()`). A second holdout
  candidate is worth acquiring before the first real "unseen" evaluation, so that a single
  project's idiosyncrasies don't dominate the final claim.

### 9.2 Intermediate annotations needed

Wall centerlines/thickness, room polygons, door/window instances with host-wall association,
detected symbols (structural columns, fixtures), dimension witnesses, schedule table structure,
viewport type per region, resolved scale, level assignment, and the relationship edges from §7.
None of this needs to be built from scratch as a labeling exercise for every project — for
native-vector drawings, a large fraction can be **bootstrapped from the deterministic graph
reconstruction itself** (§4.2) and only spot-checked/corrected by a human, which is far cheaper
than hand-annotating raster images from zero.

### 9.3 Active-learning loop

Prioritize labeling by where the deterministic graph reconstruction currently produces
`AMBIGUOUS`/`UNRESOLVED`/`CONFLICTING` states (§6) — these are exactly the cases where more
evidence or a human label would change the outcome, as opposed to cases the system already
resolves confidently and correctly. This reuses the existing fail-closed status machine as a
free-of-charge informativeness signal, rather than building a separate uncertainty-sampling
mechanism.

---

## 10. Accuracy and verification framework

Report six distinct metrics, not one percentage — directly reusing the categories the
`ACCURACY_GAP_LEDGER.md` discipline already gestures at (development vs. holdout, "NOT_RUN" until
genuinely measured) and making them a formal, always-reported tuple:

| Metric | Definition | Current state in this repo |
|---|---|---|
| Development accuracy | Accuracy on projects whose failures have influenced implementation | Currently the only number regularly reported (headline dashboard) |
| Validation accuracy | Accuracy on independent projects used only to gate migration readiness | Not yet separated from development in this repo — worth introducing explicitly once the project count grows |
| Unseen holdout accuracy | Accuracy on frozen, never-inspected-during-development projects | `NOT_RUN` — one holdout sealed, zero scored |
| Selective accuracy + coverage | Accuracy only on outputs the system elects to answer, stated alongside the fraction it answered | Not currently tracked; the benchmark's own headline table already has `Coverage | NOT_RUN by current quantity benchmark` and `Abstentions | NOT_RUN` rows waiting to be filled in |
| Critical-error rate | Wrong project match, wrong scale, wrong unit, double-count, unauthorized deduction | Not currently tracked as a distinct category (currently folded into "gross mismatch") |
| Confidence calibration | Whether stated confidence predicts actual correctness | Not currently tracked |

Also report **item-weighted (micro) and project-balanced (macro)** accuracy separately — a
5-project development set where one project (Umma, currently 15/15) dominates the item count can
otherwise mask per-project weakness (KSTVET 3/13, Murera 1/11) behind a healthy-looking blended
number.

### What would legitimately support an 80/90/95/99% claim

Never claim a number the evidence doesn't support. Concretely, before any claim above the current
honest development number:

1. The task universe (units, tolerances, exclusions, denominator/aggregation method) is frozen
   *before* the evaluation, matching this repo's own existing rule that benchmark rules and
   production code cannot change in the same PR.
2. Code, extraction rules, and any model versions are frozen for that evaluation run (the new
   atomic report-set publication infrastructure, `pb_benchmark_report_set.py`, already gives every
   report a shared `run_id`/`evaluated_commit_sha` — this is the right mechanism to build the
   freeze on).
3. Holdout files and their expected values are hash-frozen (already the pattern
   `pb_holdout_suite_registry.py` implements) and never read by the developing agent before the
   run.
4. The holdout is genuinely diverse across project family, source portal, and drafting convention
   — not one project standing in for "unseen."
5. Report the metric tuple above, with confidence intervals, not a point estimate alone.
6. A "99% at 70% coverage" result must always be reported as **"99% selective accuracy at 70%
   coverage,"** never simplified to "99% accurate."
7. No code or tolerance change happens after viewing the holdout result; a subsequent change means
   a new evaluated version, not an inherited score.

---

## 11. Failure-mode analysis (pressure-testing the design)

| Adversarial case | Expected system behavior | Mechanism already available or needed |
|---|---|---|
| Scanned/raster-only plan | Fall back through the staged cascade (§8); lower coverage, not invented geometry | Existing OCR fail-closed image-quality gate in `pb_drawing_ocr_evidence_layer.py` is the right model |
| Rotated drawing | Native text-direction (`line["dir"]` already read by `pb_orthogonal_envelope_evidence.py`) should normalize orientation before dimension classification | Extend existing direction-vector reading generically |
| Multiple plans per sheet / overlapping views | Viewport segmentation must assign each entity to exactly one viewport or explicitly split evidence between DERIVED partitions | `pb_viewport_segmentation.py` already has RESOLVED/DERIVED/AMBIGUOUS states for exactly this |
| Irregular/curved-wall buildings | Wall reconstruction must represent a curved segment as such (polyline approximation with an explicit `is_curved` flag) rather than silently straight-lining it | New — not currently handled by any audited module |
| Multi-storey buildings with repeated typical floors | Level entities should allow "typical floor ×N" as an explicit multiplier relationship, never silently duplicated per-instance geometry that could double-count | New — `CanonicalLevel` exists but this multiplier concept was not found in the audited portion of `pb_canonical_building.py` |
| Duplicated tags across sheets | Reconciliation must key on (tag, viewport/sheet) not tag alone — this is the exact bug already flagged for `pb_drawing_ocr_evidence_layer.EvidenceReconciler.reconcile`, which keys by tag string only (`by_tag_native: Dict[str, ...]`, last-write-wins) | Needs fixing as part of the reconciliation-layer generalization in §4.4 |
| Missing or conflicting schedules | Fail closed to `UNRESOLVED`/`CONFLICT_MANUAL_REVIEW`, never guess a count from geometry alone | Already the correct behavior in `pb_raster_schedule_extractor.deduplicate_schedule_rows` |
| Wrong printed scale | Must not silently produce scaled measurements; escalate to review | `pb_page_scale_calibration_authority.py` already implements exactly this (conflicting scale → `BLOCKED`) |
| Incomplete dimension chains | Partial constraint resolution, explicit `PARTIALLY_CONSTRAINED` status, never interpolated | `pb_dimension_graph_constraint_engine.ConstraintStatus` already has this state |
| Handwritten annotations | Treated as low-confidence OCR evidence only, never promoted to firm authority without independent corroboration | Existing OCR confidence-downgrade pattern generalizes directly |
| Revisions (demolition/existing/new work) | Requires an explicit revision/scope tag on entities (`existing`/`demolished`/`new`) so a demolition-plan wall doesn't get counted as new-build wall area | New — no revision-scope concept found in the audited schema; flag as an open gap for Part 14 |
| Mirrored units | Geometry reconstruction must be orientation-agnostic (area/length formulas are already mirror-invariant by construction; the risk is entity *identity* — two mirrored units' openings must not be deduplicated as "the same tag" merely because their type marks match) | Needs an explicit per-instance identity separate from type mark, matching the existing "physical instance ≠ type mark" principle already used in the opening-evidence B1-B4 stack |
| Drawing/BOQ scope mismatch | Already explicitly modeled and excluded from headline scoring — `tenders_ke_mbagha_maternity_dispensary` is registered today specifically as a "Real-World Scope Divergence Stress Test," carried in the dashboard but excluded from headline accuracy | Keep this category; it is a correct, already-implemented pattern, not a gap |

For every row above, the desired behavior under genuine uncertainty is **abstention with a
recorded reason code**, not a best-effort guess — this is the one property that must hold
uniformly across the whole redesign for a future 99% claim to mean anything.

---

## 12. PR-by-PR implementation roadmap

Early workstreams are explicitly **not** judged by development-score movement — several should
target exactly 0% score change, proving the plumbing works before any accuracy claim rides on it.

| # | Objective | Primary files/interfaces touched | Expected score movement | Depends on |
|---|---|---|---:|---|
| P1 | Define `DocumentEvidence`/`ViewportEvidence`/`EntityEvidence`/`QuantityEvidence` contracts, stable ID scheme, schema versioning | New `pb_evidence_contracts.py` (or similar); no existing extraction code changes | **0%** | none |
| P2 | Wrap `GenericPlanReaderExtractor` unchanged behind a `LegacyExtractorAdapter` implementing the new contracts as an export shape only | New adapter module; zero changes inside `pb_planreader_pdf_extractor.py` itself | **0%** | P1 |
| P3 | Shadow runner: run legacy extractor + (initially empty) new pipeline on the same PDF, freeze both outputs before any gold is loaded | New shadow-comparison script; extend `pb_benchmark_report_set.py`'s existing run-identity model rather than inventing a second one | **0%** | P2 |
| P4 | Reuse `pb_vector_geometry_v130.py`'s existing `snap_geometry`/`detect_wall_pairs` as the first real wall-candidate generator, feeding `EntityEvidence` only (shadow, not authoritative) | Bridge module wiring `pb_vector_geometry_v130` output into the P1 contracts | **0%** (shadow only) | P1 |
| P5 | Extend `pb_viewport_segmentation.py` and `pb_viewport_dimension_binding.py` (already built, currently unwired) to actually gate wall-candidate evidence by viewport ownership | Modify call sites, not the underlying modules | **0%** (shadow only) | P4 |
| P6 | Build room-polygon reconstruction by feeding `MultiSpaceFootprintBuilder` real polygons (from P4/P5's wall graph) instead of one synthetic rectangle, in shadow | Extend `pb_multi_space_footprint_geometry.py` callers only; the geometry engine itself likely needs no changes | **0%** (shadow only) | P5 |
| P7 | Extend `pb_canonical_building.py`/`pb_geometry_services.py` per §5's concrete schema additions; populate from P6's shadow graph | `pb_canonical_building.py`, `pb_geometry_services.py` | **0%** (shadow only) | P6 |
| P8 | Unify wall/room height resolution onto `pb_dimension_graph_constraint_engine.resolve_wall_height()` only; retire or explicitly demote `pb_height_evidence_v150.py`'s always-succeeds path to Tier-5-only | `pb_height_evidence_v150.py`, call sites in `pb_planreader_pdf_extractor.py` | Likely **0%**, possibly small negative (fewer silent guesses) — acceptable and expected | independent, can run parallel to P4-P7 |
| P9 | Fix the OCR-layer tag-normalization gap (call `pb_opening_tag_normalization.normalize_opening_tag` instead of the independent regex) and the tag-only (not tag+sheet) reconciliation key in `pb_drawing_ocr_evidence_layer.EvidenceReconciler` | `pb_drawing_ocr_evidence_layer.py` | Likely **0%** on current benchmarks (none currently exercise this path), closes a latent double-count/split-identity risk | independent |
| P10 | Real per-wall opening hosting: replace the single synthetic `"perimeter_walling"` `WallInstance` with per-wall binding from P7's graph | `pb_planreader_pdf_extractor.py:1518-1568`, `pb_opening_deduction_pipeline.py` (fix the order-dependent bbox tie-break flagged in §3 at the same time) | **Not a goal**; measure honestly, expect movement in both directions across the 5 registered benchmarks | P7 |
| P11 | Selective authority: allow schedule/explicit-count families (mature, already deterministic) to become authoritative from the new pipeline first, per-family feature flag, legacy remains authoritative for everything else | Feature-flag plumbing in the benchmark adapter | Migration-gate dependent, not predicted | P3, P9 |
| P12 | Migrate room/floor area families to new-pipeline authority once P6/P7's gate is met | Adapter flag change only | Migration-gate dependent | P7, P8 |
| P13 | Migrate wall/opening-deduction families once P10's gate is met | Adapter flag change | Migration-gate dependent | P10 |
| P14 | Semantic ontology binding for finishes (§4.5), replacing the current page-wide keyword-detector methods in `pb_planreader_pdf_extractor.py` one finish family at a time | `pb_planreader_pdf_extractor.py` (remove `_has_dpm_specification` etc. once the semantic layer covers them), new ontology module | Family-gate dependent | P7 |
| P15 | Legacy retirement: once every family has passed its gate on new-pipeline authority, make `GenericPlanReaderExtractor` read-only/deprecated, delete retired-family logic | `pb_planreader_pdf_extractor.py` reduction | None (already migrated) | all prior |

For each PR: state the objective, the exact files/interfaces, the tests required (unit + the
relevant metamorphic tests from §11), the success criterion, dependencies, expected benchmark
impact (explicitly "0%, and that's fine" for P1-P9), and regression risk. Every family-migration
PR (P11-P14) must be reversible via a single feature-flag change, not a code revert — this is the
concrete form of "prefer a lower truthful score over a higher contaminated score": if a family
regresses after going authoritative, flip its flag back to legacy and keep the new engine as
shadow while it's fixed, rather than reverting the whole PR.

---

## 13. Exact specification for the next Cursor workstream

The proposed default next step — "canonical wall/room/opening graph reconstruction" — is directly
supported by this audit, with two corrections to keep it from duplicating existing work:

1. **Do not build wall/room reconstruction from scratch.** `pb_vector_geometry_v130.py` already
   implements native vector extraction (`extract_native_page`), endpoint-snapping into a node/edge
   graph (`snap_geometry`), and parallel-line wall-pair detection (`detect_wall_pairs`) — it is
   simply wired into a different, unrelated app entry point (`pb_planreader_v126_app.py`), not the
   benchmark pipeline. Cursor's viewport-segmentation foundation should feed evidence into
   *extending* this existing geometry module (junction classification, room-face extraction from
   the wall graph's cycles, opening-to-wall hosting) rather than writing a parallel wall-detection
   algorithm.

2. **Target `pb_canonical_building.py`'s existing schema as the output, not a new graph.** Per
   §1.2 and §5, the schema (`CanonicalWall`, `CanonicalOpening`, `CanonicalSpace`, `Provenance`,
   fail-closed defaults) is already well-designed and already used by the 3D subsystem — it is
   simply not populated by any automated PDF evidence pipeline yet. Cursor's job is exactly that
   missing population step: real geometry (from item 1) plus real evidence (from its own
   viewport/vector substrate) flowing into the *existing* dataclasses, extended per §5's three
   concrete additions (authority/confidence-tier field, supporting/conflicting evidence id lists,
   opening→host-wall reference).

Concrete deliverables for this workstream:

- A `WallGraphReconstructor` consuming `pb_vector_geometry_v130`-style snapped segments plus
  `pb_viewport_segmentation`-scoped ownership, producing candidate `CanonicalWall` entities with
  centerline, thickness (corroborated via the existing `resolve_corroborated_wall_thickness_m`
  ≥2-source-agreement rule — do not weaken this), and junction type.
- A `RoomFaceExtractor` producing candidate `CanonicalSpace` polygons from the wall graph's closed
  cycles, reusing `MultiSpaceFootprintGeometry`'s area/shared-edge math rather than reimplementing
  it.
- An `OpeningHostResolver` producing `CanonicalOpening` entities hosted by a specific
  `CanonicalWall` id, using real spatial proximity to a wall centerline (not bbox overlap with
  first-match), and identity via `pb_opening_tag_normalization.normalize_opening_tag` uniformly
  (fixing the independent, less-guarded OCR-layer tag regex along the way, per P9 above).
- All three run **in shadow only** (P4-P7 in §12) against the same PDFs already registered as
  development benchmarks (KSTVET, Murera, Ghazi, Umma, Lamu) plus at minimum one genuinely
  multi-wing/multi-room drawing (Ghazi already qualifies) and one with a disconnected secondary
  building (Lamu's twin-toilet block, currently explicitly out of scope for scoring precisely
  because no multi-building graph exists — this workstream is what would let that gap finally
  close).
- Ambiguity (two equally-plausible wall interpretations, an opening equidistant from two walls)
  must produce an explicit `AMBIGUOUS`/`UNRESOLVED` graph state, never a best-guess pick — matching
  the existing `pb_contextual_wd_card_evidence.py` near-tie abstention pattern exactly.
- Zero changes to `pb_planreader_pdf_extractor.py`'s live wiring, `pb_benchmark_accuracy_engine.py`,
  or any benchmark gold file in this workstream — it is infrastructure, evaluated by shadow-mode
  comparison and synthetic/metamorphic tests (§11), not by development-benchmark score movement.

---

## 14. Risks and unresolved research questions

- **Population gap, not just a schema gap.** §1.2's caveat is the single biggest open risk to this
  whole plan: if the 3D subsystem's canonical model is in practice populated mostly by user-edited
  input rather than automated extraction, extending its schema is necessary but not sufficient —
  the automated population pipeline (§13) is a substantial new engineering effort, not a rewiring
  task. This should be explicitly re-verified (does anything construct `CanonicalWall` from real
  PDF geometry anywhere in the 3D subsystem today?) before committing to a timeline.
- **Two live pipelines means two places to keep correct during migration.** Until P15 (legacy
  retirement) is genuinely complete, the production 3D application and the benchmark/accuracy
  pipeline can silently diverge in what they consider "the building" for the same PDF. The shadow
  infrastructure (P3) exists specifically to make this divergence visible rather than surprising.
- **Revision/scope handling (existing vs. demolition vs. new work) has no home in the current
  schema** (§11) — this needs a design decision before any project containing renovation/partial
  scope can be safely migrated, and none of the audited modules currently address it at all.
- **Typical-floor multiplication** (§11) is architecturally unresolved — whether repeated storeys
  should be one `CanonicalLevel` with a multiplier or N distinct levels needs a decision before
  multi-storey buildings (the Lamu-adjacent "Luanda NG-CDF" candidate examined and rejected this
  session for a missing priced BOQ was exactly this shape: ground+first floor, "typical" layout)
  can be handled correctly.
- **Vector-line wall detection quality on real, noisy CAD exports is unverified.**
  `pb_vector_geometry_v130.snap_geometry`/`detect_wall_pairs` exist and are tested, but this audit
  did not verify their real-world precision/recall on the specific development benchmark PDFs —
  that measurement (in shadow mode, per P4) should be the first empirical checkpoint of the whole
  roadmap, before any further investment.
- **Cost/benefit of a learned vision model for the raster-only residual is genuinely unknown** —
  §8's recommendation to defer model-based room/wall detection is a judgment call based on the
  observation that the current benchmark population is entirely native-vector; if future
  benchmark acquisition (per this session's ongoing county-portal search) turns up a meaningfully
  raster/scanned-heavy population, that judgment should be revisited with real data rather than
  assumed.
- **The "second, disagreeing analysis" this document reconciles was not independently verified
  line-by-line** — its structural recommendations (KEEP/ADAPT/REPLACE framing, shadow-mode
  design, per-family migration gates, PR roadmap shape) were judged sound and incorporated because
  they converge with this document's independently-verified findings, but its specific file-level
  claims (e.g., about `pb_opening_evidence_v170.py`'s exact usage of `pb_canonical_building`) were
  checked against direct evidence in this pass and corrected where they overstated actual wiring
  (§1.2). Any further claim from that source about a file not directly re-verified here should be
  treated as a hypothesis, not a fact, until read directly.
