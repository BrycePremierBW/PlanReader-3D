# W1–W10 wall/room topology — observability architecture note

This note is a reading of the adopted stack at
`537a32edeeb67ecb7bcf4939c7a4876af25b48f7`. It does not change that stack.
The diagnostic harness (`pb_wall_topology_diagnostics.py`) only *summarizes*
already-produced records.

Nothing in W1–W10 is live-wired into `pb_planreader_pdf_extractor`.
`WallCandidate` is never promoted to a true wall by this workstream.

## Call graph

```
extract_native_page(page)                    [pb_vector_geometry_v130]
        │  segments[], words[], rects[]
        ▼
segment_page_viewports(page)                 [F.07 / pb_viewport_segmentation]
        │  fail-closed unless RESOLVED (or explicit DERIVED) + FLOOR_PLAN + bbox
        │  segments scoped by both endpoints inside the viewport
        ▼
W2  build_wall_graph_for_viewport(segments)  [pb_wall_room_topology_stage_a]
        │  graph{nodes, edges, adjacency, excluded_segments}
        ▼
W3  classify_junctions(graph)                [pb_wall_room_topology_junction_classifier]
        │  JunctionCandidate[] + TopologyRelationship[]  (ids still Stage-A edge ids)
        ▼
W4  assemble_wall_candidates(graph, …)       [pb_wall_room_topology_wall_assembly]
        │  ★ WallCandidate first created here
        │  edge_id → wall_candidate_id
        │  optional rekey_junctions_to_wall_candidates
        ▼
W5  reconstruct_room_candidates(graph, map)  [pb_wall_room_topology_room_faces]
        │  ★ RoomCandidate first created here (label="")
        ▼
W6  derive_room_wall_relationships(rooms, walls)
        │  new RoomCandidate/WallCandidate copies + RoomTopologyRelationship[]
        ▼
W7  detect_opening_host_candidates(walls)    [dangling-end gaps only]
        │  OpeningHostCandidate[]  (host_status is currently always ambiguous_host)
        ▼
W8  bind_room_labels_from_words(rooms, words)
        ▼
W9  reconcile_topology(...)                  [report only; does not mutate]
        ▼
W10 adapt_topology_to_canonical_level(...)   [shadow adapter; takeoff_eligible=False]
```

Optional research binder (not a W-number): `pb_hosted_opening_wall_binding.bind_hosted_opening_to_walls`
connects `HostedOpeningSpan` to `WallCandidate` without changing W1–W10.

---

## W1 — contracts (`pb_wall_room_topology_contracts.py`)

**Input:** none (data only).

**Output dataclasses:**
- `JunctionCandidate`
- `TopologyRelationship` (wall–wall, requires `via_junction_id`)
- `RoomTopologyRelationship` (room–wall / room–room)
- `WallCandidate`
- `RoomCandidate`
- `OpeningHostCandidate`

**IDs / provenance:** content-derived later via `stable_contract_id`. Status uses
the one `EvidenceResolutionStatus` vocabulary. Metre fields use
`MeasurementAuthorityType`. A `PROVISIONAL` authority can never be
`CORROBORATED`.

**Geometry:** none computed here.

**Fail-closed / discard / ambiguity:**
- constructors reject empty ids, non-finite numbers, inconsistent pairs
- `REASON_AMBIGUOUS` and related named reason codes
- `OpeningHostStatus`: `hosted` | `ambiguous_host` | `unhosted`

**WallCandidate created?** Schema only — no instances.
**Room faces?** Schema only.
**Opening-host binding?** Schema only.

---

## W2 — Stage A (`pb_wall_room_topology_stage_a.py`)

**Input:** one viewport's already-scoped raw segment dicts
(`id, x1,y1,x2,y2, width, stroke, fill, layer, dashes`). Viewport ownership is
the caller's job.

