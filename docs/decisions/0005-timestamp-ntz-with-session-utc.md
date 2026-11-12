# 0005: `TIMESTAMP_NTZ` for trip times, with the session time zone pinned to UTC

Status: accepted (checklist 2, October 2026). Backfilled in Phase 0 from the checklist documents and a `make profile` run on 2026-11-11.

## Context

The source stores New York wall-clock time with no zone. All four pickup and dropoff columns are `timestamp_ntz` in all 44 loaded months of both services.

## Decision

Silver uses `TIMESTAMP_NTZ` for `pickup_at` and `dropoff_at`. The Spark session time zone is pinned to UTC, so every run reads the same clock values whatever the machine's settings.

## Alternatives

Not written down at the time. Listed by Claude Code in Phase 0 for the owner to confirm or correct:

- `TIMESTAMP` (with zone) in `America/New_York`: correct instants, but daylight-saving changes would have to be resolved from wall-clock values that are ambiguous for one hour each autumn.
- Leaving the session zone at the machine default: results could change between a laptop and CI.

## Consequences

- Dates and hours in gold are New York wall-clock values.
- The repeated hour at the end of daylight saving cannot be told apart. This matters for the MTA entries data in Phase 2 (2025-11-02 and 2026-11-01).
- The Phase 0 integration test covers the `TIMESTAMP_NTZ` DDL and the `months(pickup_at)` partition in CI.
