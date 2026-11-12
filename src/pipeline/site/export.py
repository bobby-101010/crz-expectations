"""Read the warehouse and write the small JSON files the status page is rendered from."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from pipeline.metrics import Catalog, Metric, daily_series
from pipeline.registry import Entry, Window

VERDICTS = "local.expectations.verdicts"
DRIVERS = "local.expectations.drivers"
CHECKS = "local.checks.results"
BASELINES = "local.gold.baselines"
TOP_DRIVERS = 3
WORST_FIRST = {"fail": 0, "warn": 1, "pass": 2}


def latest_verdicts(spark: SparkSession) -> list[dict]:
    """The rows of the most recent scoring run."""
    verdicts = spark.table(VERDICTS)
    latest = verdicts.orderBy(F.desc("scored_at")).select("run_id").first()
    if latest is None:
        return []
    rows = verdicts.where(F.col("run_id") == latest["run_id"]).collect()
    return [row.asDict(recursive=True) for row in rows]


def top_drivers(spark: SparkSession, run_id: str) -> list[dict]:
    """The three largest gaps per expectation and dimension for one scoring run."""
    if not spark.catalog.tableExists(DRIVERS):
        return []
    rows = (
        spark.table(DRIVERS)
        .where((F.col("run_id") == run_id) & (F.col("gap_rank") <= TOP_DRIVERS))
        .orderBy("expectation_id", "dimension", "gap_rank")
        .collect()
    )
    return [row.asDict() for row in rows]


def latest_checks(spark: SparkSession) -> DataFrame:
    """The most recent result for each check, table and partition."""
    results = spark.table(CHECKS)
    newest = results.groupBy("check_id", "target_table", "partition_value").agg(
        F.max("checked_at").alias("checked_at")
    )
    return results.join(newest, ["check_id", "target_table", "partition_value", "checked_at"])


def check_summary(rows: list[dict]) -> list[dict]:
    """Latest results -> one line per check: how many passed, warned and failed, and the worst."""
    by_check: dict[str, list[dict]] = {}
    for row in rows:
        by_check.setdefault(row["check_id"], []).append(row)
    summary = []
    for check_id, results in sorted(by_check.items()):
        counts = {status: sum(r["status"] == status for r in results) for status in WORST_FIRST}
        worst = min(results, key=lambda r: (WORST_FIRST[r["status"]], r["partition_value"]))
        summary.append(
            {
                "check_id": check_id,
                "target_table": worst["target_table"],
                "status": worst["status"],
                "results": len(results),
                **counts,
                "detail": worst["message"] if worst["status"] != "pass" else "",
                "detail_scope": worst["partition_value"] if worst["status"] != "pass" else "",
                "checked_at": max(r["checked_at"] for r in results),
            }
        )
    return summary


def metric_daily(
    spark: SparkSession, metric: Metric, catalog: Catalog, filters: dict, window: Window
) -> dict[date, float]:
    """A metric's value per day. A ratio metric is the ratio of its two parts each day."""
    if metric.kind == "sum":
        rows = daily_series(spark, metric, window.start, window.end, filters=filters).collect()
        return {row["metric_date"]: float(row["value"]) for row in rows}
    parts = []
    for part in (metric.numerator, metric.denominator):
        base = catalog.metrics[part["metric"]]
        parts.append(metric_daily(spark, base, catalog, part.get("filters", {}), window))
    top, bottom = parts
    return {day: top[day] / bottom[day] for day in sorted(top) if bottom.get(day)}


