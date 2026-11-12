import argparse
import time
from datetime import date

from pipeline.jobs import daily_entries, silver_entries
from pipeline.jobs.ingest_entries import pull_month
from pipeline.months import month_range
from pipeline.session import build_session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM")
    parser.add_argument("--end", required=True, help="YYYY-MM")
    args = parser.parse_args()

    months = month_range(args.start, args.end)
    today = date.today()
    spark = build_session(f"backfill entries {args.start} to {args.end}")
    for position, month in enumerate(months, start=1):
        began = time.monotonic()
        path, pulled = pull_month(month, today)
        if path is None:
            print(f"[{position}/{len(months)}] {month}: the source has no rows yet", flush=True)
            continue
        read, kept = silver_entries.run(spark, month)
        daily_entries.run(spark, month)
        print(
            f"[{position}/{len(months)}] {month}: pulled {pulled:,}, read {read:,}, kept {kept:,}, "
            f"dropped {read - kept:,}, {time.monotonic() - began:.0f}s",
            flush=True,
        )
    spark.stop()


if __name__ == "__main__":
    main()
