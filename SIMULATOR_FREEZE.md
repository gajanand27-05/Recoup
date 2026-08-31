# SIMULATOR FREEZE

The simulator was frozen **before the agent was written**. This file, the git tag,
and `verify-sim` in CI are what make that a checkable claim rather than an assertion.

| | |
|---|---|
| `sha256(simulator/)` | `a45ffdec3b83fab5dd7ec452a23b5d1e22565002c08d7c0b070a5f765f6eaee5` |
| Frozen at (UTC) | 2026-08-31T01:17:24.467595Z |
| Commit | `e8cc9097a7ea0e8a5f7ec1d3e283f2784f28f190` |
| Tag | `sim-freeze-v1` |
| Parameters locked | 17 |

The hash covers every file in `src/recoup/simulator/` **including `PARAMS.md`**, with
line endings normalised so a CRLF checkout does not read as tampering. `freeze.py`
itself is excluded, because a file cannot hash its own output.

## Verify it yourself

```bash
python tasks.py verify-sim     # recomputes the hash, fails on drift    (make verify-sim in CI)
git show sim-freeze-v1         # tag date precedes every commit in src/recoup/agent/
git log --oneline --diff-filter=A -- src/recoup/agent/ | tail -1
```

The third command is the one that matters. `--diff-filter=A` finds the commit that
*added* each file, so it is not fooled by a file that was later deleted.

## What is frozen

**4 MEASURED** parameters, each with a URL and a stated population.
**10 ASSUMPTION** parameters — not sourced, and swept in the
sensitivity analysis rather than presented as findings:

| Parameter | Swept over |
|---|---|
| `amount_distribution` | [29900, 499900] |
| `amount_weights` | [0.0, 1.0] |
| `attempt_decay_compounding` | [0.0, 1.0] |
| `channel_multiplier_sms` | [0.07, 1.5] |
| `channel_multiplier_whatsapp` | [0.5, 1.5] |
| `decay_beyond_curve` | [0.9, 1.0] |
| `hard_decline_multiplier` | [0.3, 1.0] |
| `residual_hard_fraction` | [0.0, 0.3] |
| `self_recovery_rate_hard` | [0.0, 0.1] |
| `self_recovery_rate_soft` | [0.05, 0.35] |

Full provenance, including the figures that were located and deliberately rejected,
is in `src/recoup/simulator/PARAMS.md`.