**Output:** graph dict `{nodes, edges, adjacency, excluded_segments}` after:
1. hatch/dimension/text-frame/dash pre-filter (`filter_structural_segments`)
2. `split_segments_at_intersections`
3. `snap_geometry` (endpoint snap, default 2.5 pt)
4. `merge_collinear_degree_two_nodes` (default 3°)

**IDs:** split fragments become `split_N`. Merged edges become
`merged_{id}_{id}` and record `collinear_merge_source_edge_ids`.
`excluded_segments` keep original ids plus `reason_codes`.

**Geometry:** native PDF-point linework only. No metres. No wall thickness.

**Fail-closed / discard:**
- dashed / hatch-layer / dimension-layer / text-frame-layer segments excluded
- short segments are **never** dropped for length (short returns must survive)
- split round-trip **drops per-fragment stroke/dash/layer** (consulted before split)

**Ambiguity:** not classified here.

**WallCandidate created?** No.

---

## W3 — junction classifier (`pb_wall_room_topology_junction_classifier.py`)

**Input:** W2 graph + `document_id`, `page_id`, `viewport_id`.

**Output:**
- `List[JunctionCandidate]`
- `List[TopologyRelationship]` (`CONNECTED_TO`, `CONTINUES_AS`, `TERMINATES_AT`,
  `INTERSECTS`, `BRANCHES_FROM`)

**IDs:** `stable_contract_id`. `incident_wall_candidate_ids` are still
**Stage-A edge ids** (documented sequencing; W4 re-keys later).

**Geometry:** incident angles, collinear through-pairs, near-miss node pairs,
rejected crossings against W2-excluded segments.

**Fail-closed / discard:**
- coincident edges deduplicated (kept in a new graph dict)
- short isolated arms demoted to `AMBIGUOUS` (furniture vs short return)
- near-miss nodes → `NEAR_JUNCTION_REVIEW` (`ABSTAINED`)
- `REJECTED_NON_WALL_CROSSING` recorded instead of silent absence

**Ambiguity:** `JunctionType.AMBIGUOUS` / `UNRESOLVED` / review types carry
`EvidenceResolutionStatus.ABSTAINED`.

---

## W4 — wall assembly (`pb_wall_room_topology_wall_assembly.py`)

**Input:** W2 graph + W3 junctions + W3 relationships + `viewport_id`.

**Output:**
- `List[WallCandidate]` — **first creation of WallCandidate**
- `edge_id_to_wall_candidate_id`
- `assemble_wall_topology` also returns re-keyed `JunctionCandidate`s

**IDs:** `candidate_id = stable_contract_id("wall", {viewport_id, ordered endpoints})`.
`face_a_segment_ids` = ordered Stage-A edge ids. `end_node_ids` from W3
`node_id`s.

**Geometry:** centerline polyline in page points. `thickness_m=None`,
`length_m=None`, `representation="single_line"` (double-line pairing is
explicitly not attempted). `interior_exterior="unresolved"`.

**Fail-closed / discard:**
- merge only through `CONTINUES_AS` **and** a junction type that permits
  extension (`COLLINEAR_CONTINUATION`, `T` bar, `X`, `MULTI_WAY`) with
  `status=CANDIDATE`
- `L_CORNER`, `ENDPOINT`, `AMBIGUOUS`, `NEAR_JUNCTION_REVIEW`, `UNRESOLVED`
  are chain boundaries — edges become separate candidates, not deleted
- non-simple chains get `non_simple_chain_topology_fallback_ordering`

**Ambiguity:** blocking junction recorded as
`chain_extension_blocked_by:{type}_at_{start|end}`.

---

## W5 — room faces (`pb_wall_room_topology_room_faces.py`)

**Input:** W2 graph + W4 `edge_id_to_wall_candidate_id` + document/viewport/page.

**Output:** `List[RoomCandidate]` — **first creation of room faces**.
`label=""`. `floor_area_m2=None` (only `area_page_pts2`).

