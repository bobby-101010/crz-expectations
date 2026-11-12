"""The silver and gold jobs, end to end, on tiny bronze fixtures with Iceberg.

Fixture schemas copy the column types `make profile` shows for the real files:
int zone ids from 2023-02 on, timestamps without a zone, and no fee column
before 2025.
"""

from datetime import date, datetime

import pytest

from pipeline.jobs import daily_trips, silver_trips
from pipeline.transforms import SILVER_COLUMNS

pytestmark = pytest.mark.integration


def gold_rows(spark):
    rows = spark.table(daily_trips.TABLE).collect()
    return {(r["trip_date"], r["service"]): (r["trips"], r["cbd_fee_trips"]) for r in rows}


EXPECTED_GOLD = {
    (date(2025, 1, 4), "yellow"): (1, 1),
    (date(2025, 1, 5), "yellow"): (2, 1),
    (date(2025, 1, 5), "fhvhv"): (2, 1),
    (date(2025, 1, 6), "fhvhv"): (1, 1),
    (date(2024, 12, 30), "fhvhv"): (1, 0),
    (date(2024, 12, 31), "fhvhv"): (1, 0),
}


def test_silver_job_creates_the_table_with_the_declared_schema(lake, loaded):
    silver = lake.table(silver_trips.TABLE)

    assert [(f.name, f.dataType.simpleString()) for f in silver.schema] == list(
        SILVER_COLUMNS.items()
    )
    partitioning = {
        row["col_name"]: row["data_type"]
        for row in lake.sql(f"DESCRIBE TABLE {silver_trips.TABLE}").collect()
        if row["col_name"].startswith("Part ")
    }
    assert partitioning == {"Part 0": "service", "Part 1": "months(pickup_at)"}


def test_silver_job_reports_rows_read_and_kept(loaded):
    assert loaded == {
        ("yellow", "2025-01"): (4, 3),  # the stray December row is dropped
        ("fhvhv", "2025-01"): (3, 3),
        ("fhvhv", "2024-12"): (2, 2),
    }


def test_silver_keeps_wall_clock_times_and_nulls_a_missing_fee(lake, loaded):
    silver = lake.table(silver_trips.TABLE)

    january_4 = silver.where("service = 'yellow' AND pickup_at < '2025-01-05'").collect()
    assert [(r["pickup_at"], r["dropoff_at"], r["cbd_congestion_fee"]) for r in january_4] == [
        (datetime(2025, 1, 4, 23, 50), datetime(2025, 1, 5, 0, 10), 0.75)
    ]

    december = silver.where("source_month = '2024-12'")
    assert december.count() == 2
    assert december.where("cbd_congestion_fee IS NOT NULL").count() == 0
    assert silver.where("service = 'yellow' AND operator_code IS NOT NULL").count() == 0


def test_gold_job_creates_the_table_and_counts_by_date_and_service(lake, loaded):
    gold = lake.table(daily_trips.TABLE)

    assert [(f.name, f.dataType.simpleString()) for f in gold.schema] == [
        ("trip_date", "date"),
        ("service", "string"),
        ("trips", "bigint"),
        ("cbd_fee_trips", "bigint"),
    ]
    assert gold_rows(lake) == EXPECTED_GOLD


def test_rerunning_a_month_replaces_it_and_leaves_other_months_alone(lake, loaded):
    assert silver_trips.run(lake, "yellow", "2025-01") == (4, 3)
    assert silver_trips.run(lake, "fhvhv", "2025-01") == (3, 3)
    daily_trips.run(lake, "2025-01")

    assert lake.table(silver_trips.TABLE).count() == 8
    assert gold_rows(lake) == EXPECTED_GOLD
