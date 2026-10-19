SERVICE ?= yellow
MONTH ?= 2025-01
START ?= 2025-01
END ?= 2025-03
RUN := docker compose run --rm spark
CLUSTER := docker compose --profile cluster

.PHONY: build test shell download profile silver gold backfill history cluster-up cluster-down cluster-silver

build: ; docker compose build

test: ; $(RUN) pytest -q

shell: ; $(RUN) bash

download: ; $(RUN) python -m pipeline.jobs.ingest --service $(SERVICE) --month $(MONTH)

profile: ; $(RUN) python -m pipeline.jobs.profile_schema

silver: ; $(RUN) python -m pipeline.jobs.silver_trips --service $(SERVICE) --month $(MONTH)

gold: ; $(RUN) python -m pipeline.jobs.daily_trips --month $(MONTH)

backfill: ; $(RUN) python -m pipeline.jobs.backfill --start $(START) --end $(END)

history: ; mkdir -p data/spark-events && docker compose --profile history up -d history

cluster-up: ; $(CLUSTER) up -d --scale spark-worker=2 spark-master spark-worker

cluster-down: ; $(CLUSTER) rm -sf spark-master spark-worker

cluster-silver: ; docker compose run --rm -e SPARK_MASTER=spark://spark-master:7077 spark python -m pipeline.jobs.silver_trips --service $(SERVICE) --month $(MONTH)
