# CRZ Expectations

Expectation-driven data pipeline on NYC congestion pricing data: Spark 4.1 + Iceberg, local on a Mac, run through Docker. The design spec is `docs/SPEC.md`; read the section for the current phase before planning. The spec wins over anything else.

## Commands (Mac terminal, repo root; Docker Desktop must be running)

- `make test`: unit tests in the container. `make lint`: ruff.
- `make silver|gold SERVICE= MONTH=`, `make backfill START= END=`, `make gold-backfill START= END=`
- `make checks [MONTH=]`, `make score`, `make drivers`, `make site` (added as their phases land)
- Develop on 1 to 3 months. Ask before any run likely to take more than 10 minutes.

## Rules

- Never edit or delete files under `data/bronze/`. Ask before dropping any table.
- Pinned versions (PySpark 4.1.3, Iceberg 1.12.0 for Spark 4.1/Scala 2.13, uv 0.11.7, Python 3.12): never change without asking.
- Jobs are `run(spark, ...)` + `main()`; logic in pure, unit-tested DataFrame functions; one month of one source per unit of work; idempotent writes.
- Read bronze one file at a time; explicit casts; fail loudly on missing required columns.
- Never write or change `expected`, `confidence`, `rationale` or `statement` in `expectations/registry.yaml`. New expectations come only from an elicitation record in `docs/elicitation/` plus the owner's approval.
- Never write essay prose (`docs/essay.md`). Outlines and fact checks are fine.
- Never commit `~/Documents/Anki/` content to this repo.
- One branch and PR per phase (`phase-N-name`). Plan first, in plan mode, and wait for approval.
- Report test and run results exactly, including failures. Do not say something works unless you ran it.
- At the end of each phase, draft the entry in `docs/ai-log.md` (template in the spec, Appendix B) and leave the owner's sections for the owner.
