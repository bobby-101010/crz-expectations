"""The silver and gold jobs, end to end, on tiny bronze fixtures with Iceberg.

Fixture schemas copy the column types `make profile` shows for the real files:
int zone ids from 2023-02 on, timestamps without a zone, and no fee column
before 2025.
"""

from datetime import date, datetime

import pytest

from pipeline.jobs import daily_trips, silver_trips
from pipeline.jobs.ingest import bronze_path
from pipeline.transforms import SILVER_COLUMNS

pytestmark = pytest.mark.integration

YELLOW_SCHEMA = (
    "tpep_pickup_datetime timestamp_ntz, tpep_dropoff_datetime timestamp_ntz, "
    "trip_distance double, PULocationID int, DOLocationID int, cbd_congestion_fee double"
)
FHVHV_SCHEMA = (
    "hvfhs_license_num string, pickup_datetime timestamp_ntz, dropoff_datetime timestamp_ntz, "
    "PULocationID int, DOLocationID int, trip_miles double"
)

YELLOW_2025_01 = [
    # Picked up before tolling began, dropped off after: the January 4 case.
    (datetime(2025, 1, 4, 23, 50), datetime(2025, 1, 5, 0, 10), 2.5, 161, 236, 0.75),
    (datetime(2025, 1, 5, 8, 0), datetime(2025, 1, 5, 8, 20), 1.2, 161, 162, 0.75),
    (datetime(2025, 1, 5, 9, 0), datetime(2025, 1, 5, 9, 30), 8.0, 132, 7, 0.0),
    # A stray row from another month: silver must drop it.
    (datetime(2024, 12, 31, 23, 59), datetime(2025, 1, 1, 0, 5), 1.0, 1, 2, 0.0),
]
FHVHV_2025_01 = [
    ("HV0003", datetime(2025, 1, 5, 9, 0), datetime(2025, 1, 5, 9, 25), 79, 148, 3.1, 1.5),
    ("HV0005", datetime(2025, 1, 5, 10, 0), datetime(2025, 1, 5, 10, 40), 7, 129, 4.0, 0.0),
    ("HV0003", datetime(2025, 1, 6, 9, 0), datetime(2025, 1, 6, 9, 15), 230, 48, 1.1, 1.5),
]
FHVHV_2024_12 = [
    ("HV0003", datetime(2024, 12, 30, 8, 0), datetime(2024, 12, 30, 8, 30), 79, 148, 3.1),
    ("HV0005", datetime(2024, 12, 31, 8, 0), datetime(2024, 12, 31, 8, 30), 7, 129, 4.0),
]


def write_bronze(spark, service, month, rows, schema):
    path = bronze_path(service, month)
    spark.createDataFrame(rows, schema).coalesce(1).write.mode("overwrite").parquet(str(path))


def gold_rows(spark):
    rows = spark.table(daily_trips.TABLE).collect()
    return {(r["trip_date"], r["service"]): (r["trips"], r["cbd_fee_trips"]) for r in rows}


@pytest.fixture(scope="module")
def loaded(lake):
    """Bronze fixtures for three service-months, run through silver and gold once."""
    write_bronze(lake, "yellow", "2025-01", YELLOW_2025_01, YELLOW_SCHEMA)
    write_bronze(
        lake, "fhvhv", "2025-01", FHVHV_2025_01, FHVHV_SCHEMA + ", cbd_congestion_fee double"
    )
    write_bronze(lake, "fhvhv", "2024-12", FHVHV_2024_12, FHVHV_SCHEMA)

    counts = {
        ("yellow", "2025-01"): silver_trips.run(lake, "yellow", "2025-01"),
        ("fhvhv", "2025-01"): silver_trips.run(lake, "fhvhv", "2025-01"),
        ("fhvhv", "2024-12"): silver_trips.run(lake, "fhvhv", "2024-12"),
    }
    daily_trips.run(lake, "2025-01")
    daily_trips.run(lake, "2024-12")
    return counts


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
