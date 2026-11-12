"""Scoring: an expectation's observed value and its verdict (spec section 7.6)."""

import re
from dataclasses import dataclass
from datetime import date

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from pipeline.metrics import Catalog, Metric, daily_series
from pipeline.months import month_bounds
from pipeline.registry import Entry, Window

BASELINES = "local.gold.baselines"
CHECK_RESULTS = "local.checks.results"

# Gold table -> the check targets it is built from. A failing check on any of them,
# overlapping an entry's dates, makes the verdict `data_issue`.
LINEAGE = {
    "gold.daily_trip_slices": {
        "silver.trips",
        "bronze/yellow",
        "bronze/fhvhv",
        "checks.ingest_stats",
        "reference.cbd_zones",
    },
    "gold.daily_entries": {"silver.crz_entries", "bronze/crz_entries"},
}

ALL_TIME = (date.min, date.max)


@dataclass(frozen=True)
class Observation:
    value: float | None
    note: str | None = None


@dataclass(frozen=True)
class FailingCheck:
    check_id: str
    target_table: str
    partition_value: str


def base_metrics(metric: Metric, catalog: Catalog) -> list[Metric]:
    """The sum metrics a metric is computed from: itself, or a ratio's two parts."""
    if metric.kind == "sum":
        return [metric]
    return [catalog.metrics[part["metric"]] for part in (metric.numerator, metric.denominator)]


def window_sum(spark: SparkSession, metric: Metric, filters: dict, window: Window) -> float | None:
    """A sum metric added up over a window. None if the window has no rows."""
    total = (
        daily_series(spark, metric, window.start, window.end, filters=filters)
        .agg(F.sum("value").alias("total"))
        .first()["total"]
    )
    return None if total is None else float(total)


def window_value(
    spark: SparkSession, metric: Metric, catalog: Catalog, filters: dict, window: Window
) -> float | None:
    """A window's total for a sum metric, or the ratio of its two totals for a ratio metric."""
    if metric.kind == "sum":
        return window_sum(spark, metric, filters, window)
    parts = []
    for part in (metric.numerator, metric.denominator):
        base = catalog.metrics[part["metric"]]
        parts.append(window_sum(spark, base, part.get("filters", {}), window))
    top, bottom = parts
    return None if top is None or not bottom else top / bottom


def change_vs_period(window_total: float | None, comparison_total: float | None) -> Observation:
    """Percent change of the window against the comparison window."""
    if window_total is None or not comparison_total:
        return Observation(None, "no data in the window or the comparison window")
    return Observation(100 * (window_total / comparison_total - 1))


def value_range(metric: Metric, window_total: float | None, days: int) -> Observation:
    """The daily mean of a sum metric over the window, or a ratio metric's window ratio."""
    if window_total is None:
        return Observation(None, "no data in the window")
    return Observation(window_total if metric.kind == "ratio" else window_total / days)


def share_within_baseline(days: list[tuple[float, float | None, float | None]]) -> Observation:
    """Percent of days whose value lies in that day's p10 to p90 band, both ends included.

    Each item is (value, p10, p90). A day with no baseline is left out of the count
    and named in the note.
    """
    judged = [(value, low, high) for value, low, high in days if low is not None]
    unjudged = len(days) - len(judged)
    note = (
        f"{unjudged} of {len(days)} days have no baseline and are not counted" if unjudged else None
    )
    if not judged:
        return Observation(None, note or "no days in the window")
    inside = sum(1 for value, low, high in judged if low <= value <= high)
    return Observation(100 * inside / len(judged), note)


def within_baseline(spark: SparkSession, metric: Metric, entry: Entry) -> Observation:
    """`share_within_baseline` for an entry, from the daily series and gold.baselines."""
    if metric.kind != "sum" or len(entry.filters) > 1:
        return Observation(None, "baselines exist for one slice of a sum metric at most")
    slice_key, slice_value = next(iter(entry.filters.items()), ("all", "all"))
    band = (
        spark.table(BASELINES)
        .where(F.col("metric") == metric.name)
        .where((F.col("slice_key") == slice_key) & (F.col("slice_value") == str(slice_value)))
        .select(F.col("baseline_date").alias("metric_date"), "p10", "p90")
    )
    rows = (
        daily_series(spark, metric, entry.window.start, entry.window.end, filters=entry.filters)
        .join(band, "metric_date", "left")
        .collect()
    )
    return share_within_baseline([(float(r["value"]), r["p10"], r["p90"]) for r in rows])


