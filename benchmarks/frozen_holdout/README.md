# Frozen Holdout Suite

This directory holds genuinely unseen Plan+BOQ projects used only for the
**final, verified 99% accuracy measurement** — never for development,
diagnosis, or tuning.

## The rule

While implementing or tuning any extraction logic (`pb_*.py`), **never
open `expected_boq_summary.json` for any project under this directory.**
That file is the ground-truth answer key; reading it while writing
extraction code — even "just to understand the failure" — is exactly the
backward-solving this suite exists to prevent. If a failure needs to be
understood, use a **development** project instead
(`benchmarks/public_tenders/`), which exists for precisely that purpose.

`KSTVET` (`tenders_ke_kstvet_cbc_classroom`) and `Murera`
(`tenders_ke_murera_science_lab`) are development/diagnostic projects,
not holdout evidence — their expected quantities have already been
inspected in this codebase's history and must never be presented as
unseen holdout results.

## Directory schema

Each registered project is a subdirectory named by its `benchmark_id`,
containing the same four files as a development project under
`benchmarks/public_tenders/`:

- `source_manifest.json` — where the PDF/BOQ came from, retrieval date,
  verification notes.
- `benchmark_rules.json` — tolerances, item-tag mappings, comparison
  rules.
- `expected_project.json` — non-secret project identity facts (name,
  location, building dimensions) used for identity matching.
- `expected_boq_summary.json` — the ground-truth answer key. **Never
  read this while developing.**

Source PDFs themselves are not committed to the repository; they are
referenced by filename in `source_manifest.json` and kept alongside the
benchmark tooling's existing local file conventions.

## Registering a project

Use `pb_holdout_suite_registry.register_holdout_project()`:

```python
from pathlib import Path
from pb_holdout_suite_registry import register_holdout_project

record = register_holdout_project(
    Path("benchmarks/frozen_holdout/some_new_project"),
    development_project_dirs=[
        Path("benchmarks/public_tenders/tenders_ke_kstvet_cbc_classroom"),
        Path("benchmarks/public_tenders/tenders_ke_murera_science_lab"),
    ],
)
```

This validates the four required files are present and parse as JSON,
rejects the project if its identity (`project_name` / `project_number` /
`client`) collides with a known development project, and writes a
`.holdout_lock.json` recording a SHA-256 checksum of the ground-truth
answer file. Registration is a one-time administrative step — it may
require reading the real BOQ to populate `expected_boq_summary.json` in
the first place, which is legitimate; the discipline is about not
reading it *during extraction development*, not about it never being
created.

## Verifying nothing was edited after registration

```python
from pb_holdout_suite_registry import verify_holdout_untouched

result = verify_holdout_untouched(Path("benchmarks/frozen_holdout/some_new_project"))
assert result.is_untouched, result.mismatches
```

This recomputes the checksum and compares it to what was recorded at
registration — a concrete, technical proof that the ground truth was not
quietly edited later (e.g. to "improve" a score), not just a matter of
trusting unaided discipline.

## Status

No projects are registered yet. This suite currently has **zero**
holdout projects; the final 99% claim cannot be validated until real,
verified Plan+BOQ projects are supplied and registered here.
