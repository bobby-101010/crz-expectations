# Trip lifecycle

**Source.** The TLC publishes one file per month for yellow taxis and one for ride-hail (Uber and Lyft). One record is one trip.

**Silver.** Loading a month writes one row per record to `silver.trips`, with `service` = 'yellow' or 'fhvhv'. `operator_code` is 'HV0003' (Uber) or 'HV0005' (Lyft), and null for yellow. Records whose `pickup_at` is outside the file's month are not written. `pickup_at` and `dropoff_at` are New York wall-clock times. Reloading a month replaces its rows.

**Fee.** Tolling began on 2025-01-05 at 00:00. `silver.trips.cbd_congestion_fee` is copied from the source, not derived from zones. It is null for every trip before 2025-01 (not recorded) and filled for every trip from 2025-01. 0 means recorded as no fee. A "fee trip" is a row with `cbd_congestion_fee` > 0. Usual values are 0.75 for yellow and 1.5 for ride-hail.

**Reversals.** A negative `cbd_congestion_fee`, such as -0.75, marks a reversal record: a second row that cancels an earlier trip row. The original row, with a positive fee, is usually also present. Both stay in `silver.trips`; there is no status column. Trip counts include both rows. Fee-trip counts include only the original.

**Zone.** `reference.cbd_zones` has one row per TLC taxi zone. `in_cbd` is true for the 38 zones inside the toll zone. `location_id` joins to `silver.trips.pickup_zone_id` and `dropoff_zone_id`. Zones 264, 265 and null ids count as outside. A trip is classed only by its two ends: `zone_relation` is 'both_in', 'pickup_in', 'dropoff_in' or 'neither'. A trip touches the zone when `zone_relation` is not 'neither'. A trip that only passes through is 'neither'. Zone class and fee are independent: some 'neither' trips carry a fee, and some in-zone trips carry none.

**Gold.** After silver, two daily tables are rebuilt for the month. Both assign a trip to the date of `pickup_at`, so a trip that crosses midnight counts only on its pickup date.
- `gold.daily_trips`: one row per `trip_date` and `service`. `trips` counts every silver row. `cbd_fee_trips` counts fee trips. Use it for totals by service.
- `gold.daily_trip_slices`: one row per `trip_date`, `service`, `operator_code`, `zone_relation` and `pickup_hour`. `trips` and `fee_trips` mean the same. Use it for operator, hour or zone breakdowns, summing `trips` over the rows needed. Its totals equal `gold.daily_trips`.

Fee-trip counts are 0 before 2025. Trips picked up on 2025-01-04 and dropped off after tolling began can carry the fee: 401 yellow trips carry it, and they count under 2025-01-04.

**Which table.** Use gold for counts per day or longer. Use `silver.trips` only for single trips, `dropoff_at`, individual zones, `trip_miles` or fee amounts, and always filter `service` and a `pickup_at` range.

**Normal range.** `gold.baselines` holds a normal band, not observed counts, for `metric` = 'tlc_trips' (daily sum of `gold.daily_trip_slices.trips`) and 'tlc_cbd_touch_trips' (the same where `zone_relation` is not 'neither').
