# Load-and-checks lifecycle

**Loading.** The unit of work is one month of one source: yellow trips, ride-hail trips, or MTA entries. A load reads the month's source file and replaces that month in `silver.trips` or `silver.crz_entries`.

**Recorded per load.** Each load appends one row to `checks.ingest_stats`. `service` is 'yellow', 'fhvhv' or 'crz_entries'. `source_month` is the month as 'YYYY-MM'. `rows_read` is the rows in the source file. `rows_kept` is the rows written to silver. `loaded_at` is when the load finished (UTC). `run_id` identifies that load only; it does not join to `run_id` in other tables.

**Dropped rows.** Dropped rows are `rows_read` minus `rows_kept`; no column stores them. They are rows whose date is outside the file's month: the pickup time for trips, the 10-minute block for entries. Nothing else is dropped.

**Reloads.** A month loaded again gets another row, and old rows stay. The current figures are the row with the latest `loaded_at` for each `service` and `source_month`. Do not sum across loads, and do not use this table to count trips or entries.

**Checks.** After loading, a checks run appends one row per check execution to `checks.results`. One row is one `check_id` on one `target_table` and `partition_value`. `status` is 'pass', 'warn' or 'fail'. `observed` is the number measured (its meaning depends on the check), `threshold` the rule as text, and `message` what was found. Rows of one run share `run_id` and `checked_at`.

`target_table` is a table such as 'silver.trips', 'silver.crz_entries', 'reference.cbd_zones' or 'checks.ingest_stats', or a source such as 'bronze/yellow', 'bronze/fhvhv' or 'bronze/crz_entries'. `partition_value` is the part checked: 'yellow/2025-01' (service and month), 'fhvhv/2025' (service and year), a month, a year, a source name, or 'all'.

Some `check_id` values:
- 'dropped_share': dropped rows over `rows_read` for a trip month. Warns above 0.001.
- 'silver_volume': a month's rows against the median of prior months. Warns outside 0.75 to 1.35.
- 'required_nulls': fails on any null pickup or dropoff time or zone.
- 'fee_presence': fails unless the fee is null before 2025-01 and filled from 2025-01.
- 'regression_totals': fails if yearly trip totals differ from fixed known totals.
- 'entries_days_complete': fails if a date in an entries month has no rows.
- 'freshness': warns when the source has published more than is loaded.
- 'cbd_zone_membership': warns if under 0.95 of trips that start and end in one in-zone zone carry the fee.

**Latest result.** The table is append-only, and a run for one month skips the table-wide checks, so the newest run does not contain every check. The current result is the row with the latest `checked_at` for each `check_id`, `target_table` and `partition_value`.

**What a status does.** A 'warn' is recorded only. A current 'fail' on an expectation's inputs turns its verdict in `expectations.verdicts` into 'data_issue'. A later 'pass' for the same check and partition clears it.
