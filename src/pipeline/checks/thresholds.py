"""Thresholds for the data checks.

Values come from the history already loaded and are approved by the owner before
use (docs/SPEC.md section 7.1). The reasoning is in docs/decisions/0007.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # silver_volume: rows / median of the prior months must lie in [low, high].
    volume_low: float
    volume_high: float
    # dropped_share: rows dropped as out-of-month / rows read.
    dropped_share_max: float
    # required_nulls: the largest null share among the required columns.
    required_null_share_max: float
    # dropoff_before_pickup: share of trips that end before they start.
    ends_before_start_share_max: float
    # fee_before_launch: fee trips dropped off before tolling began. Set by the spec.
    fee_before_launch_max: int = 10


# Approved by the owner on 2026-11-11 (docs/decisions/0007).
APPROVED: Thresholds | None = Thresholds(
    volume_low=0.75,
    volume_high=1.35,
    dropped_share_max=0.001,
    required_null_share_max=0.0,
    ends_before_start_share_max=0.001,
)
