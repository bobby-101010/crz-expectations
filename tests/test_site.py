import json
import re
from pathlib import Path

from pipeline.site.charts import fmt, range_bar, series_chart
from pipeline.site.export import calibration, check_summary, write
from pipeline.site.render import load, render

REPO = "https://example.org/repo"

META = {
    "generated_at": "2026-11-12T05:51:00+00:00",
    "scored_at": "2026-11-12T05:31:00+00:00",
    "run_id": "run1",
    "registry_commit": "abc1234-dirty",
    "repo_url": REPO,
    "calibration": {"prospective": 1, "scored": 0, "held": 0, "mean_confidence": None},
}


def verdict(**changes):
    return {
        "id": "example-entry",
        "statement": "Trips <rise> a little.",
        "origin": "derived",
        "author": "ai_sme",
        "recorded": "2026-11-11",
        "elicited_in": "docs/elicitation/x.md",
        "metric": "tlc_trips",
        "filters": {"service": "yellow"},
        "comparison": "change_vs_period",
        "window": ["2025-01-05", "2026-01-03"],
        "comparison_window": ["2024-01-07", "2025-01-04"],
        "confidence": 80,
        "driver_dimensions": ["service"],
        "entry_note": "Not counted toward calibration.",
        "reported_outcome": None,
        "verdict": "held",
        "observed": 1.72,
        "expected_low": -2.5,
        "expected_high": 4.0,
        "unit": "percent",
        "failing_checks": [],
        "verdict_note": None,
    } | changes


def page(verdicts, drivers=(), series=None):
    data = {
        "meta": META,
        "verdicts": list(verdicts),
        "drivers": list(drivers),
        "checks": [
            {
                "check_id": "freshness",
                "target_table": "bronze/yellow",
                "status": "warn",
                "results": 3,
                "pass": 2,
                "warn": 1,
                "fail": 0,
                "detail": "one month behind",
                "detail_scope": "yellow",
                "checked_at": "2026-11-12T05:00:00+00:00",
            }
        ],
        "freshness": [
            {
                "partition_value": "yellow",
                "status": "warn",
                "message": "one month behind",
                "checked_at": "2026-11-12T05:00:00+00:00",
            }
        ],
        "series": series or {},
    }
    return render(data)


def test_numbers_are_formatted_in_their_unit():
    assert fmt(1.724, "percent") == "+1.72%"
    assert fmt(-4.86, "percent") == "-4.86%"
    assert fmt(71.43, "percent_of_days") == "71.4% of days"
    assert fmt(4.994, "ratio") == "4.99"
    assert fmt(1234567.8, None) == "1,234,568"


def test_range_bar_describes_itself_and_places_the_marker_inside_the_drawing():
    svg = range_bar(1.72, -2.5, 4.0, "percent")

    assert 'role="img"' in svg
    assert 'aria-label="Observed +1.72%. Expected -2.50% to +4.00%."' in svg
    marker = float(re.search(r'class="marker" x1="([\d.]+)"', svg).group(1))
    band = float(re.search(r'class="band" x="([\d.]+)"', svg).group(1))
    assert 0 < band < marker < 320

    pending = range_bar(None, -7.5, -1.0, "percent")
    assert "Not observed yet." in pending and "marker" not in pending

    outside = range_bar(9.0, -2.5, 4.0, "percent")
    assert 0 < float(re.search(r'class="marker" x1="([\d.]+)"', outside).group(1)) < 320


def test_series_chart_draws_the_window_the_comparison_and_a_band():
    svg = series_chart([1.0, 3.0, 2.0], [2.0, 2.0, 2.0], None, "Daily <trips>")

    assert svg.count("<polyline") == 2
    assert 'aria-label="Daily &lt;trips&gt;"' in svg

    banded = series_chart([5.0, 6.0], None, [(4.0, 7.0), (4.0, 7.0)], "x")
    assert "baseline-band" in banded
    assert series_chart([4.0], None, None, "x").count("<circle") == 1
    assert series_chart([], [], None, "x") == ""


def test_check_summary_counts_statuses_and_reports_the_worst():
    rows = [
        {
            "check_id": "required_nulls",
            "target_table": "silver.trips",
            "partition_value": p,
            "status": s,
            "message": m,
            "checked_at": "2026-11-12T05:00:00",
        }
        for p, s, m in (
            ("yellow/2025-01", "pass", "ok"),
            ("yellow/2025-02", "fail", "3 nulls"),
            ("yellow/2025-03", "warn", "odd"),
        )
    ]

    (summary,) = check_summary(rows)

    assert (summary["status"], summary["pass"], summary["warn"], summary["fail"]) == (
        "fail",
        1,
        1,
        1,
    )
    assert (summary["detail"], summary["detail_scope"]) == ("3 nulls", "yellow/2025-02")


