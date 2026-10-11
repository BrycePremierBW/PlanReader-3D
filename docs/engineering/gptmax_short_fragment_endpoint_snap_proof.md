# GPT MAX — exact endpoint trace for short source fragments

## Architecture review before implementation

Read `AGENTS.md`, `docs/AI_ENGINEERING_PLAYBOOK.md`,
`docs/wall_topology_observability_architecture.md`,
`docs/planreader_wall_room_topology_spec.md`,
`docs/planreader_public_tender_benchmarks.md`, and `.github/workflows/ci.yml`.

Observed call path: `tools.diag_opening_wall_face_preservation.source_face_report`
calls `compose_live_wall_opening_authority`; the physical-wall producer's
`_assemble_scope_result` calls `build_wall_graph_for_viewport`. W2 splits source
segments, `_snap_geometry_indexed` maps endpoints to nodes and discards an edge
when both endpoints map to one node. W4 `assemble_wall_candidates` consumes the
surviving graph, and `collect_physical_wall_identities` records its source path.

Observed defect in the read-only audit introduced by PR #2176:
`audit_short_source_fragments` calls any absent split edge `SNAP_COLLAPSED`.
It receives no endpoint assignments for discarded edges. Absence alone cannot
distinguish a true snap collapse from a damaged/incomplete diagnostic graph.
Its displacement is also unavailable for the very fragments being investigated.
The follow-up #2176 head `0c0155bd` conservatively renames that absence and
checks the producer's disappearance ledger. This successor retains those
validations and adds direct endpoint evidence; it does not overwrite that head.

Inference: retaining the assignments made by the actual snap operation can
locate a lost terminal source fragment without changing topology or rerunning
snapping to guess where it went. It cannot establish wall continuity, physical
equivalence, host authority or a missing metric measurement.

Proposed change: under the existing `GPTMAX_W2_SHORT_SOURCE_AUDIT=1` opt-in,
retain both endpoint node IDs before the `a == b` discard. The audit may report
`SNAP_COLLAPSED` only when that actual trace assigns both endpoints to the same
valid node. Missing trace remains an unresolved omission. Reject duplicate node
or edge identities, inconsistent trace/edge ownership and corrupt merge leaves.
Record collapsed-fragment node geometry and displacement as observations only.

Expected abstentions: missing/ambiguous/nonfinite original source parent remains
unproven; a missing edge without endpoint assignments remains unresolved;
different endpoint nodes with a missing edge or missing/foreign/duplicate node
IDs are invalid trace data. No inference from endpoint proximity or node order.

Authority boundary: positive primitive provenance -> observational W2 trace
only. No new topology, source observation, W4 identity, scale, host, frame,
opening count, canonical object, deduction or QuantityEvidence is published.
Graph output without the opt-in is unchanged. With opt-in, removing only the
diagnostic sidecar must give the same graph and original-source host report.

Benchmark observations excluded from implementation: the archived original
Lot16 paired artifact is workflow `38068100685`, artifact `11675407730`, source
SHA `10109b4b6e85e6e27af81f6399ce4b92abfdba80f87dc69dd5887bd6f3a65844`.
It motivates investigation of source-painted short tails but supplies no
algorithm threshold, expected quantity or physical-equivalence decision.
The observation bound remains W2's existing supplied snap tolerance.

Files outside this change: frozen V2 manifests/truth/evaluator/scoring,
source PDFs, physical opening/host/frame publishers, measurement/quantity and
customer-output writers, W4 grouping and W10 eligibility defaults. The
20,000-source-primitive cap and strict host/frame retention comparator remain.

Validation: true collapse and missing trace; corrupted and duplicate topology;
source parent negatives; raw and merged ancestry; translation/rotation/scale,
input-order, unrelated-content, deterministic replay and no-mutation tests;
default/opt-in graph equality; original-source default/opt-in report equality.
No host recovery or benchmark accuracy gain is claimed by this diagnostic.

## Verified original-source observations

On Python 3.12.14 with the repository-pinned PyMuPDF 1.28.0, OpenCV 4.14.0.94
and Shapely 2.1.2, the source report before/after endpoint instrumentation was
exactly equal: 23 physical openings, 14 authenticated hosts, nine frames.
W2 traced 525 actual collapsed short positive-source fragments, 67 retained raw
edges and two merged fragments; 33 short fragments lacked a unique positive
parent and were skipped. These are source-stage observations, not item counts.

The archived blocked compact+T branch `1ca637b3` was independently re-executed
on the original PDF. Every actual indexed snap graph was compared against the
instrumented snap graph after removing only the endpoint assignment trace;
they were identical. All source-report fields reproduced the archived artifact.
The branch still has 23 physical openings, 18 hosts and nine frames and still
fails the strict original host/frame identity retention gate.

Two actual changed physical candidate spans now have direct disappearance
evidence, not merely an absent edge:

| Original source fragment | Actual snapped node | Maximum endpoint displacement |
| --- | --- | --- |
| `:1585`, (410.25, 341.50) to (410.25, 342.72) pt | (410.475, 342.5166666667) pt | 1.0412665898 pt |
| `:324`, (582.60, 531.25) to (584.50, 531.25) pt | (582.9166666667, 531.6283333333) pt | 1.6279068019 pt |

Both endpoints of each fragment were assigned by the actual snap operation to
one node. This explains the lost raw terminal span; it does not make the
changed W4 candidates physically equivalent or restore a host/frame receipt.
The next geometry hypothesis must retain that exact painted source span in
shadow while proving unique source ownership and leaving unproven gaps open.

The paired Maryborough source check and exact-head Python 3.13/3.14 CI are
additional merge gates. A local Lot16 proof alone does not satisfy them.

The change is replayed on main `f52ca76f8419860e61d4c3750c02d246ca061322`.
Only W2's observational entry points and new diagnostic/test/workflow files are
changed; current main's opening-page proof cache and source membership witness
are retained. The focused suite passes 249 tests, including both new trace
checks and the current page-cache, source-membership and strict retention tests.
Provider/gold isolation, frozen V2 integrity, undefined-name checks and patch
whitespace checks pass. Python 3.13/3.14 source CI remains an independent gate.
