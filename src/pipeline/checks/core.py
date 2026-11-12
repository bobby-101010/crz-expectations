"""Check results, and the Iceberg table that keeps them."""

from dataclasses import astuple, dataclass
from datetime import datetime

from pyspark.sql import SparkSession

RESULTS_TABLE = "local.checks.results"

PASS, WARN, FAIL = "pass", "warn", "fail"

RESULTS_SCHEMA = (
    "run_id string, checked_at timestamp, check_id string, target_table string, "
    "partition_value string, status string, observed double, threshold string, message string"
)


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    target_table: str
    partition_value: str
    status: str
    observed: float | None
    threshold: str
    message: str


def judge(ok: bool, on_breach: str) -> str:
    return PASS if ok else on_breach


def ensure_results_table(spark: SparkSession) -> None:
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.checks")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {RESULTS_TABLE} (
            run_id STRING,
            checked_at TIMESTAMP,
            check_id STRING,
            target_table STRING,
            partition_value STRING,
            status STRING,
            observed DOUBLE,
            threshold STRING,
            message STRING
        ) USING iceberg
        """
    )


def append_results(
    spark: SparkSession, run_id: str, checked_at: datetime, results: list[CheckResult]
) -> None:
    """Add one row per result. The table is append-only, so history is kept."""
    if not results:
        return
    ensure_results_table(spark)
    rows = [
        (run_id, checked_at, *astuple(r)[:4], _as_float(r.observed), r.threshold, r.message)
        for r in results
    ]
    spark.createDataFrame(rows, RESULTS_SCHEMA).writeTo(RESULTS_TABLE).append()


def _as_float(value: float | None) -> float | None:
    return None if value is None else float(value)
