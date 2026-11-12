"""Compute drivers for the latest scoring run and append them to `expectations.drivers`."""

from dataclasses import astuple

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from pipeline.drivers import NO_VALUE, DriverRow, driver_rows
from pipeline.jobs.score import TABLE as VERDICTS
from pipeline.metrics import Metric, daily_series, load_catalog
from pipeline.registry import Entry, Window, load_registry
from pipeline.session import build_session

TABLE = "local.expectations.drivers"
SCORED = ("held", "violated_low", "violated_high")

SCHEMA = (
    "run_id string, expectation_id string, dimension string, slice_value string, "
    "comparison_value double, observed_value double, expected_value double, gap double, "
    "share_of_gap double, gap_rank int"
)


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.expectations")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            run_id STRING,
            expectation_id STRING,
            dimension STRING,
            slice_value STRING,
            comparison_value DOUBLE,
            observed_value DOUBLE,
            expected_value DOUBLE,
            gap DOUBLE,
            share_of_gap DOUBLE,
            gap_rank INT
        ) USING iceberg
        """
    )


def slice_totals(
    spark: SparkSession, metric: Metric, entry: Entry, window: Window, dimension: str
) -> dict[str, float]:
    """A sum metric over a window, per value of one dimension. A null value is `(none)`."""
    rows = (
        daily_series(spark, metric, window.start, window.end, by=dimension, filters=entry.filters)
        .groupBy(F.coalesce(F.col(dimension).cast("string"), F.lit(NO_VALUE)).alias("slice_value"))
        .agg(F.sum("value").alias("total"))
        .collect()
    )
    return {row["slice_value"]: float(row["total"]) for row in rows}


def entry_drivers(spark: SparkSession, entry: Entry, metric: Metric) -> list[DriverRow]:
    """Driver rows for every dimension an entry lists."""
    rows: list[DriverRow] = []
    for dimension in entry.drivers:
        observed = slice_totals(spark, metric, entry, entry.window, dimension)
        comparison = slice_totals(
            spark, metric, entry, entry.effective_comparison_window(), dimension
        )
        rows.extend(
            driver_rows(dimension, observed, comparison, entry.expected.low, entry.expected.high)
        )
    return rows


def run(spark: SparkSession, entries: list[Entry] | None = None) -> list[tuple]:
    """Drivers for the latest scoring run. Returns the rows written.

    Only `change_vs_period` entries that were held or violated get drivers. A scoring
    run that already has drivers is left alone, so a second call writes nothing.
    """
    ensure_table(spark)
    if not spark.catalog.tableExists(VERDICTS):
        return []
    verdicts = spark.table(VERDICTS)
    latest = verdicts.orderBy(F.desc("scored_at")).select("run_id").first()
    if latest is None:
        return []
    run_id = latest["run_id"]
    if spark.table(TABLE).where(F.col("run_id") == run_id).limit(1).count():
        return []

    catalog = load_catalog()
    by_id = {e.id: e for e in (load_registry(catalog=catalog) if entries is None else entries)}
    scored = verdicts.where((F.col("run_id") == run_id) & F.col("verdict").isin(*SCORED)).collect()

    rows = []
    for verdict in scored:
        entry = by_id.get(verdict["expectation_id"])
        if entry is None or entry.comparison != "change_vs_period" or not entry.drivers:
            continue
        for driver in entry_drivers(spark, entry, catalog.metrics[entry.metric]):
            rows.append((run_id, entry.id, *astuple(driver)))
    if rows:
        spark.createDataFrame(rows, SCHEMA).writeTo(TABLE).append()
    return rows


def main() -> None:
    spark = build_session("drivers")
    rows = run(spark)
    if not rows:
        print("no drivers written: no scored entries, or this scoring run already has them")
    shown = None
    for run_id, entry_id, dimension, name, before, after, expected, gap, share, rank in rows:
        if (entry_id, dimension) != shown:
            print(f"\n{entry_id} by {dimension} (scoring run {run_id[:8]})")
            shown = (entry_id, dimension)
        if rank <= 5:
            share_text = "" if share is None else f"{100 * share:+.0f}% of the gap"
            print(
                f"  {rank}. {name:<14} comparison {before:>13,.0f}  observed {after:>13,.0f}  "
                f"expected {expected:>13,.0f}  gap {gap:>+13,.0f}  {share_text}"
            )
    spark.stop()


if __name__ == "__main__":
    main()
