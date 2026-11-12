from datetime import date

import pytest

from pipeline.metrics import load_catalog
from pipeline.reference import cbd_zones, holiday_rows, unknown_cbd_zones


def test_cbd_zones_marks_membership_for_every_tlc_zone(spark):
    lookup = spark.createDataFrame(
        [("161", "Manhattan", "Midtown Center", "Yellow Zone"), ("7", "Queens", "Astoria", "Boro")],
        "LocationID string, Borough string, Zone string, service_zone string",
    )
    cbd = spark.createDataFrame([("161", "MULTIPOLYGON (...)")], "taxi_zone string, polygon string")

    rows = cbd_zones(lookup, cbd, date(2026, 11, 12)).orderBy("location_id").collect()

    assert [r.asDict() for r in rows] == [
        {
            "location_id": 7,
            "zone": "Astoria",
            "borough": "Queens",
            "in_cbd": False,
            "membership_source": "mta_yfdc-w5jh",
            "pulled_on": date(2026, 11, 12),
        },
        {
            "location_id": 161,
            "zone": "Midtown Center",
            "borough": "Manhattan",
            "in_cbd": True,
            "membership_source": "mta_yfdc-w5jh",
            "pulled_on": date(2026, 11, 12),
        },
    ]
    assert unknown_cbd_zones(lookup, cbd) == []


def test_a_cbd_zone_missing_from_the_lookup_is_reported(spark):
    lookup = spark.createDataFrame(
        [("7", "Queens", "Astoria")], "LocationID string, Borough string, Zone string"
    )
    cbd = spark.createDataFrame([("161",), ("7",)], "taxi_zone string")

    assert unknown_cbd_zones(lookup, cbd) == [161]


def test_reference_builders_fail_loudly_on_a_missing_column(spark):
    lookup = spark.createDataFrame([("7", "Queens")], "LocationID string, Borough string")
    cbd = spark.createDataFrame([("7",)], "taxi_zone string")

    with pytest.raises(ValueError, match="Zone"):
        cbd_zones(lookup, cbd, date(2026, 11, 12))


def test_holidays_cover_2023_to_2027_and_include_new_york_days():
    rows = dict(holiday_rows())

    assert min(rows).year == 2023 and max(rows).year == 2027
    assert "Columbus Day" in rows[date(2026, 10, 12)]
    assert "Election Day" in rows[date(2026, 11, 3)]
    assert "Veterans Day" in rows[date(2026, 11, 11)]
    assert date(2026, 11, 16) not in rows


def test_every_metric_in_the_catalog_resolves():
    catalog = load_catalog()

    assert set(catalog.metrics) == {
        "tlc_trips",
        "tlc_cbd_touch_trips",
        "tlc_fee_trips",
        "crz_entries",
        "excluded_roadway_entries",
        "fhvhv_per_yellow",
    }
    assert {m.name for m in catalog.metrics.values() if m.baseline} == {
        "tlc_trips",
        "tlc_cbd_touch_trips",
        "crz_entries",
    }
    assert catalog.metrics["fhvhv_per_yellow"].numerator == {
        "metric": "tlc_trips",
        "filters": {"service": "fhvhv"},
    }
    assert len(catalog.vehicle_classes) == 6
    assert catalog.vehicle_classes["tlc_taxi_fhv"] == "TLC Taxi/FHV"


def test_a_catalog_that_does_not_resolve_is_rejected(tmp_path):
    bad = tmp_path / "metrics.yaml"
    bad.write_text(
        "metrics:\n"
        "  trips:\n"
        "    {kind: sum, source: gold.t, date_column: d, value: trips, dimensions: [service]}\n"
        "  share:\n"
        "    kind: ratio\n"
        "    numerator: {metric: trips, filters: {operator: uber}}\n"
        "    denominator: {metric: trips}\n"
    )

    with pytest.raises(ValueError, match="operator"):
        load_catalog(bad)
