# GPT MAX — Lot16 original raster source → W4 ancestry audit

This tool probes the precise gap behind **seven** source-reported Lot16
raster-opening failures, without creating a physical wall, host, source
completeness claim, opening count or commercial quantity. It uses unchanged
producers, not inferred geometry.

## Authority chain

Original PDF SHA-256
`10109b4b6e85e6e27af81f6399ce4b92abfdba80f87dc69dd5887bd6f3a65844`
→ `SourceVisibilityProducer.ingest_native_pdf_bytes`
→ `compose_live_wall_opening_authority`
→ `PhysicalWallCandidateAuthority.resolve_scope`
→ `PhysicalOpeningAuthority.prove_existence`
→ `_opening_geometry`
→ `_authenticated_raster_source_lines`
→ `nonpublishing_raster_source_w4_membership`.

Only opening existences with a source-production reason mentioning
`raster_source_band_` and no host are audited. The original source G17
support-observation IDs remain in each report entry. Producer-produced exact
visible raster primitive IDs are matched to W4 `physical_identity`
`source_primitive_ids`; each parallel/local-band primitive carries *all*
existing W4 ancestry candidate IDs.

**Deliberately missing authority:** an original source primitive ID appearing
in a W4 identity does NOT show that any W4 chain reaches an authenticated
opening flank end. The same long raster source primitive can parent remote W2
fragments. The diagnostic therefore never chooses a candidate, assigns a
host, collapses identities, overrides AMBIGUOUS equivalence, or reports an
opening as measured. The list includes both genuinely orphaned source lines
and source lines with positive W4 ancestry; neither case by itself solves
the local host relation.

## Original baseline

The archive for the original page 3 source recorded 23 physical openings,
14 authenticated host bindings and 9 original host frames, without proof of
a complete 27-denominator benchmark object universe. The seven first
`raster_source_band_*_source_primitive_unmapped` cases consist of six
left-source and one right-source failure, while the other two original
unhosted openings report no authenticated wall band. The tool targets the
seven and does not silently classify the other two as source prim failures.

### Run after obtaining the original source drawing

```bash
PYTHONPATH=. python -u tools/diag_gptmax_raster_host_source_membership.py \
  --pdf "documents/sources/1. Construction Plans - Lot 16 Power (REV E).pdf" \
  --page-id 3 \
  --expected-source-sha 10109b4b6e85e6e27af81f6399ce4b92abfdba80f87dc69dd5887bd6f3a65844 \
  --output lot16-raster-source-w4-membership.json
```

The SHA-pinned independent CI run asserts the original 23/14/9 source
receipts and seven missing primitive-side bindings are unchanged. Python
3.13 and 3.14 focused tests enforce zero publication even when a source
primitive has several W4 ancestry candidates, no candidates, bad geometry
or no local source witnesses.

**Engineering next gate:** inspect whether each missing physical flank
has an original source raster primitive in the producer's authenticated
visible segment universe; then trace that exact primitive through W2
filtering, splitting and snapping to W4 `source_edge_fragments`. Only after
an exact segment owner and local source-band endpoint agree, and upstream
physical equivalence is resolved, may the existing host authority consider
promoting a real binding. Keep the 20,000 source primitive safety limit.

Frozen V2 manifests, object universe, reference takeoff, scoring and
tolerances are untouched. No numerical accuracy improvement is asserted.
# Continuation design, 2026-10-11

Observed: `nonpublishing_raster_source_w4_membership` projects the authenticated
raw parent line but lists W2 edge IDs without their retained geometry. A long
parent can own remote fragments, and collapsed fragments are not surviving W2
edges. The helper also unions repeated W4 addresses before detecting conflicts.

Inference: these omissions obscure the first failing ownership stage. Parent
membership alone cannot decide local contact or physical equivalence.

Proposed: validate the aperture coordinate frame and finite derived projections;
quarantine repeated W4 addresses and contradictory shared W2 edge receipts;
retain each actual edge's source geometry, local axis interval and separately
observed aperture-end distances; enumerate source snap-loss fragments separately
with no surviving-edge status. Keep all alternatives and all publication flags
false. Test remote same-parent fragments, conflicting addresses, overflow,
rotation/replay, and collapsed-only parent evidence. Original PDF runs must
retain exact opening/host/frame receipts. Source observations and benchmark
counts do not determine algorithms, constants, IDs or owner selection.

## W2 to W3 source ancestry disappearance trace

