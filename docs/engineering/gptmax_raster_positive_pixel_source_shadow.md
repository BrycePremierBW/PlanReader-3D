# Producer-owned positive pixel-run source shadow

Observed: `SourceObservationProducer.ingest_native_pdf_bytes` fixes immutable
PDF bytes and page scope. `render_native_page_png` resolves its own page parent
and render frame. `publish_derived_observations` appends source-derived records
without changing an older snapshot. Its authority proves only
`SOURCE_OBSERVATION_EXISTS`. Normal raster visibility independently requires
`RasterSegmentVisibilityReceipt` in `SourceVisibilityAuthority.resolve_visible`.
`_foreground_mask` and `_component_segments` in the original raster detector
define foreground polarity and existing component rejection predicates.

Inference: complete original-positive pixel runs inside rejected components can
be independently source-receipted without claiming the component is a wall.
The detector's rejection remains an opposing observation. Pixel source
nomination cannot substitute for normal visible-segment, wall, physical
equivalence, host-band or opening authority.

Proposed: an isolated tool-owned producer ingests actual PDF bytes, runs the
unchanged polarity/morphology rules over its own full-page render and records
every sufficiently long contiguous positive row/column in pre-snap rejected
components. Every pixel must belong to both the component and the original
foreground. Endpoints remain complete; no query, opening or benchmark geometry
controls nomination. A separate versioned source kind and geometry-addressed
reference avoid changing ordinary raster v1 indices. The read-only query side
requires actual source records, factory-owned receipts, native page lineage,
render replay and complete run membership. Nonzero page rotation is abstained
until a separate coordinate-transform proof exists. The existing 20,000-source
limit applies before any derived batch is published; no truncation is allowed.

The isolated W2/W3/W4 replay uses existing graph and candidate functions only.
Its candidate owners are experimental and cannot publish physical hosts or
quantities. All competing runs and graph ancestry remain visible. Ordinary
SourceVisibilityProducer extraction and all customer writers remain unchanged.

Benchmark observations: original Lot16 source observations 23/14/9 and the
first missing flank's pixels are retention/source checks only. No project,
filename, opening box, expected quantity, frozen denominator, gold or tolerance
sets nomination rules. Full Plan V2 and its 20,000-source cap are unchanged.

Validation: original-source hashes and replay; synthetic branched components,
holes, morphology-added pixels, complete endpoints, translation/transpose,
polarity, deterministic IDs, source/parent/receipt substitution, stale/foreign
scope, nonzero rotation, atomic cap failure, original-reader abstention and
unchanged default source extraction. Architecture review proceeds under the
user's explicit autonomous engineering instruction; no commercial promotion
is included.

## Verified original source and remaining authority gate

PDF SHA `10109b4b6e85e6e27af81f6399ce4b92abfdba80f87dc69dd5887bd6f3a65844`,
page 3, 144-DPI render SHA
`64e58ab817b1b89d3c83e0e04a972f5e4e48fa3816d346af9cc809b9b56357ab`.
The full-page rule authenticates 1,952 source-pixel nominations. The isolated
replay also retains 4,083 ordinary visible source records: 6,035 total inputs,
10,288 surviving W2 edges and 4,038 experimental W4 candidates. These are
source/algorithm records, not physical wall or opening quantities. Full-page
replay differs from the existing authenticated viewport pipeline and has no
floor-plan viewport authority. Normal source records and their snapshot remain
unchanged. Every W2 parent, W3-removed edge and snap-collapsed parent is retained;
the compact ledger stores each collapsed fragment once and references its ID
from every parent. No first or nearest run is selected.

For the previously observed first unresolved left flank, independently
nominated runs include the following. Opening geometry did not control their
nomination; this table is a subsequent comparison with existing source evidence.

| Full pixel endpoints | Independent pixel source observation | Experimental W2 edges | Experimental W4 candidate |
| --- | --- | --- | --- |
| `(851,496)-(851,504)` | `source_observation_3ec284f184db53c5d720454c1a4ad177` | `split_10222` | `wall_ff0035842ff75f2870f6` |
| `(852,491)-(852,505)` | `source_observation_acfe0b16d439a4b1f12835d27fe84fd2` | `split_26933`, `split_26934` | unavailable |
| `(853,496)-(853,505)` | `source_observation_50dffd89614cb11c8c1e58abadda6091` | `split_12792` | unavailable |
| `(854,496)-(854,504)` | `source_observation_c9559d16c418ca620392628caf63671d` | `split_30987` | unavailable |

The latter two source parents also retain snap-collapsed fragments. A surviving
experimental candidate does not identify a physical host. The next unresolved
gate is structural/visible-line authority for the source nomination, followed
by authenticated viewport W2/W4 membership, physical equivalence and complete
host-band proof. The normal visibility reader rejects this independent shadow
kind. No production opening or host is changed.

Validation: 65 dedicated regressions and 495 combined ownership, visibility,
lineage, W2/W4 and flank regressions pass locally. The exact compact original
report SHA is `a078f369abdbb3a2428750f1e0989094d21c13717e99a7341501bb44dd5de289`.
The actual independent original-source host/frame extraction remains
byte-identical to SHA `e8d04e46648b7db5d0c3872dc5bb170158b4557be98e8508492ed85b6ebe7c53`
(23/14/9), with zero missing, lost, changed or added proofs. Provider isolation,
frozen V2 integrity, truth separation, Ruff and exact embedded source CI checks
pass. Required exact-head Python 3.13/3.14 full/focused CI and original-source
artifact review remain mandatory before merge.

The existing single-row schedule identity regression in issue #2264 still
reproduces on current main production code under local Python 3.12; no full
local suite pass or identity-authority relaxation is claimed.
