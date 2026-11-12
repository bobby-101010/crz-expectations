SERVICE ?= yellow
MONTH ?= 2025-01
START ?= 2025-01
END ?= 2025-03
RUN := docker compose run --rm spark
CLUSTER := docker compose --profile cluster

.PHONY: build test test-integration lint shell checks check-profile ingest-stats-backfill reference entries slices gold-backfill baselines validate score drivers site airflow-build airflow-up airflow-down airflow-check download profile silver gold backfill history cluster-up cluster-down cluster-silver

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
# It is marked -dirty when anything but the generated site has uncommitted changes.
score: ; docker compose run --rm -e REGISTRY_COMMIT=$$(git rev-parse --short HEAD)$$(test -z "$$(git status --porcelain -- . ':!site')" || echo -dirty) spark python -m pipeline.jobs.score

# Drivers for the latest scoring run. Run `make score` first.
drivers: ; $(RUN) python -m pipeline.jobs.drivers

# Export the status page's data and render site/index.html. Run score and drivers first.
site: ; $(RUN) python -m pipeline.jobs.site

AIRFLOW := docker compose --profile airflow

# The Airflow image is built on the project image, so that one is built first.
airflow-build: build ; $(AIRFLOW) build airflow

airflow-up: ; $(AIRFLOW) up -d airflow

airflow-down: ; $(AIRFLOW) rm -sf airflow

# Lists the DAGs and fails if either does not load.
airflow-check: ; $(AIRFLOW) run --rm airflow sh /app/dags/check.sh

history: ; mkdir -p data/spark-events && docker compose --profile history up -d history

cluster-up: ; $(CLUSTER) up -d --scale spark-worker=2 spark-master spark-worker

cluster-down: ; $(CLUSTER) rm -sf spark-master spark-worker

cluster-silver: ; docker compose run --rm -e SPARK_MASTER=spark://spark-master:7077 spark python -m pipeline.jobs.silver_trips --service $(SERVICE) --month $(MONTH)
