"""Pull one month of the MTA entries dataset into bronze through the Socrata API.

Each pull is a new file, `crz_entries/<YYYY-MM>/pulled_<YYYY-MM-DD>.csv`. A month
still in progress is pulled again later, beside the earlier pull.
"""

import argparse
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pipeline.months import month_bounds

DATASET_URL = "https://data.ny.gov/resource/t6yz-b64h.csv"
PAGE_ROWS = 50_000

Fetch = Callable[[str], bytes]


def month_dir(month: str) -> Path:
    return Path(os.environ.get("BRONZE_DIR", "/data/bronze")) / "crz_entries" / month


def latest_pull(month: str) -> Path | None:
    pulls = sorted(month_dir(month).glob("pulled_*.csv"))
    return pulls[-1] if pulls else None


def page_url(month: str, offset: int, limit: int = PAGE_ROWS) -> str:
    start, end = month_bounds(month)
    query = {
        "$where": f"toll_date >= '{start}T00:00:00' and toll_date < '{end}T00:00:00'",
        "$order": ":id",
        "$limit": limit,
        "$offset": offset,
    }
    base = os.environ.get("ENTRIES_URL", DATASET_URL)
    return f"{base}?{urllib.parse.urlencode(query)}"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "crz-expectations"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def pull_month(
    month: str, today: date, get: Fetch = fetch, page_rows: int = PAGE_ROWS
) -> tuple[Path | None, int]:
    """Page through one month. Returns (file, data rows). No file if the month has no rows.

    A pull already taken today is kept.
    """
    target = month_dir(month) / f"pulled_{today.isoformat()}.csv"
    if target.exists():
        with open(target, "rb") as existing:
            return target, sum(1 for _ in existing) - 1

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    rows = 0
    try:
        with open(partial, "wb") as out:
            offset = 0
            while True:
                lines = get(page_url(month, offset, page_rows)).splitlines(keepends=True)
                header, data = lines[:1], lines[1:]
                if offset == 0:
                    out.writelines(header)
                out.writelines(data)
                if data and not data[-1].endswith(b"\n"):
                    out.write(b"\n")
                rows += len(data)
                if len(data) < page_rows:
                    break
                offset += page_rows
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    if rows == 0:
        partial.unlink()
        return None, 0
    partial.rename(target)
    return target, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()
    path, rows = pull_month(args.month, date.today())
    print(f"{path}  {rows:,} rows")


if __name__ == "__main__":
    main()
