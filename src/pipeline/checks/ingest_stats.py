"""Rows read and kept by each silver load, in `checks.ingest_stats`."""

from datetime import datetime

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

TABLE = "local.checks.ingest_stats"

SCHEMA = (
    "run_id string, loaded_at timestamp, service string, source_month string, "
    "rows_read bigint, rows_kept bigint"
)


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.checks")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            run_id STRING,
            loaded_at TIMESTAMP,
            service STRING,
            source_month STRING,
            rows_read BIGINT,
            rows_kept BIGINT
        ) USING iceberg
        """
    )


def append(
    spark: SparkSession,
    run_id: str,
    loaded_at: datetime,
    rows: list[tuple[str, str, int, int]],
) -> None:
    """Add one row per (service, month, rows read, rows kept). Append-only."""
    if not rows:
        return
    ensure_table(spark)
    records = [(run_id, loaded_at, *row) for row in rows]
    spark.createDataFrame(records, SCHEMA).writeTo(TABLE).append()


def latest(spark: SparkSession) -> dict[tuple[str, str], tuple[int, int]]:
    """(service, month) -> (rows read, rows kept) from the most recent load of each."""
    ensure_table(spark)
    newest_first = Window.partitionBy("service", "source_month").orderBy(F.desc("loaded_at"))
    rows = (
        spark.table(TABLE)
        .withColumn("position", F.row_number().over(newest_first))
        .where("position = 1")
        .collect()
    )
    return {(r["service"], r["source_month"]): (r["rows_read"], r["rows_kept"]) for r in rows}
