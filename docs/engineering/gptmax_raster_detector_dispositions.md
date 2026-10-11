# Original raster detector source dispositions

Observed: `SourceVisibilityProducer.capture_raster_visible_segments` obtains an
immutable full-page render from `SourceObservationProducer.render_native_page_png`
at the existing `RASTER_RENDER_DPI`, then calls
`detect_axis_aligned_raster_segments`. The detector selects foreground, opens
horizontal/vertical masks, filters connected components, rounds/deduplicates,
performs three endpoint-snap passes, deduplicates again and applies its existing
minimum page-point length. Source visibility subsequently applies native image
region coverage and publishes source observations. W2/W4 and opening host
authority are later boundaries.

Inference: a pre-snap accepted component can still disappear or merge before
source observation publication. Its bounding box can intersect a sealed flank
without any of its actual mask pixels intersecting that flank. Neither fact
proves a missing physical host or permits transferring another flank's ancestry.

Proposed: a read-only CLI records actual original function inputs, returns and
snap-loop locals using a temporary thread-local Python trace. It keeps every
exact component parent when detector geometry coalesces, records losses and
reads exact component pixels for optional page-point query regions. The
observer refuses an existing trace, unknown producer loop structure, malformed
or over-limit inventories and any observed/unobserved detector disagreement.
It restores tracing on every exit. Producer functions remain unchanged; receipt
checks use their existing component/dedupe predicates and actual snap locals.
Original PDF SHA, immutable render scope and render
hash are retained. All publication/equivalence/completeness flags remain false.

Benchmark observations: the original Lot16 23/14/9 evidence is a retention
prerequisite, not an implementation input. No source filename, project identity,
opening count, expected quantity, frozen truth or scoring value sets a detector
threshold. The existing 20,000-primitive limit remains unchanged. Optional pixel
queries are observations of a render, not authenticated opening ownership.

Validation: synthetic polarity/empty inputs, component holes, retained and lost
snap passes, geometry coalescence, exact length boundaries, reversed input order,
translation/axis transpose, unknown/malformed input, trace restoration, original
producer output equality and original PDF/render SHA verification. Source
visibility's subsequent region-coverage filtering is explicitly outside this
detector diagnostic; output indices are detector addresses, not fabricated
source primitive or wall identities.

## Verified original Lot16 source observation

Original PDF SHA-256
`10109b4b6e85e6e27af81f6399ce4b92abfdba80f87dc69dd5887bd6f3a65844`, page 3,
144-DPI render SHA-256
`64e58ab817b1b89d3c83e0e04a972f5e4e48fa3816d346af9cc809b9b56357ab`.
The original producer output remains exactly 2,356 segments. All 2,830 component
receipts match the separately verified original component census: 40 components
fail pre-snap filtering; 434 accepted post-snap lines fail the original 4-point
minimum. The three snap passes record 836 endpoint changes and zero nonpositive
span removals on this page. These are detector-stage observations, not counts of
physical walls, missing openings or recoverable quantities.

The source query for opening `physical_opening_existence_f819752382d44a00d9f28feca4b00787`
uses its previously verified G17 left-flank render-space box
`[425.28, 247.68, 427.44, 252.48]`. Query coordinates were derived from the exact
PR #2260 source archive (ancestry JSON SHA-256
`b557a9061509f5a8058ea5d09bccc05f4a400534b062eef80e1a36572fecfb66`,
required-flank JSON SHA-256
`3100908d00529376c33b3b6daa08590d551370ba23af35640e724adb2cbab99f`).
They are a diagnostic request, not an authenticated opening-to-component edge.

The vertical original mask component has pixel box `[851,491,905,510]` and fails
the existing aspect predicate. Its 36 pixels in this query are also positive in
the original foreground mask. Complete contiguous column runs, preserving
endpoints beyond the query rather than clipping to it, include:

| Pixel endpoints | Render point endpoints |
| --- | --- |
| `(851,496)–(851,504)` | `(425.5,248)–(425.5,252)` |
| `(852,491)–(852,505)` | `(426,245.5)–(426,252.5)` |
| `(853,496)–(853,505)` | `(426.5,248)–(426.5,252.5)` |
| `(854,496)–(854,504)` | `(427,248)–(427,252)` |

In a read-only geometry experiment all four satisfy the unchanged existing
flank band/overlap/endpoint predicates. They are **pixel-run observations**, not
source primitive records, W2 edges, W4 identities, physical equivalence or host
proof. No candidate is selected. The first unresolved authority is now precise:
independently source-authenticated primitive nomination for this rejected
branched mask, followed by actual W2/W4 ownership and complete host-band proof.
The original source host/frame prerequisites remain 23/14/9; no host recovery or
benchmark improvement is claimed.

Morphology masks can contain pixels outside the original foreground. Pixel-run
receipts therefore require positive component pixels **and** positive original
foreground at every integer pixel center. Runs retain real holes and full
endpoints. They carry no source primitive ID and cannot publish a physical wall.
Native page rotation and display render coordinates are recorded separately.
