# AGENTS.md — permanent rules for AI work in PlanReader-3D

This file is the contract every AI session (Claude, Cursor, or otherwise)
must follow in this repository. It does not depend on any session
remembering a prior conversation. Read this file, `docs/AI_ENGINEERING_PLAYBOOK.md`,
and the task-specific brief you were given, before proposing or changing
code.

## The governing target

≥99.0% of measurable takeoff items within ±5% of independently verified
ground truth, on a **frozen, unseen** project-level holdout. This requires
generalization from real drawing evidence — not memorization of the
development benchmark's own expected values.

## Non-negotiable rules

- Detection is not measurement authority. A plausible value is not an
  authoritative value.
- Preserve document, source-hash, revision, page, viewport, entity, and
  evidence ownership through every stage.
- Reuse `EvidenceResolutionStatus`, `QuantityEvidence`, `stable_contract_id`,
  and existing authority modules. Do not introduce a second scale resolver,
  evidence vocabulary, quantity schema, or canonical graph.
- Unknown, conflicting, stale, or ambiguous evidence must abstain. Retain
  all plausible candidates; never resolve ties using nearest, first, or
  smallest.
- Never use filenames, project names, benchmark IDs, or expected BOQ values
  as prediction inputs, thresholds, or tuning targets. No magic correction
  multipliers. No symmetry assumptions. No "looks approximately right"
  quantities.
- Never change production code and benchmark-defining files (gold values,
  tolerances, scoring) in the same PR.
- Do not give AI output, defaults, title-block scale text, a geometric gap
  width, or an empty detector result firm authority on its own.
- New topology and extraction work begins in **shadow mode** (research,
  diagnostic-only, not wired into the live extraction path or commercial
  publishing) until a separate authority-promotion review approves wiring
  it in. Do not modify commercial output in the same change that introduces
  the capability.
- Never weaken an existing safe abstention to raise coverage or score.

## Independence of evidence

A signal only counts as corroborating another if it comes from genuinely
different structural evidence:

- A room face built FROM a wall candidate's own geometry does not
  independently corroborate that same candidate.
- A candidate merely touching (one-hop connectivity to) an already-evidenced
  neighbour is not itself evidenced by anything except contact.
- Candidate length is not proof of anything, in either direction: a short
  candidate is not weaker evidence, a long one is not stronger.
- Passing a broad plausibility band (a gap that could be a wall thickness)
  is not proof — a room-width pair, a glazing gap, and a real wall thickness
  can all fall inside the same generously-wide band.

## Git and PR discipline

- Work in an isolated worktree; the shared main checkout is read-only for
  verification.
- Never merge a research branch into `main` or into another feature branch
  without explicit instruction.
- Research PRs stay **draft**, titled `[Research, DO NOT MERGE] ...`, until
  explicitly promoted.
- Create new commits; do not amend published history unless asked.
- Never skip hooks or CI checks to force a merge.

## Required testing, for every geometric or evidentiary hypothesis

- Synthetic positive cases and synthetic look-alike negatives (the specific
  thing a naive version of the technique would wrongly accept).
- Ambiguity and conflict cases, with an explicit expected abstention.
- Translation, rotation, and scale metamorphic tests.
- Input-order and segment-splitting (re-chunking) invariance.
- Unrelated-content and viewport-expansion invariance.
- Deterministic replay and stable-ID checks.
- No-mutation checks (a reissue produces a new record; it never edits the
  input in place).
- Proof that live predictions and commercial quantities are unchanged while
  the work is in shadow mode.

Real development drawings may reveal a failure mode worth fixing, but the
benchmark's own expected quantities must never determine an algorithm or a
threshold.

## Distinguish these explicitly, in every report

- **Observed repository behaviour** (verified by reading the code or
  running it).
- **Inference** (a conclusion drawn from that behaviour).
- **Proposed change** (not yet made).
- **Benchmark observation** (context only — must not influence the
  algorithm or its thresholds).

## The trace-before-code habit

Before implementing anything touching wall, room, or opening geometry,
trace one real quantity end-to-end through the actual call path — file and
function references, not module names from memory. See
`docs/AI_ENGINEERING_PLAYBOOK.md` for the reference trace and the
architecture's own known gaps. A report that repeats documentation without
citing the functions actually involved has not done this step.

Stop for review after a research deliverable. Do not chain into wiring a
new capability into production without that review.
