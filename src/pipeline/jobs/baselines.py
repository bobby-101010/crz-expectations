"""Build gold.baselines for every catalog metric marked `baseline: true`. Reads gold only."""

from datetime import date
from functools import reduce

from pyspark.sql import DataFrame, SparkSession

from pipeline.baselines import baselines, sliced_series
from pipeline.metrics import Catalog, daily_series, load_catalog
from pipeline.session import build_session

HOLIDAYS = "local.reference.holidays"
TABLE = "local.gold.baselines"
EVERYTHING = (date(2000, 1, 1), date(2100, 1, 1))


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.gold")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            metric STRING,
            slice_key STRING,
            slice_value STRING,
            baseline_date DATE,
            method STRING,
            p10 DOUBLE,
            p50 DOUBLE,
            p90 DOUBLE,
            n_obs INT
        ) USING iceberg
        PARTITIONED BY (metric, months(baseline_date))
        """
    )


def all_series(spark: SparkSession, catalog: Catalog) -> DataFrame | None:
    """Every baseline metric, unsliced and by each single dimension, in one long frame."""
    parts = []
    for metric in catalog.metrics.values():
        if not metric.baseline:
            continue
        if not spark.catalog.tableExists(f"local.{metric.source}"):
            continue
        for dimension in (None, *metric.dimensions):
            daily = daily_series(spark, metric, *EVERYTHING, by=dimension)
            parts.append(sliced_series(daily, metric.name, dimension))
    return reduce(DataFrame.unionByName, parts) if parts else None


def run(spark: SparkSession) -> int:
    """Rebuild every baseline from gold. Returns the number of rows written."""
    ensure_table(spark)
    series = all_series(spark, load_catalog())
    if series is None:
        return 0
    baselines(series, spark.table(HOLIDAYS)).writeTo(TABLE).overwritePartitions()
    return spark.table(TABLE).count()


def main() -> None:
    spark = build_session("baselines")
    rows = run(spark)
    print(f"gold.baselines: {rows:,} rows")
    (
        spark.table(TABLE)
        .groupBy("metric", "slice_key")
        .count()
        .orderBy("metric", "slice_key")
        .show(50, truncate=False)
    )
    spark.stop()


if __name__ == "__main__":
    main()
