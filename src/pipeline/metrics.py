"""The metric catalog: a small semantic layer over the gold tables (spec section 7.4)."""

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

CATALOG_PATH = Path(__file__).resolve().parents[2] / "expectations" / "metrics.yaml"


@dataclass(frozen=True)
class Metric:
    name: str
    kind: str  # "sum" or "ratio"
    source: str | None = None
    date_column: str | None = None
    value: str | None = None
    filter: str | None = None
    dimensions: tuple[str, ...] = ()
    baseline: bool = False
    numerator: dict = field(default_factory=dict)
    denominator: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Catalog:
    metrics: dict[str, Metric]
    vehicle_classes: dict[str, str]  # canonical label -> source label


def load_catalog(path: Path | None = None) -> Catalog:
    """Read and validate the catalog. Raises ValueError on anything that does not resolve."""
    path = path or Path(os.environ.get("METRICS_CATALOG", CATALOG_PATH))
    raw = yaml.safe_load(path.read_text())
    metrics = {}
    for name, spec in raw["metrics"].items():
        spec = dict(spec)
        spec["dimensions"] = tuple(spec.get("dimensions", ()))
        metrics[name] = Metric(name=name, **spec)

    classes = raw.get("vehicle_classes", {})
    if len(set(classes.values())) != len(classes):
        raise ValueError("vehicle_classes must map one-to-one")

    for metric in metrics.values():
        if metric.kind == "sum":
            if not (metric.source and metric.date_column and metric.value):
                raise ValueError(f"{metric.name}: a sum metric needs source, date_column and value")
        elif metric.kind == "ratio":
            if metric.baseline or metric.dimensions:
                raise ValueError(f"{metric.name}: a ratio metric has no dimensions or baseline")
            for part in (metric.numerator, metric.denominator):
                base = metrics.get(part.get("metric"))
                if base is None or base.kind != "sum":
                    raise ValueError(f"{metric.name}: {part} does not name a sum metric")
                unknown = set(part.get("filters", {})) - set(base.dimensions)
                if unknown:
                    raise ValueError(f"{metric.name}: {unknown} are not dimensions of {base.name}")
        else:
            raise ValueError(f"{metric.name}: unknown kind {metric.kind!r}")
    return Catalog(metrics, classes)


def daily_series(
    spark: SparkSession,
    metric: Metric,
    start: date,
    end: date,
    by: str | None = None,
    filters: dict | None = None,
) -> DataFrame:
    """A sum metric per day in [start, end], both dates included.

    Returns `metric_date`, `value`, and the `by` dimension if one is given.
    Ratio metrics are computed by the caller from two filtered sum series.
    """
    if metric.kind != "sum":
        raise ValueError(f"{metric.name}: daily_series handles sum metrics only")
    for dimension in [*([by] if by else []), *(filters or {})]:
        if dimension not in metric.dimensions:
            raise ValueError(f"{dimension!r} is not a dimension of {metric.name}")

    day = F.col(metric.date_column)
    rows = spark.table(f"local.{metric.source}").where((day >= F.lit(start)) & (day <= F.lit(end)))
    if metric.filter:
        rows = rows.where(metric.filter)
    for dimension, wanted in (filters or {}).items():
        rows = rows.where(F.col(dimension) == F.lit(wanted))
    keys = [day.alias("metric_date"), *([F.col(by)] if by else [])]
    return rows.groupBy(*keys).agg(F.sum(metric.value).alias("value"))
