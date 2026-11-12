import math

import pytest

from pipeline.drivers import driver_rows


def test_slice_gaps_sum_to_the_total_gap():
    comparison = {"yellow": 41_169_300.0, "fhvhv": 239_470_448.0, "green": 1_234_567.0}
    observed = {"yellow": 48_722_388.0, "fhvhv": 243_589_684.0, "green": 987_654.0}
    low, high = -2.5, 4.0

    rows = driver_rows("service", observed, comparison, low, high)

    midpoint = (low + high) / 2 / 100
    total_gap = sum(observed.values()) - sum(comparison.values()) * (1 + midpoint)
    assert math.isclose(sum(row.gap for row in rows), total_gap, rel_tol=1e-12)
    assert math.isclose(sum(row.share_of_gap for row in rows), 1.0, rel_tol=1e-9)
    for row in rows:
        assert row.expected_value == pytest.approx(row.comparison_value * (1 + midpoint))
        assert row.gap == pytest.approx(row.observed_value - row.expected_value)


def test_slices_are_ranked_by_the_size_of_their_gap_whatever_its_sign():
    rows = driver_rows(
        "zone_relation",
        observed={"both_in": 100.0, "neither": 300.0, "pickup_in": 50.0},
        comparison={"both_in": 100.0, "neither": 200.0, "pickup_in": 100.0},
        expected_low=0.0,
        expected_high=0.0,
    )

    assert [(r.gap_rank, r.slice_value, r.gap) for r in rows] == [
        (1, "neither", 100.0),
        (2, "pickup_in", -50.0),
        (3, "both_in", 0.0),
    ]
    assert [r.share_of_gap for r in rows] == [2.0, -1.0, 0.0]


def test_a_slice_in_only_one_window_counts_as_zero_in_the_other():
    rows = driver_rows(
        "operator_code",
        observed={"HV0003": 110.0, "HV0006": 5.0},
        comparison={"HV0003": 100.0, "HV0004": 20.0},
        expected_low=10.0,
        expected_high=10.0,
    )
    by_slice = {r.slice_value: r for r in rows}

    assert by_slice["HV0006"].comparison_value == 0.0
    assert (by_slice["HV0006"].expected_value, by_slice["HV0006"].gap) == (0.0, 5.0)
    assert by_slice["HV0004"].observed_value == 0.0
    assert by_slice["HV0004"].gap == pytest.approx(-22.0)
    assert by_slice["HV0003"].gap == pytest.approx(0.0)
    assert by_slice["HV0004"].gap_rank == 1


def test_share_is_empty_when_the_total_gap_is_exactly_zero():
    rows = driver_rows(
        "service",
        observed={"yellow": 120.0, "fhvhv": 80.0},
        comparison={"yellow": 100.0, "fhvhv": 100.0},
        expected_low=0.0,
        expected_high=0.0,
    )

    assert [r.gap for r in rows] == [-20.0, 20.0]
    assert [r.share_of_gap for r in rows] == [None, None]
    assert [(r.gap_rank, r.slice_value) for r in rows] == [(1, "fhvhv"), (2, "yellow")]
