# 0003: Read one bronze file at a time

Status: accepted (checklist 2, October 2026). Backfilled in Phase 0 from the checklist documents and a `make profile` run on 2026-11-11.

## Context

The monthly TLC files drift between years. `make profile` over the 44 loaded months shows:

- `PULocationID` and `DOLocationID` are `bigint` in 2023-01 and `int` from 2023-02, for both services.
- Yellow has `airport_fee` in 2023-01 and `Airport_fee` from 2023-02.
- `cbd_congestion_fee` is absent before 2025-01, for both services.
- Yellow gains `request_source` in 2026-06.

Reading several months in one call makes Spark apply one schema to all of them, which can fail when a column's type differs between files.

## Decision

Each job reads exactly one bronze file. `conform_trips` casts every column explicitly, matches source names without regard to case, turns a missing optional column into nulls, and raises an error naming any missing required column.

## Alternatives

Not written down at the time. Listed by Claude Code in Phase 0 for the owner to confirm or correct:

- One read over a glob of months with `mergeSchema`: fewer jobs, but type conflicts surface as runtime errors far from their cause, and a missing column becomes nulls silently.
- Rewriting bronze to one schema first: breaks the rule that bronze is never edited.

## Consequences

The unit of work is one month of one source, which is also what makes reruns safe with `overwritePartitions()`.
