"""One pass over silver trips that gives every count the trip checks need."""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

REQUIRED_NOT_NULL = ["pickup_at", "dropoff_at", "pickup_zone_id", "dropoff_zone_id"]


def profile_trips(trips: DataFrame) -> DataFrame:
    """Silver trips -> one row of counts per service and source month."""
    ends_before_start = F.col("dropoff_at") < F.col("pickup_at")
    return trips.groupBy("service", "source_month").agg(
        F.count("*").alias("rows"),
        *[
            F.sum(F.col(name).isNull().cast("long")).alias(f"null_{name}")
            for name in REQUIRED_NOT_NULL
        ],
        F.sum(F.when(ends_before_start, 1).otherwise(0)).cast("long").alias("ends_before_start"),
        F.count("cbd_congestion_fee").alias("fee_recorded"),
        F.sum(F.when(F.col("cbd_congestion_fee") > 0, 1).otherwise(0))
        .cast("long")
        .alias("fee_trips"),
    )


def silver_partition_rows(spark: SparkSession, table: str) -> dict[tuple[str, str], int]:
    """(service, month) -> row count, from Iceberg partition metadata. Reads no data files."""
    rows = (
        spark.table(f"{table}.partitions")
        .select(
            F.col("partition.service").alias("service"),
            F.col("partition.pickup_at_month").alias("months_since_1970"),
            "record_count",
        )
        .collect()
    )
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        year, month_index = divmod(row["months_since_1970"], 12)
        key = (row["service"], f"{1970 + year}-{month_index + 1:02d}")
        counts[key] = counts.get(key, 0) + row["record_count"]
    return counts
