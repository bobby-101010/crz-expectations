"""Fixtures for integration tests: real jobs, Iceberg, a temporary warehouse.

These tests need the Iceberg session from `build_session`. Spark allows one
session per process and fixes its jars at startup, so they run in their own
pytest process: `pytest -m integration` (or `make test-integration`).
"""

from datetime import datetime

import pytest
from pyspark.sql import SparkSession

from pipeline.jobs import daily_trips, silver_trips
from pipeline.jobs.ingest import bronze_path
from pipeline.session import build_session

# Fixture schemas copy the column types `make profile` shows for the real files:
# int zone ids from 2023-02 on, timestamps without a zone, and no fee column before 2025.
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


@pytest.fixture(scope="session")
def lake(tmp_path_factory):
    """An Iceberg session whose bronze, warehouse and event log are all temporary."""
    if SparkSession.getActiveSession() is not None:
        pytest.fail(
            "A Spark session without Iceberg is already running. "
            "Run integration tests on their own: pytest -m integration"
        )

    root = tmp_path_factory.mktemp("lake")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("BRONZE_DIR", str(root / "bronze"))
        env.setenv("WAREHOUSE_DIR", str(root / "warehouse"))
        env.setenv("SPARK_EVENTS_DIR", str(root / "spark-events"))

        spark = build_session("integration tests")
        warehouse = spark.conf.get("spark.sql.catalog.local.warehouse")
        if warehouse != str(root / "warehouse"):
            spark.stop()
            pytest.fail(f"Refusing to run: the catalog points at {warehouse}, not a temp folder")

        yield spark
        spark.stop()


@pytest.fixture(scope="session")
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
