# Sources

Every source the project reads, with its columns as actually received. Checked on 2026-11-11 unless a line says otherwise.

Terms of use have not been verified yet for any source. Each section says what was found. This is open for the owner.

## TLC yellow taxi trips

- URL: `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_YYYY-MM.parquet`
- Landing page: <https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page>
- Used for: `silver.trips` (`service = 'yellow'`)
- Loaded: 2023-01 to 2026-09. Latest published: 2026-09 (file dated 2026-10-29). 2026-10 returns HTTP 403, which is how this host answers for a month that is not published.

Columns, from `make profile` over the first 44 loaded files (2023-01 to 2026-08). A range means the months where the column has that type.

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
- Loaded: 2023-01 to 2026-09. Latest published: 2026-09 (file dated 2026-10-29). 2026-10 returns HTTP 403.

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
- Used for: `reference.cbd_zones` (names and borough).
- Bronze: `data/bronze/reference/taxi_zone_lookup/pulled_<date>.csv`. First snapshot 2026-11-12.
- Header as received: `"LocationID","Borough","Zone","service_zone"`
- 265 rows, ids 1 to 265. Id 264 is borough `Unknown`, zone `N/A`. Id 265 is borough `N/A`, zone `Outside of NYC`.

Terms of use: not verified.

## MTA Central Business District Taxi Zones (`yfdc-w5jh`)

- URL: <https://data.ny.gov/d/yfdc-w5jh>
- Used for: `reference.cbd_zones` (membership).
- Bronze: `data/bronze/reference/cbd_taxi_zones/pulled_<date>.csv`. First snapshot 2026-11-12.
- Posting frequency, from the dataset's metadata: as needed.

Columns, from `https://data.ny.gov/api/views/yfdc-w5jh/columns.json`:

| Field | Display name | Type |
| --- | --- | --- |
| `taxi_zone` | Taxi Zone | number |
| `polygon` | Polygon | polygon |

The dataset has 38 rows. Every `taxi_zone` value is a TLC `LocationID`, and the TLC lookup places all 38 in Manhattan, so membership is joined by id (decision 0008).

Terms of use: the dataset's metadata has no licence field set. Attribution is "Metropolitan Transportation Authority". Not verified further.

## MTA Congestion Relief Zone Vehicle Entries (`t6yz-b64h`)

- URL: <https://data.ny.gov/d/t6yz-b64h>
- Article describing it: <https://mta.info/article/most-detailed-view-of-nyc-traffic-so-far>
- Used for: `silver.crz_entries` and `gold.daily_entries`.
- Bronze: `data/bronze/crz_entries/<YYYY-MM>/pulled_<date>.csv`, one month per pull, paged 50,000 rows at a time through `https://data.ny.gov/resource/t6yz-b64h.csv` ordered by `:id`.
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
- One row is one 10-minute block, vehicle class, and detection group: 6 classes times 12 groups is 72 rows per block and 10,368 rows on a normal day.
- Daylight saving: 2025-03-09 and 2026-03-08 have 9,936 rows (an hour is missing). 2025-11-02 has 10,800, because each block from 1:00 to 1:50 appears twice with identical key columns. Silver keeps both rows (decision 0009).
- `vehicle_class` labels as received: `1 - Cars, Pickups and Vans`, `2 - Single-Unit Trucks`, `3 - Multi-Unit Trucks`, `4 - Buses`, `5 - Motorcycles`, `TLC Taxi/FHV`. Silver stores canonical names from `expectations/metrics.yaml`.
- `time_period` is `Peak` or `Overnight`.
- `detection_group` has 12 values: Brooklyn Bridge, East 60th St, FDR Drive at 60th St, Holland Tunnel, Hugh L. Carey Tunnel, Lincoln Tunnel, Manhattan Bridge, Queensboro Bridge, Queens Midtown Tunnel, West 60th St, West Side Highway at 60th St, Williamsburg Bridge.
- `detection_region` has 7 values: Brooklyn, East 60th St, FDR Drive, New Jersey, Queens, West 60th St, West Side Highway.
- In the CSV every value arrives as a quoted string, and timestamps look like `2025-01-05T00:00:00.000`.

Limitations, paraphrased from the dataset's metadata: it should not be used to calculate program revenue, because entries carry no exemption status, payment method, or repeat-entry information.

Terms of use: the dataset's metadata has no licence field set. Attribution is "Metropolitan Transportation Authority". Not verified further.
