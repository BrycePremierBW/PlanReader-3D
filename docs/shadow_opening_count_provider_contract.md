# Opening-count shadow provider contract

Family status: **frozen at `NEW_SHADOW`**.

Do not activate `NEW_SELECTIVE` or `NEW_AUTHORITATIVE` from this note. Legacy
remains authoritative for door/window counts. The frozen development gate
passed; coverage is still incomplete and several eligible items are
evidence-limited. Authority is a separate decision.

Canonical gate: `pb_shadow_opening_count_gate.py` (`OPENING_COUNT_MIGRATION_GATE`).
Provider: `pb_shadow_opening_count_provider.py` (`ShadowOpeningCountProvider`).
Evidence helpers: `pb_shadow_opening_evidence.py`.
Evaluator (gold only after freeze): `pb_shadow_opening_count_eval.py`.

## Reproduce the development shadow report

```bash
PYTHONPATH=. python3 scripts/run_shadow_opening_count_report.py \
  --output shadow_reports/opening_count_shadow_development.json
```

Regression suite (does not rewrite benchmark scores):

```bash
PYTHONPATH=. python3 -m pytest \
  tests/test_shadow_opening_count_gate.py \
  tests/test_shadow_opening_count_provider.py \
  tests/test_shadow_opening_count_eval.py \
  tests/test_shadow_opening_count_evidence.py \
  tests/test_shadow_opening_count_handoff.py
```

## Inputs

- Source PDF path.
- Optional 0-based `pages`.
- Optional injected OCR lines for tests (`ocr_lines_by_page`).
- Optional raster OCR toggle/DPI (shadow-only Tesseract via
  `DrawingOCREngine(custom_ocr_func=...)`; the default engine used by legacy
  is unchanged).

The provider does not accept benchmark IDs, expected quantities, mappings,
tolerances, or holdout identifiers.

## Outputs

`OpeningCountBundle`:

- `quantities`: `QuantityEvidence` type counts (`window_count`, `door_count`,
  `opening_count`) plus optional `door_total` / `window_total` aggregates.
- `entity_evidence`: type-level candidates; plan-tag instance candidates are
  not takeoff-authoritative.
- `canonical_openings`: type-level records only (`takeoff_eligible=False`,
  `spatially_reconstructed=False`).
- `conflicts`, `ambiguous_marks`, `duplicate_observations`, `diagnostics`.

Answered counts use unit `ea`. Abstained records have `value=None` and
blocking reasons. Diagnostics always set `authoritative=False`,
`authority_state=new_shadow`, `gold_consulted=False`.

## Supported authority classes

| Output authority | Meaning |
|---|---|
| `schedule_extracted` | Type count from an opening schedule / card, optionally corroborated by plan tags |
| `provisional` | Plan-tag type count only |
| `blocked` | Abstained; not an answer |

Formulas: `explicit_schedule_count`, `schedule_plan_corroborated`,
`plan_tag_count`, `sum_of_authoritative_type_counts`.

Elevation-only observations are not a type-total authority class.

## Abstention reasons

- `duplicate_schedule_conflict`
- `conflicting_dimensions`
- `schedule_vs_plan_count_mismatch` / other F.12 `conflict_manual_review` types
- `missing_quantity`
- `missing_identity_evidence`
- `supporting_view_only` (elevation/section appearance without plan or schedule)
- `ambiguous_opening_identity` (WD without F.28 window proof; OCR `DI`/`WI`/`WDI`)

Bill/BOQ/NRM/work-section pages are skipped rather than answered as zero.

## Cross-view semantics

Ownership is document → page → viewport → evidence. View type is retained.

- Schedule mark: type-definition evidence.
- Plan mark: physical-instance candidate evidence.
- Elevation/detail mark: supporting/appearance evidence.

These are not three openings. Schedule Qty 4 + four plan marks + two elevation
labels remains **4**, not 10. Duplicate detail/elevation sheets do not inflate
the type count.

## Aggregation semantics

If two or more authoritative type counts exist in one family:

`door_total` / `window_total` = sum of those type counts

The aggregate keeps source quantity and evidence IDs. It is not a gold key
(`steel_casement_windows`, `doors_complete` are never emitted). Evaluators
must exclude family totals from coverage, precision, hallucinations, and
legacy/new agreement.

## Known evidence limitations

Do not chase these with project-specific mappings or looser identity rules:

- **KSTVET**: drawings with casement sizes; no independently defensible W/D type marks.
- **Murera**: raster/partial schedules; gold asks for aggregates that cannot be mapped generically.
- **Ghazi**: figured dimensions only. Dimensions may support geometry, not D1/W1 identity.
- **Lamu**: no reliable D1 identity.

A 100% precision / 62.5% coverage shadow family is the intended stop.

## Frozen gate result (development, 24 eligible items)

- Answered: 15 (Umma D1–D12, WD1–WD3)
- Coverage: 62.5% (reported; **not** a gate input)
- Precision on answered identities: 100%
- Exact correctness among answered: 100%
- Recall: 62.5%
- Hallucinations / conflicts / duplicates / fake dimension identities: 0
- Provenance: complete
- Legacy/new agreement on answered type keys: 15/15
- Gate: **PASS**
- Recommendation: **remain NEW_SHADOW**
- Legacy headline (authoritative): **24 / 61 = 39.34%** (unchanged)

## Why authority must remain NEW_SHADOW

The gate measures precision and exactness **among answered items**. Nine
eligible items remain unanswered because the drawings do not supply a general,
independently defensible identity. Promoting the family would put incomplete
shadow coverage into production while legacy still answers the commercial
headline. Coverage was never a gate requirement and must not be used to
justify `NEW_SELECTIVE`.
