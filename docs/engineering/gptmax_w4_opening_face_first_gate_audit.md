# GPT MAX — read-only W4 opening-face first-failure audit

## Observed repository behaviour

Studied `AGENTS.md`, `docs/AI_ENGINEERING_PLAYBOOK.md`,
`docs/wall_topology_observability_architecture.md`,
`docs/planreader_wall_room_topology_spec.md`,
`docs/planreader_public_tender_benchmarks.md`,
`.github/workflows/ci.yml`, and current producer/diagnostic code.

Exact source path: `SourceVisibilityProducer.ingest_native_pdf_bytes` →
`compose_live_wall_opening_authority` →
`PhysicalWallCandidateProducer.resolve_scope` →
`_source_page_segments` →
`_filter_repeated_non_physical_drafting_primitives` →
`_proven_filled_wall_strips` /
`_filter_proven_wall_strip_geometry` →
`build_wall_graph_for_viewport` (W2) →
`assemble_wall_topology` (W4) →
`collect_physical_wall_identities` →
`physical_opening_authority.prove_existence` (separate G17 authority) →
`physical_wall_candidate_authority.resolve_scope`.
`tools/diag_opening_wall_face_preservation.py` already reports source/host
receipts and the non-publishing face-preservation sidecar, but does not
enumerate the **first disappearance stage** of all four opening faces.

The historical diagnostic in #1869 (`tools/diag_gptmax_lot16_w4_face_coverage.py`)
contains an additional original-source stage census and remains unique,
while #2181's live source-face bridge was deliberately kept out of W4
because real-source identity retention failed.

## Inference

For an individually corroborated six-line G17 pattern, tracing each of
its four source-proven interrupted faces through the original producer's
stage inventory can isolate missing W4 ownership without inferring a host.
The trace is **descriptive only**: a wall-face observation, even when
corroborated, is not physical wall equivalence, complete opening-universe
proof, geometric scale, quantity or commercial authority.

## Proposed change

Preserve and adapt the historical stage census as a **separate, opt-in,
read-only CLI** accepting an exact PDF and source page. Remove hardcoded
project path, project-specific SHA and page/scope constants from the
implementation. Emit an explicit real-source SHA, original snapshot,
per-opening and per-face stage reasons with original W4 owners and
equivalence ambiguity. Emit explicit false publication booleans.

The stage audit must never modify source objects, W2/W4 graphs,
opening/host identities, topology filters, equivalence policy, scale,
measurement, quantity, customer output or caches except as the unchanged
upstream producer normally does. It cannot select a nearest or first
competing owner. It must retain all competing original candidate IDs.

## Expected abstentions

Missing raw primitive → no wall-face reportable W2 support.
Repeated motif/structural/strip/graph loss → no W4 physical owner.
Multiple, unresolved or equivalence-ambiguous W4 owners → no selection.
Incomplete original G17 source support → no invented four-face roles.
No stage (including single usable W4 owner) authorises a host or quantity.

## Frozen assets and exclusions

No edits to source PDFs; frozen V2 manifests, reference takeoffs, object
universes, tolerances, evaluator or scoring; source cap (20,000);
production W2/W4, physical host/frame, canonical object, quantities
or customer projection. No benchmark names, expected values or scores
are used as algorithm inputs.

## Proof before integration

- Synthetic positives, negative observation kind/prefix and graph
  ancestry, conflict and duplicate ownership.
- Output determinism and read-only separation.
- Actual SHA-verified Lot16 page 3 source diagnostic;
  compare exact original source reports before/after audit.
- Full Python 3.13/3.14 CI, source-isolation and frozen V2 integrity.
- If any producer output changes or existing host/frame receipt disappears,
  keep this PR draft and unmerged.
