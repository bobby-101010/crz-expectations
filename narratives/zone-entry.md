# Zone-entry lifecycle

**Source.** The MTA detects vehicles entering the Congestion Relief Zone and publishes counts, not single vehicles. One source row is one 10-minute block, vehicle class and crossing point. Data starts on 2025-01-05, when tolling began, so no before-and-after comparison is possible.

**Silver.** Each pull of a month replaces that month in `silver.crz_entries`, one row per source row. `interval_start` is the block's start in New York wall-clock time and `toll_date` its date. Nothing is merged: when daylight saving ends (2025-11-02) each block from 1:00 to 1:50 appears twice and both rows are real, so sum them.

**Vehicle classes.** `vehicle_class` is 'cars_pickups_vans', 'single_unit_trucks', 'multi_unit_trucks', 'buses', 'motorcycles' or 'tlc_taxi_fhv'. 'tlc_taxi_fhv' is taxis and for-hire vehicles in the per-trip charge plan. These are vehicle entries, not trips.

**Entry points.** `detection_group` is the crossing where the vehicle was first detected, 12 values such as 'Lincoln Tunnel'. `detection_region` is a wider area, 7 values, only in `silver.crz_entries`. Neither is a taxi zone.

**Peak and overnight.** `time_period` is 'Peak' or 'Overnight', as the MTA labels the block. Peak is 5 AM to 9 PM on weekdays and 9 AM to 9 PM on weekends.

**Excluded roadways.** `crz_entries` counts vehicles that entered the zone. `excluded_roadway_entries` counts vehicles that entered the Central Business District but stayed on the FDR Drive, the West Side Highway/West Street or the Hugh L. Carey Tunnel connections; they are not charged. The two never overlap, and their sum is all entries into the district.

**Gold.** After silver, `gold.daily_entries` is rebuilt for the month: one row per `entry_date`, `vehicle_class`, `detection_group` and `time_period`, summing both count columns. Sum `crz_entries` over the rows needed. Use it for day grain or coarser. Use `silver.crz_entries` only for hours, 10-minute blocks or `detection_region`.

**Normal range.** After gold, `gold.baselines` is rebuilt in full. One row is one `metric`, slice and `baseline_date`. For entries, `metric` = 'crz_entries', the daily sum of `gold.daily_entries.crz_entries`. `slice_key` = 'all' with `slice_value` = 'all' is the whole metric. Other rows have `slice_key` 'vehicle_class', 'detection_group' or 'time_period' and one value in `slice_value`, never a combination. `excluded_roadway_entries` has no baseline.

The history of a date is the 8 dates exactly 7, 14, ... 56 days earlier. Dates in `reference.holidays` (one row per `holiday_date`) and dates without data are left out and not replaced. `p10`, `p50` and `p90` are percentiles of the remaining daily values, and `n_obs` is how many were used, 6 to 8. A date with fewer than 6 has no row, so rows start at 2025-02-16. A holiday still gets its own row. The normal band is `p10` to `p90`, ends included. `gold.baselines` never holds what happened; compare it with the sum from `gold.daily_entries` for the same date and slice.
