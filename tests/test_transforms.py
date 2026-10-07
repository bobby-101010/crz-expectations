from datetime import date, datetime

from pipeline.jobs.daily_trips import month_bounds
from pipeline.transforms import daily_trips


def test_daily_trips_counts_and_drops_stray_dates(spark):
    rows = [
        (datetime(2025, 1, 5, 8, 0), 0.75),
        (datetime(2025, 1, 5, 9, 0), 0.0),
        (datetime(2025, 1, 6, 9, 0), None),
        (datetime(2024, 12, 31, 23, 59), 0.0),  # stray row from another month
    ]
    trips = spark.createDataFrame(
        rows, "tpep_pickup_datetime timestamp, cbd_congestion_fee double"
    )

    result = daily_trips(trips, date(2025, 1, 1), date(2025, 2, 1)).collect()

    assert {r["trip_date"]: (r["trips"], r["cbd_fee_trips"]) for r in result} == {
        date(2025, 1, 5): (2, 1),
        date(2025, 1, 6): (1, 0),
    }


def test_month_bounds_rolls_over_december():
    assert month_bounds("2025-12") == (date(2025, 12, 1), date(2026, 1, 1))
    