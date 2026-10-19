import argparse
import os
import shutil
import urllib.request
from pathlib import Path

FILE_PREFIX = {"yellow": "yellow_tripdata", "fhvhv": "fhvhv_tripdata"}


def bronze_path(service: str, month: str) -> Path:
    root = Path(os.environ.get("BRONZE_DIR", "/data/bronze"))
    return root / service / f"{FILE_PREFIX[service]}_{month}.parquet"


def download(service: str, month: str) -> Path:
    """Fetch one monthly file into bronze. A file that is already there is kept."""
    target = bronze_path(service, month)
    if target.exists():
        return target

    base = os.environ.get(
        "TLC_BASE_URL", "https://d37ci6vzurychx.cloudfront.net/trip-data"
    )
    url = f"{base}/{target.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "crz-expectations"})
    try:
        with urllib.request.urlopen(request) as response, open(partial, "wb") as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.rename(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True, choices=sorted(FILE_PREFIX))
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()
    path = download(args.service, args.month)
    print(f"{path}  {path.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
    