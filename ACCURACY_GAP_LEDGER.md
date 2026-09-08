# PlanReader Accuracy Gap Ledger

This ledger records measured development-benchmark movements and rejected
accuracy candidates. It is engineering evidence, **not** proof of the final
>=99% target. KSTVET and Murera are development/diagnostic projects and can
never be represented as unseen holdout evidence.

## Measurement rules

- Never populate a measured result without an execution artifact or reproducible run.
- A rejected/regressing candidate remains visible rather than being rewritten away.
- Benchmark gold, mappings, tolerances, or denominators may not be changed to improve a candidate result.
- `null` / `NOT_RUN` means the current benchmark infrastructure did not measure that field.
- Final verified master accuracy remains `NOT_RUN` until a genuinely unseen frozen holdout exists and is scored under the master verification protocol.

## Current development headline

| Metric | Value |
|---|---:|
| Accepted within governing <=5% quantity criterion | 5 / 24 |
| Development accuracy | 20.83% |
| KSTVET | 4 / 13 = 30.77% |
| Murera | 1 / 11 = 9.09% |
| Coverage | NOT_RUN by current quantity benchmark |
| Abstentions | NOT_RUN by current quantity benchmark |
| Critical-error count | NOT_RUN by current quantity benchmark |
| Final unseen-holdout master accuracy | NOT_RUN |

## Gap entries

| Failure cluster | Frequency | Severity | Affected outputs | Suspected root cause | Generic fix / candidate | Measured before | Measured candidate/after | Confidence | Leakage risk | Status | Next action / evidence |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| F.13 raw dimension evidence / destructive anchor ambiguity | Initial candidate changed 3 KSTVET quantity outputs; 0 Murera | MAJOR | KSTVET floor finish and two internal wall-finish comparisons | A valid printed dimension row was discarded when dense vector linework made the graphical anchor ambiguous; downstream F.15 wall-thickness corroboration then disappeared | Preserve documented text constraints when vector anchoring is ambiguous/unsupported; use full witness binding only to add orientation/anchor authority | Main combined 5/24 = 20.83%; KSTVET 4/13; Murera 1/11 | Initial rejected candidate 4/24 = 16.67%; **post-fix candidate restored 5/24 = 20.83%, KSTVET 4/13, Murera 1/11, zero item deltas** | High | Low; generic authority separation plus synthetic mutation/metamorphic tests | RESOLVED IN F.13 CANDIDATE | Run 34241728461 exposed the regression. Post-fix run 34242384720 restored every compared item with unchanged hallucination/miss counts. Keep this regression test permanently. |
| F.22 compound footprint finish basis | 1 scored item crossed <=5% boundary | MODERATE | Internal floor finish | Enclosed finish area was measured on structural outer face while wall thickness was independently evidenced; open verandah required different measurement basis | Component-aware clear-face finish area while preserving structural bed footprint | Combined 4/24 = 16.67% | Combined 5/24 = 20.83%; KSTVET 23.08% -> 30.77%; Murera unchanged | High | Low; unchanged gold and same PDFs | MERGED | PR #206 / commit 774a61f. Preserve through F.13/F.07 work. |
| F.23A vertical datum authority | Quantity score unchanged; authority risk present | CRITICAL authority/safety risk | Wall height dependent wall/finish outputs | Missing/conflicting vertical evidence could inherit assumed default height; roof/floor datum conflicts could be collapsed | Fail closed on conflicting datums; expose provisional wall-height authority and demote confidence when height is assumed | Combined 5/24 = 20.83% | Combined 5/24 = 20.83%; zero quantity movements | High | Low | MERGED | PR #207 / commit 0d97b998. Remaining default-height behavior must remain visibly provisional until stronger evidence exists. |
| Final representative unseen holdout | 0 registered projects | CRITICAL verification gap | Entire final >=99% claim | No genuinely unseen frozen project-level holdout has been registered/scored | Acquire, seal, annotate and independently score representative holdout under frozen master metric | NOT_RUN | NOT_RUN | Certain | High if holdout identities/labels leak | OPEN | Do not claim VERIFIED >=99% from development benchmarks. |

## Required fields for future entries

Every new entry must preserve:

```text
failure cluster
frequency
severity
affected outputs
suspected root cause
generic fix
measured before/after effect
confidence
leakage risk
next action
execution evidence
coverage
abstentions
critical errors
project split
```

Fields absent from the evaluator remain `null` / `NOT_RUN`; they are never inferred from a quantity percentage.
