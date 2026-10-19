import argparse

from pyspark.sql import SparkSession

from pipeline.months import month_bounds
from pipeline.session import build_session
from pipeline.transforms import daily_trips

SILVER = "local.silver.trips"
TABLE = "local.gold.daily_trips"


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.gold")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            trip_date DATE,
            service STRING,
            trips BIGINT,
            cbd_fee_trips BIGINT
        ) USING iceberg
        PARTITIONED BY (months(trip_date))
        """
    )


def run(spark: SparkSession, month: str) -> None:
    """Silver trips of one month, all services -> gold daily counts."""
    start, end = month_bounds(month)
    ensure_table(spark)
    daily_trips(spark.table(SILVER), start, end).writeTo(TABLE).overwritePartitions()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()
    start, end = month_bounds(args.month)

    spark = build_session(f"daily_trips {args.month}")
    run(spark, args.month)
    (
        spark.table(TABLE)
        .where(f"trip_date >= '{start}' AND trip_date < '{end}'")
        .orderBy("trip_date", "service")
        .show(62)
    )
    spark.stop()


if __name__ == "__main__":
    main()