def observe(spark: SparkSession, entry: Entry, catalog: Catalog) -> Observation:
    """An entry's observed value, in the unit of its comparison."""
    metric = catalog.metrics[entry.metric]
    if entry.comparison == "within_baseline":
        return within_baseline(spark, metric, entry)
    total = window_value(spark, metric, catalog, entry.filters, entry.window)
    if entry.comparison == "value_range":
        return value_range(metric, total, entry.window.days)
    comparison = window_value(
        spark, metric, catalog, entry.filters, entry.effective_comparison_window()
    )
    return change_vs_period(total, comparison)


def latest_loaded(spark: SparkSession, metric: Metric, catalog: Catalog) -> date | None:
    """The latest date every source of a metric has. None if a source is missing or empty."""
    latest = []
    for base in base_metrics(metric, catalog):
        table = f"local.{base.source}"
        if not spark.catalog.tableExists(table):
            return None
        newest = spark.table(table).agg(F.max(base.date_column).alias("newest")).first()["newest"]
        if newest is None:
            return None
        latest.append(newest)
    return min(latest)


def partition_dates(partition_value: str) -> tuple[date, date]:
    """The dates a check result covers.

    'yellow/2025-01' and '2025-01' are a month, 'fhvhv/2025' and '2025' a year, and
    anything else is all time.
    """
    month = re.search(r"(?:^|/)(\d{4}-\d{2})$", partition_value)
    if month:
        start, end = month_bounds(month.group(1))
        return start, date.fromordinal(end.toordinal() - 1)
    year = re.search(r"(?:^|/)(\d{4})$", partition_value)
    if year:
        return date(int(year.group(1)), 1, 1), date(int(year.group(1)), 12, 31)
    return ALL_TIME


def current_failures(spark: SparkSession) -> list[FailingCheck]:
    """Checks whose most recent result, per check, table and partition, is `fail`."""
    if not spark.catalog.tableExists(CHECK_RESULTS):
        return []
    results = spark.table(CHECK_RESULTS)
    newest = results.groupBy("check_id", "target_table", "partition_value").agg(
        F.max("checked_at").alias("checked_at")
    )
    rows = (
        results.join(newest, ["check_id", "target_table", "partition_value", "checked_at"])
        .where("status = 'fail'")
        .select("check_id", "target_table", "partition_value")
        .distinct()
        .collect()
    )
    return [FailingCheck(r["check_id"], r["target_table"], r["partition_value"]) for r in rows]


def failing_checks_for(entry: Entry, catalog: Catalog, failures: list[FailingCheck]) -> list[str]:
    """Ids of failing checks on the entry's source tables that overlap its windows."""
    targets = set()
    for base in base_metrics(catalog.metrics[entry.metric], catalog):
        targets |= LINEAGE.get(base.source, set())
    windows = [entry.window, *filter(None, [entry.effective_comparison_window()])]
    return sorted(
        {
            failure.check_id
            for failure in failures
            if failure.target_table in targets
            and any(w.overlaps(*partition_dates(failure.partition_value)) for w in windows)
        }
    )


def decide(entry: Entry, latest: date | None, failing: list[str], observed: float | None) -> str:
    """The verdict, in the spec's order of precedence."""
    if not entry.measurable:
        return "not_scoreable"
    if latest is None or entry.window.end > latest:
        return "pending"
    if failing:
        return "data_issue"
    if observed is None:
        return "data_issue"
    if entry.expected.low <= observed <= entry.expected.high:
        return "held"
    return "violated_low" if observed < entry.expected.low else "violated_high"
