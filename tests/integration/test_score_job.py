"""The scoring job, end to end, with Iceberg: every kind of verdict, including `data_issue`."""

from datetime import UTC, date, datetime, timedelta

import pytest

from pipeline.checks.core import PASS, CheckResult, append_results
from pipeline.jobs import baselines, daily_entries, daily_trip_slices, score
from pipeline.registry import Entry
from pipeline.scoring import current_failures

pytestmark = pytest.mark.integration

COMMON = {
    "statement": "An example.",
    "author": "human",
    "recorded": date(2026, 11, 11),
    "approved_by": "owner",
    "approved_on": date(2026, 11, 11),
    "rationale": "Because.",
    "confidence": 80,
}
JAN_5 = {"start": date(2025, 1, 5), "end": date(2025, 1, 5)}
JAN_4 = {"start": date(2025, 1, 4), "end": date(2025, 1, 4)}

# Nine Mondays of entries: 100, 110, ... 180. The ninth is above its band of 107 to 163.
FIRST_MONDAY = date(2025, 8, 4)
NINTH_MONDAY = FIRST_MONDAY + timedelta(weeks=8)

ENTRIES = [
    Entry.model_validate(
        COMMON
        | {
            "id": "yellow-doubles",  # 2 trips on January 5 against 1 on January 4
            "origin": "retrospective",
            "metric": "tlc_trips",
            "filters": {"service": "yellow"},
            "comparison": "change_vs_period",
            "window": JAN_5,
            "comparison_window": JAN_4,
            "expected": {"low": 50.0, "high": 150.0, "unit": "percent"},
        }
    ),
    Entry.model_validate(
        COMMON
        | {
            "id": "ratio-too-low",  # 2 ride-hail trips over 2 yellow trips
            "origin": "retrospective",
            "metric": "fhvhv_per_yellow",
            "comparison": "value_range",
            "window": JAN_5,
            "expected": {"low": 2.0, "high": 3.0, "unit": "ratio"},
        }
    ),
    Entry.model_validate(
        COMMON
        | {
            "id": "ninth-monday-outside",
            "origin": "retrospective",
            "metric": "crz_entries",
            "comparison": "within_baseline",
            "window": {"start": NINTH_MONDAY, "end": NINTH_MONDAY},
            "expected": {"low": 50.0, "high": 100.0, "unit": "percent_of_days"},
        }
    ),
    Entry.model_validate(
        COMMON
        | {
            "id": "not-loaded-yet",
            "origin": "prospective",
            "metric": "tlc_trips",
            "comparison": "change_vs_period",
            "window": {"start": date(2025, 2, 3), "end": date(2025, 2, 9)},
            "expected": {"low": -5.0, "high": 5.0, "unit": "percent"},
        }
    ),
    Entry.model_validate(
        COMMON
        | {
            "id": "official-projection",
            "origin": "official",
            "sources": ["https://example.org/report"],
            "window": JAN_5,
            "measurable": False,
            "not_measurable_reason": "No observed series shares the baseline.",
            "confidence": None,
        }
    ),
]


@pytest.fixture(scope="module")
def gold(lake, loaded, reference_tables):
    daily_trip_slices.run(lake, "2025-01")
    daily_trip_slices.run(lake, "2024-12")
    daily_entries.ensure_table(lake)
    mondays = [
        (FIRST_MONDAY + timedelta(weeks=n), "buses", "Lincoln Tunnel", "Peak", 100 + 10 * n, 0)
        for n in range(9)
    ]
    lake.createDataFrame(
        mondays,
        "entry_date date, vehicle_class string, detection_group string, time_period string, "
        "crz_entries bigint, excluded_roadway_entries bigint",
    ).writeTo(daily_entries.TABLE).append()
    baselines.run(lake)

    # Earlier tests leave failing checks on the fixture data (it is not the real history).
    # Record a later pass for each, so this module starts with no failing checks.
    cleared = [
        CheckResult(f.check_id, f.target_table, f.partition_value, PASS, None, "", "cleared")
        for f in current_failures(lake)
    ]
    append_results(lake, "run-clear", datetime.now(UTC) + timedelta(seconds=1), cleared)


def test_scoring_gives_each_kind_of_verdict_and_appends_them(lake, gold):
    rows = {row["expectation_id"]: row for row in score.run(lake, "abc1234-dirty", ENTRIES)}

    doubles = rows["yellow-doubles"]
    assert (doubles["verdict"], doubles["observed"], doubles["unit"]) == ("held", 100.0, "percent")
    assert (doubles["expected_low"], doubles["expected_high"]) == (50.0, 150.0)

    assert (rows["ratio-too-low"]["verdict"], rows["ratio-too-low"]["observed"]) == (
        "violated_low",
        1.0,
    )
    assert (rows["ninth-monday-outside"]["verdict"], rows["ninth-monday-outside"]["observed"]) == (
        "violated_low",
        0.0,
    )
    pending = rows["not-loaded-yet"]
    assert (pending["verdict"], pending["observed"]) == ("pending", None)
    assert pending["note"] == "data is loaded through 2025-01-06"
    official = rows["official-projection"]
    assert (official["verdict"], official["expected_low"]) == ("not_scoreable", None)
    assert official["note"] == "No observed series shares the baseline."

    stored = lake.table(score.TABLE)
    assert stored.count() == 5
    assert dict(stored.dtypes)["failing_checks"] == "array<string>"
    assert {r["registry_commit"] for r in stored.collect()} == {"abc1234-dirty"}


def test_a_failing_check_on_the_inputs_turns_the_verdict_into_data_issue(lake, gold):
    target = ("required_nulls", "silver.trips", "yellow/2025-01")
    failed = CheckResult(*target, "fail", 0.2, "0", "nulls found")
    append_results(lake, "run-fail", datetime.now(UTC) + timedelta(seconds=2), [failed])

    rows = {row["expectation_id"]: row for row in score.run(lake, "abc1234", ENTRIES)}

    assert rows["yellow-doubles"]["verdict"] == "data_issue"
    assert rows["yellow-doubles"]["failing_checks"] == ["required_nulls"]
    assert rows["yellow-doubles"]["observed"] == 100.0
    assert rows["ratio-too-low"]["verdict"] == "data_issue"
    # Another source, another table: not affected.
    assert rows["ninth-monday-outside"]["verdict"] == "violated_low"
    # Precedence: pending and not_scoreable come before data_issue.
    assert rows["not-loaded-yet"]["verdict"] == "pending"
    assert rows["official-projection"]["verdict"] == "not_scoreable"

    # A later passing result for the same check and partition clears it.
    fixed = CheckResult(*target, PASS, 0.0, "0", "no nulls")
    append_results(lake, "run-pass", datetime.now(UTC) + timedelta(seconds=9), [fixed])
    rows = {row["expectation_id"]: row for row in score.run(lake, "abc1234", ENTRIES)}
    assert rows["yellow-doubles"]["verdict"] == "held"

    assert lake.table(score.TABLE).select("run_id").distinct().count() == 3
