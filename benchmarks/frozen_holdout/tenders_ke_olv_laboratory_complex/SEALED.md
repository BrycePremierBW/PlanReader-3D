# SEALED — pending final transcription

This project is deliberately registered with only `source_manifest.json`
present. It has **no** `benchmark_rules.json` or `expected_boq_summary.json`
yet, and therefore no `.holdout_lock.json` — `list_registered_holdout_projects()`
silently excludes any directory without a lock file, so this project does
not participate in any scoring or verification run until it is completed.

**Do not** open the source PDF's Bill of Quantities pages (approx. 2-241)
to transcribe expected quantities as part of routine development. That
transcription is a one-time act reserved for whoever actually performs the
final master-accuracy verification — not before, and not as a side effect
of investigating an unrelated accuracy gap.

What has already been inspected and is safe (not gold data):
- The table of contents (page 3): section/bill *names*, not quantities.
- The architectural drawing sheets (pages 242-245): used only to confirm
  the package is genuine (native-vector, real title block, drawing/BOQ
  project-identity match) and to assess building type/complexity for
  diversity purposes.

To complete registration when a real final-verification run is being
performed:
1. Transcribe a representative set of measurable BOQ items from the real
   Bills of Quantities (pages ~2-241) into `expected_boq_summary.json`,
   following the schema used by `benchmarks/public_tenders/*/expected_boq_summary.json`.
2. Write `benchmark_rules.json` with `item_mappings` to the extractor's
   real tag names.
3. Call `pb_holdout_suite_registry.register_holdout_project()` to hash-lock
   all four files.
4. From that point on, `verify_holdout_untouched()` will detect any edit.
