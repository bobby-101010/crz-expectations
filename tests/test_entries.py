from datetime import date, datetime

import pytest

from pipeline.checks import entries as entry_checks
from pipeline.jobs.ingest_entries import latest_pull, pull_month
from pipeline.transforms_entries import (
    SILVER_ENTRIES_COLUMNS,
    conform_entries,
    daily_entries,
    unmapped_vehicle_classes,
)

CLASSES = {"cars_pickups_vans": "1 - Cars, Pickups and Vans", "tlc_taxi_fhv": "TLC Taxi/FHV"}
NOV = (date(2025, 11, 1), date(2025, 12, 1))
BRONZE_SCHEMA = (
    "toll_date string, toll_10_minute_block string, time_period string, vehicle_class string, "
    "detection_group string, detection_region string, CRZ_Entries string, "
    "excluded_roadway_entries string"
)


def bronze_row(block, vehicle_class, entries, excluded="0"):
    return (
        block[:10] + "T00:00:00.000",
        block,
        "Overnight",
        vehicle_class,
        "Lincoln Tunnel",
        "New Jersey",
        entries,
        excluded,
    )


def test_conform_entries_casts_maps_classes_and_keeps_the_repeated_hour(spark):
    bronze = spark.createDataFrame(
        [
            # The clock repeats 1:00 to 2:00 on this date, so the source has two rows per block.
            bronze_row("2025-11-02T01:10:00.000", "TLC Taxi/FHV", "50", "3"),
            bronze_row("2025-11-02T01:10:00.000", "TLC Taxi/FHV", "41"),
            bronze_row("2025-11-02T02:00:00.000", "1 - Cars, Pickups and Vans", "7.0"),
            bronze_row("2025-12-01T00:00:00.000", "TLC Taxi/FHV", "9"),  # next month, dropped
        ],
        BRONZE_SCHEMA,
    )

    silver = conform_entries(bronze, CLASSES, *NOV, date(2026, 11, 12))

    assert [(f.name, f.dataType.simpleString()) for f in silver.schema] == list(
        SILVER_ENTRIES_COLUMNS.items()
    )
    rows = silver.orderBy("interval_start", F_desc("crz_entries")).collect()
    assert [(r["interval_start"], r["vehicle_class"], r["crz_entries"]) for r in rows] == [
        (datetime(2025, 11, 2, 1, 10), "tlc_taxi_fhv", 50),
        (datetime(2025, 11, 2, 1, 10), "tlc_taxi_fhv", 41),
        (datetime(2025, 11, 2, 2, 0), "cars_pickups_vans", 7),
    ]
    assert rows[0]["toll_date"] == date(2025, 11, 2)
    assert rows[0]["excluded_roadway_entries"] == 3
    assert rows[0]["source_pull_date"] == date(2026, 11, 12)


def F_desc(name):
    from pyspark.sql import functions as F

    return F.desc(name)


def test_a_source_label_missing_from_the_catalog_is_reported(spark):
    bronze = spark.createDataFrame(
        [
            bronze_row("2025-11-02T01:10:00.000", "TLC Taxi/FHV", "1"),
            bronze_row("2025-11-02T01:10:00.000", "6 - Hovercraft", "1"),
        ],
        BRONZE_SCHEMA,
    )

    assert unmapped_vehicle_classes(bronze, CLASSES) == ["6 - Hovercraft"]
    assert unmapped_vehicle_classes(bronze.where("vehicle_class LIKE 'TLC%'"), CLASSES) == []


def test_conform_entries_fails_loudly_on_a_missing_column(spark):
    bronze = spark.createDataFrame([("2025-11-02T00:00:00.000",)], "toll_date string")

    with pytest.raises(ValueError, match="toll_10_minute_block"):
        conform_entries(bronze, CLASSES, *NOV, date(2026, 11, 12))


