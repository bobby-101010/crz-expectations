MONTH ?= 2025-01
BRONZE := data/bronze/yellow/yellow_tripdata_$(MONTH).parquet
URL := https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_$(MONTH).parquet

.PHONY: build download run test shell

build: ; docker compose build

download: $(BRONZE)

$(BRONZE): ; mkdir -p $(dir $@) && curl -fL -o $@ $(URL) || (rm -f $@; exit 1)

run: download ; docker compose run --rm spark python -m pipeline.jobs.daily_trips --month $(MONTH)

test: ; docker compose run --rm spark pytest -q

shell: ; docker compose run --rm spark bash
