from datetime import date, datetime, timedelta

import pytest

from pipeline.baselines import baselines, sliced_series
from pipeline.transforms import daily_trip_slices

JAN = (date(2025, 1, 1), date(2025, 2, 1))


def test_slices_classify_each_trip_by_which_ends_are_in_the_zone(spark):
    zones = spark.createDataFrame(
        [(161, True), (162, True), (7, False)], "location_id int, in_cbd boolean"
    )
    silver = spark.createDataFrame(
        [
            ("yellow", None, datetime(2025, 1, 5, 8, 5), 161, 162, 0.75),
            ("yellow", None, datetime(2025, 1, 5, 8, 50), 161, 162, 0.0),
            ("yellow", None, datetime(2025, 1, 5, 8, 10), 161, 7, 0.75),
            ("yellow", None, datetime(2025, 1, 5, 9, 0), 7, 162, 0.75),
            ("fhvhv", "HV0003", datetime(2025, 1, 5, 9, 0), 7, 7, 1.5),
            ("fhvhv", "HV0003", datetime(2025, 1, 5, 9, 0), None, 999, None),
            ("fhvhv", "HV0003", datetime(2025, 2, 1, 0, 0), 161, 162, 1.5),  # next month
        ],
        "service string, operator_code string, pickup_at timestamp_ntz, pickup_zone_id int, "
        "dropoff_zone_id int, cbd_congestion_fee double",
    )

    rows = daily_trip_slices(silver, zones, *JAN).collect()

    assert {
        (r["service"], r["operator_code"], r["zone_relation"], r["pickup_hour"]): (
            r["trips"],
            r["fee_trips"],
        )
        for r in rows
    } == {
        ("yellow", None, "both_in", 8): (2, 1),
        ("yellow", None, "pickup_in", 8): (1, 1),
        ("yellow", None, "dropoff_in", 9): (1, 1),
        ("fhvhv", "HV0003", "neither", 9): (2, 1),
    }
    assert {r["trip_date"] for r in rows} == {date(2025, 1, 5)}


def test_baseline_uses_the_same_weekday_of_the_prior_eight_weeks_without_holidays(spark):
    first = date(2026, 3, 2)  # a Monday
    mondays = [first + timedelta(weeks=n) for n in range(10)]
    values = [(day, float(10 * (n + 1))) for n, day in enumerate(mondays)]
    values.append((first + timedelta(days=1), 999.0))  # a Tuesday, which must not mix in
    daily = spark.createDataFrame(values, "metric_date date, value double")
    holidays = spark.createDataFrame([(mondays[3],)], "holiday_date date")

    rows = baselines(sliced_series(daily, "crz_entries", None), holidays).collect()
    by_date = {r["baseline_date"]: r for r in rows}

    # Fewer than six usable values: no row. That covers the first seven Mondays and the Tuesday.
    assert set(by_date) == {mondays[7], mondays[8], mondays[9]}

    # Monday 8 looks back at Mondays 1 to 7 without the holiday: 10, 20, 30, 50, 60, 70.
    assert (by_date[mondays[7]]["n_obs"], by_date[mondays[7]]["p50"]) == (6, 40.0)

    # Monday 9 has 10, 20, 30, 50, 60, 70, 80. Linear interpolation gives 16, 50 and 74.
    ninth = by_date[mondays[8]]
    assert ninth["n_obs"] == 7
    assert (ninth["p10"], ninth["p50"], ninth["p90"]) == pytest.approx((16.0, 50.0, 74.0))
    assert (ninth["metric"], ninth["slice_key"], ninth["slice_value"]) == (
        "crz_entries",
        "all",
        "all",
    )
    assert ninth["method"] == "same_weekday_trailing_8"

    # Monday 10 no longer reaches Monday 1, which is nine weeks back.
    assert by_date[mondays[9]]["p50"] == 60.0


def test_sliced_series_names_the_slice_and_drops_null_values(spark):
    daily = spark.createDataFrame(
        [(date(2026, 3, 2), "HV0003", 5), (date(2026, 3, 2), None, 7)],
        "metric_date date, operator_code string, value bigint",
    )

    rows = sliced_series(daily, "tlc_trips", "operator_code").collect()

    assert [(r["slice_key"], r["slice_value"], r["value"]) for r in rows] == [
        ("operator_code", "HV0003", 5)
    ]