def test_calibration_counts_only_prospective_entries():
    entries = [
        {"origin": "prospective", "verdict": "held", "confidence": 80},
        {"origin": "prospective", "verdict": "violated_low", "confidence": 90},
        {"origin": "prospective", "verdict": "pending", "confidence": 80},
        {"origin": "retrospective", "verdict": "held", "confidence": 95},
    ]

    assert calibration(entries) == {
        "prospective": 3,
        "scored": 2,
        "held": 1,
        "mean_confidence": 85.0,
    }


def test_the_page_shows_each_expectation_with_its_verdict_drivers_and_links():
    drivers = [
        {
            "expectation_id": "example-entry",
            "dimension": "service",
            "slice_value": "yellow",
            "gap": 4637079.0,
            "share_of_gap": 4.24,
            "gap_rank": 1,
        },
        {
            "expectation_id": "example-entry",
            "dimension": "service",
            "slice_value": "fhvhv",
            "gap": -3543880.0,
            "share_of_gap": None,
            "gap_rank": 2,
        },
    ]
    series = {
        "example-entry": {
            "window": [["2025-01-05", 10.0], ["2025-01-06", 12.0]],
            "comparison": [["2024-01-07", 9.0], ["2024-01-08", 11.0]],
        }
    }

    html = page([verdict()], drivers, series)

    assert 'id="example-entry"' in html
    assert "Trips &lt;rise&gt; a little." in html  # text from the registry is escaped
    assert "Observed <b>+1.72%</b>, expected -2.50% to +4.00%" in html
    assert ">Held<" in html and ">Derived<" in html
    assert "+4,637,079" in html and "+424%" in html and "n/a" in html
    assert f"{REPO}/blob/abc1234/expectations/registry.yaml" in html
    assert f"{REPO}/blob/main/docs/elicitation/x.md" in html
    assert "(with uncommitted changes)" in html
    assert "none of the 1 has been scored yet" in html
    assert "ai-log" not in html
    assert "docs/essay.md" not in html


def test_the_page_explains_pending_unscoreable_and_unsupported_drivers():
    html = page(
        [
            verdict(
                id="waiting",
                verdict="pending",
                observed=None,
                verdict_note="data is loaded through 2026-10-31",
                origin="prospective",
            ),
            verdict(
                id="official",
                verdict="not_scoreable",
                observed=None,
                expected_low=None,
                expected_high=None,
                unit=None,
                metric=None,
                comparison=None,
                filters={},
                comparison_window=None,
                confidence=None,
                origin="official",
                author="agency",
                elicited_in=None,
                reported_outcome={
                    "value": -11,
                    "unit": "percent",
                    "note": "No baseline named.",
                    "source": "https://example.org/release",
                },
            ),
            verdict(
                id="ratio",
                comparison="value_range",
                comparison_window=None,
                unit="ratio",
                observed=4.99,
                expected_low=4.93,
                expected_high=5.07,
                origin="retrospective",
            ),
        ]
    )

    assert "Expected -2.50% to +4.00%" in html and "Data is loaded through 2026-10-31." in html
    assert "No data this project holds shares the expectation" in html
    assert "https://example.org/release" in html
    assert "Drivers are not supported for this comparison." in html
    assert html.count('<article class="card') == 3


def test_export_files_round_trip_through_load(tmp_path: Path):
    from datetime import UTC, date, datetime

    data = {
        "meta": META | {"generated_at": datetime(2026, 11, 12, tzinfo=UTC)},
        "verdicts": [verdict(recorded=date(2026, 11, 11))],
        "drivers": [],
        "checks": [],
        "freshness": [],
        "series": {},
    }

    paths = write(data, tmp_path)

    assert sorted(p.name for p in paths) == [
        "checks.json",
        "drivers.json",
        "freshness.json",
        "meta.json",
        "series.json",
        "verdicts.json",
    ]
    assert json.loads((tmp_path / "verdicts.json").read_text())[0]["recorded"] == "2026-11-11"
    assert 'id="example-entry"' in render(load(tmp_path))


def test_the_committed_page_matches_its_committed_data():
    """`site/index.html` is what `site/data/` renders to, so the two cannot drift apart."""
    from pipeline.jobs.site import ROOT

    site = ROOT / "site"
    essay = (ROOT / "docs" / "essay.md").exists()
    assert (site / "index.html").read_text() == render(load(site / "data"), essay_exists=essay)
