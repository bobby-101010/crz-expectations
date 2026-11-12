# Expectation lifecycle

**Registry.** An expectation is a written statement about a metric over a period, with an expected range. Its sentence, reasoning, metric and filters live only in `expectations/registry.yaml`, keyed by the id stored as `expectation_id`.

**Scoring run.** Each scoring run scores every registry entry and appends one row per expectation to `expectations.verdicts`. All rows of a run share `run_id` and `scored_at`. Earlier runs are kept, so each `expectation_id` has many rows. The current state is the rows of the run with the latest `scored_at`.

**What a row holds.** `window_start` to `window_end` (inclusive) is the period the expectation is about. `expected_low` and `expected_high` are the written range. `observed` is what was measured, in `unit`:
- 'percent': percent change of the period total against an earlier comparison period.
- 'percent_of_days': percent of days in the period whose value lies inside that day's `p10` to `p90` band in `gold.baselines`. Days without a baseline are not counted; `note` says how many.
- 'ratio': a ratio of two totals over the period.

**Verdict.** `verdict` is decided in this order:
1. 'not_scoreable': the entry is marked not measurable. `observed`, the range and `unit` are null; `note` says why.
2. 'pending': the period ends after the latest date loaded in the gold table the metric reads. `observed` is null.
3. 'data_issue': a data check on the metric's inputs has 'fail' as its newest result in `checks.results`, for dates overlapping the period or the comparison period. `failing_checks` lists the `check_id` values. Also given when the period has no data. A 'warn' never causes it.
4. 'held': `observed` is inside the range, ends included.
5. 'violated_low' or 'violated_high': `observed` is below or above the range.

Only 'held', 'violated_low' and 'violated_high' are outcomes about the world.

**Drivers.** After scoring, the drivers step reads the latest scoring run and appends rows to `expectations.drivers` under the same `run_id`. Only expectations with `unit` = 'percent' that were held or violated get rows, and only for dimensions the registry entry lists. One row is one `expectation_id`, `dimension` (such as 'service', 'operator_code', 'zone_relation') and `slice_value`. '(none)' stands for a null value, such as the operator of yellow taxis.

`comparison_value` and `observed_value` are the slice's totals over the comparison period and the period, in trips or vehicle entries. `expected_value` is `comparison_value` moved by the midpoint of the expected range. `gap` is `observed_value` minus `expected_value`. Gaps of one dimension add up to the total gap. `share_of_gap` is the slice's gap over that total, as a fraction; it can be far above 1 or negative when the total is small. `gap_rank` 1 is the largest absolute gap in its dimension. A driver says where a gap is, not why.

**Latest drivers.** `expectations.drivers` has no timestamp. Find the `run_id` with the latest `scored_at` in `expectations.verdicts`, then take the drivers rows with that `run_id`.
