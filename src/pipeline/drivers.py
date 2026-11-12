"""Drivers: where the gap between observed and expected comes from (spec section 7.7).

A driver locates a gap. It does not say why, and it is never called a cause.
"""

from dataclasses import dataclass

NO_VALUE = "(none)"  # the label for a slice whose dimension is null, such as yellow's operator


@dataclass(frozen=True)
class DriverRow:
    dimension: str
    slice_value: str
    comparison_value: float
    observed_value: float
    expected_value: float
    gap: float
    share_of_gap: float | None
    gap_rank: int


def driver_rows(
    dimension: str,
    observed: dict[str, float],
    comparison: dict[str, float],
    expected_low: float,
    expected_high: float,
) -> list[DriverRow]:
    """Break the gap of a `change_vs_period` entry down by the slices of one dimension.

    Every slice is expected to move by the same percentage: the midpoint of the
    expected range. So `expected = comparison * (1 + m)` and `gap = observed - expected`
    for each slice, and the slice gaps add up exactly to the total gap. A slice in
    only one window counts as zero in the other.

    `share_of_gap` is the slice's gap over the total gap. It is None when the total
    is exactly zero. When the total is small, shares are large and of both signs.
    """
    midpoint = (expected_low + expected_high) / 2 / 100
    gaps = {}
    for slice_value in sorted(set(observed) | set(comparison)):
        before = float(comparison.get(slice_value, 0.0))
        after = float(observed.get(slice_value, 0.0))
        expected = before * (1 + midpoint)
        gaps[slice_value] = (before, after, expected, after - expected)

    total = sum(gap for *_, gap in gaps.values())
    ranked = sorted(gaps, key=lambda name: (-abs(gaps[name][3]), name))
    return [
        DriverRow(
            dimension,
            name,
            *gaps[name],
            None if total == 0 else gaps[name][3] / total,
            rank,
        )
        for rank, name in enumerate(ranked, start=1)
    ]
