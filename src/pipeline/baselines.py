"""What "normal" looks like for a metric: the `same_weekday_trailing_8` baseline."""

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

METHOD = "same_weekday_trailing_8"
WEEKS = 8
MINIMUM_OBSERVATIONS = 6


def baselines(series: DataFrame, holidays: DataFrame) -> DataFrame:
    """Daily values per slice -> p10, p50 and p90 of the same weekday over the prior 8 weeks.

    `series` has `metric`, `slice_key`, `slice_value`, `metric_date` and `value`.
    The history of a date is the 8 dates exactly 7, 14, ... 56 days before it.
    Holidays are left out of the history, so a holiday among them leaves 7 values.
    A holiday still gets its own row. A date with fewer than 6 values gets none.
    Percentiles are exact and interpolate linearly, as spec section 6 requires.
    """
    holiday_dates = F.broadcast(
        holidays.select(F.col("holiday_date").alias("metric_date"), F.lit(True).alias("holiday"))
    )
    day_number = F.datediff("metric_date", F.lit("1970-01-01"))
    history = (
        Window.partitionBy("metric", "slice_key", "slice_value", F.dayofweek("metric_date"))
        .orderBy(day_number)
        .rangeBetween(-7 * WEEKS, -7)
    )
    usual = F.when(F.col("holiday").isNull(), F.col("value").cast("double"))
    return (
        series.join(holiday_dates, "metric_date", "left")
        .select(
            "metric",
            "slice_key",
            "slice_value",
            F.col("metric_date").alias("baseline_date"),
            F.lit(METHOD).alias("method"),
            F.percentile(usual, 0.1).over(history).alias("p10"),
            F.percentile(usual, 0.5).over(history).alias("p50"),
            F.percentile(usual, 0.9).over(history).alias("p90"),
            F.count(usual).over(history).cast("int").alias("n_obs"),
        )
        .where(F.col("n_obs") >= MINIMUM_OBSERVATIONS)
    )


def sliced_series(daily: DataFrame, metric: str, dimension: str | None) -> DataFrame:
    """A `daily_series` result -> the long shape `baselines` takes. Null slices are left out."""
    if dimension is None:
        slice_key, slice_value = F.lit("all"), F.lit("all")
    else:
        daily = daily.where(F.col(dimension).isNotNull())
        slice_key, slice_value = F.lit(dimension), F.col(dimension).cast("string")
    return daily.select(
        F.lit(metric).alias("metric"),
        slice_key.alias("slice_key"),
        slice_value.alias("slice_value"),
        "metric_date",
        "value",
    )
