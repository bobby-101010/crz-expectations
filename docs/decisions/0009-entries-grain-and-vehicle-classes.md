# 0009: Entries keep the source grain, including the repeated hour, and use canonical vehicle classes

Status: accepted (Phase 2, 2026-11-11). Approved by the owner in the Phase 2 plan.

## Context

One row of the MTA entries dataset is one 10-minute block, vehicle class, and detection group: 6 classes times 12 groups, so 72 rows per block and 10,368 rows on a normal day.

Daylight saving changes that. The day the clock goes forward has 9,936 rows, because an hour is missing. The day it goes back has 10,800: each block from 1:00 to 1:50 appears twice, with identical values in every key column. The block time is a wall-clock value with no zone.

The source labels its classes `1 - Cars, Pickups and Vans`, `2 - Single-Unit Trucks`, `3 - Multi-Unit Trucks`, `4 - Buses`, `5 - Motorcycles`, and `TLC Taxi/FHV`. The registry filters on canonical names.

## Decision

- `silver.crz_entries` is one row per source row. Nothing is merged or dropped except rows outside the month. On the two autumn dates so far (2025-11-02, and 2026-11-01 once loaded), `interval_start` with class and group is not unique.
- Daily totals in gold add both rows of a repeated block, which is correct: both hours happened.
- Vehicle classes are stored under canonical names: `cars_pickups_vans`, `single_unit_trucks`, `multi_unit_trucks`, `buses`, `motorcycles`, `tlc_taxi_fhv`. The mapping lives in `expectations/metrics.yaml` and is one-to-one.
- The silver job stops on any source label that is not in the mapping, so a renamed class cannot silently drop entries.
- A month is pulled through the API in pages of 50,000 rows ordered by row id, into a new dated file each time. Silver is rebuilt from the latest pull.

## Alternatives

- Adding a sequence number to tell the two repeated hours apart: the source gives no order between them, so any numbering would be invented.
- Summing the repeated rows into one in silver: changes the source grain and hides the effect.
- Keeping the source's labels: the leading numbers and the slash make poor filter values, and a registry entry should not depend on the source's spelling.

## Consequences

- Any analysis at 10-minute grain must handle the two daylight-saving days each year.
- This is the same wall-clock limitation as decision 0005, seen from the other dataset.
