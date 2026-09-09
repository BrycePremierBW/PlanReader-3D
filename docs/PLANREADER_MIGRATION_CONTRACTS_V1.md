# PlanReader Migration Contracts v1

This document defines the compatibility boundary for migrating PlanReader from the current legacy extractor into a shared evidence -> physical graph -> deterministic quantity architecture.

The migration is deliberately score-neutral at this stage. These contracts do not change production extraction, benchmark rules, tolerances, expected quantities, or commercial authority.

## Data flow

```text
source PDF/image set
        |
        v
DocumentEvidence + EvidenceAtom
        |
        v
ViewportEvidence
        |
        v
EntityEvidence
        |
        v
existing canonical building model
        |
        v
QuantityEvidence
        |
        +--------------------+
        |                    |
        v                    v
production adapter      benchmark adapter
TakeoffOutputRow        ExtractedPrediction
```

`ExtractedPrediction` remains a compatibility/output shape. It is not the new internal system of record.

## Contract ownership

### DocumentEvidence

Owns immutable source identity:

- SHA-256 of the exact input source;
- document/page identity;
- evidence references;
- producer/version metadata.

Large text/vector/raster payloads may be stored as separate content-addressed artifacts. The document contract references them rather than requiring one monolithic JSON file.

### EvidenceAtom

Represents one raw observation such as:

- a native figured dimension;
- an OCR text span;
- a vector line candidate;
- a schedule cell;
- a scale observation;
- a finish note.

It is evidence, not yet a physical wall/room/opening.

### ViewportEvidence

Owns page-local spatial context:

- viewport bounds;
- view type;
- viewport resolution state;
- evidence ownership;
- scale evidence and the resolved scale reference where permitted.

Ambiguous or unsupported viewports cannot claim a resolved scale through this contract.

### EntityEvidence

Bundles evidence about one candidate physical object before it is committed to the canonical building graph. Conflicting evidence remains explicit and cannot be labelled corroborated while unresolved conflicts remain.

### QuantityEvidence

Represents a deterministic quantity result and its complete trace:

- quantity family and semantic key;
- numeric value/unit or explicit abstention;
- source entity/evidence IDs;
- deterministic formula/version;
- authority/status/confidence;
- blocking reasons and reason codes.

A non-abstained quantity must have source traceability. An abstained quantity must not carry a numeric value and must explain why it abstained.

## Shadow-mode boundary

The migration authority vocabulary is fixed in `MigrationAuthorityState`:

1. `legacy_authoritative`
2. `new_shadow`
3. `new_selective`
4. `new_authoritative`
5. `legacy_retired`

The new engine must first operate in shadow. Its result is compared to the legacy result with `ShadowQuantityComparison`.

The shadow comparison contract deliberately has no expected/gold field. Development benchmark expected quantities may be joined only by the evaluator after legacy and new outputs have been frozen.

## Anti-leakage boundary

Production evidence/graph/quantity code must not depend on benchmark IDs, expected BOQ quantities, benchmark item mappings, benchmark-result artifacts, or holdout gold.

Benchmark-specific mapping belongs in the evaluator only.

Future CI should run the extraction dependency closure without a mounted `benchmarks/` directory in addition to source-code leakage checks.

## Compatibility rules

During migration:

- current production behavior remains authoritative unless a quantity family explicitly advances state;
- the canonical building schema remains the physical graph foundation;
- existing scale authority, opening safety, geometry services, schedule parsing, and takeoff authority should be adapted rather than rewritten;
- family migrations are independent so one family can roll back without reverting the whole engine;
- no migration gate may be changed after viewing the score it governs.

## Next implementation steps

The next changes after this contract are:

1. legacy extractor adapter with byte-for-byte parity;
2. gold-free shadow runner and frozen artifacts;
3. QuantityEvidence -> ExtractedPrediction benchmark adapter;
4. QuantityEvidence -> commercial takeoff output adapter;
5. Cursor viewport/evidence bridge into these contracts;
6. canonical graph evidence fusion;
7. first selective authority migration for explicit schedule/count families.
