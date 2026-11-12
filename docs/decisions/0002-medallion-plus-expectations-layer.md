# 0002: Medallion layers, plus a separate expectations layer

Status: accepted (checklist 1, October 2026). Backfilled in Phase 0 from the checklist documents and spec section 4.

## Context

The pipeline has two different jobs: refining data, and judging it against what was written down beforehand.

## Decision

- Data layers use the medallion names. Bronze holds source files exactly as received. Silver holds one conformed table per source at source grain. Gold holds daily aggregates and baselines, and can be rebuilt at any time.
- Expectations are a layer of their own (`local.expectations`, with the registry file in git). The layer keeps its own name because it judges the data and does not refine it.
- Data checks are also separate, and gate scoring (spec section 2).

## Alternatives

Not written down at the time. Listed by Claude Code in Phase 0 for the owner to confirm or correct:

- Putting verdicts in gold: simpler, but it mixes derived data that can be rebuilt with an append-only record of judgments.
- Folding expectations into data checks: loses the difference between a claim about the data and a claim about the world.

## Consequences

Gold can be dropped and rebuilt without touching verdict history. The registry and verdicts are append-only.
