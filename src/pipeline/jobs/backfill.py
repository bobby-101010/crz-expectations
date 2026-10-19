import argparse
import time

from pipeline.jobs import daily_trips, silver_trips
from pipeline.jobs.ingest import FILE_PREFIX, download
from pipeline.months import month_range
from pipeline.session import build_session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM")
    parser.add_argument("--end", required=True, help="YYYY-MM")
    parser.add_argument("--services", default="yellow,fhvhv")
    args = parser.parse_args()

    months = month_range(args.start, args.end)
    services = args.services.split(",")
    unknown = [service for service in services if service not in FILE_PREFIX]
    if unknown:
        parser.error(f"unknown services {unknown}")

    spark = build_session(f"backfill {args.start} to {args.end}")
    for position, month in enumerate(months, start=1):
        began = time.monotonic()
        for service in services:
            download(service, month)
            read, kept = silver_trips.run(spark, service, month)
            print(f"  {service} {month}: read {read:,}, kept {kept:,}, dropped {read - kept:,}")
        daily_trips.run(spark, month)
        print(f"[{position}/{len(months)}] {month} done in {time.monotonic() - began:.0f}s", flush=True)
    spark.stop()


if __name__ == "__main__":
    main()
