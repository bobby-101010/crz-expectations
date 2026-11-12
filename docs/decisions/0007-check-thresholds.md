# 0007: Thresholds for the trip data checks

Status: proposed by Claude Code on 2026-11-11. Not in use until the owner approves.

## Context

Spec section 7.1 says thresholds come from the months already loaded, not from guesses. Each metric below was computed for all 88 service-months (yellow and ride-hail, 2023-01 to 2026-08) with `make check-profile`, which reads silver once and writes nothing.

| Metric | Service | Lowest | Median | 95th percentile | Highest |
| --- | --- | --- | --- | --- | --- |
| Rows against the median of the prior 6 months | yellow | 0.806 (2026-02) | 1.017 | 1.137 | 1.256 (2025-05) |
| | ride-hail | 0.952 (2023-08) | 1.005 | 1.077 | 1.119 (2025-12) |
| Share of rows read that were outside the month | yellow | 0.0000016 | 0.0000083 | 0.000020 | 0.000056 (2023-03) |
| | ride-hail | 0 | 0 | 0 | 0 |
| Highest null share among the four required columns | both | 0 | 0 | 0 | 0 |
| Share of trips that end before they start | yellow | 0 | 0.000019 | 0.00024 | 0.00034 (2025-11) |
| | ride-hail | 0 | 0 | 0.00037 | 0.00059 (2025-11) |

The volume ratio has 41 values per service, because the first three months have fewer than three prior months.

Two things the numbers show:

- **No required column has ever been null.** That is zero nulls in about 1.04 billion rows.
- **Trips that end before they start are a daylight-saving effect.** The three highest months for both services are the three Novembers. In November 2025, 12,204 of 12,204 such ride-hail trips and 1,431 of 1,435 such yellow trips were picked up on November 2 between 1:00 and 2:00, the hour the clock repeats. The times are wall-clock values without a zone (decision 0005), so a trip that starts before the clock goes back and ends after it appears to end early. Outside November the ride-hail share is at most 0.00000005.

## Proposal

| Check | On breach | Proposed threshold | Why |
| --- | --- | --- | --- |
| `silver_volume` | warn | 0.75 to 1.35 times the median of the prior months | Every loaded month passes, with about 0.05 to 0.1 of margin beyond the extremes (0.806 and 1.256). A half-loaded or double-loaded file is far outside. |
| `dropped_share` | warn | at most 0.001 | About 18 times the worst month (0.000056). A file holding the wrong month would be near 1. |
| `required_nulls` | fail | 0, so any null fails | History has none. A null in a pickup time or zone would be new and would affect every metric. |
| `dropoff_before_pickup` | warn | at most 0.001 | About 1.7 times the worst month (0.00059). Each November's daylight-saving hour passes without a yearly warning. |
| `fee_before_launch` | warn | at most 10 | Set by the spec. Four are known. |

`fee_presence`, `schema_required_columns`, `regression_totals`, and `freshness` have no tunable threshold.

## Alternatives

- **One volume band per service.** Ride-hail is much steadier than yellow (0.95 to 1.12), so a shared band is loose for it. A band of 0.90 to 1.20 for ride-hail alone would be tighter. The proposal keeps one band for simplicity.
- **A tighter volume band, such as 0.85 to 1.20,** would have warned on three of the 82 judged service-months (yellow 2026-02, 2024-08, and 2025-05). Those were real months, not bad files.
- **A small tolerance for required nulls, such as 0.000001,** would avoid a hard fail from a handful of bad rows. A fail turns verdicts into `data_issue`, so strictness has a cost.
- **A tighter `dropoff_before_pickup` threshold, such as 0.0002,** would warn every November. That documents the daylight-saving effect in the results, at the price of a warning that needs explaining each year.

## Consequences

With the proposed values, no loaded month warns or fails on these five checks. The only expected non-pass in a full run is `freshness`, because TLC 2026-09 is published and not yet loaded.
