"""Reference tables, the entries jobs, trip slices, baselines and their checks, with Iceberg."""

from datetime import date, timedelta

import pytest

from pipeline.checks.thresholds import Thresholds
from pipeline.jobs import (
    baselines,
    checks,
    daily_entries,
    daily_trip_slices,
    daily_trips,
    reference,
    silver_entries,
)
from pipeline.jobs.ingest_entries import month_dir
from pipeline.transforms_entries import SILVER_ENTRIES_COLUMNS

pytestmark = pytest.mark.integration

T = Thresholds(0.5, 2.0, 0.5, 0.0, 0.0)

ENTRIES_HEADER = (
    '"toll_date","toll_hour","toll_10_minute_block","minute_of_hour","hour_of_day",'
    '"day_of_week_int","day_of_week","toll_week","time_period","vehicle_class",'
    '"detection_group","detection_region","crz_entries","excluded_roadway_entries"\n'
)


def entries_line(block, vehicle_class, entries, excluded):
    day = block[:10]
    return (
        f'"{day}T00:00:00.000","{block[:13]}:00:00.000","{block}","0","0","1","Sunday",'
        f'"{day}T00:00:00.000","Overnight","{vehicle_class}","Lincoln Tunnel","New Jersey",'
        f'"{entries}","{excluded}"\n'
    )


def test_reference_job_builds_zones_and_holidays(lake, reference_tables):
    assert reference_tables[:2] == (5, 2)
    assert reference_tables[2] > 50

    zones = {r["location_id"]: r for r in lake.table(reference.ZONES_TABLE).collect()}
    assert zones[161]["in_cbd"] and not zones[236]["in_cbd"]
    assert zones[161]["pulled_on"] == date(2026, 11, 12)
    assert dict(lake.table(reference.HOLIDAYS_TABLE).dtypes) == {
        "holiday_date": "date",
        "name": "string",
    }


def test_entries_jobs_build_silver_and_gold_from_the_latest_pull(lake):
    folder = month_dir("2025-01")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pulled_2026-11-05.csv").write_text(
        ENTRIES_HEADER + entries_line("2025-01-05T00:00:00.000", "TLC Taxi/FHV", 1, 0)
    )
    (folder / "pulled_2026-11-12.csv").write_text(
        ENTRIES_HEADER
        + entries_line("2025-01-05T00:00:00.000", "TLC Taxi/FHV", 50, 2)
        + entries_line("2025-01-05T00:10:00.000", "TLC Taxi/FHV", 40, 0)
        + entries_line("2025-01-06T00:00:00.000", "1 - Cars, Pickups and Vans", 30, 1)
        + entries_line("2025-02-01T00:00:00.000", "TLC Taxi/FHV", 9, 0)  # next month, dropped
    )

    assert silver_entries.run(lake, "2025-01") == (4, 3)
    silver = lake.table(silver_entries.TABLE)
    assert [(f.name, f.dataType.simpleString()) for f in silver.schema] == list(
        SILVER_ENTRIES_COLUMNS.items()
    )
    assert {r["source_pull_date"] for r in silver.collect()} == {date(2026, 11, 12)}

    daily_entries.run(lake, "2025-01")
    gold = lake.table(daily_entries.TABLE).collect()
    assert {
        (r["entry_date"], r["vehicle_class"]): (r["crz_entries"], r["excluded_roadway_entries"])
        for r in gold
    } == {
        (date(2025, 1, 5), "tlc_taxi_fhv"): (90, 2),
        (date(2025, 1, 6), "cars_pickups_vans"): (30, 1),
    }


def test_an_unmapped_vehicle_class_stops_the_silver_job(lake):
    folder = month_dir("2025-03")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pulled_2026-11-12.csv").write_text(
        ENTRIES_HEADER + entries_line("2025-03-01T00:00:00.000", "6 - Hovercraft", 1, 0)
    )

    with pytest.raises(ValueError, match="Hovercraft"):
        silver_entries.run(lake, "2025-03")


def test_slice_totals_equal_daily_trips_for_every_day(lake, loaded, reference_tables):
    for month in ("2025-01", "2024-12"):
        daily_trip_slices.run(lake, month)

    slices = lake.table(daily_trip_slices.TABLE)
    by_day = {
        (r["trip_date"], r["service"]): (r["trips"], r["fee_trips"])
        for r in slices.groupBy("trip_date", "service")
        .agg({"trips": "sum", "fee_trips": "sum"})
        .selectExpr(
            "trip_date", "service", "`sum(trips)` AS trips", "`sum(fee_trips)` AS fee_trips"
        )
        .collect()
    }
    daily = {
        (r["trip_date"], r["service"]): (r["trips"], r["cbd_fee_trips"])
        for r in lake.table(daily_trips.TABLE).collect()
    }
    assert by_day == daily

    # The January 4 trip starts in zone 161 (in) and ends in zone 236 (out).
    january_4 = slices.where("trip_date = '2025-01-04'").collect()
    assert [(r["zone_relation"], r["pickup_hour"], r["trips"]) for r in january_4] == [
        ("pickup_in", 23, 1)
    ]


def test_baselines_job_writes_percentiles_for_catalog_metrics(lake, reference_tables):
    # Nine Mondays of entries, written straight to gold, give the ninth a full history.
    first = date(2025, 6, 2)
    rows = [
        (first + timedelta(weeks=n), "tlc_taxi_fhv", "Lincoln Tunnel", "Peak", 100 + 10 * n, 0)
        for n in range(9)
    ]
    daily_entries.ensure_table(lake)
    lake.createDataFrame(
        rows,
        "entry_date date, vehicle_class string, detection_group string, time_period string, "
        "crz_entries bigint, excluded_roadway_entries bigint",
    ).writeTo(daily_entries.TABLE).append()

    assert baselines.run(lake) > 0

    table = lake.table(baselines.TABLE)
    ninth = table.where(f"metric = 'crz_entries' AND baseline_date = '{rows[8][0]}'")
    by_slice = {(r["slice_key"], r["slice_value"]): r for r in ninth.collect()}
    assert set(by_slice) == {
        ("all", "all"),
        ("vehicle_class", "tlc_taxi_fhv"),
        ("detection_group", "Lincoln Tunnel"),
        ("time_period", "Peak"),
    }
    everything = by_slice[("all", "all")]
    assert (everything["n_obs"], everything["p50"]) == (8, 135.0)
    assert (everything["p10"], everything["p90"]) == pytest.approx((107.0, 163.0))
    assert dict(table.dtypes)["n_obs"] == "int"


def test_entries_and_zone_checks_run_once_their_tables_exist(lake, loaded, reference_tables):
    results = checks.collect(
        lake, None, T, lambda service, month: False, entries_probe=lambda: date(2025, 1, 7)
    )
    by_key = {(r.check_id, r.partition_value): r for r in results}

    assert by_key[("entries_days_complete", "2025-01")].status == "pass"
    fresh = by_key[("freshness", "crz_entries")]
    assert (fresh.status, fresh.observed) == ("warn", 1)
    # No fixture trip starts and ends in the same in-zone zone, so the share is 0.
    assert by_key[("cbd_zone_membership", "2025")].status == "warn"
