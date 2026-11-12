"""Rebuild gold trip tables for a range of months from silver. Bronze is not read."""

import argparse
import time

from pipeline.jobs import daily_trip_slices, daily_trips
from pipeline.months import month_range
from pipeline.session import build_session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM")
    parser.add_argument("--end", required=True, help="YYYY-MM")
    args = parser.parse_args()

    months = month_range(args.start, args.end)
    spark = build_session(f"gold backfill {args.start} to {args.end}")
    for position, month in enumerate(months, start=1):
        began = time.monotonic()
        daily_trips.run(spark, month)
        daily_trip_slices.run(spark, month)
        print(
            f"[{position}/{len(months)}] {month} done in {time.monotonic() - began:.0f}s",
            flush=True,
        )
    spark.stop()


if __name__ == "__main__":
    main()
