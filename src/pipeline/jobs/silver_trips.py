import argparse

from pyspark.sql import SparkSession

from pipeline.jobs.ingest import FILE_PREFIX, bronze_path
from pipeline.months import month_bounds
from pipeline.session import build_session
from pipeline.transforms import conform_trips

TABLE = "local.silver.trips"


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.silver")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            service STRING,
            operator_code STRING,
            pickup_at TIMESTAMP_NTZ,
            dropoff_at TIMESTAMP_NTZ,
            pickup_zone_id INT,
            dropoff_zone_id INT,
            trip_miles DOUBLE,
            cbd_congestion_fee DOUBLE,
            source_month STRING
        ) USING iceberg
        PARTITIONED BY (service, months(pickup_at))
        """
    )


def run(spark: SparkSession, service: str, month: str) -> tuple[int, int]:
    """Bronze file of one service and month -> silver. Returns (rows read, rows kept)."""
    start, end = month_bounds(month)
    ensure_table(spark)

    bronze = spark.read.parquet(str(bronze_path(service, month)))
    conform_trips(bronze, service, month, start, end).writeTo(TABLE).overwritePartitions()

    read = bronze.count()
    kept = (
        spark.table(TABLE)
        .where(f"service = '{service}' AND pickup_at >= '{start}' AND pickup_at < '{end}'")
        .count()
    )
    return read, kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True, choices=sorted(FILE_PREFIX))
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()

    spark = build_session(f"silver_trips {args.service} {args.month}")
    read, kept = run(spark, args.service, args.month)
    print(f"{args.service} {args.month}: read {read:,}, kept {kept:,}, dropped {read - kept:,}")
    spark.stop()


if __name__ == "__main__":
    main()
