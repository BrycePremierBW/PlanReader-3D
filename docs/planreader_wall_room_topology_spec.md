# General Wall + Room Topology Reconstruction — Implementation-Ready Spec

**Owner:** geometry / canonical-graph workstream (this document).
**Explicitly not this document's job:** M5 commercial takeoff projection (other ChatGPT); door/window
schedule-count extraction (Cursor); dataset/adversarial evaluation (Gemini). This spec produces
wall and room **candidates** and an opening-**host interface**; it does not compute schedule
counts, does not run deductions, and does not become authoritative for anything without passing
through shadow mode first.
**Baseline at time of writing:** development 24/61 = 39.34% (`ACCURACY_GAP_LEDGER.md`); unseen
holdout `NOT_RUN`. This workstream is not expected or intended to move that number — see §19.
**Predecessor document:** `docs/planreader_v2_architecture_design.md` (the full 14-part
architecture audit). This document assumes that audit's findings and goes deep on exactly one
piece of it (§4.2, §7, §13 there). Do not re-derive the migration contracts
(`DocumentEvidence`/`ViewportEvidence`/`EntityEvidence`/`QuantityEvidence`) here — reuse them as
already specified.

**Correction to the brief's premise, verified directly before writing this spec:** significantly
more of this algorithm already exists in the repository than the previous audit surfaced. Reading
`pb_vector_geometry_v130.py` and `pb_accuracy_v13_engines_v145.py`/`pb_room_face_takeoff.py` in
full (not summarized this time) found a working half-edge planar-face traversal, a working
double-line wall-pair detector, and an already-thorough room-plausibility filter that *already*
rejects the building-outline-as-a-room and title-block-as-a-room failure modes the brief lists as
things this design must handle. The job below is therefore substantially **integration and
provenance work**, not algorithm invention from zero. Sections 1-3 name exactly what is reused.

---

## 1. Existing modules to reuse (verified by direct reading, not summary)

