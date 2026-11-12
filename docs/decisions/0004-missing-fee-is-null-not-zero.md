# 0004: A missing congestion fee is null, not zero

Status: accepted (checklist 2, October 2026). Backfilled in Phase 0 from the checklist documents.

## Context

Before 2025 the source files have no `cbd_congestion_fee` column. From 2025-01 they do.

## Decision

Silver stores null where the source has no fee column. Null says "not recorded". Zero says "recorded as no fee".

## Alternatives

- Filling zero before 2025: every query works without null handling, but a count of zero-fee trips would then mix "no fee charged" with "no fee existed".

## Consequences

- `COUNT(cbd_congestion_fee)` gives the number of trips with a recorded fee: 0 for 2023 and 2024, and every trip from 2025 (spec section 3).
- Gold counts fee trips as `cbd_congestion_fee > 0`, which is false for null, so months before 2025 get 0 fee trips.
- The `fee_presence` check in Phase 1 depends on this.
