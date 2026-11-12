from datetime import datetime

import pytest

from pipeline.checks import trips
from pipeline.checks.profile import profile_trips
from pipeline.checks.thresholds import Thresholds
from pipeline.jobs.checks import latest_published, prior_months
from pipeline.months import shift_month

T = Thresholds(
    volume_low=0.8,
    volume_high=1.25,
    dropped_share_max=0.01,
    required_null_share_max=0.0,
    ends_before_start_share_max=0.01,
)

CLEAN = {
    "rows": 1000,
    "null_pickup_at": 0,
    "null_dropoff_at": 0,
    "null_pickup_zone_id": 0,
    "null_dropoff_zone_id": 0,
    "ends_before_start": 0,
    "fee_recorded": 1000,
    "fee_trips": 400,
}


def test_shift_month_crosses_years_both_ways():
    assert shift_month("2025-01", -2) == "2024-11"
    assert shift_month("2025-11", 3) == "2026-02"
    assert prior_months("2025-02", 3) == ["2025-01", "2024-12", "2024-11"]


def test_profile_counts_everything_in_one_pass(spark):
    silver = spark.createDataFrame(
        [
            ("yellow", "2025-01", datetime(2025, 1, 5, 8), datetime(2025, 1, 5, 9), 1, 2, 0.75),
            ("yellow", "2025-01", datetime(2025, 1, 5, 8), datetime(2025, 1, 5, 7), 1, None, 0.0),
            ("yellow", "2025-01", datetime(2025, 1, 6, 8), None, None, 2, None),
            ("fhvhv", "2024-12", datetime(2024, 12, 6, 8), datetime(2024, 12, 6, 9), 3, 4, None),
        ],
        "service string, source_month string, pickup_at timestamp_ntz, dropoff_at timestamp_ntz, "
        "pickup_zone_id int, dropoff_zone_id int, cbd_congestion_fee double",
    )

    profiles = {
        (r["service"], r["source_month"]): r.asDict() for r in profile_trips(silver).collect()
    }

    assert profiles[("yellow", "2025-01")] == {
        "service": "yellow",
        "source_month": "2025-01",
        "rows": 3,
        "null_pickup_at": 0,
        "null_dropoff_at": 1,
        "null_pickup_zone_id": 1,
        "null_dropoff_zone_id": 1,
        "ends_before_start": 1,
        "fee_recorded": 2,
        "fee_trips": 1,
    }
    assert profiles[("fhvhv", "2024-12")]["fee_recorded"] == 0


def test_schema_required_columns_ignores_case_and_allows_a_missing_fee():
    columns = ["hvfhs_license_num", "pickup_datetime", "dropoff_datetime", "pulocationid"]
    columns += ["dolocationid", "trip_miles"]

    assert trips.schema_required_columns(columns, "fhvhv", "2023-01").status == "pass"

    broken = trips.schema_required_columns(columns[:-1], "fhvhv", "2023-01")
    assert (broken.status, broken.observed) == ("fail", 1.0)
    assert "trip_miles" in broken.message


def test_silver_volume_warns_outside_the_band_and_needs_three_prior_months():
    prior = [100, 110, 90, 105]  # median 102.5

    assert trips.silver_volume("yellow", "2025-01", 100, prior, T).status == "pass"
    assert trips.silver_volume("yellow", "2025-01", 60, prior, T).status == "warn"
    assert trips.silver_volume("yellow", "2025-01", 140, prior, T).status == "warn"
    assert trips.silver_volume("yellow", "2025-01", 100, prior, T).observed == pytest.approx(
        100 / 102.5
    )
    assert trips.silver_volume("yellow", "2023-02", 100, [100, 100], T) is None


def test_dropped_share_warns_above_the_threshold():
    assert trips.dropped_share("yellow", "2025-01", 1000, 995, T).status == "pass"
    high = trips.dropped_share("yellow", "2025-01", 1000, 900, T)
    assert (high.status, high.observed) == ("warn", pytest.approx(0.1))


def test_required_nulls_fails_on_the_worst_column():
    assert trips.required_nulls("yellow", "2025-01", CLEAN, T).status == "pass"

    result = trips.required_nulls("yellow", "2025-01", CLEAN | {"null_dropoff_zone_id": 5}, T)
    assert (result.status, result.observed) == ("fail", pytest.approx(0.005))
    assert "highest share is dropoff_zone_id" in result.message


def test_dropoff_before_pickup_warns_above_the_threshold():
    assert trips.dropoff_before_pickup("yellow", "2025-01", CLEAN, T).status == "pass"
    result = trips.dropoff_before_pickup("yellow", "2025-01", CLEAN | {"ends_before_start": 20}, T)
    assert (result.status, result.observed) == ("warn", pytest.approx(0.02))


def test_fee_presence_flips_at_2025_01():
    before = CLEAN | {"fee_recorded": 0, "fee_trips": 0}

    assert trips.fee_presence("yellow", "2024-12", before).status == "pass"
    assert trips.fee_presence("yellow", "2025-01", CLEAN).status == "pass"

    leaked = trips.fee_presence("yellow", "2024-12", before | {"fee_recorded": 3})
    assert (leaked.status, leaked.observed) == ("fail", 3)
    gap = trips.fee_presence("yellow", "2025-01", CLEAN | {"fee_recorded": 990})
    assert (gap.status, gap.observed) == ("fail", 10)


def test_fee_before_launch_allows_the_known_residual():
    assert trips.fee_before_launch(4, T).status == "pass"
    assert trips.fee_before_launch(10, T).status == "pass"
    assert trips.fee_before_launch(11, T).status == "warn"


def test_freshness_counts_months_behind():
    assert trips.freshness("yellow", "2026-08", "2026-08").status == "pass"

    behind = trips.freshness("yellow", "2026-08", "2026-09")
    assert (behind.status, behind.observed) == ("warn", 1)

    unreachable = trips.freshness("yellow", "2026-08", None)
    assert (unreachable.status, unreachable.observed) == ("warn", None)


def test_latest_published_stops_at_the_first_missing_month():
    published = {"2026-09", "2026-10", "2026-12"}

    assert latest_published("yellow", "2026-08", lambda _, m: m in published) == "2026-10"
    assert latest_published("yellow", "2026-08", lambda _, m: False) == "2026-08"

    def unreachable(service, month):
        raise OSError("no network")

    assert latest_published("yellow", "2026-08", unreachable) is None


def test_regression_totals_passes_on_the_baseline_and_fails_on_any_difference():
    baseline = dict(trips.REGRESSION_TOTALS)
    assert [r.status for r in trips.regression_totals(baseline)] == ["pass"] * 6

    trips_2025, recorded, fee_trips = baseline[("yellow", 2025)]
    changed = baseline | {("yellow", 2025): (trips_2025, recorded, fee_trips + 1)}
    del changed[("fhvhv", 2023)]

    by_scope = {r.partition_value: r for r in trips.regression_totals(changed)}
    assert by_scope["yellow/2025"].status == "fail"
    assert by_scope["fhvhv/2023"].status == "fail"
    assert by_scope["fhvhv/2023"].observed is None
    assert by_scope["yellow/2024"].status == "pass"