**IDs:** `room_ref` via `stable_contract_id`. `bounding_wall_candidate_ids`
matched from face edges back to W4 ids.

**Geometry:** `extract_planar_faces` (unmodified) + void/containment flag +
tiny-loop review.

**Fail-closed / discard:**
- unbounded exterior already excluded by the face extractor
- untraceable boundary edge → `ABSTAINED`
- tiny spurious loop → `ABSTAINED` (kept visible, not deleted)
- duplicate polygons collapsed by canonical fingerprint

**Ambiguity:** abstained rooms remain in the list.

---

## W6 — room↔wall relationships (`pb_wall_room_topology_room_wall_relationships.py`)

**Input:** W5 rooms + W4 walls.

**Output:** new (non-mutated) rooms, new walls, `RoomTopologyRelationship[]`
(`BOUNDED_BY`, `BOUNDS`, `ADJACENT_TO`, `SEPARATES`).

**IDs:** same `candidate_id` / `room_ref`. Shared walls stay one id.

**Geometry:** wall-usage counts only (how many rooms cite a wall).

**Fail-closed:** a wall used by 3+ rooms emits **no** adjacency/separates
rows, leaves `interior_exterior="unresolved"`, reason
`wall_used_by_three_or_more_rooms_relationship_skipped`.

**Wall copies:** `interior_exterior` becomes `interior` (exactly 2 rooms),
`exterior` (exactly 1), else `unresolved`.

---

## W7 — opening-host binding (`pb_wall_room_topology_opening_host_binding.py`)

**Input:** W4/W6 `WallCandidate`s (dangling `ENDPOINT` pairs).

**Output:** `OpeningHostCandidate[]`.

**IDs:** `host_candidate_id` via `stable_contract_id`.
`wall_candidate_id` is one considered id; all partners listed in
`candidate_wall_ids_considered`.

**Geometry:** collinear dangling-end gaps above Stage-A snap tolerance,
relative max-gap vs shorter wall.

**Fail-closed:**
- `host_status="hosted"` is **not reachable** from this detector
- every gap is `ambiguous_host` (two flanking chains; do not pick one)
- unpaired dangling end is **not** an opening (discarded, not `unhosted`)

---

## W8 — room labels (`pb_wall_room_topology_room_label_binding.py`)

**Input:** rooms + raw PDF words `{text, bbox}` (or prefiltered label candidates).

**Output:** new `RoomCandidate` copies with `label` bound or abstained.

**Reuse:** `filter_room_label_candidates`, W5 `_point_in_polygon`.
Does **not** reuse `attach_room_labels` (that function silently takes
`matches[0]`).

**Fail-closed:**
- label in 0 rooms → unused
- label in 2+ rooms → `ROOM_LABEL_POSITION_AMBIGUOUS`, bind to none
- two distinct texts in one room → `ABSTAINED`, `label=""`

---

## W9 — reconciliation (`pb_wall_room_topology_reconciliation.py`)

**Input:** junctions, walls, rooms, room relationships, opening hosts.

**Output:** `TopologyReconciliationSummary` only. **Does not mutate inputs.**

**Value:** status tallies, flagged-entity pointers, cross-stage referential
integrity. Does not decide wall truth.

---

## W10 — canonical adapter (`pb_wall_room_topology_canonical_adapter.py`)

**Input:** walls, rooms, opening hosts + `document_id` / `viewport_id`.

**Output:** one `CanonicalLevel` with `takeoff_eligible=False`,
`deduction_authority=False`, `height_m=None`. No `CanonicalOpening`
(W7 hosts are still ambiguous).

**IDs:** reused verbatim (`candidate_id` → `CanonicalWall.id`).

**Fail-closed:** never `ReviewState.CONFIRMED`; never publishes floor area.

---

## One candidate, end to end

Take a 100×80 rectangle of four solid undashed segments in one RESOLVED
floor-plan viewport `vp_1`.

1. **W2** keeps all four segments. After split/snap/merge the graph has four
   edges and four degree-2 nodes (corners).