| Module / function | What it already does, verified | Reuse as |
|---|---|---|
| `pb_vector_geometry_v130.extract_native_page(pdf_page)` | Reads native `"l"` line and `"re"` rectangle drawing primitives plus word bboxes from PyMuPDF; returns `{segments[], rects[], words[], width, height}`. Segments carry `id, kind ("line"/"rect_edge"), x1,y1,x2,y2, width, stroke, fill, layer, dashes`. | The `DocumentEvidence`-layer native geometry source. Use unchanged. |
| `pb_vector_geometry_v130.snap_geometry(segments, tolerance_pt=1.25)` | Endpoint-snaps nearby segment endpoints into stable graph nodes (running-average merge within tolerance), returns `{nodes: [{id,x,y,samples,degree}], edges: [...], adjacency}`. Edges are segments augmented with `a,b` (node indices), `length_pt`, `angle_deg`. | The base node/edge graph. Extend (§7), do not replace. |
| `pb_vector_geometry_v130.detect_wall_pairs(segments, px_per_m)` | Finds parallel, overlapping long segments within a plausible wall-thickness gap range (`0.04–0.45 × px_per_m`, or `0.8–18.0 pt` when scale is unknown), requiring ≥45% projection overlap. This **is** a working double-line-wall detector. | The double-line wall-face pairing evidence source (§5). |
| `pb_accuracy_v13_engines_v145.split_segments_at_intersections(segments)` | Brute-force pairwise segment-intersection test, splits every segment at every true crossing before graph traversal. O(n²); flagged as a performance concern in §18. | The intersection-splitting step, run before `snap_geometry`/face traversal. |
| `pb_accuracy_v13_engines_v145.extract_planar_faces(segments, min_area)` | Genuine directed half-edge traversal over the split/snapped segment graph: builds an adjacency map, sorts neighbors by angle, walks clockwise-predecessor faces, keeps positively-signed (bounded) faces above `min_area`, de-duplicates cyclic rotations. **This is real, correct, general planar-face extraction — not a "largest two dimensions" heuristic.** Naturally handles disconnected components (a face never traverses across a graph component it isn't part of), so multiple disconnected buildings on one sheet already fall out of this algorithm for free. | The room/space candidate polygon generator (§8). Extend to also emit an interior-edge list). |
| `pb_accuracy_v13_engines_v145.attach_room_labels(faces, labels)` | Point-in-polygon matching of room-label text centroids to extracted faces, defaults to `f"Room {idx}"` when unlabeled. | The label-attachment step (§8.4), extend for label-conflict handling. |
| `pb_room_face_takeoff.filter_face(polygon, scale_info, page_w, page_h, all_polygons, label)` → `FilterResult` | **Already implements, correctly and fail-closed:** minimum-vertex rejection, hard/soft area thresholds (soft-min rejects small *unlabeled* polygons but keeps small *labeled* ones provisionally — furniture vs. a genuinely small labeled room), title-block-zone rejection, page-coverage rejection ("polygon covers >X% of the page → building outline, not a room" — this is the exact existing defense against the brief's "do not assume one rectangular outer envelope" concern), a **containment-based outline rejection** (a candidate face that contains many other candidates' centroids is rejected as an outline, not a room), elongation-ratio handling for corridors (long+unlabeled → reject, long+labeled → accept provisionally), and void/hole detection (a face containing another valid face's centroid is flagged `has_voids=True` with a confidence penalty, not rejected). | The room-plausibility gate (§8.2). Reuse essentially unchanged; extend only to also accept an externally-resolved room-type ontology tag as corroborating label evidence. |
| `pb_room_face_takeoff.RoomFace` (dataclass) | `room_ref, label, polygon_pdf_pts, polygon_m, floor_area_m2, area_page_pts2, perimeter_m, geometry_confidence, evidence, source_page, drawing_number, scale_source, calibration_confidence, has_voids, status` | The room-candidate schema base (§8.1) — extend, don't replace. |
| `pb_multi_space_footprint_geometry.compute_polygon_area/perimeter`, `compute_collinear_segment_overlap` | Shoelace area/perimeter; genuine shared-collinear-edge detection between two solid polygons (used today only for the "verandah shares a wall with the main room" case, but the algorithm itself is general). | The shared-boundary/adjacency computation (§8.5). |
| `pb_dimension_chain_evidence_extractor.resolve_corroborated_wall_thickness_m` | Requires ≥2 independent dimension-chain candidates to agree before returning a wall thickness; otherwise `None`. | Wall-thickness corroboration (§9), keep the ≥2-source rule exactly as-is. |
| `pb_dimension_graph_constraint_engine` (`DimensionObservation`, `DimensionChain`, `ConstraintStatus`, `resolve_wall_height`, `classify_chain_segments`) | Strict, fail-closed dimension/height resolution with an explicit `CONFLICT_MANUAL_REVIEW` state; never guesses. | The one wall-height/dimension resolver (§10) — see the companion architecture doc §4.3 for why `pb_height_evidence_v150.py`'s independent always-succeeds resolver must not be a second source of truth here. |
| `pb_page_scale_calibration_authority.py` (`resolve_page_scale_calibration`, `measurement_authority_for_page_scale`) | The existing scale authority: multi-tier status machine, title-block-only readings capped at PROVISIONAL, conflicting sources `BLOCKED`. | **The only scale resolver this workstream calls.** See §11 — do not call `pb_vector_geometry_v130.solve_scale()` or `pb_room_face_takeoff.page_scale_info`/`vector_analysis_scale_info` as authorities; they are candidate *evidence inputs* into the one authority, if kept at all. |
| `pb_viewport_segmentation.segment_page_viewports` | Real spatial viewport regions with RESOLVED/DERIVED/AMBIGUOUS states and view-type classification; already transitively live in the accuracy pipeline. | Viewport ownership scoping for every candidate below (§4). |
| `pb_drawing_evidence_binding.ReconciliationStatus` (`CONFIRMED`/`PROVISIONAL`/`CONFLICT_MANUAL_REVIEW`) | Existing cross-view reconciliation status enum. | Base for the extended fusion-status set in §9. |
| `pb_opening_deduction_pipeline.OpeningInstance`, `WallInstance`, `GenericOpeningDeductionPipeline` | Existing per-instance opening dataclass and (currently coarse, bbox-overlap) wall-binding logic; deduction math itself (`calculate_wall_deductions`) is genuinely per-instance-summed and fail-closed. | The opening-host **consumer** (§13) — this workstream produces the real wall geometry this pipeline currently lacks; it does not change the deduction math itself. |
| `pb_canonical_building.py` (`CanonicalWall`, `CanonicalOpening`, `CanonicalSpace`, `Provenance`, fail-closed defaults) | The target schema, per the companion architecture doc §1.2/§5. | The output destination (§4, §14) — populate via new code, do not invent a parallel schema. |
| `pb_geometry_services.py` | Deterministic geometry over supplied canonical objects (`wall_gross_area`, `potential_net_wall_area` with overlap detection, `space_floor_area`). | The deterministic quantity layer that consumes this workstream's output — out of scope to modify here, but the wall/room schema must satisfy its input contract. |

## 2. Modules that should be extended (not replaced)

- `pb_vector_geometry_v130.py` — add curve/bezier (`"c"` item) capture to `extract_native_page`
  (currently only `"l"` and `"re"` are read; curved walls are invisible today, §6.6), add junction
  classification to `snap_geometry`'s node output (currently only raw `degree` is computed, §7).
- `pb_accuracy_v13_engines_v145.extract_planar_faces` — extend to retain, per face edge, the
  originating segment `id`(s) so a room polygon's boundary can be traced back to specific wall
  candidates (needed for `bounds`/`bounded_by`, §8.3). Currently the function returns bare point
  lists with no provenance back to input segments.
- `pb_room_face_takeoff.RoomFace` — add `adjacent_room_refs`, `bounding_wall_candidate_ids`,
  `opening_ids` fields (§8.1).
- `pb_opening_deduction_pipeline.bind_openings_to_walls` — replace the bbox-overlap-with-first-match
  branch (order-dependent, flagged in the companion audit) with real centerline-proximity binding
  fed by this workstream's wall graph (§13); keep its fail-closed `PROVISIONAL_UNBOUND` outcome
  for genuinely unresolved cases.
- `pb_canonical_building.CanonicalElement` — add `authority: MeasurementAuthorityType` and
  `supporting_evidence_ids`/`conflicting_evidence_ids` fields, per the companion doc §5.
- `pb_multi_space_footprint_geometry.py` — its `MultiSpaceFootprintBuilder` convenience API
  (`add_main_room`, `add_verandah` with hard-coded `adjacency="front"`) should gain an
  `add_polygon_space` bulk-ingestion path that accepts arbitrary real polygons from §8's face
  extraction directly, so the *existing, already-correct* area/shared-edge engine underneath it
  gets exercised generally instead of only through the two rectangle-shaped convenience methods.

## 3. Modules/functions that should eventually be deprecated (not in this PR — see roadmap)

- `GenericPlanReaderExtractor._detect_outer_envelope()` — superseded once wall/room topology is
  authoritative for a project family; retire per the companion doc's deprecation table, only after
  its gate is met (§19).
- `pb_orthogonal_envelope_evidence.py` — demoted from "the building" to **one evidence hypothesis
  among several** feeding the new fusion layer (§9), consistent with the brief's explicit
  instruction. Not deleted — its independent floor-area corroboration is still a legitimate,
  useful signal, just no longer privileged as the sole path to a building envelope.
- `pb_vector_geometry_v130.solve_scale()` — once `pb_page_scale_calibration_authority.py` is the
  sole authority (§11), this becomes redundant. Its `dimension_scale_evidence`/
  `printed_scale_evidence` extraction functions remain useful as *evidence providers* into the one
  authority; the consensus-solving logic itself (`solve_scale`) is the part to retire.
- `pb_room_face_takeoff.page_scale_info` / `vector_analysis_scale_info` — same reasoning; a third
  independent scale accessor is exactly the duplicated-evidence risk the companion audit flagged
  generically and this reading confirms concretely exists a third time.

---

## 4. Exact data flow

```
DocumentEvidence (per page: native segments, rects, words — pb_vector_geometry_v130.extract_native_page)
        │
        ▼
ViewportEvidence (pb_viewport_segmentation.segment_page_viewports — RESOLVED/DERIVED/AMBIGUOUS)
        │  (every step below operates within ONE viewport's segment/word subset at a time;
        │   a segment or word not fully contained in exactly one eligible viewport is excluded
        │   from topology reconstruction for this pass and recorded as `unassigned`, matching
        │   pb_viewport_dimension_binding.py's existing full-containment rule — reuse it)
        ▼
STAGE A — segment preparation
  A1. split_segments_at_intersections(segments)         [pb_accuracy_v13_engines_v145]
  A2. snap_geometry(split_segments, tolerance_pt)        [pb_vector_geometry_v130, extended §7]
        → WallGraph{nodes[], edges[], adjacency}
        │
        ▼
STAGE B — wall candidate generation (§5, §6)
  B1. detect_wall_pairs(segments, px_per_m)              [pb_vector_geometry_v130]  → double-line candidates
  B2. single-line wall candidate promotion (NEW)          → single-line candidates
  B3. junction classification over WallGraph nodes (NEW)  → T/L/X/curve-endpoint tags
        → List[WallCandidate]  (§5 schema)
        │
        ▼
STAGE C — room candidate generation (§8)
  C1. extract_planar_faces(split_segments)               [pb_accuracy_v13_engines_v145, extended §2]
  C2. attach_room_labels(faces, room_label_words)         [pb_accuracy_v13_engines_v145]
  C3. filter_face(...) per candidate                      [pb_room_face_takeoff, unchanged]
  C4. shared-boundary / adjacency via compute_collinear_segment_overlap [pb_multi_space_footprint_geometry]
        → List[RoomCandidate]  (§8.1 schema, extended RoomFace)
        │
        ▼
STAGE D — evidence fusion (§9)
  cross-reference wall candidates from B against room-candidate boundaries from C;
  cross-reference dimension evidence (pb_dimension_chain_evidence_extractor) against
  wall length/room extent (§10); cross-reference orthogonal-envelope/explicit-floor-area
  evidence as ONE hypothesis, not authoritative (§3)
        → EntityEvidence bundles with fusion status: proposed/supported/corroborated/
          ambiguous/conflicting/unresolved (§9)
        │
        ▼
STAGE E — canonical promotion (§14)
  only CORROBORATED or SUPPORTED entities are promoted to CanonicalWall/CanonicalSpace/
  CanonicalOpening (pb_canonical_building.py, extended §2); PROPOSED/AMBIGUOUS/CONFLICTING
  remain visible as EntityEvidence for debugging/observability but are never promoted
        │
        ▼
CanonicalBuildingGraph (shadow mode only — §19)
        │
        ▼
pb_geometry_services.py (deterministic geometry/quantity computation — out of scope here)
```

---

## 5. Wall candidate schema

```python
@dataclass(frozen=True)
class WallCandidate:
    candidate_id: str                       # stable, content-derived (see §18 cache keys)
    viewport_id: str
    representation: Literal["double_line", "single_line", "curved"]

    # Geometry — always populated in PDF-point space; metre space populated only once
    # scale authority (§11) resolves for this viewport.
    centerline_pts: List[Tuple[float, float]]   # polyline; 2 points for a straight run,
                                                 # >2 for a curved wall's sampled centerline
    face_a_segment_ids: List[str]               # originating segment id(s), one side
    face_b_segment_ids: Optional[List[str]]     # originating segment id(s), other side;
                                                 # None for a single_line candidate
    is_curved: bool
    curve_control_pts: Optional[List[Tuple[float, float]]]  # raw bezier control points, curved only

    thickness_m: Optional[float]            # None until corroborated (§9); NEVER defaulted
    thickness_authority: MeasurementAuthorityType  # see §10 — Tier 5 (assumption) forbidden here
    length_m: Optional[float]               # None until scale resolves (§11)

    end_node_ids: Tuple[str, str]            # references into the WallGraph node set (§7)
    junction_types: Tuple[JunctionType, JunctionType]  # classification at each endpoint (§7)

    interior_exterior: Literal["interior", "exterior", "unresolved"]  # §6.9
    level_id: Optional[str]                  # None until level ownership resolves (multi-storey, §8.6)

    embedded_columns: List[str]              # candidate_ids of ColumnCandidate objects found
                                              # to sit within this wall's thickness envelope (§6.10)

    fusion_status: FusionStatus               # §9
    confidence: float                         # 0.0-1.0, derived per §9's rules, never hand-tuned per project
    supporting_evidence_ids: List[str]
    conflicting_evidence_ids: List[str]
    reason_codes: List[str]                   # e.g. "double_line_pair", "thickness_unresolved",
                                               # "gap_below_min_wall_width", "collinear_merge_applied"
```

**Non-orthogonal/angled walls:** `centerline_pts` are plain `(x, y)` tuples with no orthogonality
assumption anywhere in this schema or in `detect_wall_pairs`'s parallel-angle test (it compares
two segments' *own* angles to each other, via `_angle_delta`, not to any global axis) — angled
and non-orthogonal walls are handled by construction, not as a special case.

**Short returns:** a wall segment shorter than the minimum length threshold used by
`detect_wall_pairs` (`_segment_length(s) >= 16.0` pt) is excluded from double-line pairing but
must still appear as a `single_line` candidate at low confidence (`reason_codes` includes
`"short_return"`) rather than being silently dropped — a short return at a corner is real wall,
not noise, and dropping it would break junction closure at that corner.

## 6. Wall reconstruction — the twelve required cases

| Case | Handling |
|---|---|
| 6.1 Single-line walls | Promoted directly to a `single_line` `WallCandidate` when no parallel partner is found by `detect_wall_pairs`; `thickness_m=None` until corroborated by dimension evidence (§9) — never assumed from a "typical" value. |
| 6.2 Double-line walls | `detect_wall_pairs` output, `representation="double_line"`, `thickness_m` derived from `gap_pt / px_per_m` once §11's scale authority resolves, cross-checked (not overridden) against any figured wall-thickness dimension via §9's ≥2-source corroboration rule. |
| 6.3 Varying wall thickness | Represented as **two or more adjacent `WallCandidate`s sharing an end node**, not one candidate with a thickness range — a wall that steps in thickness is topologically two wall runs meeting at a node, which the junction/node model already supports without a new concept. |
| 6.4 Fragmented vectors | `snap_geometry`'s tolerance-based endpoint merge (default 1.25pt) already reunites near-miss endpoints into one node before any wall logic runs — this is the direct, already-implemented fix for fragmentation, extended in §7 with a second, coarser "collinear merge" pass for fragments that don't share an endpoint at all (a wall drawn as three separate collinear segments with small gaps). |
| 6.5 Collinear fragments | New pass in `snap_geometry` extension (§7): after node-snapping, merge edge chains where consecutive edges share a node, have `angle_delta ≈ 0`, and the shared node has `degree == 2` (i.e., nothing else connects there) into one logical wall run before junction classification — a degree-2 node in the middle of a straight run is a drafting artifact, not a real junction. |
| 6.6 Curved walls | **New capability required** — `extract_native_page` currently reads only `"l"` and `"re"` drawing items; PyMuPDF's `"c"` (bezier curve) items are not captured at all today. Add curve capture, represent as `is_curved=True` with `curve_control_pts` retained verbatim and a sampled polyline `centerline_pts` (fixed sampling density, e.g. every 5pt of arc length) for downstream face-traversal compatibility — face extraction operates on the sampled polyline, not the raw bezier, so §1's `extract_planar_faces` needs no change to consume curved walls once this sampling step exists. |
| 6.7 Angled/non-orthogonal walls | No special case — see §5's note; `_angle_delta` and the projection-overlap math in `detect_wall_pairs` are already angle-agnostic. |
| 6.8 Short returns | See §5. |
| 6.9 Openings/gaps (interior/exterior classification) | A gap in an otherwise-collinear wall run (two `WallCandidate`s that would collinear-merge per 6.5 except for a real physical gap wider than the snap tolerance) is a candidate opening location, handed to §13's opening-host interface — **not** resolved here as door-vs-window (that is schedule evidence, Cursor's territory); this workstream only proposes "a wall-line gap exists at position X on wall Y," it does not classify what fills it. Interior vs. exterior classification for a wall itself (not the gap) comes from face-traversal adjacency (§8): a wall bounding exactly one extracted room face on the building's outer boundary chain is exterior; a wall bounding two room faces is interior; a wall bounding zero resolved faces is `"unresolved"`, never guessed. |
| 6.10 Columns embedded in walls | A `ColumnCandidate` (short, roughly-square or circular closed polygon, from `rects` or a small closed face) whose bounding box falls entirely within a `WallCandidate`'s thickness envelope is referenced by that wall's `embedded_columns` list, not merged into the wall's own geometry — keeps the column identifiable for its own structural quantity while still letting the wall's centerline pass through it correctly. |
| 6.11 Overlapping lines / hatching / dimension lines crossing walls / furniture touching walls | All handled by the **minimum-length and aspect filters already implicit in `detect_wall_pairs`** (short segments, and the `0.045×length` area/overlap ratio floor) plus a new pre-filter (§7) that excludes segments whose `stroke`/`dashes`/`layer` metadata (already captured by `extract_native_page` but not yet used downstream) matches a known hatch-pattern or dimension-line convention before wall-pairing runs — reuse the captured metadata that already exists in the segment dict rather than adding new extraction. Furniture touching a wall produces a short, usually non-parallel segment that fails `detect_wall_pairs`'s parallel-angle gate and is correctly never promoted to a wall candidate; it may still appear as noise in `extract_planar_faces`'s raw output and must be caught by `filter_face`'s existing small-unlabeled-polygon rejection (§1) — no new filtering logic needed there. |
| 6.12 Scan noise (raster/hybrid drawings) | Out of scope for the vector path entirely — see §12 for when/how a raster detector is invoked, and note that raster-derived wall candidates use the *same* `WallCandidate` schema with `reason_codes` indicating `"raster_source"`, so downstream fusion treats them uniformly, just with generally lower baseline confidence per §9. |

## 7. Junction schema (new — does not exist today)

`snap_geometry`'s nodes currently carry only `{id, x, y, samples, degree}`. Extend with:

```python
@dataclass(frozen=True)
class JunctionCandidate:
    node_id: str                             # == the underlying WallGraph node id
    position_pt: Tuple[float, float]
    junction_type: JunctionType              # ENDPOINT | L_CORNER | T_JUNCTION | X_CROSSING | UNRESOLVED
    incident_wall_candidate_ids: List[str]   # WallCandidates meeting here, in angular order
    incident_angles_deg: List[float]         # matching angular order, for junction-type derivation
    confidence: float
    reason_codes: List[str]
```

**Classification rule (deterministic, no ML needed for the native-vector case):**
`junction_type` is derived purely from `degree` (post collinear-merge, §6.5) and the incident
angle pattern:

- `degree == 1` → `ENDPOINT` (a genuine wall end, e.g. a short return meeting nothing — must be
  distinguished from a mid-run fragmentation artifact by the collinear-merge pass in §6.5 having
  already run first).
- `degree == 2` with `angle_delta(incident_1, incident_2) ≈ 180°` (within a tolerance, e.g. 5°) →
  not a junction at all — already merged away by §6.5; if it survives to this point (angle delta
  outside tolerance), it is an `L_CORNER`.
- `degree == 3` → `T_JUNCTION` when two of the three incident walls are collinear (`angle_delta ≈
  0/180°` between that pair) and the third meets them at a non-trivial angle; `UNRESOLVED` if no
  such collinear pair exists (an irregular three-way meeting that doesn't match the standard
  T-junction shape — fail closed rather than force-classify).
- `degree == 4` with two collinear pairs at roughly perpendicular or otherwise consistent angles →
  `X_CROSSING`.
- `degree >= 5`, or a `degree == 3`/`4` node that doesn't match the collinear-pair patterns above →
  `UNRESOLVED` — genuinely irregular junctions (five walls meeting at one point, say) are rare
  enough in real drafting that force-fitting a type is worse than admitting uncertainty; the node
  and its candidates still exist and still participate in face traversal, just without a clean
  T/L/X label.

This rule set is intentionally simple and fully deterministic — no model inference needed for the
native-vector case, consistent with §12's native-first principle.

## 8. Room/space candidate schema

### 8.1 Schema (extends `pb_room_face_takeoff.RoomFace`, does not replace it)

```python
@dataclass(frozen=True)
class RoomCandidate:
    # --- existing RoomFace fields, unchanged semantics ---
    room_ref: str
    label: str
    polygon_pdf_pts: List[Tuple[float, float]]
    polygon_m: Optional[List[Tuple[float, float]]]
    floor_area_m2: Optional[float]
    area_page_pts2: float
    perimeter_m: Optional[float]
    geometry_confidence: float
    evidence: List[str]
    source_page: int
    drawing_number: str
    scale_source: str
    calibration_confidence: float
    has_voids: bool
    status: str

    # --- new fields required for topology ---
    bounding_wall_candidate_ids: List[str]      # which WallCandidates form this polygon's boundary,
                                                 # in perimeter order — the provenance link back
                                                 # through extract_planar_faces (§2 extension)
    adjacent_room_refs: List[str]                # rooms sharing a boundary segment (§8.5)
    opening_refs: List[str]                      # candidate opening locations on this room's
                                                  # boundary (from §6.9), before schedule
                                                  # classification
    exterior_boundary: bool                       # True if this polygon is on the outer chain of
                                                  # its connected component (i.e. has at least one
                                                  # bounding wall classified "exterior", §6.9)
    explicit_area_label_m2: Optional[float]       # a printed "XX m²" area annotation found inside
                                                  # this polygon, if any (§8.6)
    area_conflict: Optional[Dict[str, float]]     # {"polygon_area_m2": ..., "explicit_area_m2": ...}
                                                   # populated only when both exist and disagree
                                                   # beyond tolerance — never silently resolved
    level_id: Optional[str]
    building_component_id: str                    # which disconnected graph component this
                                                   # room belongs to (§8.7 — multi-building support)
```

### 8.2 Polygon validity

Delegated entirely to `pb_room_face_takeoff.filter_face` (§1) — reused unchanged. Its existing
checks (minimum vertices, hard/soft area bounds, title-block-zone rejection, page-coverage
rejection, containment-based outline rejection, elongation handling) already satisfy "do not
assume one rectangular outer envelope": the outline-rejection rule is precisely the mechanism that
prevents a whole-building bounding polygon from ever being accepted as a room, regardless of how
many rooms it is later found to actually contain.

### 8.3 Holes

`filter_face`'s existing `has_voids` detection (a candidate containing another valid face's
centroid) is reused unchanged for the "this room has an internal void" case (e.g. a room with a
structural core cut out of it). This is distinct from — and evaluated independently of —
`area_conflict` (8.6): a hole affects the polygon-derived area calculation itself; an area
conflict is a disagreement between the (possibly hole-corrected) polygon area and a separately
printed area label.

