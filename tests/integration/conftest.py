"""Fixtures for integration tests: real jobs, Iceberg, a temporary warehouse.

These tests need the Iceberg session from `build_session`. Spark allows one
session per process and fixes its jars at startup, so they run in their own
pytest process: `pytest -m integration` (or `make test-integration`).
"""

import pytest
from pyspark.sql import SparkSession

from pipeline.session import build_session


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
