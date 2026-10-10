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