### 8.4 Room labels, unlabeled spaces, conflicting labels

`attach_room_labels`'s point-in-polygon matching (§1) is reused for the common case. Two
extensions:

- **Unlabeled spaces** are retained as `RoomCandidate`s with `label = f"Room {idx}"` (existing
  default) and a lower `geometry_confidence`, per `filter_face`'s existing soft-area-penalty
  behavior for unlabeled small/elongated polygons — not dropped.
- **Conflicting labels** (two distinct room-label text candidates whose centroids both fall inside
  the same polygon) must resolve to `label = None`, `fusion_status = AMBIGUOUS` (§9), with both
  candidate labels recorded in `evidence` — never picked by document order or centroid distance
  alone, mirroring the existing near-tie abstention pattern already used elsewhere in this
  codebase (`pb_contextual_wd_card_evidence.py`'s score-margin abstention).

### 8.5 Shared boundaries and adjacency

`pb_multi_space_footprint_geometry.compute_collinear_segment_overlap` (§1) already computes real
collinear shared-edge length between two polygons — generalize its current pairwise-loop usage
(today run only for a hand-selected main-room/verandah pair) to run over *every* pair of extracted
`RoomCandidate` polygons within the same connected building component (§8.7), populating
`adjacent_room_refs` on both sides whenever shared edge length exceeds a small tolerance (e.g.
0.3m, to exclude corner-touching-only false adjacency).

### 8.6 Explicit area labels vs. polygon-area conflicts

Reuse `pb_explicit_floor_area_evidence.py`'s existing extraction pattern (a labelled "FLOOR AREA …
m²" annotation), but scope it **per room polygon** (does the annotation's text position fall
inside this specific polygon?) rather than per-page as it is used today. When both a polygon-
derived area and a spatially-scoped explicit label exist for the same `RoomCandidate`:
- If they agree within a fixed relative tolerance (reuse `pb_orthogonal_envelope_evidence.py`'s
  existing 1.5% corroboration tolerance as the starting value — do not invent a new number without
  reason), the polygon area is used as the authoritative geometry (Tier 1, real reconstructed
  topology) and the explicit label serves as corroborating evidence, raising confidence.
