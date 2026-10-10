# GPT MAX — original-source first host gate / W4 collision census

## Producer authority and source call graph

The input must be the untouched JSON from
`tools/diag_opening_wall_face_preservation.py` on an authenticated source PDF,
through `SourceVisibilityProducer.ingest_native_pdf_bytes` →
`compose_live_wall_opening_authority` →
`PhysicalWallCandidateAuthority.resolve_scope` →
`OpeningHostWallUniverseAuthority` →
`OpeningHostBindingAuthority` →
`source_face_report`.

This new script reads that source report **after** production execution. It
does not call geometry detectors, bind a host, collect quantities, or alter
source visibility, W2/W3/W4, equivalence, the 20,000 wall topology primitive cap,
the original PDF, any benchmark manifest/evaluator/scoring, or customer output.
It checks that the recorded SHA matches an independently supplied SHA; it
cannot cryptographically reauthenticate the original PDF using the report
alone. Do not treat a caller-created JSON or report-contained SHA as source
proof without the upstream run/artifact and PDF SHA.

### Invocation against an original source report

```bash
PYTHONPATH=. python tools/diag_gptmax_source_host_first_gate.py \
  --source-report /path/to/producer-source-default.json \
  --expected-source-sha ACTUAL_UNCHANGED_PDF_SHA256 \
  --output /path/to/original-host-first-gate.json
```

The report strictly crosschecks original page scope, source SHA, source-safety
cap, wall identity lineage, host summary, and opening receipt IDs.
It surfaces:
- Complete original-source host receipts with missing first-gate reasons.
- `raster_source_band_left/right_source_primitive_unmapped`, separately from
  `raster_source_band_left/right_local_wall_owner_unmapped` and generic
  `no_authenticated_host_wall_band`.
- Collided W4 geometric candidate **addresses**, retaining each competing
  W2 edge and W3 end-junction ID.
- Misassociated W4 source edge versus physical identity sidecar edge. Source
  physical equivalence is **not** derived from equal/different W4 addresses.

### Frozen source baseline observations (2026-10-11)

Exact archived original Lot16 PDF SHA:
`10109b4b6e85e6e27af81f6399ce4b92abfdba80f87dc69dd5887bd6f3a65844`.
Original recorded production handoff has 23 authenticated opening existences,
14 host bindings, 9 host frames. Its semantic opening inventory is explicitly
`conflict` and `physical_opening_universe_complete=false`: it has 23
representatives, 591 conflicting visible-source observations and 468 residual
visible-source observations. These are evidence-observation counts, NOT more
physical openings or schedule quantities. Seven of the nine unhosted opening receipts
have an explicit left/right source primitive mapping blocker and two contain
only `no_authenticated_host_wall_band`. This census is **not** a 27-denominator
benchmark run.

Exact archived original Maryborough PDF SHA:
`b1be53531412005f42937c89d0cfce66fbbe608315016bbb56731029ffc9e007`.
Original report has 180 opening existences, 3 hosts, 0 frames. Its semantic
inventory also has status `conflict`, 180 opening representatives, 7,325
conflicting source observations and 1,533 residual observations, with
`physical_opening_universe_complete=false` and
`structural_enumeration_complete=false`. The **177** unhosted original physical openings have first-gate classes: **94** missing authenticated host wall bands, **62** blocked by ambiguous physical-wall equivalence (42 direct and 20 with concurrent two-face lineage ambiguity), and **21** with incomplete wall-source scope / boundary evidence (14 viewport-cropped and seven scope-bounds unresolved). These source classifications are not a promise that the producer could seal the quantities after a single fix. Page 7 W4
has 3,737 source candidate records but only 3,736 unique addresses. The
source-edge and junction records `split_2296` and `split_9744`
share the address `wall_6d948b1b47258597fa66`, and the
physical identity sidecar erroneously uses `split_9744` for both.
Both W4 candidate centerlines are nearly coincident, so **physical SAME vs
DISTINCT remains unresolved**. Neither address rewrites nor source intersection
guesses can approve a commercial host.

### Security, fail-closed invariants and integration

Reports with missing/foreign source SHA, a changed primitive cap, duplicate
opening IDs, foreign pages/wall scopes, contradiction between summary and
individual receipts, and wall/identity address mismatches raise `ValueError`.
The diagnostic deliberately does not throw on W4 *candidate* ID collisions,
because an original producer report with that defect must remain auditable.
It emits no suggested host, material, measured area, inferred opening count,
physical wall equivalence or benchmark percentage. Every publication flag is
false; `benchmark_accuracy` is null.

Unit tests on Python 3.13/3.14 cover collision preservation, schema/lineage
negatives and unknown host abstention. The next production implementation
belongs to source-primitve-to-W4 mapping, W4 identity (#2236), and W2 source
geometry continuity (GPT MAX), each gated by exact original-source host/frame
receipt retention. Do not copy source-project coordinates into prediction code.
# Continuation design, 2026-10-11

Observed: semantic lineage validation runs before scope validation, so a foreign
snapshot can produce a generic semantic-lineage error and fail the existing
snapshot regression. Summary cardinalities use Python numeric equality, which
also accepts booleans/floats. Member collection validation reaches `set()` before
rejecting malformed or nonstring values. Host-frame counts do not independently
prove their association with a hosted opening.

Proposed: explicit document/revision/snapshot/SHA lineage errors; exact integer
cardinalities; typed unique string member inventories; exact frame-to-hosted
opening association and source provenance checks. Preserve incomplete semantic
universe facts as observed negatives and never allow a count/host/quantity.
Malformed, substituted and foreign receipts must fail closed without mutation.
No producer, source geometry, frozen truth or commercial publisher changes.
