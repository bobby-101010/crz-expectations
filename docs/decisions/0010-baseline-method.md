# 0010: How `same_weekday_trailing_8` baselines are computed

Status: accepted (Phase 2, 2026-11-11). Approved by the owner in the Phase 2 plan.

## Context

Spec section 6 defines the baseline as the same weekday over the previous 8 weeks, holidays excluded, with exact percentiles and no row below 6 observations. Three details were open, and one registry entry (`prospective-crz-entries-2026-11-15-week-normal`) depends on them: its expert assumed each weekday's band is built from 7 or 8 values.

## Decision

- **The history of a date is fixed in the calendar:** the 8 dates exactly 7, 14, ... 56 days earlier. It is not "the 8 most recent usable dates". A holiday among them is left out and not replaced, so it leaves 7 values.
- **Holidays are removed from the history only.** A holiday still gets its own baseline row, built from the ordinary days before it.
- **A date with missing data** simply contributes nothing, like a holiday.
- **Slices** are the unsliced metric (`slice_key = 'all'`) and each single value of each dimension. Combinations of dimensions get no baselines. Rows whose dimension value is null (yellow taxis have no operator) are left out of that dimension's slices.
- **Percentiles** use Spark's exact `percentile`, which interpolates linearly, over a window partitioned by slice and weekday.
- **The whole table is rebuilt** from gold on each run. It never reads silver.
- **The metric catalog was written in this phase,** not Phase 3, because the baselines job is defined by the catalog's `baseline: true` flag.

## Alternatives

- "The 8 most recent non-holiday same weekdays": always 8 values, but it reaches further back around holidays and does not match what the expert assumed.
- Skipping baseline rows for holidays: scoring would then have to decide what a missing band means. Keeping the row leaves that choice to scoring.
- `percentile_approx`: faster on large data, but not exact, and these windows hold 8 values.

## Consequences

- The first 6 weeks of any series have no baseline.
- Around holidays, a band rests on 7 or fewer values and holds fewer ordinary days than its name suggests. The expert's reasoning in the elicitation record covers this.