def test_daily_entries_sums_by_date_class_group_and_period(spark):
    silver = spark.createDataFrame(
        [
            (
                date(2025, 11, 2),
                datetime(2025, 11, 2, 1, 10),
                "Overnight",
                "tlc_taxi_fhv",
                "A",
                50,
                3,
            ),
            (
                date(2025, 11, 2),
                datetime(2025, 11, 2, 1, 10),
                "Overnight",
                "tlc_taxi_fhv",
                "A",
                41,
                0,
            ),
            (date(2025, 11, 2), datetime(2025, 11, 2, 9, 0), "Peak", "tlc_taxi_fhv", "A", 5, 1),
            (date(2025, 12, 1), datetime(2025, 12, 1, 9, 0), "Peak", "tlc_taxi_fhv", "A", 5, 1),
        ],
        "toll_date date, interval_start timestamp_ntz, time_period string, vehicle_class string, "
        "detection_group string, crz_entries bigint, excluded_roadway_entries bigint",
    )

    rows = daily_entries(silver, *NOV).collect()

    assert {
        (r["entry_date"], r["time_period"]): (r["crz_entries"], r["excluded_roadway_entries"])
        for r in rows
    } == {
        (date(2025, 11, 2), "Overnight"): (91, 3),
        (date(2025, 11, 2), "Peak"): (5, 1),
    }


def test_pull_month_pages_until_a_short_page_and_writes_the_header_once(tmp_path, monkeypatch):
    monkeypatch.setenv("BRONZE_DIR", str(tmp_path))
    data = [f"row{n}\n".encode() for n in range(5)]
    calls = []

    def get(url):
        calls.append(url)
        offset = int(url.split("offset=")[1].split("&")[0])
        return b"header\n" + b"".join(data[offset : offset + 2])

    path, rows = pull_month("2025-01", date(2026, 11, 12), get, page_rows=2)

    assert rows == 5 and len(calls) == 3
    assert path == tmp_path / "crz_entries" / "2025-01" / "pulled_2026-11-12.csv"
    assert path.read_bytes() == b"header\n" + b"".join(data)
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    assert "toll_date+%3E%3D+%272025-01-01T00%3A00%3A00%27" in calls[0]

    # The same day again keeps the file. A later day adds a new one beside it.
    assert pull_month("2025-01", date(2026, 11, 12), get, page_rows=2) == (path, 5)
    assert len(calls) == 3
    later, _ = pull_month("2025-01", date(2026, 11, 19), get, page_rows=2)
    assert latest_pull("2025-01") == later and path.exists()


def test_pull_month_leaves_no_file_when_the_source_has_no_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("BRONZE_DIR", str(tmp_path))

    assert pull_month("2027-01", date(2026, 11, 12), lambda url: b"header\n") == (None, 0)
    assert list((tmp_path / "crz_entries" / "2027-01").iterdir()) == []
    assert latest_pull("2027-01") is None


def test_entries_days_complete_fails_on_a_gap_and_respects_launch_and_latest():
    january = {date(2025, 1, day) for day in range(5, 32)}

    full = entry_checks.entries_days_complete("2025-01", january, date(2025, 2, 10))
    assert (full.status, full.observed) == ("pass", 0.0)

    gap = entry_checks.entries_days_complete(
        "2025-01", january - {date(2025, 1, 20)}, date(2025, 2, 10)
    )
    assert (gap.status, gap.observed) == ("fail", 1.0)
    assert "2025-01-20" in gap.message

    partial = {date(2026, 11, day) for day in range(1, 8)}
    assert (
        entry_checks.entries_days_complete("2026-11", partial, date(2026, 11, 7)).status == "pass"
    )


def test_cbd_zone_membership_warns_below_95_percent():
    assert entry_checks.cbd_zone_membership(1000, 960).status == "pass"
    low = entry_checks.cbd_zone_membership(1000, 900)
    assert (low.status, low.observed) == ("warn", 0.9)


def test_entries_freshness_counts_days_behind():
    assert entry_checks.entries_freshness(date(2026, 10, 31), date(2026, 10, 31)).status == "pass"
    behind = entry_checks.entries_freshness(date(2026, 10, 31), date(2026, 11, 7))
    assert (behind.status, behind.observed) == ("warn", 7)
    assert entry_checks.entries_freshness(date(2026, 10, 31), None).status == "warn"
