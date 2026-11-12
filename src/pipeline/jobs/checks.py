import argparse
import urllib.error
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from pipeline.checks import ingest_stats, trips
from pipeline.checks.core import CheckResult, append_results, ensure_results_table
from pipeline.checks.profile import profile_trips, silver_partition_rows
from pipeline.checks.thresholds import APPROVED, Thresholds
from pipeline.jobs.ingest import bronze_path, tlc_url
from pipeline.months import month_bounds, month_range, shift_month
from pipeline.session import build_session

SILVER = "local.silver.trips"
LAUNCH = "2025-01-05 00:00:00"
FRESHNESS_LOOKAHEAD_MONTHS = 6

Probe = Callable[[str, str], bool]


def tlc_published(service: str, month: str) -> bool:
    """True if the source has this month's file. Raises if the host cannot be reached."""
    request = urllib.request.Request(
        tlc_url(service, month), method="HEAD", headers={"User-Agent": "crz-expectations"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30):
            return True
    except urllib.error.HTTPError as error:
        if error.code in (403, 404):
            return False
        raise


def latest_published(service: str, loaded: str, probe: Probe) -> str | None:
    """The last month in a row, from the loaded one on, that the source has. None if unreachable."""
    latest = loaded
    try:
        for month in month_range(
            shift_month(loaded, 1), shift_month(loaded, FRESHNESS_LOOKAHEAD_MONTHS)
        ):
            if not probe(service, month):
                break
            latest = month
    except OSError:
        return None
    return latest


def prior_months(month: str, count: int) -> list[str]:
    return [shift_month(month, -back) for back in range(1, count + 1)]


def month_profiles(spark: SparkSession, month: str | None) -> dict[tuple[str, str], dict]:
    silver = spark.table(SILVER)
    if month is not None:
        start, end = month_bounds(month)
        silver = silver.where(
            (F.col("pickup_at") >= F.lit(start)) & (F.col("pickup_at") < F.lit(end))
        )
    return {
        (row["service"], row["source_month"]): row.asDict()
        for row in profile_trips(silver).collect()
    }


def collect(
    spark: SparkSession, month: str | None, t: Thresholds, probe: Probe
) -> list[CheckResult]:
    """Run the checks for one month, or for every loaded month plus the table-wide checks."""
    partition_rows = silver_partition_rows(spark, SILVER)
    profiles = month_profiles(spark, month)
    stats = ingest_stats.latest(spark)
    results: list[CheckResult] = []

    for service, source_month in sorted(profiles):
        profile = profiles[(service, source_month)]

        bronze = bronze_path(service, source_month)
        if bronze.exists():
            columns = spark.read.parquet(str(bronze)).columns
            results.append(trips.schema_required_columns(columns, service, source_month))

        prior = [
            partition_rows[(service, earlier)]
            for earlier in prior_months(source_month, trips.VOLUME_HISTORY_MONTHS)
            if (service, earlier) in partition_rows
        ]
        volume = trips.silver_volume(service, source_month, profile["rows"], prior, t)
        if volume is not None:
            results.append(volume)

        if (service, source_month) in stats:
            read, kept = stats[(service, source_month)]
            results.append(trips.dropped_share(service, source_month, read, kept, t))

        results.append(trips.required_nulls(service, source_month, profile, t))
        results.append(trips.dropoff_before_pickup(service, source_month, profile, t))
        results.append(trips.fee_presence(service, source_month, profile))

    if month is None:
        early_fee_trips = (
            spark.table(SILVER)
            .where((F.col("cbd_congestion_fee") > 0) & (F.col("dropoff_at") < F.lit(LAUNCH)))
            .count()
        )
        results.append(trips.fee_before_launch(early_fee_trips, t))

        totals: dict[tuple[str, int], list[int]] = {}
        for (service, source_month), profile in profiles.items():
            year_total = totals.setdefault((service, int(source_month[:4])), [0, 0, 0])
            for position, name in enumerate(("rows", "fee_recorded", "fee_trips")):
                year_total[position] += profile[name]
        results.extend(trips.regression_totals({key: tuple(v) for key, v in totals.items()}))

        for service in sorted({service for service, _ in profiles}):
            loaded = max(m for s, m in profiles if s == service)
            results.append(
                trips.freshness(service, loaded, latest_published(service, loaded, probe))
            )

    return results


def run(
    spark: SparkSession,
    month: str | None = None,
    thresholds: Thresholds | None = APPROVED,
    probe: Probe = tlc_published,
) -> list[CheckResult]:
    """Run the checks and append their results to `checks.results`."""
    if thresholds is None:
        raise RuntimeError(
            "No approved thresholds. See docs/decisions/0007 and pipeline/checks/thresholds.py."
        )
    ensure_results_table(spark)
    results = collect(spark, month, thresholds, probe)
    append_results(spark, uuid.uuid4().hex, datetime.now(UTC), results)
    return results


def show_profile(spark: SparkSession) -> None:
    """Print the per-month numbers the thresholds are chosen from. Writes nothing."""
    partition_rows = silver_partition_rows(spark, SILVER)
    profiles = month_profiles(spark, None)
    stats = ingest_stats.latest(spark)
    print("service,month,rows,volume_ratio,dropped_share,null_share_max,ends_before_start_share")
    for service, month in sorted(profiles):
        profile = profiles[(service, month)]
        prior = [
            partition_rows[(service, earlier)]
            for earlier in prior_months(month, trips.VOLUME_HISTORY_MONTHS)
            if (service, earlier) in partition_rows
        ]
        wide_open = Thresholds(0, float("inf"), 1, 1, 1)
        volume = trips.silver_volume(service, month, profile["rows"], prior, wide_open)
        read, kept = stats.get((service, month), (None, None))
        cells = [
            service,
            month,
            profile["rows"],
            "" if volume is None else f"{volume.observed:.4f}",
            "" if not read else f"{(read - kept) / read:.3e}",
            f"{trips.required_nulls(service, month, profile, wide_open).observed:.3e}",
            f"{profile['ends_before_start'] / profile['rows']:.3e}",
        ]
        print(",".join(str(cell) for cell in cells))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="YYYY-MM. Without it, every loaded month is checked.")
    parser.add_argument("--profile", action="store_true", help="Print the numbers; write nothing.")
    args = parser.parse_args()

    spark = build_session(f"checks {args.month or 'all'}")
    if args.profile:
        show_profile(spark)
    else:
        results = run(spark, args.month)
        for result in results:
            if result.status != "pass":
                print(
                    f"{result.status.upper():5} {result.check_id} {result.partition_value}:"
                    f" {result.message}"
                )
        counts = Counter(result.status for result in results)
        print(
            f"{len(results)} results: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
        )
    spark.stop()


if __name__ == "__main__":
    main()
