"""Data checks on the MTA entries data and on the zone reference table.

Rules and breach levels are in docs/SPEC.md section 7.1.
"""

from datetime import date, timedelta

from pipeline.checks.core import FAIL, WARN, CheckResult, judge
from pipeline.months import month_bounds

SILVER = "silver.crz_entries"
ENTRIES_BEGIN = date(2025, 1, 5)
ZONE_FEE_SHARE_MIN = 0.95  # set by the spec


def entries_days_complete(month: str, dates_with_rows: set[date], latest: date) -> CheckResult:
    """Every date in the month, up to the latest loaded date, has rows."""
    start, end = month_bounds(month)
    first = max(start, ENTRIES_BEGIN)
    last = min(end - timedelta(days=1), latest)
    expected = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    missing = [day for day in expected if day not in dates_with_rows]
    return CheckResult(
        "entries_days_complete",
        SILVER,
        month,
        judge(not missing, FAIL),
        float(len(missing)),
        "0 dates without rows",
        f"missing {[day.isoformat() for day in missing]}"
        if missing
        else f"all {len(expected)} dates from {first} to {last} have rows",
    )


def cbd_zone_membership(same_zone_trips: int, with_fee: int) -> CheckResult:
    """Trips that start and end in one in-zone zone should nearly all carry the fee."""
    share = with_fee / same_zone_trips if same_zone_trips else 0.0
    return CheckResult(
        "cbd_zone_membership",
        "reference.cbd_zones",
        "2025",
        judge(share >= ZONE_FEE_SHARE_MIN, WARN),
        share,
        f"at least {ZONE_FEE_SHARE_MIN}",
        f"{with_fee:,} of {same_zone_trips:,} trips that start and end in the same in-zone zone "
        "carry the fee (2025-01-05 to 2025-12-31)",
    )


def entries_freshness(latest_loaded: date, latest_published: date | None) -> CheckResult:
    """Latest date loaded against the latest date the source has published."""
    if latest_published is None:
        return CheckResult(
            "freshness",
            "bronze/crz_entries",
            "crz_entries",
            WARN,
            None,
            "0 days behind",
            f"loaded through {latest_loaded}; the source could not be reached",
        )
    behind = (latest_published - latest_loaded).days
    return CheckResult(
        "freshness",
        "bronze/crz_entries",
        "crz_entries",
        judge(behind <= 0, WARN),
        behind,
        "0 days behind",
        f"loaded through {latest_loaded}; published through {latest_published}",
    )
