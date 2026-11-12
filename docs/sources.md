# Sources

Every source the project reads, with its columns as actually received. Checked on 2026-11-11 unless a line says otherwise.

Terms of use have not been verified yet for any source. Each section says what was found. This is open for the owner.

## TLC yellow taxi trips

- URL: `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_YYYY-MM.parquet`
- Landing page: <https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page>
- Used for: `silver.trips` (`service = 'yellow'`)
- Loaded: 2023-01 to 2026-08. Latest published: 2026-09 (file dated 2026-10-29). 2026-10 returns HTTP 403, which is how this host answers for a month that is not published.

Columns, from `make profile` over the 44 loaded files. A range means the months where the column has that type.

| Column | Type | Used by silver |
| --- | --- | --- |
| `VendorID` | bigint 2023-01; int from 2023-02 | |
| `tpep_pickup_datetime` | timestamp_ntz | `pickup_at` |
| `tpep_dropoff_datetime` | timestamp_ntz | `dropoff_at` |
| `passenger_count` | double 2023-01; bigint from 2023-02 | |
| `trip_distance` | double | `trip_miles` |
| `RatecodeID` | double 2023-01; bigint from 2023-02 | |
| `store_and_fwd_flag` | string | |
| `PULocationID` | bigint 2023-01; int from 2023-02 | `pickup_zone_id` |
| `DOLocationID` | bigint 2023-01; int from 2023-02 | `dropoff_zone_id` |
| `payment_type` | bigint | |
| `fare_amount`, `extra`, `mta_tax`, `tip_amount`, `tolls_amount`, `improvement_surcharge`, `total_amount`, `congestion_surcharge` | double | |
| `airport_fee` | double, 2023-01 only | |
| `Airport_fee` | double, from 2023-02 | |
| `cbd_congestion_fee` | double, from 2025-01; absent before | `cbd_congestion_fee` |
| `request_source` | string, from 2026-06; absent before | |

Quirks:

- The 2023-01 file uses wider types than every later month.
- `airport_fee` changes capitalization after 2023-01. Silver matches names without regard to case.
- Files contain a few trips picked up outside their month. Silver drops them and reports the count.
- 401 yellow trips picked up on 2025-01-04 carry the fee. 397 were dropped off after tolling began at midnight. Four are unexplained (spec section 3).

Terms of use: not verified.

## TLC high-volume for-hire trips (`fhvhv`)

- URL: `https://d37ci6vzurychx.cloudfront.net/trip-data/fhvhv_tripdata_YYYY-MM.parquet`
- Data dictionary: <https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_hvfhs.pdf>
- Used for: `silver.trips` (`service = 'fhvhv'`)
- Loaded: 2023-01 to 2026-08. Latest published: 2026-09 (file dated 2026-10-29). 2026-10 returns HTTP 403.

| Column | Type | Used by silver |
| --- | --- | --- |
| `hvfhs_license_num` | string | `operator_code` (`HV0003` is Uber, `HV0005` is Lyft) |
| `dispatching_base_num`, `originating_base_num` | string | |
| `request_datetime`, `on_scene_datetime` | timestamp_ntz | |
| `pickup_datetime` | timestamp_ntz | `pickup_at` |
| `dropoff_datetime` | timestamp_ntz | `dropoff_at` |
| `PULocationID` | bigint 2023-01; int from 2023-02 | `pickup_zone_id` |
| `DOLocationID` | bigint 2023-01; int from 2023-02 | `dropoff_zone_id` |
| `trip_miles` | double | `trip_miles` |
| `trip_time` | bigint | |
| `base_passenger_fare`, `tolls`, `bcf`, `sales_tax`, `congestion_surcharge`, `airport_fee`, `tips`, `driver_pay` | double | |
| `shared_request_flag`, `shared_match_flag`, `access_a_ride_flag`, `wav_request_flag`, `wav_match_flag` | string | |
| `cbd_congestion_fee` | double, from 2025-01; absent before | `cbd_congestion_fee` |

Quirks: the same 2023-01 type difference for the zone ids, and no fee column before 2025.

Terms of use: not verified.

## TLC taxi zone lookup

- URL: `https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv`
- Used for: `reference.cbd_zones` (names and borough), from Phase 2. Not loaded yet.
- Header as received: `"LocationID","Borough","Zone","service_zone"`

Terms of use: not verified.

## MTA Central Business District Taxi Zones (`yfdc-w5jh`)

- URL: <https://data.ny.gov/d/yfdc-w5jh>
- Used for: `reference.cbd_zones` (membership), from Phase 2. Not loaded yet.
- Posting frequency, from the dataset's metadata: as needed.

Columns, from `https://data.ny.gov/api/views/yfdc-w5jh/columns.json`:

| Field | Display name | Type |
| --- | --- | --- |
| `taxi_zone` | Taxi Zone | number |
| `polygon` | Polygon | polygon |

Note for Phase 2: the dataset has a `taxi_zone` number column. Whether it holds TLC `LocationID` values has not been checked against the lookup. If it does, the name-matching fallback in spec section 13 is not needed.

Terms of use: the dataset's metadata has no licence field set. Attribution is "Metropolitan Transportation Authority". Not verified further.

## MTA Congestion Relief Zone Vehicle Entries (`t6yz-b64h`)

- URL: <https://data.ny.gov/d/t6yz-b64h>
- Article describing it: <https://mta.info/article/most-detailed-view-of-nyc-traffic-so-far>
- Used for: `silver.crz_entries`, from Phase 2. Not loaded yet.
- Posting frequency, from the dataset's metadata: weekly.
- State on 2026-11-11: first `toll_date` 2025-01-05, latest `toll_date` 2026-10-31, 6,894,288 rows, rows last updated 2026-11-05 19:26:44 UTC.

Columns, from `https://data.ny.gov/api/views/t6yz-b64h/columns.json`:

| Field | Display name | Type | Silver column (spec section 6) |
| --- | --- | --- | --- |
| `toll_date` | Toll Date | calendar_date | `toll_date` |
| `toll_hour` | Toll Hour | calendar_date | |
| `toll_10_minute_block` | Toll 10 Minute Block | calendar_date | `interval_start` |
| `minute_of_hour` | Minute of Hour | number | |
| `hour_of_day` | Hour of Day | number | |
| `day_of_week_int` | Day of Week Int | number | |
| `day_of_week` | Day of Week | text | |
| `toll_week` | Toll Week | calendar_date | |
| `time_period` | Time Period | text | `time_period` |
| `vehicle_class` | Vehicle Class | text | `vehicle_class` |
| `detection_group` | Detection Group | text | `detection_group` |
| `detection_region` | Detection Region | text | `detection_region` |
| `crz_entries` | CRZ Entries | number | `crz_entries` |
| `excluded_roadway_entries` | Excluded Roadway Entries | number | `excluded_roadway_entries` |

Quirks:

- Toll weeks run Sunday to Saturday (`toll_week` is the Sunday).
- Each date from 2026-10-18 to 2026-10-31 has 10,368 rows. Other dates were not counted.
- 2025-11-02 and 2026-11-01 are 25-hour days. How the repeated hour appears in `toll_10_minute_block` has not been checked.

Limitations, paraphrased from the dataset's metadata: it should not be used to calculate program revenue, because entries carry no exemption status, payment method, or repeat-entry information.

Terms of use: the dataset's metadata has no licence field set. Attribution is "Metropolitan Transportation Authority". Not verified further.
