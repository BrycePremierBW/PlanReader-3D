# Original raster component rejection diagnostic

## Observed repository behavior

Read `AGENTS.md`, the AI engineering playbook, W1-W10 observability architecture,
topology specification, active benchmark boundary and CI workflow. Traced
`SourceVisibilityProducer.augment_with_raster_visible_segments` through the
immutable `SourceObservationProducer.render_native_page_png` seam to
`detect_axis_aligned_raster_segments`, `_component_segments`, intersection
snapping and source-visible publication. W2 accepts those exact published
primitives; G17 separately renders image-only opening primitives at 300 DPI.
Neither component detection nor a component bounding box proves a wall host.

The original Lot16 page-3 SHA is
`10109b4b6e85e6e27af81f6399ce4b92abfdba80f87dc69dd5887bd6f3a65844`.
Its original producer-owned 144-DPI render SHA is
`64e58ab817b1b89d3c83e0e04a972f5e4e48fa3816d346af9cc809b9b56357ab`.
An independent read-only replay reproduces all 2,356 raster detector segments,
including primitive 1597 at `(424.5,272.5)-(424.5,300)`. All seven failing G17
flanks lack qualifying raw-parent evidence in the 2,672 observed W2 inputs.
This is an observed input inventory, not complete physical-source coverage.

For the first failing left flank, an original vertical-mask component bounding
box `(425.5,245.5)-(452.5,255)` intersects the sealed band. Its 55-pixel width
and 20-pixel height fail the existing vertical aspect predicate. Bounding-box
intersection does not prove the component is that flank or a physical wall.
Several source regions combine linework into broad connected components; a
whole-component centerline cannot silently replace independently sealed bands.

## Inference

At least this observed rejection occurs before W2. Transferring primitive 1597's
removed W3 ancestry cannot establish the missing left-flank primitive. Source
component retention is needed to inspect extraction loss without loosening any
detector predicate or creating a new host relation.

## Proposed diagnostic

Observe the actual original detector's component masks and retain typed bounding
boxes, pixel dimensions and every failing existing pre-snap predicate. Call the
original component function unchanged and assert exact detector-output parity.
Render exclusively through the existing immutable producer seam with its
existing 144-DPI setting. Caller pixels, thresholds and inferred line segments
do not enter the original-source CLI. Every report has false host, quantity,
equivalence and source-universe-completeness permissions. Malformed receipts,
foreign source hashes and over-limit observational inventories fail closed.

Synthetic proof covers both orientations, aspect/length negatives, malformed
stats, translation, transposition, permutation, replay, unrelated components,
input immutability and unchanged detector output. An original SHA-pinned PDF
run validates render lineage and exact original detector parity. No production
file, source primitive publication, W2-W4 geometry, host authority, tolerance,
frozen V2 file or 20,000 primitive cap changes.

## Benchmark boundary

Source IDs and failure observations guide inspection only. Original segment
counts are source receipts, not physical walls, openings, metric quantities or
frozen V2 accuracy. No source count or expected BOQ value determines a predicate.

## Verified implementation and original-source replay

The observer calls the original `_component_segments` unchanged and independently
reruns the unobserved detector, rejecting any output difference. The original
SHA-pinned page yields 2,830 component receipts, including 40 rejected by existing
pre-snap predicates. Later snapping, deduplication and final minimum-length
checks remain independent; this is not a census of every detector disappearance.
The final original detector still emits exactly 2,356 segments. The 55-by-20
vertical component is retained as a rejected receipt at pixel box
`[851,491,905,510]`, with no ownership or host promotion.

Source report SHA-256:
`367c0beb8014db6da512b367ad6e46678b15369ccd0d35af28ce42e82fa7c1b6`.
Thirty-two focused regressions pass locally. The source-specific workflow pins
the exact PR head, verifies immutable source/render hashes and detector parity,
and retains the original report. Full CI and exact-head source jobs remain merge
gates. This diagnostic does not recover or publish any new host.
