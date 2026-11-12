# 0006: Rebuild gold rather than migrate it

Status: accepted (checklist 2, October 2026). Backfilled in Phase 0 from the checklist documents.

## Context

Checklist 1 built `gold.daily_trips` with three columns, straight from bronze. Checklist 2 added silver and a `service` column to gold, so the old table no longer matched.

## Decision

The old table was deleted (`rm -rf data/warehouse/gold/daily_trips`) and rebuilt from silver. Gold is derived data, so rebuilding is simpler and safer than migrating. With the `hadoop` catalog the folder is the table, so removing the folder drops it.

## Alternatives

Not written down at the time. Listed by Claude Code in Phase 0 for the owner to confirm or correct:

- `ALTER TABLE ... ADD COLUMN service` and backfill it: keeps snapshots, but the old rows had no service and the grain changed, so every row would be rewritten anyway.

## Consequences

- The rebuilt yellow numbers were checked against checklist 1: 97,804 trips and 401 fee trips on 2025-01-04, and 79,624 and 51,509 on 2025-01-05.
- From the spec onward, gold may still be dropped and rebuilt, but only after asking the owner (spec section 8).
