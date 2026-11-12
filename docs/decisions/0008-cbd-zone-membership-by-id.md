# 0008: Zone membership comes from the MTA's zone ids, joined to the TLC lookup by id

Status: accepted (Phase 2, 2026-11-11). Approved by the owner in the Phase 2 plan.

## Context

`gold.daily_trip_slices` needs to know which TLC taxi zones lie inside the Congestion Relief Zone. The spec's risk table expected the MTA dataset (`yfdc-w5jh`) to hold polygons without TLC zone ids, and planned to match on zone names or to join shapes.

The dataset as received has two columns, `taxi_zone` and `polygon`. Its 38 `taxi_zone` values are all TLC `LocationID`s, and the TLC lookup places all 38 in Manhattan.

## Decision

- `reference.cbd_zones` has one row per TLC zone (265). `in_cbd` is true for the 38 ids in the MTA dataset, joined by id.
- The job stops if the MTA list contains an id the TLC lookup does not have.
- Both sources are kept in bronze as dated snapshots, and `pulled_on` records the snapshot used.
- The `cbd_zone_membership` check tests the result against the fee itself: trips that start and end in one in-zone zone should nearly all carry it.

## Alternatives

- Matching on zone names: not needed, and names are less stable than ids.
- A spatial join of the TLC shapefile to the toll boundary: more faithful at the edges, but it adds a geospatial dependency to answer a question the MTA has already answered with a list.

## Consequences

- A trip is classified by its pickup and dropoff zones only. A trip that passes through the zone without starting or ending there lands in `neither`, as the spec says.
- Zones 264 (unknown) and 265 (outside NYC), and null zone ids, count as outside the zone.

## What the first run showed (2026-11-12)

`cbd_zone_membership` came out at 94.8%, just under the spec's 95%, so it warns: 1,823,293 of 1,922,810 trips that start and end in one in-zone zone carry the fee (2025-01-05 to 2025-12-31).

The shortfall is in yellow taxi records, not in the zone list:

- Ride-hail is at 98.1% (971,876 of 990,865). Yellow is at 91.4% (851,417 of 931,945), and between 90.0% and 93.1% in every month.
- 19% of those yellow trips record zero miles. They carry the fee 82% of the time, against 94% for the rest.
- No listed zone looks wrongly included. The lowest is Battery Park at 69% on 378 trips, and every zone with more than 5,000 trips is at 86% or more.
- No unlisted zone looks wrongly left out. The highest fee shares on same-zone trips outside the list are zones that border 60th Street: Lincoln Square East 44%, Central Park 36%, Upper East Side South 27%.

Two things follow. The zone list is accepted as it is. And classification by zone is approximate at the 60th Street edge: some trips in the bordering zones do enter the toll zone, pay the fee, and land in `neither`.

Why about 9% of yellow trips inside the zone carry no fee is not explained. It stays a warning in the results.
