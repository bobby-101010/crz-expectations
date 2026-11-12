# 0011: Scoring rules the spec left open

Status: accepted (Phase 3, 2026-11-12). Approved by the owner in the Phase 3 plan.

## Context

Spec section 7.6 defines three comparisons and five verdicts in an order of precedence. Building the scoring job needed four details it does not state.

## Decision

- **"Latest loaded date"** is the latest date in the gold table a metric reads. For a ratio metric it is the earlier of its two parts. An entry is `pending` while its window ends after that date.
- **`data_issue` uses lineage, not service.** Each gold table has a fixed list of check targets it is built from (`LINEAGE` in `src/pipeline/scoring.py`). A check counts if its most recent result for that check, table and partition is `fail`, and the partition's dates overlap the entry's window or comparison window. A partition such as `yellow/2025-01` covers that month, `fhvhv/2025` that year, and `all` everything. The service in the partition is not compared with the entry's filters, so a failed ride-hail month also blocks a yellow-only entry.
- **A day with no baseline** is left out of the `within_baseline` count, and the verdict's note says how many days were left out. Both ends of the band count as inside.
- **No data in a window that is not pending** gives `data_issue` with a note, since the spec has no verdict for it.
- **`value_range` on a sum metric** divides the window total by the number of calendar days in the window.

The append-only rule also freezes `confidence`, with the fields the spec lists, because the registry's own header says so and the calibration score depends on it. Entries are compared as written, so adding an explicit value where a default applied counts as a change.

## Alternatives

- Matching a failing check's service to the entry's filters: fewer blocked verdicts, but it needs every check to declare which slices it covers.
- Counting a day with no baseline as outside the band: simpler, but it would turn a missing baseline into evidence against the expectation.

## Consequences

- A `warn` never blocks scoring. Only a `fail` does. Today no check fails, and the one warning (`cbd_zone_membership`, decision 0008) does not affect verdicts.
- A later passing result for the same check and partition clears the `data_issue`.

## First scoring run (2026-11-12, registry commit `3548f36`)

1 `not_scoreable`, 7 `pending`, 5 `held`. No new MTA or TLC data had been published, so every prospective entry is pending.

| Entry | Observed | Expected | Verdict |
| --- | --- | --- | --- |
| `derived-cbd-touch-trips-first-year` | +1.72% | -2.5 to +4.0 | held |
| `retrospective-fhvhv-per-yellow-first-year` | 4.99 | 4.93 to 5.07 | held |
| `retrospective-reproduce-mta-table-3-2-total` | +0.79% | +0.3 to +1.4 (target +0.82) | held |
| `retrospective-reproduce-mta-table-3-2-yellow` | +16.71% | +15.9 to +17.9 (target +16.87) | held |
| `retrospective-reproduce-mta-table-3-2-fhvhv` | -4.86% | -5.6 to -4.2 (target -4.86) | held |

The three reproduction entries are the pipeline's check against a published figure. All three land within 0.2 points of the MTA's Table 3-2 targets.
