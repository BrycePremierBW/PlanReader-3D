# W4 identity collision — source-first repair proposal

## Observed (2026-10-11)
Read AGENTS.md, docs/AI_ENGINEERING_PLAYBOOK.md, docs/wall_topology_observability_architecture.md, docs/planreader_wall_room_topology_spec.md, docs/planreader_public_tender_benchmarks.md, .github/workflows/ci.yml, pb_wall_room_topology_wall_assembly.py, pb_physical_wall_identity.py, pb_physical_wall_candidate_authority.py and pb_opening_host_binding_authority.py.

Producer authority path: immutable source visibility → W2 build_wall_graph_for_viewport → W3 classify_junctions → W4 assemble_wall_topology / assemble_wall_candidates (first wall candidate IDs) → collect_physical_wall_identities (keyed by wall_candidate_id) → _assemble_scope_result → resolve_physical_wall_equivalence → source-local host binding.

The current W4 ID intentionally hashes geometry but not U1 source ancestry. Real original Maryborough source SHA b1be53531412005f42937c89d0cfce66fbbe608315016bbb56731029ffc9e007, page 7, produces 3,737 W4 records and 3,736 unique IDs: wall_6d948b1b47258597fa66 represents *two different raw W2 edges* split_2296 and split_9744, with different endpoint W3 junction IDs. Current collect_physical_wall_identities dict comprehension silently assigns the later physical identity to both records. Three previously hosted openings do not include this candidate ID in their member wall lists; absence from those members alone is not host safety proof.

## Inference / authority boundary
An equality of unscaled, rounded W4 path fingerprints proves neither equal underlying W2 source lineage nor physical-wall equivalence. W4 may need *distinct candidate addresses* to preserve competing evidence. This must not promote two candidates as physically distinct or grant a count/measurement/host/QuantityEvidence. Any new identifier must be conditional only on actual same-ID conflict and source-owned evidence, not PDF filename, project, benchmark expected values or a tolerance relaxed to change outcomes.

## Proposed narrow change
Before returning assembled W4 candidates, scan *all* candidate IDs. Leave every non-colliding wall and edge map byte-for-byte unchanged. For a collided group, derive an additional deterministic candidate discriminator from existing source primitive lineage, original W2 edge geometry and W3 endpoint junction provenance; distinguish original candidate addresses only if every source-owned discriminator is valid and unique. Recompute only those collided candidate IDs and the edge→candidate map; preserve the original geometric ID in candidate metadata and reason codes. No physical SAME/DISTINCT resolution or host selection happens here. If source support is absent, foreign, nonfinite or still collides, fail closed instead of arbitrarily choosing one wall. Separately guard keyed identity collection against silent same-ID collision.

## Tests / expected negatives
- Same centerline/endpoints with independently evidenced source edges and junction ownership produces two unique, order-stable candidate **addresses**.
- Reversed path, arbitrary edge-list order, rotation/translation, unchanged legitimate collinear rechunking and unrelated content do not rekey unaffected candidates.
- Duplicated/foreign/missing source ancestry and nonfinite edge coordinates must not create fallback identities.
- Original source guard: exact SHA, 20k cap, Lot16 23 openings/14 hosts/9 frames and Maryborough 180/3/0 with strict receipt retention, Python 3.13 and 3.14 suites, provider isolation and frozen V2 integrity.
- Real positive diagnostics and synthetic geometry are not permission to merge if the source host/frame identities change.

## Unchanged
Source PDFs, W2 snapping and thresholds, W3 junction classification, W4 same/different physical equivalence rules, output publishers, dimensions/scale, all frozen V2 truth/evaluator files.
# Continuation design, 2026-10-11

Observed: duplicate physical-identity collection raises a generic `ValueError`
and the production helper catches that error by prefix text across both
assembly and collection calls. An unrelated exception with the same prefix can
be hidden. One corruption regression also asserts text rather than the new
typed source-address exception.

Proposed: a dedicated duplicate-address exception from the existing physical
identity collector; catch only the two producer-owned exception types. Assert
the typed collision for corruption and independently test misleading generic
errors from both call sites. Preserve normal return objects and original source
receipts. This changes failure handling only, never physical equivalence,
geometry, quantities, the 20k cap or frozen truth.
