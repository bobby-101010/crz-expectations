"""Pure builders for the reference tables: CBD zone membership and holidays."""

from datetime import date

import holidays
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

MEMBERSHIP_SOURCE = "mta_yfdc-w5jh"
HOLIDAY_YEARS = range(2023, 2028)

LOOKUP_COLUMNS = ["LocationID", "Borough", "Zone"]
CBD_COLUMNS = ["taxi_zone"]


def require_columns(frame: DataFrame, required: list[str], what: str) -> dict[str, str]:
    """Lower-case name -> actual name. Raises if a required column is missing."""
    actual = {name.lower(): name for name in frame.columns}
    missing = [name for name in required if name.lower() not in actual]
    if missing:
        raise ValueError(f"{what} lacks columns {missing}")
    return actual


def cbd_zones(lookup: DataFrame, cbd: DataFrame, pulled_on: date) -> DataFrame:
    """TLC zone lookup + the MTA's list of zones in the toll zone -> one row per TLC zone."""
    names = require_columns(lookup, LOOKUP_COLUMNS, "the zone lookup")
    cbd_names = require_columns(cbd, CBD_COLUMNS, "the CBD zone list")

    zones = lookup.select(
        F.col(names["locationid"]).cast("int").alias("location_id"),
        F.col(names["zone"]).cast("string").alias("zone"),
        F.col(names["borough"]).cast("string").alias("borough"),
    )
    members = cbd.select(
        F.col(cbd_names["taxi_zone"]).cast("double").cast("int").alias("location_id"),
        F.lit(True).alias("member"),
    ).distinct()
    return zones.join(members, "location_id", "left").select(
        "location_id",
        "zone",
        "borough",
        F.coalesce("member", F.lit(False)).alias("in_cbd"),
        F.lit(MEMBERSHIP_SOURCE).alias("membership_source"),
        F.lit(pulled_on).cast("date").alias("pulled_on"),
    )


def unknown_cbd_zones(lookup: DataFrame, cbd: DataFrame) -> list[int]:
    """CBD zone ids that the TLC lookup does not have. Should be empty."""
    names = require_columns(lookup, LOOKUP_COLUMNS, "the zone lookup")
    cbd_names = require_columns(cbd, CBD_COLUMNS, "the CBD zone list")
    known = lookup.select(F.col(names["locationid"]).cast("int").alias("location_id"))
    listed = cbd.select(
        F.col(cbd_names["taxi_zone"]).cast("double").cast("int").alias("location_id")
    )
    return sorted(row["location_id"] for row in listed.join(known, "location_id", "anti").collect())


def holiday_rows() -> list[tuple[date, str]]:
    """US federal and New York State holidays, 2023 to 2027, from the `holidays` package."""
    calendar = holidays.country_holidays("US", subdiv="NY", years=HOLIDAY_YEARS)
    return sorted(calendar.items())
