SERVICE ?= yellow
MONTH ?= 2025-01
START ?= 2025-01
END ?= 2025-03
RUN := docker compose run --rm spark
CLUSTER := docker compose --profile cluster

.PHONY: build test test-integration lint shell checks check-profile ingest-stats-backfill reference entries slices gold-backfill baselines validate score download profile silver gold backfill history cluster-up cluster-down cluster-silver

build: ; docker compose build

test: ; $(RUN) pytest -q -m "not integration"

test-integration: ; $(RUN) pytest -q -m integration

lint: ; $(RUN) sh -c "ruff check . && ruff format --check ."

shell: ; $(RUN) bash

download: ; $(RUN) python -m pipeline.jobs.ingest --service $(SERVICE) --month $(MONTH)

profile: ; $(RUN) python -m pipeline.jobs.profile_schema

silver: ; $(RUN) python -m pipeline.jobs.silver_trips --service $(SERVICE) --month $(MONTH)

gold: ; $(RUN) python -m pipeline.jobs.daily_trips --month $(MONTH)

backfill: ; $(RUN) python -m pipeline.jobs.backfill --start $(START) --end $(END)

# `make checks` covers every loaded month. `make checks MONTH=2025-01` covers one.
checks: ; $(RUN) python -m pipeline.jobs.checks $(if $(filter command,$(origin MONTH)),--month $(MONTH))

check-profile: ; $(RUN) python -m pipeline.jobs.checks --profile

ingest-stats-backfill: ; $(RUN) python -m pipeline.jobs.backfill_ingest_stats

reference: ; $(RUN) python -m pipeline.jobs.reference

# Pull, silver and gold for the MTA entries data, one month at a time.
entries: ; $(RUN) python -m pipeline.jobs.backfill_entries --start $(START) --end $(END)

slices: ; $(RUN) python -m pipeline.jobs.daily_trip_slices --month $(MONTH)

# Rebuild gold trip tables from silver. Bronze is not read.
gold-backfill: ; $(RUN) python -m pipeline.jobs.gold_backfill --start $(START) --end $(END)

baselines: ; $(RUN) python -m pipeline.jobs.baselines

validate: ; $(RUN) python -m pipeline.registry validate

# The registry commit comes from the host, because git is not used inside the container.
score: ; docker compose run --rm -e REGISTRY_COMMIT=$$(git rev-parse --short HEAD)$$(test -z "$$(git status --porcelain)" || echo -dirty) spark python -m pipeline.jobs.score

history: ; mkdir -p data/spark-events && docker compose --profile history up -d history

cluster-up: ; $(CLUSTER) up -d --scale spark-worker=2 spark-master spark-worker

cluster-down: ; $(CLUSTER) rm -sf spark-master spark-worker

cluster-silver: ; docker compose run --rm -e SPARK_MASTER=spark://spark-master:7077 spark python -m pipeline.jobs.silver_trips --service $(SERVICE) --month $(MONTH)
