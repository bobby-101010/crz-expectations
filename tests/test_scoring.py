from datetime import date

import pytest

from pipeline.metrics import load_catalog
from pipeline.registry import Entry
from pipeline.scoring import (
    ALL_TIME,
    FailingCheck,
    change_vs_period,
    decide,
    failing_checks_for,
    partition_dates,
    share_within_baseline,
    value_range,
)

CATALOG = load_catalog()


def entry(**changes) -> Entry:
    fields = {
        "id": "example",
        "statement": "Yellow trips fall.",
        "origin": "prospective",
        "author": "human",
        "recorded": date(2026, 11, 11),
        "approved_by": "owner",
        "approved_on": date(2026, 11, 11),
        "metric": "tlc_trips",
        "comparison": "change_vs_period",
        "window": {"start": date(2025, 3, 10), "end": date(2025, 3, 16)},
        "expected": {"low": -5.0, "high": 5.0, "unit": "percent"},
        "confidence": 80,
        "rationale": "Because.",
    }
    return Entry.model_validate(fields | changes)


def test_change_vs_period_is_a_percent_change():
    assert change_vs_period(110.0, 100.0).value == pytest.approx(10.0)
    assert change_vs_period(90.0, 100.0).value == pytest.approx(-10.0)
    assert change_vs_period(None, 100.0).value is None
    assert change_vs_period(110.0, 0.0).value is None


def test_value_range_is_a_daily_mean_for_sums_and_the_window_ratio_for_ratios():
    assert value_range(CATALOG.metrics["tlc_trips"], 700.0, 7).value == 100.0
    assert value_range(CATALOG.metrics["fhvhv_per_yellow"], 5.0, 7).value == 5.0
    assert value_range(CATALOG.metrics["tlc_trips"], None, 7).value is None


def test_share_within_baseline_includes_both_ends_and_skips_days_without_a_band():
    days = [(10.0, 10.0, 20.0), (20.0, 10.0, 20.0), (21.0, 10.0, 20.0), (9.0, 10.0, 20.0)]
    inside = share_within_baseline(days)
    assert (inside.value, inside.note) == (50.0, None)

    with_gap = share_within_baseline([*days[:2], (15.0, None, None)])
    assert with_gap.value == 100.0
    assert with_gap.note == "1 of 3 days have no baseline and are not counted"

    assert share_within_baseline([(15.0, None, None)]).value is None


def test_partition_dates_reads_months_years_and_everything_else_as_all_time():
    assert partition_dates("yellow/2025-01") == (date(2025, 1, 1), date(2025, 1, 31))
    assert partition_dates("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
    assert partition_dates("fhvhv/2025") == (date(2025, 1, 1), date(2025, 12, 31))
    assert partition_dates("2025") == (date(2025, 1, 1), date(2025, 12, 31))
    assert partition_dates("all") == ALL_TIME
    assert partition_dates("yellow") == ALL_TIME


def test_failing_checks_count_only_on_source_tables_and_overlapping_dates():
    failures = [
        FailingCheck("required_nulls", "silver.trips", "yellow/2025-03"),  # in the window
        FailingCheck("fee_presence", "silver.trips", "fhvhv/2024-03"),  # in the comparison window
        FailingCheck("schema_required_columns", "bronze/yellow", "yellow/2025-06"),  # other month
        FailingCheck("entries_days_complete", "silver.crz_entries", "2025-03"),  # other source
        FailingCheck("regression_totals", "silver.trips", "yellow/2023"),  # other year
    ]

    assert failing_checks_for(entry(), CATALOG, failures) == ["fee_presence", "required_nulls"]

    entries_entry = entry(metric="crz_entries")
    assert failing_checks_for(entries_entry, CATALOG, failures) == ["entries_days_complete"]

    ratio = entry(
        metric="fhvhv_per_yellow",
        comparison="value_range",
        expected={"low": 4.0, "high": 6.0, "unit": "ratio"},
    )
    assert failing_checks_for(ratio, CATALOG, failures) == ["required_nulls"]

    table_wide = [FailingCheck("fee_before_launch", "silver.trips", "all")]
    assert failing_checks_for(entry(), CATALOG, table_wide) == ["fee_before_launch"]


def test_verdicts_follow_the_order_of_precedence():
    loaded = date(2025, 12, 31)
    unmeasurable = entry(
        measurable=False,
        not_measurable_reason="No baseline.",
        metric=None,
        comparison=None,
        expected=None,
        confidence=None,
    )

    assert decide(unmeasurable, None, ["required_nulls"], None) == "not_scoreable"
    assert decide(entry(), date(2025, 3, 15), ["required_nulls"], 0.0) == "pending"
    assert decide(entry(), None, [], None) == "pending"
    assert decide(entry(), loaded, ["required_nulls"], 0.0) == "data_issue"
    assert decide(entry(), loaded, [], None) == "data_issue"
    assert decide(entry(), loaded, [], -5.0) == "held"
    assert decide(entry(), loaded, [], 5.0) == "held"
    assert decide(entry(), loaded, [], -5.01) == "violated_low"
    assert decide(entry(), loaded, [], 5.01) == "violated_high"
    assert decide(entry(), date(2025, 3, 16), [], 0.0) == "held"