def entry_series(spark: SparkSession, entry: Entry, catalog: Catalog) -> dict:
    """Daily values for an entry's window, and its comparison window or baseline band."""
    metric = catalog.metrics[entry.metric]
    window = metric_daily(spark, metric, catalog, entry.filters, entry.window)
    series = {"window": [[day, value] for day, value in sorted(window.items())]}
    comparison = entry.effective_comparison_window()
    if comparison is not None:
        values = metric_daily(spark, metric, catalog, entry.filters, comparison)
        series["comparison"] = [[day, value] for day, value in sorted(values.items())]
    if entry.comparison == "within_baseline" and len(entry.filters) <= 1:
        slice_key, slice_value = next(iter(entry.filters.items()), ("all", "all"))
        band = (
            spark.table(BASELINES)
            .where(F.col("metric") == metric.name)
            .where((F.col("slice_key") == slice_key) & (F.col("slice_value") == str(slice_value)))
            .where(F.col("baseline_date").between(entry.window.start, entry.window.end))
            .orderBy("baseline_date")
            .collect()
        )
        series["band"] = [[r["baseline_date"], r["p10"], r["p90"]] for r in band]
    return series


def expectation_record(entry: Entry, verdict: dict) -> dict:
    """What the page shows for one expectation: the registry entry joined to its verdict."""
    comparison = entry.effective_comparison_window()
    return {
        "id": entry.id,
        "statement": entry.statement,
        "origin": entry.origin,
        "author": entry.author,
        "recorded": entry.recorded,
        "elicited_in": entry.elicited_in,
        "metric": entry.metric,
        "filters": entry.filters,
        "comparison": entry.comparison,
        "window": [entry.window.start, entry.window.end],
        "comparison_window": [comparison.start, comparison.end] if comparison else None,
        "confidence": entry.confidence,
        "driver_dimensions": entry.drivers,
        "entry_note": entry.note,
        "reported_outcome": entry.reported_outcome.model_dump() if entry.reported_outcome else None,
        "verdict": verdict["verdict"],
        "observed": verdict["observed"],
        "expected_low": verdict["expected_low"],
        "expected_high": verdict["expected_high"],
        "unit": verdict["unit"],
        "failing_checks": verdict["failing_checks"],
        "verdict_note": verdict["note"],
    }


def calibration(expectations: list[dict]) -> dict:
    """The expert's record on prospective entries only, against their stated confidence."""
    prospective = [e for e in expectations if e["origin"] == "prospective"]
    scored = [e for e in prospective if e["verdict"] in ("held", "violated_low", "violated_high")]
    stated = [e["confidence"] for e in scored if e["confidence"] is not None]
    return {
        "prospective": len(prospective),
        "scored": len(scored),
        "held": sum(e["verdict"] == "held" for e in scored),
        "mean_confidence": sum(stated) / len(stated) if stated else None,
    }


def collect(spark: SparkSession, entries: list[Entry], catalog: Catalog, repo_url: str) -> dict:
    """Everything the page needs, as plain data keyed by output file."""
    verdict_rows = latest_verdicts(spark)
    by_id = {row["expectation_id"]: row for row in verdict_rows}
    scored_entries = [entry for entry in entries if entry.id in by_id]
    expectations = [expectation_record(entry, by_id[entry.id]) for entry in scored_entries]

    run = verdict_rows[0] if verdict_rows else {}
    checks = [row.asDict() for row in latest_checks(spark).collect()]
    freshness = sorted(
        (
            {key: row[key] for key in ("partition_value", "status", "message", "checked_at")}
            for row in checks
            if row["check_id"] == "freshness"
        ),
        key=lambda row: row["partition_value"],
    )
    return {
        "meta": {
            "generated_at": datetime.now(UTC),
            "scored_at": run.get("scored_at"),
            "run_id": run.get("run_id"),
            "registry_commit": run.get("registry_commit"),
            "repo_url": repo_url,
            "calibration": calibration(expectations),
        },
        "verdicts": expectations,
        "drivers": top_drivers(spark, run["run_id"]) if run else [],
        "checks": check_summary(checks),
        "freshness": freshness,
        "series": {
            entry.id: entry_series(spark, entry, catalog)
            for entry in scored_entries
            if entry.measurable
        },
    }


def write(data: dict, folder: Path) -> list[Path]:
    """One JSON file per key. Dates and times are written as ISO strings."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in data.items():
        path = folder / f"{name}.json"
        path.write_text(json.dumps(content, indent=1, default=_iso, sort_keys=True) + "\n")
        written.append(path)
    return written


def _iso(value):
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"cannot write {type(value).__name__} as JSON")
