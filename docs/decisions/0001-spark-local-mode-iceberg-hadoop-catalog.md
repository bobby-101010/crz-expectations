# 0001: Spark local mode, with Iceberg on the `hadoop` catalog

Status: accepted (checklist 1, October 2026). Backfilled in Phase 0 from the checklist documents.

## Context

The project runs on one laptop (M4 MacBook Air, 24 GB) inside Docker. It needs a table format with partition overwrite and snapshots, and it must be reproducible by a reviewer with only Docker.

## Decision

- Spark runs in local mode with a 6 GB driver. In local mode the driver does all the work, so driver memory is the setting that matters.
- Tables are Iceberg, in a `hadoop`-type catalog named `local` at `/data/warehouse`. This catalog stores each table as a plain folder and needs no catalog service.
- PySpark is pinned to 4.1.3, not 4.2.0, because Iceberg 1.12.0 ships Spark runtimes for 4.1 and 4.0 only. The runtime is `iceberg-spark-runtime-4.1_2.13:1.12.0`.
- A two-worker standalone cluster exists under the Compose profile `cluster`. It was used once, on one yellow month, to see executors as separate processes. It is not the default, because one laptop gains no speed from splitting itself into containers.

## Alternatives

Not written down at the time. Listed by Claude Code in Phase 0 for the owner to confirm or correct:

- A REST or JDBC catalog: closer to production, but adds a service to run and to explain.
- The standalone cluster as the default: same hardware, more moving parts.
- Plain Parquet folders without a table format: no atomic partition overwrite and no snapshots.

## Consequences

- With the `hadoop` catalog the folder is the table, so deleting the folder drops the table (see 0006).
- The `hadoop` catalog is safe for one writer on a local file system. It is not a choice for concurrent writers or object stores.
