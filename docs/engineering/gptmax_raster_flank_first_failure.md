# Original raster flank ownership first-failure trace

## Observed repository behavior
Read AGENTS.md, docs/AI_ENGINEERING_PLAYBOOK.md, docs/wall_topology_observability_architecture.md, docs/planreader_wall_room_topology_spec.md, docs/planreader_public_tender_benchmarks.md and .github/workflows/ci.yml. Traced SourceVisibilityProducer.ingest_native_pdf_bytes -> compose_live_wall_opening_authority -> PhysicalWallCandidateAuthority.resolve_scope -> PhysicalOpeningAuthority.prove_existence -> _opening_geometry -> _authenticated_raster_source_lines -> _resolve_raster_source_band_host_from_records. Existing PhysicalWallSourceEdgeFragment.geometry retains W2 source edge geometry independently of WallCandidate.centerline_pts. source_snap_collapsed_fragments are observational negatives and are not surviving topology.

## Inference
A parent ID can survive while its local W2 fragment or its W4 chain misses the opening end. Source ancestry alone cannot tell these failures apart. Existing read-only PR #2260 reports parent and edge IDs; this independent diagnostic adds source geometry and endpoint evidence without changing that PR or production authority.

## Proposed changes and eight engineering tasks
1. Require complete, unique and same-source G17 support receipts before flank analysis.
2. Report exactly matched face/end flank geometry; ambiguous and malformed support abstains.
3. Report every original source primitive passing the existing flank endpoint, band and overlap predicates.
4. Trace each primitive to its actual W2 fragments, checking geometry and parent containment.
5. Report W2 and W4 endpoint positions separately, including displacement and remote fragments.
6. Expose duplicate/contradictory edge ownership without arbitrarily selecting an owner.
7. Keep snap-collapsed source fragments separate from surviving edges and host evidence.
8. Preserve every targeted original opening as an audited or abstained row with deterministic reasons, plus source parity and metamorphic regressions.

## Expected abstentions and authority boundaries
Missing/foreign/duplicate support, ambiguous face/end matching, bad numeric geometry, contradictory edge receipts, missing primitive owners and remote W4 segments remain unavailable. Diagnostic matches never prove SAME/DISTINCT physical equivalence, choose a host, complete an opening universe, or publish count/measurement/quantity. The script does not patch producer functions or mutate their results.

## Benchmark observations excluded from implementation
Original Lot16 page 3 SHA 10109b4b6e85e6e27af81f6399ce4b92abfdba80f87dc69dd5887bd6f3a65844 and 23/14/9 observations are verification gates only. No project/page/filename constants or expected BOQ values enter the audit algorithm. Frozen Full Plan V2 truth, evaluator, tolerances and the 20,000 primitive safety cap remain untouched.
