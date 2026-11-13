# Trip lifecycle

**Source.** The TLC publishes monthly files for yellow taxis and for ride-hail (Uber and Lyft). One record is one trip. Trips are loaded through 2026-09-30.

**Silver.** Loading a month writes one row per record to `silver.trips`, with `service` = 'yellow' or 'fhvhv'. `operator_code` is 'HV0003' (Uber) or 'HV0005' (Lyft), and null for yellow. Records whose `pickup_at` is outside the file's month are not written. `pickup_at` and `dropoff_at` are New York wall-clock times.

**Fee.** Tolling began on 2025-01-05 at 00:00. `silver.trips.cbd_congestion_fee` is copied from the source, not derived from zones. It is null for every trip before 2025-01 (not recorded) and filled for every trip from 2025-01. 0 means recorded as no fee. A "fee trip" is a row with `cbd_congestion_fee` > 0. Usual values are 0.75 for yellow and 1.5 for ride-hail.

**Reversals.** A negative `cbd_congestion_fee`, such as -0.75, marks a reversal record: a second row that cancels an earlier trip row. The original row, with a positive fee, is usually also present. Both stay in `silver.trips`; there is no status column. Trip counts include both rows. Fee-trip counts include only the original. So far reversals have been seen only for 'yellow'; that is an observation, not a rule.

**Zone.** `reference.cbd_zones` has one row per TLC taxi zone. `in_cbd` is true for the 38 zones inside the toll zone. `location_id` joins to `silver.trips.pickup_zone_id` and `dropoff_zone_id`. Zones 264, 265 and null ids count as outside. A trip is classed only by its two ends: `zone_relation` is 'both_in', 'pickup_in', 'dropoff_in' or 'neither'. A trip touches the zone when `zone_relation` is not 'neither'; one that only passes through is 'neither'. Zone class and fee are independent: some 'neither' trips carry a fee, and some in-zone trips carry none.

**Gold.** After silver, two daily tables are rebuilt for the month. Both assign a trip to the date of `pickup_at`, so a trip that crosses midnight counts only on its pickup date.
- `gold.daily_trips`: one row per `trip_date` and `service`. `trips` counts every silver row. `cbd_fee_trips` counts fee trips.
- `gold.daily_trip_slices`: one row per `trip_date`, `service`, `operator_code`, `zone_relation` and `pickup_hour`. Its `trips` and `fee_trips` mean what `trips` and `cbd_fee_trips` mean in `gold.daily_trips`; the fee column is named differently. Sum `trips` over the rows needed. Its totals equal `gold.daily_trips`.

Fee-trip counts are 0 before 2025. A trip picked up before tolling began can carry the fee, and counts under its pickup date. Fee trips dated 2025-01-04 total 1,585: 401 yellow and 1,184 ride-hail. 4 of the yellow ones were dropped off before 2025-01-05 00:00.

**Which table.** Use `gold.daily_trips` for totals by service and `gold.daily_trip_slices` for operator, hour or zone breakdowns. Use `silver.trips` only for single trips, `dropoff_at`, individual zones, `trip_miles` or fee amounts, and always filter `service` and a `pickup_at` range.

**Normal range.** `gold.baselines` holds a normal band, not observed counts, for `metric` = 'tlc_trips' (daily sum of `gold.daily_trip_slices.trips`) and 'tlc_cbd_touch_trips' (the same where `zone_relation` is not 'neither'). The band is `p10` to `p90`, with median `p50`. For the whole metric filter `slice_key` = 'all'; otherwise a date returns about 33 rows per metric, one per `slice_value` of each dimension. Trip baselines start on 2023-02-14. Fee trips have no baseline.
