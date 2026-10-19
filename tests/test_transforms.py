from datetime import date, datetime

import pytest

from pipeline.transforms import SILVER_COLUMNS, conform_trips, daily_trips

JAN = (date(2025, 1, 1), date(2025, 2, 1))


def test_conform_yellow_maps_columns_and_drops_stray_dates(spark):
    bronze = spark.createDataFrame(
        [
            (datetime(2025, 1, 4, 23, 50), datetime(2025, 1, 5, 0, 10), 161, 236, 2.5, 0.75),
            (datetime(2024, 12, 31, 23, 59), datetime(2025, 1, 1, 0, 5), 1, 2, 1.0, 0.0),
        ],
        "tpep_pickup_datetime timestamp, tpep_dropoff_datetime timestamp, "
        "PULocationID bigint, DOLocationID bigint, trip_distance double, "
        "cbd_congestion_fee double",
    )

    silver = conform_trips(bronze, "yellow", "2025-01", *JAN)

    assert [(f.name, f.dataType.simpleString()) for f in silver.schema] == list(
        SILVER_COLUMNS.items()
    )
    assert [row.asDict() for row in silver.collect()] == [
        {
            "service": "yellow",
            "operator_code": None,
            "pickup_at": datetime(2025, 1, 4, 23, 50),
            "dropoff_at": datetime(2025, 1, 5, 0, 10),
            "pickup_zone_id": 161,
            "dropoff_zone_id": 236,
            "trip_miles": 2.5,
            "cbd_congestion_fee": 0.75,
            "source_month": "2025-01",
        }
    ]


def test_conform_fhvhv_before_2025_has_null_fee(spark):
    bronze = spark.createDataFrame(
        [("HV0003", datetime(2023, 1, 9, 8, 0), datetime(2023, 1, 9, 8, 30), 79, 148, 3.1)],
        "hvfhs_license_num string, pickup_datetime timestamp_ntz, "
        "dropoff_datetime timestamp_ntz, pulocationid int, dolocationid int, "
        "trip_miles double",
    )

    row = conform_trips(
        bronze, "fhvhv", "2023-01", date(2023, 1, 1), date(2023, 2, 1)
    ).first()

    assert row["operator_code"] == "HV0003" # type: ignore
    assert row["pickup_zone_id"] == 79 # type: ignore
    assert row["cbd_congestion_fee"] is None # type: ignore


def test_conform_fails_loudly_when_a_required_column_is_missing(spark):
    bronze = spark.createDataFrame(
        [(datetime(2025, 1, 5, 8, 0),)], "tpep_pickup_datetime timestamp"
    )

    with pytest.raises(ValueError, match="tpep_dropoff_datetime"):
        conform_trips(bronze, "yellow", "2025-01", *JAN)


def test_daily_trips_counts_by_date_and_service(spark):
    silver = spark.createDataFrame(
        [
            ("yellow", datetime(2025, 1, 5, 8, 0), 0.75),
            ("yellow", datetime(2025, 1, 5, 9, 0), 0.0),
            ("fhvhv", datetime(2025, 1, 5, 9, 0), 1.5),
            ("fhvhv", datetime(2025, 1, 6, 9, 0), None),
            ("fhvhv", datetime(2025, 2, 1, 0, 0), 1.5),  # next month, excluded
        ],
        "service string, pickup_at timestamp_ntz, cbd_congestion_fee double",
    )

    result = daily_trips(silver, *JAN).collect()

    assert {
        (r["trip_date"], r["service"]): (r["trips"], r["cbd_fee_trips"]) for r in result
    } == {
        (date(2025, 1, 5), "yellow"): (2, 1),
        (date(2025, 1, 5), "fhvhv"): (1, 1),
        (date(2025, 1, 6), "fhvhv"): (1, 0),
    }
