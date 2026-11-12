"""Fill `checks.ingest_stats` for service-months loaded before the table existed.

Rows read come from the bronze file, and rows kept from Iceberg partition
metadata, so nothing is reloaded. Service-months that already have a row are
left alone.
"""

import uuid
from datetime import UTC, datetime

from pyspark.sql import SparkSession

from pipeline.checks import ingest_stats
from pipeline.checks.profile import silver_partition_rows
from pipeline.jobs.ingest import bronze_path
from pipeline.session import build_session

SILVER = "local.silver.trips"


def run(spark: SparkSession) -> list[tuple[str, str, int, int]]:
    """Returns the (service, month, rows read, rows kept) rows that were added."""
    known = ingest_stats.latest(spark)
    added = []
    for (service, month), kept in sorted(silver_partition_rows(spark, SILVER).items()):
        bronze = bronze_path(service, month)
        if (service, month) in known or not bronze.exists():
            continue
        added.append((service, month, spark.read.parquet(str(bronze)).count(), kept))
    ingest_stats.append(spark, f"backfill-{uuid.uuid4().hex}", datetime.now(UTC), added)
    return added


def main() -> None:
    spark = build_session("backfill ingest stats")
    added = run(spark)
    for service, month, read, kept in added:
        print(f"{service} {month}: read {read:,}, kept {kept:,}, dropped {read - kept:,}")
    print(f"{len(added)} service-months added")
    spark.stop()


if __name__ == "__main__":
    main()
