from datetime import date

import pytest

from pipeline.months import month_bounds, month_range


def test_month_bounds_rolls_over_december():
    assert month_bounds("2025-12") == (date(2025, 12, 1), date(2026, 1, 1))


def test_month_range_crosses_a_year_and_includes_both_ends():
    assert month_range("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]


def test_month_range_rejects_a_reversed_range():
    with pytest.raises(ValueError):
        month_range("2025-02", "2025-01")
