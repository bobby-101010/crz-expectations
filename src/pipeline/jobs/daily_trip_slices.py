import argparse

from pyspark.sql import SparkSession

from pipeline.months import month_bounds
from pipeline.session import build_session
from pipeline.transforms import daily_trip_slices

SILVER = "local.silver.trips"
ZONES = "local.reference.cbd_zones"
TABLE = "local.gold.daily_trip_slices"


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.gold")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            trip_date DATE,
            service STRING,
            operator_code STRING,
            zone_relation STRING,
            pickup_hour INT,
            trips BIGINT,
            fee_trips BIGINT
        ) USING iceberg
        PARTITIONED BY (months(trip_date))
        """
    )


def run(spark: SparkSession, month: str) -> None:
    """Silver trips of one month, all services -> gold daily slices."""
    start, end = month_bounds(month)
    ensure_table(spark)
    daily_trip_slices(spark.table(SILVER), spark.table(ZONES), start, end).writeTo(
        TABLE
    ).overwritePartitions()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()

    spark = build_session(f"daily_trip_slices {args.month}")
    run(spark, args.month)
    spark.stop()


if __name__ == "__main__":
    main()