Original-source observation on current main `83bd81f`: local raster primitive
`...:1597` at `(424.5, 272.5)–(424.5, 300)` survives both source filters and
parents actual W2 edges `split_3305` and `merged_split_1530_split_3306`. Neither
edge appears in the retained W4 records. The W3/W4 caller applies
`deduplicate_coincident_edges`, whose association criterion is the snapped
node pair, and removes alternate edges without a parent-receipt sidecar.

Design: observe the unmodified actual W2 graph during the original diagnostic
composition; replay that existing read-only deduplication helper and record
each removed edge alongside the surviving edge sharing its node pair. Retain
both original edge geometries, snapped endpoints and separate source parents.
Return the original graph object to production. A shared snapped node pair
does not authenticate physical sameness, a wall host, source continuity or a
missing flank. Do not union the removed parent's lineage into W4 authority.
Regression tests must cover offset raw lines sharing snapped nodes, reversed
edge direction, input immutability and malformed/duplicate source addresses.
Fresh original-source receipt retention remains mandatory.

## Next receipt-completeness tasks, 2026-10-11

**Observed:** `original_raster_host_ancestry_census` retains G17 support IDs but
not their sealed face/end geometry. Its W2 observer records only removed-edge
associations, omits graph source scope and surviving-edge inventories, and can
coerce malformed lineage containers or boolean coordinates. The W4 ancestry
reader normalizes duplicated edge-parent lists with `set()`. Authentication of
the same page-visible line universe repeats for each opening. The real host
resolver `_resolve_raster_source_band_host_from_records` requires exact G17
solid flanks and ends, then exact source parents, local W4 chain contact and
resolved physical equivalence; the current diagnostic cannot replace these.

**Inference:** absence from a W4 identity alone cannot distinguish a removed
W2 edge, a source parent retained elsewhere, a missing W4 edge owner or a
sealed flank not supported by any authenticated raw line. Snapped-node aliases
cannot be used as a new host relation.

**Eight proposed tasks:** validate W2 graph/lineage schema without coercion;
reject duplicated/malformed W4 edge and snap-loss parent inventories; retain
exact input source scope in each actual W2 observation; retain all surviving
and removed W2 source receipts and their actual W4 edge-owner alternatives;
resolve and retain exact G17 support face/end receipts; retain finite signed
support projections without manufacturing contact; distinguish removed-parent
ancestry from independently retained ancestry; reuse authenticated raw line
inventories only under the complete immutable document/revision/SHA/snapshot/
page and source-observation key. Add adversarial, transformation, permutation
and no-mutation regressions. Original-source runs must retain every existing
opening/host/frame receipt. All additions remain read-only diagnostics.

**Benchmark boundary:** original source IDs and failure observations identify
what to inspect, never prediction rules or expected outcomes. No transfer of
removed ancestry into a W4 identity, physical SAME/DISTINCT decision, host,
opening count, quantity, safety-cap change or frozen truth edit is proposed.

## Implemented source receipt stages, 2026-10-11

The eight receipt tasks are implemented in the nonpublishing diagnostic.
The graph observer retains the actual input primitives, observation IDs and
geometry with the producer snapshot observed immediately before the W2 call.
The original graph object is returned to production. Every original W2 edge
retains its own source parents, original geometry and snapped endpoints;
W3-retained and removed edges remain separate. W4 edge alternatives require
exact sidecar geometry and parents for diagnostic membership. Conflicted edge
addresses and repeated candidate addresses are quarantined. Neither this
membership nor a common snapped-node pair proves a physical host.

Each G17 support is independently resolved by
`resolve_raster_opening_primitive`; its exact source scope, payload hash,
derivation parents and signed endpoint coordinates are retained. Failed or
foreign resolutions stay negative rows. Perpendicular ends and parallel faces
are projected without inventing a face pairing or local contact proposition.
Nonfinite input or derived geometry cannot serialize as positive evidence.

A removed edge does not imply loss of its parent when another surviving edge
retains that parent. Parent-stage receipts distinguish removed-only ancestry,
independently retained W3 ancestry, and actual usable W4 edge membership;
unknown parent inventories remain explicit. No removed source parent is
transferred into a surviving W4 identity.

Run-local source-line reuse is immutable and keyed by the exact authority,
document, revision, SHA, snapshot, page, viewport, observation IDs and
reauthenticated source payload manifest. Every warm lookup bulk-reauthenticates
the producer-owned snapshot first. Regression tests include actual producer
source-byte tampering and replaced source observations after a warm lookup.

