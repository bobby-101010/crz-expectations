"""Pure DataFrame logic for the MTA vehicle entries data."""

from datetime import date

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from pipeline.reference import require_columns

# Source columns that silver needs. Names are matched without regard to case.
REQUIRED_SOURCES = [
    "toll_date",
    "toll_10_minute_block",
    "time_period",
    "vehicle_class",
    "detection_group",
    "detection_region",
    "crz_entries",
    "excluded_roadway_entries",
]

# Silver column -> its type. The order here is the column order of the table.
SILVER_ENTRIES_COLUMNS = {
    "toll_date": "date",
    "interval_start": "timestamp_ntz",
    "time_period": "string",
    "vehicle_class": "string",
    "detection_group": "string",
    "detection_region": "string",
    "crz_entries": "bigint",
    "excluded_roadway_entries": "bigint",
    "source_pull_date": "date",
}


def unmapped_vehicle_classes(bronze: DataFrame, vehicle_classes: dict[str, str]) -> list[str]:
    """Source labels with no canonical name. The silver job stops if this is not empty."""
    names = require_columns(bronze, ["vehicle_class"], "the entries file")
    known = list(vehicle_classes.values())
    labels = bronze.select(F.col(names["vehicle_class"]).alias("label")).distinct()
    unknown = labels.where(F.col("label").isNull() | ~F.col("label").isin(known)).collect()
    return sorted(str(row["label"]) for row in unknown)


def conform_entries(
    bronze: DataFrame,
    vehicle_classes: dict[str, str],
    start: date,
    end: date,
    pull_date: date,
) -> DataFrame:
    """One pull of one month, every column a string -> the silver schema.

    One row per source row: nothing is merged, so the repeated hour at the end of
    daylight saving keeps both of its rows. Rows outside [start, end) are dropped.
    """
    names = require_columns(bronze, REQUIRED_SOURCES, "the entries file")

    def source(name: str):
        return F.col(names[name])

    to_canonical = F.create_map(
        *[
            F.lit(part)
            for canonical, label in vehicle_classes.items()
            for part in (label, canonical)
        ]
    )
    return bronze.select(
        F.to_date(source("toll_date").cast("timestamp_ntz")).alias("toll_date"),
        source("toll_10_minute_block").cast("timestamp_ntz").alias("interval_start"),
        source("time_period").cast("string").alias("time_period"),
        to_canonical[source("vehicle_class")].alias("vehicle_class"),
        source("detection_group").cast("string").alias("detection_group"),
        source("detection_region").cast("string").alias("detection_region"),
        source("crz_entries").cast("double").cast("bigint").alias("crz_entries"),
        source("excluded_roadway_entries")
        .cast("double")
        .cast("bigint")
        .alias("excluded_roadway_entries"),
        F.lit(pull_date).cast("date").alias("source_pull_date"),
    ).where((F.col("interval_start") >= F.lit(start)) & (F.col("interval_start") < F.lit(end)))


def daily_entries(entries: DataFrame, start: date, end: date) -> DataFrame:
    """Silver entries -> one row per date, vehicle class, detection group and time period."""
    return (
        entries.where(
            (F.col("interval_start") >= F.lit(start)) & (F.col("interval_start") < F.lit(end))
        )
        .groupBy(
            F.col("toll_date").alias("entry_date"),
            "vehicle_class",
            "detection_group",
            "time_period",
        )
        .agg(
            F.sum("crz_entries").alias("crz_entries"),
            F.sum("excluded_roadway_entries").alias("excluded_roadway_entries"),
        )
    )
