"""Score every registry entry and append one verdict each to `expectations.verdicts`."""

import os
import uuid
from datetime import UTC, datetime

from pyspark.sql import SparkSession

from pipeline.metrics import Catalog, load_catalog
from pipeline.registry import Entry, load_registry
from pipeline.scoring import (
    current_failures,
    decide,
    failing_checks_for,
    latest_loaded,
    observe,
)
from pipeline.session import build_session

TABLE = "local.expectations.verdicts"

SCHEMA = (
    "run_id string, scored_at timestamp, registry_commit string, expectation_id string, "
    "window_start date, window_end date, observed double, expected_low double, "
    "expected_high double, unit string, verdict string, failing_checks array<string>, note string"
)


def ensure_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.expectations")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            run_id STRING,
            scored_at TIMESTAMP,
            registry_commit STRING,
            expectation_id STRING,
            window_start DATE,
            window_end DATE,
            observed DOUBLE,
            expected_low DOUBLE,
            expected_high DOUBLE,
            unit STRING,
            verdict STRING,
            failing_checks ARRAY<STRING>,
            note STRING
        ) USING iceberg
        """
    )


def score_entry(spark: SparkSession, entry: Entry, catalog: Catalog, failures: list) -> dict:
    """One entry -> its verdict row, without the run columns."""
    row = {
        "expectation_id": entry.id,
        "window_start": entry.window.start,
        "window_end": entry.window.end,
        "observed": None,
        "expected_low": None,
        "expected_high": None,
        "unit": None,
        "verdict": "not_scoreable",
        "failing_checks": [],
        "note": entry.not_measurable_reason,
    }
    if not entry.measurable:
        return row

    row |= {
        "expected_low": entry.expected.low,
        "expected_high": entry.expected.high,
        "unit": entry.expected.unit,
        "note": None,
    }
    latest = latest_loaded(spark, catalog.metrics[entry.metric], catalog)
    if latest is None or entry.window.end > latest:
        row["verdict"] = decide(entry, latest, [], None)
        row["note"] = f"data is loaded through {latest}" if latest else "no data is loaded"
        return row

    failing = failing_checks_for(entry, catalog, failures)
    observation = observe(spark, entry, catalog)
    row |= {
        "observed": observation.value,
        "failing_checks": failing,
        "verdict": decide(entry, latest, failing, observation.value),
        "note": observation.note,
    }
    return row


def run(
    spark: SparkSession, registry_commit: str, entries: list[Entry] | None = None
) -> list[dict]:
    """Score the registry and append the verdicts. Returns the rows written."""
    catalog = load_catalog()
    entries = load_registry(catalog=catalog) if entries is None else entries
    failures = current_failures(spark)
    run_id, scored_at = uuid.uuid4().hex, datetime.now(UTC)
    rows = [
        {"run_id": run_id, "scored_at": scored_at, "registry_commit": registry_commit}
        | score_entry(spark, entry, catalog, failures)
        for entry in entries
    ]
    ensure_table(spark)
    columns = [field.split()[0] for field in SCHEMA.split(", ")]
    spark.createDataFrame([tuple(row[c] for c in columns) for row in rows], SCHEMA).writeTo(
        TABLE
    ).append()
    return rows


def main() -> None:
    registry_commit = os.environ.get("REGISTRY_COMMIT", "unknown")
    spark = build_session("score")
    rows = run(spark, registry_commit)
    print(f"registry commit {registry_commit}")
    for row in rows:
        observed = "" if row["observed"] is None else f"{row['observed']:.2f}"
        expected = (
            ""
            if row["expected_low"] is None
            else f"{row['expected_low']} to {row['expected_high']}"
        )
        failing = f" failing: {row['failing_checks']}" if row["failing_checks"] else ""
        print(
            f"{row['verdict']:<14} {row['expectation_id']:<48} observed {observed:>8}  "
            f"expected {expected} {row['unit'] or ''}{failing}"
        )
    spark.stop()


if __name__ == "__main__":
    main()
