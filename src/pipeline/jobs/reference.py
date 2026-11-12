"""Pull the two zone sources into bronze as dated snapshots, then build the reference tables."""

import os
import shutil
import urllib.request
from datetime import date
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession

from pipeline.reference import cbd_zones, holiday_rows, unknown_cbd_zones
from pipeline.session import build_session

ZONES_TABLE = "local.reference.cbd_zones"
HOLIDAYS_TABLE = "local.reference.holidays"

SOURCES = {
    "taxi_zone_lookup": "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv",
    "cbd_taxi_zones": "https://data.ny.gov/resource/yfdc-w5jh.csv?$limit=50000",
}


def snapshot_dir(name: str) -> Path:
    return Path(os.environ.get("BRONZE_DIR", "/data/bronze")) / "reference" / name


def pull_snapshot(name: str, today: date) -> Path:
    """Download one source to `pulled_<date>.csv`. A snapshot already taken today is kept."""
    target = snapshot_dir(name) / f"pulled_{today.isoformat()}.csv"
    if target.exists():
        return target
    url = os.environ.get(f"{name.upper()}_URL", SOURCES[name])
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "crz-expectations"})
    try:
        with urllib.request.urlopen(request) as response, open(partial, "wb") as out:
            shutil.copyfileobj(response, out)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.rename(target)
    return target


def latest_snapshot(name: str) -> Path:
    snapshots = sorted(snapshot_dir(name).glob("pulled_*.csv"))
    if not snapshots:
        raise FileNotFoundError(f"no snapshot of {name} in {snapshot_dir(name)}")
    return snapshots[-1]


def read_csv(spark: SparkSession, path: Path) -> DataFrame:
    """Every column as a string. The builders cast what they use."""
    return spark.read.csv(str(path), header=True, multiLine=True, escape='"')


def run(spark: SparkSession) -> tuple[int, int, int]:
    """Latest snapshots -> both reference tables. Returns (zones, zones in the CBD, holidays)."""
    lookup_path = latest_snapshot("taxi_zone_lookup")
    cbd_path = latest_snapshot("cbd_taxi_zones")
    lookup, cbd = read_csv(spark, lookup_path), read_csv(spark, cbd_path)

    unknown = unknown_cbd_zones(lookup, cbd)
    if unknown:
        raise ValueError(f"CBD zone ids {unknown} are not in the TLC zone lookup")

    pulled_on = date.fromisoformat(cbd_path.stem.removeprefix("pulled_"))
    spark.sql("CREATE NAMESPACE IF NOT EXISTS local.reference")
    # Small tables, rebuilt in full on each load.
    cbd_zones(lookup, cbd, pulled_on).writeTo(ZONES_TABLE).using("iceberg").createOrReplace()
    spark.createDataFrame(holiday_rows(), "holiday_date date, name string").writeTo(
        HOLIDAYS_TABLE
    ).using("iceberg").createOrReplace()

    zones = spark.table(ZONES_TABLE)
    return zones.count(), zones.where("in_cbd").count(), spark.table(HOLIDAYS_TABLE).count()


def main() -> None:
    today = date.today()
    for name in SOURCES:
        print(pull_snapshot(name, today))
    spark = build_session("reference")
    zones, in_cbd, holiday_count = run(spark)
    print(f"reference.cbd_zones: {zones} zones, {in_cbd} in the CBD")
    print(f"reference.holidays: {holiday_count} dates")
    spark.stop()


if __name__ == "__main__":
    main()
