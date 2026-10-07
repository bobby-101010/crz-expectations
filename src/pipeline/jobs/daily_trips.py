import argparse
from datetime import date

from pipeline.session import build_session
from pipeline.transforms import daily_trips

TABLE = "local.gold.daily_trips"
BRONZE_PATH = "/data/bronze/yellow/yellow_tripdata_{month}.parquet"


def month_bounds(month: str) -> tuple[date, date]:
    """'2025-01' -> (2025-01-01, 2025-02-01)."""
    year, mon = (int(part) for part in month.split("-"))
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return start, end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()
    start, end = month_bounds(args.month)

    spark = build_session("daily_trips")
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.gold")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            trip_date DATE,
            trips BIGINT,
            cbd_fee_trips BIGINT
        ) USING iceberg
        PARTITIONED BY (months(trip_date))
        """
    )

    bronze = spark.read.parquet(BRONZE_PATH.format(month=args.month))
    daily_trips(bronze, start, end).writeTo(TABLE).overwritePartitions()

    (
        spark.table(TABLE)
        .where(f"trip_date >= '{start}' AND trip_date < '{end}'")
        .orderBy("trip_date")
        .show(31)
    )
    spark.stop()


if __name__ == "__main__":
    main()
    