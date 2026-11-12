"""Data checks on the TLC trip data. Each is a pure function of numbers already counted.

Rules and breach levels are in docs/SPEC.md section 7.1.
"""

from statistics import median

from pipeline.checks.core import FAIL, PASS, WARN, CheckResult, judge
from pipeline.checks.profile import REQUIRED_NOT_NULL
from pipeline.checks.thresholds import Thresholds
from pipeline.months import month_range
from pipeline.transforms import OPTIONAL_SOURCES, SOURCE_COLUMNS

SILVER = "silver.trips"
FEE_STARTS = "2025-01"
VOLUME_HISTORY_MONTHS = 6
VOLUME_HISTORY_MINIMUM = 3

# Trips, trips with a fee recorded, and fee trips per service and pickup year.
# From docs/SPEC.md section 3. A change to these is a bug until explained.
REGRESSION_TOTALS = {
    ("fhvhv", 2023): (232_490_020, 0, 0),
    ("fhvhv", 2024): (239_470_448, 0, 0),
    ("fhvhv", 2025): (243_589_684, 243_589_684, 82_780_798),
    ("yellow", 2023): (38_309_496, 0, 0),
    ("yellow", 2024): (41_169_300, 0, 0),
    ("yellow", 2025): (48_722_388, 48_722_388, 34_904_980),
}


def scope(service: str, month: str) -> str:
    return f"{service}/{month}"


def schema_required_columns(columns: list[str], service: str, month: str) -> CheckResult:
    present = {name.lower() for name in columns}
    required = [s for s in SOURCE_COLUMNS[service].values() if s not in OPTIONAL_SOURCES]
    missing = [name for name in required if name.lower() not in present]
    return CheckResult(
        "schema_required_columns",
        f"bronze/{service}",
        scope(service, month),
        judge(not missing, FAIL),
        float(len(missing)),
        "0 required columns missing",
        f"missing {missing}" if missing else f"all {len(required)} required columns present",
    )


def silver_volume(
    service: str, month: str, rows: int, prior_rows: list[int], t: Thresholds
) -> CheckResult | None:
    """Rows against the median of up to six prior months. No result with fewer than three."""
    if len(prior_rows) < VOLUME_HISTORY_MINIMUM:
        return None
    typical = median(prior_rows)
    ratio = rows / typical
    return CheckResult(
        "silver_volume",
        SILVER,
        scope(service, month),
        judge(t.volume_low <= ratio <= t.volume_high, WARN),
        ratio,
        f"{t.volume_low} to {t.volume_high} times the median of the prior months",
        f"{rows:,} rows against a median of {typical:,.0f} over {len(prior_rows)} prior months",
    )


def dropped_share(
    service: str, month: str, rows_read: int, rows_kept: int, t: Thresholds
) -> CheckResult:
    share = (rows_read - rows_kept) / rows_read if rows_read else 0.0
    return CheckResult(
        "dropped_share",
        "checks.ingest_stats",
        scope(service, month),
        judge(share <= t.dropped_share_max, WARN),
        share,
        f"at most {t.dropped_share_max}",
        f"{rows_read - rows_kept:,} of {rows_read:,} rows read were outside the month",
    )


def required_nulls(service: str, month: str, profile: dict, t: Thresholds) -> CheckResult:
    shares = {name: profile[f"null_{name}"] / profile["rows"] for name in REQUIRED_NOT_NULL}
    worst = max(shares, key=shares.get)
    counts = ", ".join(f"{name} {profile[f'null_{name}']:,}" for name in REQUIRED_NOT_NULL)
    return CheckResult(
        "required_nulls",
        SILVER,
        scope(service, month),
        judge(shares[worst] <= t.required_null_share_max, FAIL),
        shares[worst],
        f"null share at most {t.required_null_share_max} in each required column",
        f"nulls: {counts}; highest share is {worst}",
    )


def dropoff_before_pickup(service: str, month: str, profile: dict, t: Thresholds) -> CheckResult:
    share = profile["ends_before_start"] / profile["rows"]
    return CheckResult(
        "dropoff_before_pickup",
        SILVER,
        scope(service, month),
        judge(share <= t.ends_before_start_share_max, WARN),
        share,
        f"at most {t.ends_before_start_share_max}",
        f"{profile['ends_before_start']:,} of {profile['rows']:,} trips end before they start",
    )


def fee_presence(service: str, month: str, profile: dict) -> CheckResult:
    """Before 2025-01 no row has a fee value. From 2025-01 every row has one."""
    if month < FEE_STARTS:
        wrong = profile["fee_recorded"]
        rule, found = "fee is null for every row", f"{wrong:,} rows have a fee value"
    else:
        wrong = profile["rows"] - profile["fee_recorded"]
        rule, found = "fee is filled for every row", f"{wrong:,} rows have a null fee"
    return CheckResult(
        "fee_presence", SILVER, scope(service, month), judge(wrong == 0, FAIL), wrong, rule, found
    )


def fee_before_launch(fee_trips_before_launch: int, t: Thresholds) -> CheckResult:
    return CheckResult(
        "fee_before_launch",
        SILVER,
        "all",
        judge(fee_trips_before_launch <= t.fee_before_launch_max, WARN),
        fee_trips_before_launch,
        f"at most {t.fee_before_launch_max}",
        f"{fee_trips_before_launch:,} fee trips were dropped off before 2025-01-05 00:00",
    )


def freshness(service: str, latest_loaded: str, latest_published: str | None) -> CheckResult:
    """Latest month loaded against the latest month the source has published."""
    if latest_published is None:
        return CheckResult(
            "freshness",
            f"bronze/{service}",
            service,
            WARN,
            None,
            "0 months behind",
            f"loaded through {latest_loaded}; the source could not be reached",
        )
    behind = len(month_range(latest_loaded, latest_published)) - 1
    return CheckResult(
        "freshness",
        f"bronze/{service}",
        service,
        judge(behind == 0, WARN),
        behind,
        "0 months behind",
        f"loaded through {latest_loaded}; published through {latest_published}",
    )


def regression_totals(totals: dict[tuple[str, int], tuple[int, int, int]]) -> list[CheckResult]:
    """One result per service and year: trips, fee recorded, and fee trips equal the baseline."""
    results = []
    for (service, year), expected in sorted(REGRESSION_TOTALS.items()):
        actual = totals.get((service, year))
        if actual == expected:
            status, message = PASS, "trips, fee recorded, and fee trips match"
        else:
            status = FAIL
            message = f"expected {expected}, found {actual} (trips, fee recorded, fee trips)"
        results.append(
            CheckResult(
                "regression_totals",
                SILVER,
                f"{service}/{year}",
                status,
                None if actual is None else actual[0],
                f"{expected[0]:,} trips",
                message,
            )
        )
    return results