2. **W3** classifies each corner `L_CORNER` (`CANDIDATE`). Relationships are
   `CONNECTED_TO` only — no `CONTINUES_AS` at an L.
3. **W4** therefore emits **four** `WallCandidate`s (one per edge). Each
   `candidate_id` is a hash of `viewport_id` + ordered endpoints.
   `face_a_segment_ids` names the Stage-A edge. Thickness/length metres stay
   `None`. Reason includes `assembled_from_1_stage_a_edges`.
4. **W5** extracts the interior face, maps all four edges back to those four
   wall ids, and emits one `RoomCandidate` with
   `bounding_wall_candidate_ids` of length 4.
5. **W6** marks each wall `exterior` (used by exactly one room) and writes
   `BOUNDED_BY` / `BOUNDS`.
6. **W7** finds no dangling-end gap (the rectangle is closed) → no hosts.
7. **W8** binds a label only if a word centroid sits in the polygon.
8. **W9** tallies four candidate walls, one room; flags walls only if they
   stay `interior_exterior="unresolved"` (they do not here).
9. **W10** copies the four walls and one space into a non-eligible
   `CanonicalLevel`.

A fifth short tick touching one side, if it survives W2, becomes a W3
`AMBIGUOUS` short arm. W4 will **not** merge across that node; the tick
becomes its own low-confidence candidate rather than being deleted or
guessed as furniture.

---

## What the diagnostic harness may report

Only fields the topology already knows (or explicit `null` / `UNKNOWN` /
`unavailable` / `not_evaluated`). It must never label a candidate a
true wall, a false wall, or a noise wall.

## Diagnostic JSON schema (v1.0.0)

Canonical serialization is `canonical_contract_json` after key-sorted
normalization and 6-decimal float rounding. No timestamps, machine paths,
or user names appear in the payload. `document_id` is a basename or an
explicit caller label.

```
{
  "schema_version": "1.0.0",
  "source": {
    "document_id": str,
    "page_id": str,
    "page_number": int,
    "viewport_id": str,
    "viewport_authority": str,
    "view_type": str | null,
    "fail_closed_reason": str | null
  },
  "pipeline": {
    "stages_evaluated": [str],
    "opening_host_evaluated": bool
  },
  "counts": { ... integer tallies ... },
  "distributions": {
    "candidate_length_pt": {min, max, mean, median, p10, p25, p50, p75, p90, p95},
    "orientation": {horizontal, vertical, diagonal, UNKNOWN},
    "junction_degree": {"0", "1", "2", "3+"},
    "junction_types": {type: count},
    "room_face_participation": {yes, no},
    "paired_face_evidence": {yes, no, unavailable},
    "fill_hatch_evidence": {yes, no, unavailable, note},
    "opening_host_binding": {BOUND, AMBIGUOUS, UNBOUND, not_evaluated}
  },
  "components": [{component_id, size, wall_candidate_ids}],
  "junctions": [...],
  "room_faces": [...],
  "wall_candidates": [...],
  "isolated_candidate_ids": [...],
  "ambiguous_candidate_ids": [...],
  "opening_hosts": [...],
  "highest_connectivity_candidate_ids": [...],
  "longest_candidate_ids": [...],
  "largest_component_candidate_ids": [...],
  "reconciliation": object | null
}
```

Per-candidate metre fields (`length_m`, `thickness_m`) stay `null` unless
W4 already populated them. Per-candidate fill/hatch is `unavailable`
because W4 does not attach hatch evidence; the aggregate `yes` count is
Stage-A `hatch_layer_excluded` segments only.

CLI: `python tools/audit_wall_topology.py plan.pdf --page N [--json ...] [--markdown ...] [--svg ...]`.
`--page` is 1-based. `--allow-derived` is off by default. `--viewport-bbox x0,y0,x1,y1`
is optional caller-supplied spatial authority and is never inferred.
