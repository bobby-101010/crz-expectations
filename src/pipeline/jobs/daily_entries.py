import argparse

from pyspark.sql import SparkSession

from pipeline.months import month_bounds
from pipeline.session import build_session
from pipeline.transforms_entries import daily_entries

SILVER = "local.silver.crz_entries"
TABLE = "local.gold.daily_entries"


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.gold")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            entry_date DATE,
            vehicle_class STRING,
            detection_group STRING,
            time_period STRING,
            crz_entries BIGINT,
            excluded_roadway_entries BIGINT
        ) USING iceberg
        PARTITIONED BY (months(entry_date))
        """
    )


def run(spark: SparkSession, month: str) -> None:
    """Silver entries of one month -> gold daily entries."""
    start, end = month_bounds(month)
    ensure_table(spark)
    daily_entries(spark.table(SILVER), start, end).writeTo(TABLE).overwritePartitions()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()

    spark = build_session(f"daily_entries {args.month}")
    run(spark, args.month)
    spark.stop()


if __name__ == "__main__":
    main()
