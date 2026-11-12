"""The check runner and the ingest stats, end to end, with Iceberg."""

import pytest

from pipeline.checks import ingest_stats
from pipeline.checks.core import RESULTS_TABLE
from pipeline.checks.profile import silver_partition_rows
from pipeline.checks.thresholds import Thresholds
from pipeline.jobs import backfill_ingest_stats, checks, silver_trips

pytestmark = pytest.mark.integration

T = Thresholds(
    volume_low=0.5,
    volume_high=2.0,
    dropped_share_max=0.1,
    required_null_share_max=0.0,
    ends_before_start_share_max=0.0,
)


def published_through_2025_02(service, month):
    return month <= "2025-02"


def test_the_silver_job_records_rows_read_and_kept(lake, loaded):
    assert ingest_stats.latest(lake) == {
        ("yellow", "2025-01"): (4, 3),
        ("fhvhv", "2025-01"): (3, 3),
        ("fhvhv", "2024-12"): (2, 2),
    }
    assert backfill_ingest_stats.run(lake) == []


def test_partition_metadata_gives_rows_per_service_and_month(lake, loaded):
    assert silver_partition_rows(lake, silver_trips.TABLE) == {
        ("yellow", "2025-01"): 3,
        ("fhvhv", "2025-01"): 3,
        ("fhvhv", "2024-12"): 2,
    }


def test_checks_refuse_to_run_without_thresholds(lake, loaded):
    with pytest.raises(RuntimeError, match="approved thresholds"):
        checks.run(lake, thresholds=None)


def test_checks_for_one_month_and_for_all_are_appended_to_the_results_table(lake, loaded):
    one_month = checks.run(lake, "2025-01", T, published_through_2025_02)
    by_key = {(r.check_id, r.partition_value): r for r in one_month}

    assert {r.partition_value for r in one_month} == {"yellow/2025-01", "fhvhv/2025-01"}
    assert by_key[("schema_required_columns", "yellow/2025-01")].status == "pass"
    assert by_key[("required_nulls", "fhvhv/2025-01")].status == "pass"
    assert by_key[("fee_presence", "yellow/2025-01")].status == "pass"
    # One of the four yellow rows read was outside the month.
    dropped = by_key[("dropped_share", "yellow/2025-01")]
    assert (dropped.status, dropped.observed) == ("warn", 0.25)
    # Fewer than three prior months, so volume is not judged.
    assert not [r for r in one_month if r.check_id == "silver_volume"]

    everything = checks.run(lake, None, T, published_through_2025_02)
    by_key = {(r.check_id, r.partition_value): r for r in everything}

    assert by_key[("fee_presence", "fhvhv/2024-12")].status == "pass"
    assert (
        by_key[("fee_before_launch", "all")].status,
        by_key[("fee_before_launch", "all")].observed,
    ) == ("pass", 0)
    assert (by_key[("freshness", "yellow")].status, by_key[("freshness", "yellow")].observed) == (
        "warn",
        1,
    )
    # The fixtures are not the real history, so the regression baseline must not match.
    regression = [r for r in everything if r.check_id == "regression_totals"]
    assert [r.status for r in regression] == ["fail"] * 6

    stored = lake.table(RESULTS_TABLE)
    assert stored.count() == len(one_month) + len(everything)
    assert stored.select("run_id").distinct().count() == 2
    assert dict(stored.dtypes)["checked_at"] == "timestamp"
    assert {r["status"] for r in stored.select("status").distinct().collect()} == {
        "pass",
        "warn",
        "fail",
    }