Current-main `545688c6b147954783e430bd7679ef9d3f09ea4c` original Lot16 source
report SHA-256 is `e8d04e46648b7db5d0c3872dc5bb170158b4557be98e8508492ed85b6ebe7c53`.
Its fresh original page-3 source remains 23 opening existences, 14 hosts and
9 frames. The independently refreshed first-gate census remains six left and
one right unmapped raster primitive failures and two missing host-band proofs.
These are source-authority observations, not frozen V2 benchmark accuracy.

Validation: 139 ancestry regressions, including real producer-store negatives;
189 combined ancestry/receipt/W3 tests before the two added producer negatives;
523 focused regressions across all five PRs before those two additions. The
source workflow now checks complete G17/W2/W3/W4 receipt inventories and their
nonpublication boundaries in addition to strict original host/frame retention.
Exact-head Actions and fresh candidate source retention remain merge gates.

## Original-source support completeness correction

The first full receipt run preserved every original opening, host and frame
proof (zero lost or changed proofs). Artifact SHA-256:
`226237463a7b231bf1058e6b47ed50bb4dc7558f67c8d74ff439b09dca433b80`.
It retained 58 requested support observations for seven openings: 42 were
band faces/ends; supplementary producer-authenticated raster strokes had been
incorrectly labelled as source-scope mismatches. The reader now retains every
supported primitive kind authenticated by the existing G17 visibility reader,
and separately marks only faces/ends eligible as host-band support. Neither
supplementary strokes nor band support alone authenticate a wall host.

The original graph-time receipts show 2,672 input primitives, 3,049 W2 edges,
2,563 W3-retained edges and 486 removed edges. Of the observed source-parent
inventories, 341 occur only on removed edges. These graph observations establish
ancestry disappearance, not 341 physical walls or opening quantities.

Primitive `...:1597` is still removed on `split_3305` and
`merged_split_1530_split_3306`; neither has a usable W4 edge membership. For
opening `physical_opening_existence_f819752382d44a00d9f28feca4b00787`, its axis
span is `[19.78, 47.28]` relative to an aperture of length `23.76`, while the
left sealed flank spans `[-5.04, -0.24]`. Thus this aperture-local orphan is
not proof of the first failing left-flank source parent. Required-flank source
matching must precede any attempt to transfer ancestry or recover a host.

## Required-flank receipt reader and final source verification

`tools/diag_gptmax_required_flank_source.py` consumes the original diagnostic
JSON and applies the existing host reader's sealed-face interval/end matching
and raw-parent endpoint, overlap and cross-band predicates. It retains every
reported source-parent/W4 alternative. It never selects a host, authenticates
physical equivalence, proves source-universe completeness, or claims to
reauthenticate the PDF from JSON. Missing candidates mean only that no
qualifying primitive was observed in the reported local line inventory.
Regression tests cover opposite-flank orphans, several W4 alternatives, remote
and cross-band lines, foreign receipts, missing ends, input order, rotation,
reversed direction, duplicated addresses and publishing input reports.

The corrected fresh original run on live-main
`107764c` retains all 58 support receipts: 28 band faces, 14 band ends, ten
line runs and six thin-ink runs. Only the 42 faces/ends are eligible as band
support. All original 23/14/9 opening/host/frame proofs are unchanged, with
zero lost or changed proofs. The exact source-workflow assertions pass locally.

| Verified original artifact | SHA-256 |
| --- | --- |
| Independent current-main source baseline | `e8d04e46648b7db5d0c3872dc5bb170158b4557be98e8508492ed85b6ebe7c53` |
| Complete support / W2-W4 ancestry report | `b557a9061509f5a8058ea5d09bccc05f4a400534b062eef80e1a36572fecfb66` |
| Strict source-retention comparison | `bf79fca8c5ae4a0ed989ae86292a32faac5cb285f2f0211d2456b6e3aa14f553` |
| Required-flank report | `3100908d00529376c33b3b6daa08590d551370ba23af35640e724adb2cbab99f` |

The diagnostic raw-line and aperture readers also reject numeric strings,
booleans and non-sequence coordinate containers. A malformed reported face
cannot manufacture sealed-flank geometry, and a coercible raw line cannot
gain diagnostic flank membership. These are diagnostic-only typed negatives;
the producer geometry, host predicates and all tolerances are unchanged.

Final focused source-receipt, required-flank, producer-integrity, strict-retention
and W3 regressions: 216 passed. No host recovery or frozen V2 accuracy gain is
asserted. The semantic opening universe remains incomplete.
