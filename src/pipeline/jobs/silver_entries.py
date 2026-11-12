import argparse
import uuid
from datetime import UTC, date, datetime

from pyspark.sql import SparkSession

from pipeline.checks import ingest_stats
from pipeline.jobs.ingest_entries import latest_pull
from pipeline.jobs.reference import read_csv
from pipeline.metrics import load_catalog
from pipeline.months import month_bounds
from pipeline.session import build_session
from pipeline.transforms_entries import conform_entries, unmapped_vehicle_classes

TABLE = "local.silver.crz_entries"
SOURCE = "crz_entries"


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.silver")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            toll_date DATE,
            interval_start TIMESTAMP_NTZ,
            time_period STRING,
            vehicle_class STRING,
            detection_group STRING,
            detection_region STRING,
            crz_entries BIGINT,
            excluded_roadway_entries BIGINT,
            source_pull_date DATE
        ) USING iceberg
        PARTITIONED BY (months(interval_start))
        """
    )


def run(spark: SparkSession, month: str) -> tuple[int, int]:
    """Latest bronze pull of one month -> silver. Returns (rows read, rows kept)."""
    pull = latest_pull(month)
    if pull is None:
        raise FileNotFoundError(f"no entries pull for {month}")
    start, end = month_bounds(month)
    vehicle_classes = load_catalog().vehicle_classes
    ensure_table(spark)

    bronze = read_csv(spark, pull)
    unmapped = unmapped_vehicle_classes(bronze, vehicle_classes)
    if unmapped:
        raise ValueError(f"entries {month}: vehicle classes {unmapped} are not in the catalog")

    pull_date = date.fromisoformat(pull.stem.removeprefix("pulled_"))
    conform_entries(bronze, vehicle_classes, start, end, pull_date).writeTo(
        TABLE
    ).overwritePartitions()

    read = bronze.count()
    kept = (
        spark.table(TABLE)
        .where(f"interval_start >= '{start}' AND interval_start < '{end}'")
        .count()
    )
    ingest_stats.append(spark, uuid.uuid4().hex, datetime.now(UTC), [(SOURCE, month, read, kept)])
    return read, kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()

    spark = build_session(f"silver_entries {args.month}")
    read, kept = run(spark, args.month)
    print(f"entries {args.month}: read {read:,}, kept {kept:,}, dropped {read - kept:,}")
    spark.stop()


if __name__ == "__main__":
    main()