- If they disagree beyond tolerance, populate `area_conflict` and set `fusion_status =
  CONFLICTING` (§9) — **never** silently prefer one over the other; this is the direct
  implementation of the brief's explicit "polygon-area vs. explicit-area conflicts" requirement.

### 8.7 Disconnected buildings, multiple plans on one sheet, courtyards, multi-storey

- **Disconnected buildings / multiple wings:** `extract_planar_faces`'s half-edge traversal
  naturally never crosses between disconnected graph components (§1) — assign a
  `building_component_id` per connected component of the post-merge `WallGraph` (a simple
  union-find over `snap_geometry`'s adjacency, computed once per viewport) and stamp every
  `RoomCandidate`/`WallCandidate` in that component with it. This is the mechanism that finally
  allows a genuinely separate structure (e.g. Lamu's twin-toilet block, currently out of scope for
  scoring specifically because no multi-building graph exists) to be represented — see the
  companion architecture doc §13.
- **Multiple plans on one sheet:** handled upstream by viewport segmentation (§4) — each viewport
  is processed independently through the whole Stage A-D pipeline; a wall/room candidate is never
  built from segments spanning two viewports (enforced by the full-containment rule already used
  by `pb_viewport_dimension_binding.py`).
- **Courtyards:** an interior void bounded entirely by wall candidates but never itself enclosed
  as a labeled room is exactly `extract_planar_faces`'s "no bounded face found in that region"
  case combined with an *outer* room polygon's `has_voids=True` — no new mechanism needed, only
  correct interpretation: a courtyard is the geometric hole in a surrounding room/wing's polygon,
  not a room candidate of its own unless it independently satisfies `filter_face`.
- **Multi-storey / repeated floors / mirrored units:** `level_id` on both schemas is populated
  from whichever sheet/viewport classification indicates storey (reuse
  `pb_sheet_classification_v172.extract_storey_level` as the text-based signal feeding this, per
  the companion doc's file inventory). A "typical floor ×N" repeated-level relationship and
  mirrored-unit identity-vs-duplication handling are **explicitly flagged as unresolved research
  questions** in the companion architecture doc §14 and are out of scope for this PR sequence —
  do not invent ad hoc handling here; each repeated/mirrored instance is reconstructed
  independently as its own `building_component_id` per occurrence until that broader design
  question is resolved.

---

## 9. Evidence-fusion rules

Extend `pb_drawing_evidence_binding.ReconciliationStatus` (currently `CONFIRMED`/`PROVISIONAL`/
`CONFLICT_MANUAL_REVIEW`) to the full six-state set the brief specifies, reusing rather than
renaming the two states that already exist:

```python
class FusionStatus(str, Enum):
    PROPOSED = "proposed"           # NEW — single low-confidence source, not yet evaluated further
    SUPPORTED = "supported"         # NEW — one strong, uncontested source (maps to existing PROVISIONAL-but-clean cases)
    CORROBORATED = "corroborated"   # == existing CONFIRMED — >=2 independent, agreeing sources
    AMBIGUOUS = "ambiguous"         # NEW — >=2 candidates score within a small margin of each other
    CONFLICTING = "conflicting"     # == existing CONFLICT_MANUAL_REVIEW — disagreeing values that should agree
    UNRESOLVED = "unresolved"       # NEW — no usable evidence at all; explicit abstention, not a zero/default
```

**Promotion rule (§14):** only `CORROBORATED` or `SUPPORTED` entities are promoted to the
canonical graph. `PROPOSED`/`AMBIGUOUS`/`CONFLICTING`/`UNRESOLVED` remain as `EntityEvidence`
records only — visible for debugging (§17-style observability), never fed into
`pb_geometry_services.py`'s quantity formulas.

**Ambiguity margin rule (reused, not invented):** apply the exact numeric pattern already proven
in `pb_contextual_wd_card_evidence.py:251-253` — when two candidate resolutions for the same
entity slot score within `max(absolute_floor, relative_fraction × top_score)` of each other,
classify `AMBIGUOUS` and abstain, rather than picking the higher-scoring one. Use this same
two-parameter shape (an absolute floor plus a relative fraction) for every ambiguity check in this
workstream — wall-vs-wall gap disambiguation, room-label conflicts (§8.4), junction-type ties —
so the whole system has one consistent, already-validated abstention behavior rather than a
different bespoke threshold per module.

**Conflict rule:** two sources are "conflicting" (not merely "different") only when they purport
to measure the *same* physical thing and disagree beyond the applicable tolerance (§8.6's 1.5%
for area; §10's dimension tolerance for lengths). Two sources measuring genuinely different things
(a wall's double-line gap vs. an unrelated dimension elsewhere on the sheet) are never compared and
never produce a false conflict.

**Corroboration rule (reused, not weakened):** keep `resolve_corroborated_wall_thickness_m`'s and
`pb_orthogonal_envelope_evidence.py`'s existing ≥2-independent-source requirement as the
`CORROBORATED` bar everywhere a "requires ≥2 agreeing sources" pattern already exists in this
codebase — do not lower it to ship faster.

---

## 10. Dimension-binding rules

Figured dimension outranks scaled/derived geometry, exactly as `pb_geometry_takeoff_model.
reconcile_figured_and_scaled()` already implements — reuse that function's precedence rule and
`max_delta_ratio` conflict-escalation behavior directly rather than re-deriving it.

Binding a dimension string to a specific geometric target uses the *spatial* mechanism already
built in `pb_figured_dimension_evidence.py`/`pb_viewport_dimension_binding.py` (word/vector bbox
proximity and containment within a single owning viewport) — **generalize its existing target
types** (currently wall-thickness-oriented, per the companion audit) to also bind to:

- **wall length:** a dimension chain segment whose endpoints project onto a `WallCandidate`'s
  centerline within a small perpendicular tolerance is evidence for that wall's `length_m`.
- **room extent:** a dimension chain fully contained within (or running along the boundary of) a
  `RoomCandidate`'s polygon is evidence for that room's extent, cross-checked against the
  polygon-derived dimension, using the same agree/conflict logic as §8.6.
- **opening width:** a dimension positioned across a wall-line gap (§6.9) is evidence for that
  gap's width — handed to Cursor's schedule-count/opening-instance work as corroborating evidence,
  not resolved into a final opening width here.
- **dimension chains generally:** unchanged — reuse `pb_dimension_chain_evidence_extractor.py`
  as-is; this workstream only adds new *targets* those chains can bind to, not a new chain
  extractor.
- **overall building extents:** an "overall" dimension (the outermost run in a chain) becomes
  `CORROBORATING` (not authoritative-by-itself) evidence for the sum of the wall-graph's own
  outer-boundary wall lengths on that axis — this is the concrete mechanism by which
  `pb_orthogonal_envelope_evidence.py`'s existing figured-dimension-plus-floor-area corroboration
  becomes one input to the real topology instead of the sole source of "the building."

**The hard rule the brief asks for explicitly:** an unrelated large number never becomes geometry.
Concretely, a parsed dimension only becomes evidence for a wall/room/opening target when it passes
one of the spatial binding tests above (proximity/containment to an *already-existing* wall or
room *candidate*, itself derived from real linework) — there is no path in this design, unlike
today's `_detect_outer_envelope`, where "the two largest numbers found anywhere on the page" can
become the building on their own.

---

## 11. Scale interaction

**One authority, reused, not reinvented:** `pb_page_scale_calibration_authority.py`'s
`resolve_page_scale_calibration`/`measurement_authority_for_page_scale`. All of §5-§10's metre-
space fields (`thickness_m`, `length_m`, `floor_area_m2`, etc.) remain `None` until this authority
resolves for the relevant viewport/page, and are stamped with whatever `AuthorityStatus`
(FIRM/PROVISIONAL/BLOCKED) that resolution produced — a wall's `thickness_m` computed under a
PROVISIONAL (title-block-only) scale reading is itself never promoted to `CORROBORATED` fusion
status regardless of how well its own geometric evidence agrees, because the scale itself hasn't
cleared FIRM.

`pb_vector_geometry_v130.dimension_scale_evidence`/`printed_scale_evidence` (§1/§3) may still be
useful as additional **evidence inputs** feeding the one authority (more independent scale
readings improve its own internal agreement check) — but `solve_scale()`'s own consensus
computation is retired in favor of the existing authority module making that decision, per §3.

---

## 12. Native/raster reconciliation

**Default: native-vector only, always.** For every registered development benchmark (KSTVET,
Murera, Ghazi, Umma, Lamu — all native-vector PDFs with real extractable text/geometry), Stages
A-D above run entirely on native evidence; no raster rendering, OCR, or CV inference happens at
all. This is a direct extension of the existing, already-correct native-first principle in
`pb_drawing_ocr_evidence_layer.py`.

**When raster/CV is invoked:** only for a viewport (not a whole document) where Stage A produces
insufficient segments to reconstruct any wall/room topology at all (a genuinely scanned/rasterized
sheet, or a viewport with zero native vector drawings) — this mirrors the "targeted raster/CV only
where unresolved" cascade already specified in the companion architecture doc §8/§12, restated here
scoped to this workstream: raster wall/room detection is a Stage-A-failure fallback, not a
parallel always-on second opinion.

**Reconciliation when both exist and disagree (native says wall, raster detector says wall in a
different position, or one says wall and the other doesn't):** treat the raster detection as
*one more piece of evidence* competing for the same `WallCandidate` slot under the exact fusion
rules in §9 — native-vector evidence enters fusion with a materially higher prior confidence
(reflecting its deterministic, non-inferred nature) than any model-based detection, consistent
with §8 of the companion architecture doc's "model output becomes `EntityEvidence` like any other
source, never a privileged override." A native/raster disagreement that both sides hold with
reasonable confidence produces `CONFLICTING`, not a silent pick of native-over-raster by fiat —
the difference between "native wins by default confidence weighting" and "native wins because a
rule says so" matters: the former can still be overturned by sufficiently strong raster+dimension
corroboration in a genuinely native-evidence-poor region, the latter cannot.

**No CV model is specified or required for this PR sequence** (§19) — this section defines the
reconciliation *contract* so that Gemini's/a future workstream's raster detector has a well-defined
slot to plug into, without this workstream needing to build or evaluate a CV model itself.

---

## 13. Opening-host interface

**Explicitly not built here: schedule counts, tag-to-quantity resolution, or deductions** — all
Cursor's or the existing deduction pipeline's territory, unchanged by this workstream.

**What this workstream must provide:** every wall-line gap identified in §6.9 becomes an
`OpeningHostCandidate`:

```python
@dataclass(frozen=True)
class OpeningHostCandidate:
    host_candidate_id: str
    wall_candidate_id: str                  # the WallCandidate this gap interrupts
    position_along_wall_m: Optional[float]   # distance from the wall's start node to the gap's
                                              # center, once scale resolves — None until then
    gap_width_m: Optional[float]
    host_status: Literal["hosted", "ambiguous_host", "unhosted"]
    candidate_wall_ids_considered: List[str]  # for "ambiguous_host": the wall candidates that
                                               # were plausible hosts, in case a downstream
                                               # process (Cursor's) needs to re-resolve later
                                               # with additional (e.g. schedule) evidence
    confidence: float
    reason_codes: List[str]
```

**Host resolution rule:** a gap is `"hosted"` by exactly one `WallCandidate` when the gap sits
within that wall's own centerline run (not at a junction) and no other wall candidate's centerline
passes within a small perpendicular tolerance of the same position. When two wall candidates are
both plausible hosts (e.g., a gap very close to a T-junction, genuinely ambiguous which of two
walls it interrupts), status is `"ambiguous_host"` — **both** candidate wall ids are retained in
`candidate_wall_ids_considered` rather than picking the nearer one, so that a later process with
better evidence (a schedule row naming a specific room/wall reference, which this workstream does
not have) can resolve it without needing to re-run geometry from scratch. A gap with no plausible
host at all (shouldn't occur if §6.9 only proposes gaps on already-identified wall runs, but
handled defensively) is `"unhosted"`.

**This is the direct, complete fix for the "everything bound to one synthetic `perimeter_walling`
wall" defect** identified in the companion architecture audit (§1.3 finding #2 there) — once this
interface exists and is populated, `pb_opening_deduction_pipeline.bind_openings_to_walls` (§2)
can be updated to consume real per-wall hosts instead of its current single-wall/bbox-overlap
fallback, in a **separate, later PR** (P13 in the companion roadmap) gated on this workstream's own
acceptance criteria (§19) being met first — this PR does not touch the deduction pipeline's actual
math.

---

## 14. Confidence / abstention rules

- **No entity is promoted to the canonical graph below `SUPPORTED`** (§9) — `PROPOSED`,
  `AMBIGUOUS`, `CONFLICTING`, and `UNRESOLVED` entities exist only as `EntityEvidence`, visible for
  debugging, never consumed by `pb_geometry_services.py`.
- **A default/assumed value (thickness, height) never sets `authority` above Tier 5** (companion
  doc §4.3/§6 here) and Tier 5 evidence alone can never produce `CORROBORATED` fusion status —
  matching the existing rule that a lone default never becomes a "firm" measurement.
- **Ambiguity is reported with both/all candidates, never silently narrowed to one** — see §9's
  margin rule and §13's `candidate_wall_ids_considered` — this is the mechanism that lets a later,
  better-informed process (with schedule evidence, room labels, or human review) resolve what this
  workstream correctly declines to guess.
- **A confidence score is always accompanied by its `reason_codes`** — a bare float with no
  accompanying explanation is not acceptable output from this workstream, matching the
  observability requirement in the companion architecture doc §11.

---

## 15. Synthetic test matrix (implementation-ready)

Each row: construct the described geometry programmatically (PyMuPDF `page.draw_line`/
`draw_rect`/`draw_bezier` or direct `insert_text` for labels/dimensions — following the existing
pattern already used by this repo's own synthetic PDF test helpers, e.g.
`tests/benchmarks/test_mutation_card_style_schedule.py`'s `_card_pdf`/`_reopen` helpers), run
Stages A-D, assert the listed outcome.

| # | Construction | Expected outcome |
|---|---|---|
| T1 | One closed rectangle, 4 single-line walls | 1 `RoomCandidate`, 4 `WallCandidate`s, 4 `L_CORNER` junctions, `exterior_boundary=True`, area within 0.5% of the constructed value |
| T2 | L-shaped closed polygon (6 walls) | 1 `RoomCandidate` matching the L-shape exactly (not decomposed into two rectangles), 6 `WallCandidate`s, 5 `L_CORNER` + junction pattern matching the reflex corner |
| T3 | Two rectangles sharing one full wall (T-junction at both ends of the shared wall) | 2 `RoomCandidate`s, adjacent to each other (§8.5), the shared wall's two end nodes both classified `T_JUNCTION`, shared wall appears once (not duplicated) in the wall-candidate list |
| T4 | Four rectangles meeting at one corner point (a plus-sign layout) | 4 `RoomCandidate`s, the center node classified `X_CROSSING`, 4 walls incident to it |
| T5 | A wall drawn at 37° to the page axes, closed into a simple parallelogram room | 1 `RoomCandidate` with the correct (non-rectangular) area, walls not misclassified as orthogonal, `interior_exterior` still correctly resolved |
| T6 | A wall drawn as a bezier arc (`"c"` item) closing a room with one curved and three straight sides | `is_curved=True` on the curved `WallCandidate`, `centerline_pts` a sampled polyline, room polygon area within a stated tolerance of the true (integrated) curved area |
| T7 | Double-line wall (two parallel segments, realistic 200mm gap at a known scale) | 1 `WallCandidate` with `representation="double_line"`, `thickness_m` within 5% of 0.200 |
| T8 | A single wall drawn as three separate collinear segments with small (<2pt) gaps between them, no shared endpoints | Collinear-merge (§6.5) produces exactly 1 `WallCandidate`, not 3, and no spurious `degree==2` junction nodes at the gap points |
| T9 | A single wall drawn as one segment split into two by inserting a redundant shared-endpoint vertex mid-run (simulating a CAD export quirk) | Exactly 1 logical wall after merge, not 2 |
| T10 | A rectangle with a door-width gap in one wall | The gap produces exactly one `OpeningHostCandidate` with `host_status="hosted"` referencing the correct wall; room polygon extraction still closes correctly across the gap (the gap must not fragment the room face — verify `extract_planar_faces`'s existing tolerance for small gaps, or specify the minimum gap-bridging tolerance if a fix is needed here) |
| T11 | A rectangle with two gaps in different walls (a door and a window position) | Two independent `OpeningHostCandidate`s, correctly attributed to their respective walls |
| T12 | A rectangle containing a second, smaller closed polygon fully inside it (an internal core/shaft) | Outer `RoomCandidate` has `has_voids=True`; the inner polygon is independently evaluated by `filter_face` on its own merits (may or may not itself qualify as a room) |
| T13 | A courtyard: a ring-shaped wall layout (outer rectangle, inner rectangle, both walled, no roof/label over the inner area) | The inner area is a void on the surrounding wing's room candidate(s), not a phantom room of its own, unless independently labeled |
| T14 | A corridor: a long, narrow, labeled rectangle (e.g. 1.2m × 12m) | Accepted as a `RoomCandidate` (label present overrides the elongation rejection per `filter_face`'s existing rule), `geometry_confidence` reflects the elongation penalty |
| T15 | Same corridor shape, unlabeled | Rejected by `filter_face`'s existing elongated-unlabeled rule — verify this reuse path explicitly with a project-agnostic synthetic fixture, not only via real-project regression |
| T16 | A verandah: a rectangle attached along one full side of a main room rectangle, both walled, verandah unlabeled but the word "VERANDAH" present nearby | Two adjacent `RoomCandidate`s (or one room + one lower-confidence unlabeled space depending on `filter_face`'s soft-area outcome), correctly adjacent (§8.5), no forced `adjacency="front"` assumption anywhere in this path |
| T17 | Two fully disconnected rectangular buildings on one page, no shared geometry at all | Two `building_component_id` values, 2 independent `RoomCandidate` sets, no cross-building adjacency ever proposed |
| T18 | Two separate floor plans (two rectangles, clearly spatially separated, e.g. left/right halves of the page) inside two distinct viewports | Each plan's walls/rooms reconstructed independently; zero segments/words shared between the two viewport-scoped runs (verify via the full-containment exclusion rule, §4) |
| T19 | A "detail" viewport containing a small rectangle that is a literal duplicate (copy-pasted) of a room already reconstructed from the main plan viewport | The detail-viewport copy does not create a second physical room instance — verify via `building_component_id`/viewport-scoping that a detail/schedule-type viewport (per `pb_drawing_evidence_binding.DrawingViewType`) is excluded from room-candidate generation entirely, or produces a candidate explicitly tagged as non-physical (reuse `CanonicalEvidenceObservation`'s existing "must never gain deduction authority" concept, per the companion doc §7) |
| T20 | A repeated "TYPICAL FLOOR" plan referenced once but intended to apply to multiple storeys (text annotation "TYPICAL 2ND-4TH FLOOR") | Reconstructed once as its own `building_component_id`/`level_id`; per §8.7, no automatic ×N multiplication is attempted — this test asserts the *documented* non-behavior (single reconstruction, no silent duplication), not a multiplier feature |
| T21 | A mirrored unit: two rooms that are geometric mirror images of each other, both physically drawn (not the same instance referenced twice) | Two independent `RoomCandidate`s, correctly two separate `room_ref`s with independent polygons — verify mirroring doesn't cause any accidental identity collapse (e.g. via a symmetry-based dedup heuristic this design does not use) |
| T22 | A room polygon plus a printed "24.5 m²" label inside it that matches the polygon's true calibrated area within tolerance | `explicit_area_label_m2` populated, `area_conflict=None`, confidence boosted per §8.6 |
| T23 | Same, but the printed label says "30.0 m²" against a true ~24.5 m² polygon | `area_conflict` populated with both values, `fusion_status=CONFLICTING`, neither value silently preferred |
| T24 | Two dimension strings on the same wall run that disagree beyond tolerance (e.g. "3000" and "3500" both apparently labeling the same run) | `fusion_status=CONFLICTING` on that wall's `length_m`, both raw values retained in evidence, no averaging |
| T25 | Two independent scale indicators on the same page (a printed "1:100" and a dimension-derived scale) that disagree beyond `pb_page_scale_calibration_authority`'s own tolerance | Scale resolves to whatever that existing authority module already does for conflicting sources (`BLOCKED`/`CONFLICTING`, per its existing status machine) — this test verifies this workstream correctly *defers* to that outcome rather than computing its own scale resolution in parallel |

## 16. Metamorphic test matrix

| Property | Construction | Expected invariant / documented abstention |
|---|---|---|
| Translation invariance | Take any T1-T21 fixture, translate every coordinate by a fixed offset | Identical topology (same junction count/types, same room count/areas within floating-point tolerance), only absolute positions differ |
| Rotation invariance | Rotate a fixture (e.g. T1's rectangle) by 90°, 45°, and an arbitrary angle (e.g. 17°) | Identical topology and areas; angle-dependent fields (`incident_angles_deg`, `angle_deg`) rotate consistently, junction *types* unchanged |
| Vector split invariance | Take a single wall segment and pre-split it into 2-5 collinear sub-segments with shared endpoints before feeding the pipeline | Identical result to the unsplit version, post collinear-merge (§6.5) |
| Collinear merge invariance | Same as above but with small deliberate gaps introduced between the pre-split pieces (within snap tolerance) | Identical result — this is the direct test of §6.4/§6.5's fragmentation handling |
| PDF object-order invariance | Shuffle the order of `page.get_drawings()` items before running Stage A (simulate by permuting the `segments` list fed to `snap_geometry`) | Identical result — `snap_geometry`'s node-locate loop and `extract_planar_faces`'s traversal must not depend on input order; if this fails, it identifies exactly the kind of order-dependent bug flagged generically in the companion audit |
| Page-padding invariance | Add unrelated whitespace/margin around an existing fixture (shift all content by a large offset, enlarge the nominal page size) | Identical topology, same as translation invariance |
| Render-DPI tolerance | N/A for the native-vector path (no rendering occurs) — applies only to the raster fallback (§12); test by rasterizing the same synthetic PDF at two different DPIs and confirming the *raster* detector path (once it exists) produces geometry within a stated tolerance, not that it's pixel-identical | Documented as a raster-path-only test, explicitly out of scope for this PR sequence's acceptance gate (§19) since no raster detector is built here |
| Unrelated-note invariance | Add an unrelated text annotation with a large plausible-looking number (e.g. a project reference "2024-045" or an unrelated note "See detail 3500mm offset") far from any wall/dimension context | Zero effect on any `WallCandidate`/`RoomCandidate` — this is the direct test of §10's "an unrelated large number never becomes geometry" rule; the number must fail every spatial-binding test in §10 and never appear in any candidate's evidence |
| Hatch removal invariance | Construct a fixture with hatching fill patterns (short crossing lines) inside a room polygon, then an identical fixture with the hatching removed | Identical wall/room topology in both — hatching lines must be filtered before wall-pairing (§6.11) and must not perturb `extract_planar_faces`'s traversal (verify hatching doesn't accidentally close spurious small faces) |
| Duplicate-detail non-counting | T19 above, formalized as a metamorphic pair: a fixture with only the main plan vs. the same fixture plus an added detail-viewport duplicate of one room | Identical room *count* and areas for the physical building — the detail duplicate must not add a phantom second instance |

**Expected abstention, not invariance, for:** T20/T21-style repeated/mirrored geometry (no
multiplier or symmetry-collapse behavior is implemented, so "invariance" doesn't apply — the
correct assertion is "reconstructed independently, no silent multiplication," per §8.7), and the
render-DPI case above (genuinely out of scope pending a raster detector).

---

## 17. Performance / caching design

Extends the companion architecture doc §12's staged cascade, scoped to this workstream's stages:

```
STAGE A (native segment extraction + intersection split + snap)
  cache key: page_content_hash + native_parser_version + split_intersections_version
             + snap_tolerance_pt
  cost driver: split_segments_at_intersections is O(n^2) pairwise — flag explicitly:
             for a dense CAD export (hundreds to low-thousands of segments per page,
             observed range in this repo's own registered benchmarks is well within
             this), O(n^2) is acceptable; a genuinely dense hybrid/hatched raster-traced
             sheet could reach segment counts where this becomes the dominant cost —
             if profiling on real documents shows this, the fix is a spatial index
             (grid/bucket segments by bounding box before pairwise testing), not a
             different algorithm; do not prematurely optimize before measuring on the
             actual registered benchmark PDFs.

STAGE B (wall candidates)
  cache key: stage_A_graph_hash + wall_pair_detector_version + junction_classifier_version

STAGE C (room candidates)
  cache key: stage_A_graph_hash + face_extraction_version + filter_face_thresholds_version
             (thresholds are a version input, not a hidden constant, so a future
             threshold tuning pass invalidates exactly the cache entries it should)

STAGE D (fusion)
  cache key: stage_B_hash + stage_C_hash + dimension_evidence_hash + scale_authority_hash
             + fusion_ruleset_version

STAGE E (canonical promotion)
  cache key: stage_D_hash + canonical_schema_version
```

**Invalidation discipline (reused from the companion doc):** changing the ambiguity-margin
constant in §9 invalidates Stage D and E only, not Stages A-C — the whole point of versioning each
stage's cache key independently. Raster/CV fallback (§12) is its own cache tier, keyed by
`viewport_hash + render_dpi + detector_version`, invoked only when Stage A's segment count for a
viewport falls below a documented minimum (an explicit constant, not an inferred threshold) — never
run by default alongside the native path.

---

## 18. PR-by-PR implementation sequence

All PRs in this sequence run in **shadow mode only** (per the companion doc's shadow-runner
infrastructure, assumed already landed as that document's P1-P6) — none of them change any
benchmark-facing `ExtractedPrediction` output or touch benchmark gold. Every PR's acceptance gate
is therefore about correctness against synthetic/metamorphic tests and shadow-mode agreement
statistics, never development-benchmark score movement.

| PR | Objective | Files | Depends on |
|---|---|---|---|
| W1 | `WallCandidate`/`JunctionCandidate`/`RoomCandidate`/`OpeningHostCandidate`/`FusionStatus` dataclasses (§5, §7, §8.1, §13, §9) | New `pb_wall_room_topology_contracts.py` | Companion doc's P1 (migration contracts) |
| W2 | Stage A: wire `split_segments_at_intersections` → `snap_geometry` (unmodified) into a single callable per viewport, add the collinear-merge pass (§6.5) and hatch/dimension-line pre-filter (§6.11) as extensions to `snap_geometry`'s input | `pb_vector_geometry_v130.py` (extend), `pb_accuracy_v13_engines_v145.py` (reuse unmodified) | W1 |
| W3 | Junction classification (§7) over W2's node output | New module or extension of `pb_vector_geometry_v130.py` | W2 |
| W4 | Wall candidate assembly: wrap `detect_wall_pairs` (double-line) + new single-line promotion (§6.1) + curve capture (§6.6, requires extending `extract_native_page` for `"c"` items) into `WallCandidate` records | `pb_vector_geometry_v130.py` (extend) | W2, W3 |
| W5 | Room candidate assembly: extend `extract_planar_faces` to retain boundary segment provenance (§2), wire through `attach_room_labels` and `filter_face` unchanged, populate the new `RoomCandidate` fields | `pb_accuracy_v13_engines_v145.py` (extend), `pb_room_face_takeoff.py` (extend `RoomFace`→`RoomCandidate`) | W1, W2 |
| W6 | Shared-boundary/adjacency (§8.5): generalize `compute_collinear_segment_overlap`'s usage to run over all room-candidate pairs per building component | `pb_multi_space_footprint_geometry.py` (extend caller, algorithm unchanged) | W5 |
| W7 | Building-component assignment (§8.7): union-find over the wall graph, stamp `building_component_id` | New small utility | W2 |
| W8 | Opening-host candidate generation (§13): gap detection on wall runs (§6.9) + host resolution | New module, consumes W4/W5 output | W4, W5 |
| W9 | Dimension binding generalization (§10): extend existing spatial-binding functions to the new target types (wall length, room extent, opening width) | `pb_figured_dimension_evidence.py` / `pb_viewport_dimension_binding.py` (extend) | W4, W5, W8 |
| W10 | Scale-authority wiring (§11): route every metre-space field through `pb_page_scale_calibration_authority.py` exclusively; retire `pb_vector_geometry_v130.solve_scale()` and `pb_room_face_takeoff.page_scale_info`/`vector_analysis_scale_info` as authorities (may keep as evidence-input helpers, §3) | `pb_page_scale_calibration_authority.py` (consumer wiring only), the three retired-authority call sites | W4-W9 |
| W11 | Fusion layer (§9): extend `pb_drawing_evidence_binding.ReconciliationStatus` to the six-state `FusionStatus`, implement the ambiguity-margin rule generically, wire orthogonal-envelope/explicit-floor-area evidence as inputs (not authorities) | `pb_drawing_evidence_binding.py` (extend enum), new fusion module | W1-W10 |
| W12 | Canonical promotion (§14): extend `pb_canonical_building.CanonicalElement` per the companion doc §5, populate `CanonicalWall`/`CanonicalSpace`/`CanonicalOpening` from `CORROBORATED`/`SUPPORTED` entities only | `pb_canonical_building.py` (extend) | W11 |
| W13 | Full synthetic test suite (§15, T1-T25) | New test module(s) | W1-W12, can be written incrementally alongside each prior PR rather than only at the end |
| W14 | Metamorphic test suite (§16) | New test module(s) | W13 |
| W15 | Shadow-mode run against the 5 registered development benchmark PDFs (KSTVET, Murera, Ghazi, Umma, Lamu) — measurement only, no authority change, no gold read for this purpose beyond what the existing benchmark infrastructure already separates | Shadow-comparison script (companion doc's P3/P5) | W1-W14 |
| W16 | Opening-host consumer update: `pb_opening_deduction_pipeline.bind_openings_to_walls` reads real per-wall hosts from W8 instead of its single-wall fallback (fixes the order-dependent bbox tie-break at the same time) — **still shadow-only**, deduction authority is a separate, later gate per the companion roadmap's P13 | `pb_opening_deduction_pipeline.py` | W8-W15 |

## 19. Acceptance gates per PR

- **W1-W3 (contracts, Stage A extensions, junction classification):** 100% pass on the relevant
  synthetic tests from §15 that don't require room extraction (T1, T5-T9); zero changes to any
  existing test's outcome (run the full existing suite, expect no regressions — these PRs touch
  shared, currently-live modules like `pb_vector_geometry_v130.py`, so existing callers must be
  unaffected).
- **W4-W5 (wall/room candidate assembly):** 100% pass on T1-T21; `filter_face` reuse verified via
  T14/T15 producing the *documented existing* accept/reject outcomes, not new behavior.
- **W6-W8 (adjacency, components, opening hosts):** T3-T4 (junction/adjacency), T10-T11 (opening
  hosting), T12-T13 (voids/courtyards), T17-T19 (multi-building/multi-viewport/duplicate-detail)
  all pass; zero false "hosted" assignments on the ambiguous-host synthetic case (a gap
  equidistant between two plausible walls must report `"ambiguous_host"`, never guess).
- **W9-W11 (dimension binding, scale, fusion):** T22-T25 all pass; the unrelated-large-number
  metamorphic test (§16) passes with zero effect on any candidate; ambiguity-margin behavior
  verified against the exact existing `pb_contextual_wd_card_evidence.py` numeric pattern reused
  in §9, not a new bespoke threshold.
- **W12 (canonical promotion):** round-trip serialization of a promoted `CanonicalWall`/
  `CanonicalSpace`/`CanonicalOpening` set passes `pb_canonical_persistence.py`'s existing
  fingerprint/staleness checks unmodified; zero `PROPOSED`/`AMBIGUOUS`/`CONFLICTING`/`UNRESOLVED`
  entities ever appear as promoted canonical elements (a direct, automatable invariant check).
- **W13-W14 (test suites):** all pass, including every metamorphic property in §16 except the
  explicitly-documented render-DPI (raster, out of scope) and repeated-floor/mirrored-unit
  (documented abstention, not invariance) cases.
- **W15 (shadow measurement):** produces a report (per project) of wall/room candidate counts,
  fusion-status breakdown, and — where the existing benchmark's own gold quantities *would* let a
  post-hoc, evaluator-side comparison happen (never inside the extraction process itself, per the
  companion doc §9's process-isolation rule) — a shadow comparison against the legacy extractor's
  current envelope/footprint numbers on the same 5 projects. **No pass/fail accuracy threshold at
  this gate** — the objective is measurement and defect discovery, consistent with the brief's
  explicit instruction not to claim authority yet.
- **W16:** verified against the existing `pb_opening_deduction_pipeline.py` test suite (unmodified
  behavior for the single-wall case, which must still work identically for any project not yet
  migrated) plus new tests for the multi-wall real-hosting case; **still shadow-only** — no
  benchmark's `ExtractedPrediction` changes as a result of this PR.

**Explicit non-goal, stated once for the whole sequence, per the brief's own instruction:** none of
W1-W16 is expected or permitted to move the 24/61 development number, and this workstream does not
score, read, or otherwise touch the sealed frozen holdout (`tenders_ke_olv_laboratory_complex`) at
any point.

---

## 20. Exact next Cursor implementation prompt (after its opening-count work is complete)

Once Cursor's schedule-count shadow extraction work is done, hand it the following, verbatim:

> Your schedule/opening-count extraction now produces reliable `(tag, quantity, evidence)` records
> in shadow mode. The geometry workstream (this document) has, in parallel, produced
> `WallCandidate` objects with real centerlines/thickness and `OpeningHostCandidate` objects
> identifying *where* a wall-line gap exists and *which wall it interrupts* (`hosted` /
> `ambiguous_host` / `unhosted`), per `docs/planreader_wall_room_topology_spec.md` §13. Neither
> side currently connects a specific physical opening instance (a gap at a specific position on a
> specific wall) to a specific schedule tag (a specific `D1`/`W3`/etc. quantity record).
>
> Your next task is exactly that bridge, and nothing else: for each `OpeningHostCandidate` with
> `host_status="hosted"`, determine which of your resolved schedule/tag records (if any) most
> plausibly corresponds to it — using real evidence (proximity of the tag's own drawing-plan
> occurrence, if any, to the gap's position; consistency between the gap's `gap_width_m` and the
> schedule record's own width, when available; count reconciliation between the number of
> `"hosted"` gaps found for a given wall/room and the schedule's stated quantity for a matching
> tag). Where two schedule tags are both plausible for the same gap, or a gap has no matching
> schedule evidence at all, follow this document's §9 fusion rules exactly: report `AMBIGUOUS` or
> `UNRESOLVED`, do not guess. Do not implement wall-deduction math (that remains
> `pb_opening_deduction_pipeline.py`'s job, gated separately per this document's W16/roadmap P13).
> Do not modify `WallCandidate`/`OpeningHostCandidate` geometry — treat them as read-only input.
> Run entirely in shadow mode against the same 5 registered development benchmarks; do not touch
> benchmark gold, do not read or score the sealed frozen holdout, and do not claim any accuracy
> number from this work until it clears its own gate in a follow-up to this specification.
