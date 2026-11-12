"""Render the status page from the exported JSON. Needs no Spark."""

import json
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from pipeline.site.charts import fmt, range_bar, series_chart

TEMPLATES = Path(__file__).parent / "templates"
FILES = ["meta", "verdicts", "drivers", "checks", "freshness", "series"]

VERDICTS = {
    "held": ("Held", "The observed value fell inside the expected range."),
    "violated_low": ("Violated: below", "The observed value fell below the expected range."),
    "violated_high": ("Violated: above", "The observed value fell above the expected range."),
    "pending": ("Pending", "The data for this window is not published or loaded yet."),
    "data_issue": (
        "Data issue",
        "A data check on this expectation's inputs failed, so the result is not trusted.",
    ),
    "not_scoreable": (
        "Not scoreable",
        "No data this project holds shares the expectation's baseline. It is shown for context.",
    ),
}
ORIGINS = {
    "prospective": ("Prospective", "Recorded before the data for its window was published."),
    "derived": (
        "Derived",
        "An expert's translation of an official projection onto a metric this project measures.",
    ),
    "official": ("Official", "Published by an agency before the outcome."),
    "retrospective": (
        "Retrospective",
        "Recorded after the data was seen. It checks the pipeline or marks what to watch. "
        "It does not test a forecast.",
    ),
}
ORIGIN_ORDER = ["prospective", "derived", "official", "retrospective"]
AUTHORS = {
    "ai_sme": "an AI agent acting as subject matter expert",
    "agency": "the agency",
    "human": "a person",
}
STATUS_LABELS = {"pass": "Pass", "warn": "Warning", "fail": "Fail"}


def load(folder: Path) -> dict:
    return {name: json.loads((folder / f"{name}.json").read_text()) for name in FILES}


def day(text: str) -> str:
    """'2026-11-08' -> 'Nov 8, 2026'."""
    parsed = date.fromisoformat(text[:10])
    return f"{parsed:%b} {parsed.day}, {parsed.year}"


def moment(text: str | None) -> str:
    if not text:
        return "never"
    parsed = datetime.fromisoformat(text)
    return f"{parsed:%b} {parsed.day}, {parsed.year} at {parsed:%H:%M} UTC"


def describe_series(item: dict, series: dict) -> str:
    """The text alternative for an expectation's chart."""
    window = [value for _, value in series.get("window", [])]
    start, end = (day(d) for d in item["window"])
    if not window:
        text = f"No data yet for {start} to {end}."
    else:
        text = (
            f"Daily {item['metric']} from {start} to {end}: {len(window)} days, "
            f"between {fmt(min(window), None)} and {fmt(max(window), None)}."
        )
    if series.get("comparison"):
        text += f" The comparison window has {len(series['comparison'])} days behind it."
    if series.get("band"):
        text += " The shaded band is each day's usual range."
    return text


def expectation_view(
    item: dict, series: dict, drivers: list[dict], repo_url: str, commit: str
) -> dict:
    """One expectation as the template shows it."""
    label, meaning = VERDICTS[item["verdict"]]
    measurable = item["expected_low"] is not None
    band_by_day = {d: (low, high) for d, low, high in series.get("band", [])}
    by_dimension: dict[str, list[dict]] = {}
    for row in drivers:
        by_dimension.setdefault(row["dimension"], []).append(
            {
                "slice": row["slice_value"],
                "gap": f"{row['gap']:+,.0f}",
                "share": None
                if row["share_of_gap"] is None
                else f"{100 * row['share_of_gap']:+,.0f}%",
            }
        )
    filters = ", ".join(f"{key} = {value}" for key, value in item["filters"].items())
    return item | {
        "verdict_label": label,
        "verdict_meaning": meaning,
        "origin_label": ORIGINS[item["origin"]][0],
        "author_text": AUTHORS[item["author"]],
        "recorded_text": day(item["recorded"]),
        "registry_url": f"{repo_url}/blob/{commit}/expectations/registry.yaml" if commit else None,
        "elicitation_url": f"{repo_url}/blob/main/{item['elicited_in']}"
        if item["elicited_in"]
        else None,
        "window_text": f"{day(item['window'][0])} to {day(item['window'][1])}",
        "comparison_text": (
            f"{day(item['comparison_window'][0])} to {day(item['comparison_window'][1])}"
            if item["comparison_window"]
            else None
        ),
        "filters_text": filters,
        "observed_text": None if item["observed"] is None else fmt(item["observed"], item["unit"]),
        "expected_text": (
            f"{fmt(item['expected_low'], item['unit'])} to "
            f"{fmt(item['expected_high'], item['unit'])}"
            if measurable
            else None
        ),
        "bar": Markup(
            range_bar(item["observed"], item["expected_low"], item["expected_high"], item["unit"])
        )
        if measurable
        else None,
        "chart": Markup(
            series_chart(
                [value for _, value in series.get("window", [])],
                [value for _, value in series.get("comparison", [])],
                [band_by_day.get(d) for d, _ in series.get("window", [])] if band_by_day else None,
                describe_series(item, series),
            )
        )
        if measurable
        else None,
        "chart_text": describe_series(item, series) if measurable else None,
        "drivers": by_dimension,
        "drivers_supported": item["comparison"] == "change_vs_period",
    }


def render(data: dict, essay_exists: bool = False) -> str:
    """The exported data -> the page's HTML."""
    meta = data["meta"]
    repo_url = meta["repo_url"]
    commit = (meta.get("registry_commit") or "").removesuffix("-dirty")
    drivers_by_entry: dict[str, list[dict]] = {}
    for row in data["drivers"]:
        drivers_by_entry.setdefault(row["expectation_id"], []).append(row)

    views = [
        expectation_view(
            item,
            data["series"].get(item["id"], {}),
            drivers_by_entry.get(item["id"], []),
            repo_url,
            commit,
        )
        for item in data["verdicts"]
    ]
    groups = [
        {
            "origin": origin,
            "label": ORIGINS[origin][0],
            "meaning": ORIGINS[origin][1],
            "items": [view for view in views if view["origin"] == origin],
        }
        for origin in ORIGIN_ORDER
    ]
    counts = [
        {
            "key": key,
            "label": VERDICTS[key][0],
            "meaning": VERDICTS[key][1],
            "count": sum(view["verdict"] == key for view in views),
        }
        for key in VERDICTS
    ]
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("index.html.j2").render(
        meta=meta,
        commit=commit,
        dirty=(meta.get("registry_commit") or "").endswith("-dirty"),
        generated=moment(meta.get("generated_at")),
        scored=moment(meta.get("scored_at")),
        groups=[group for group in groups if group["items"]],
        counts=counts,
        total=len(views),
        calibration=meta["calibration"],
        checks=[
            check | {"status_label": STATUS_LABELS[check["status"]]} for check in data["checks"]
        ],
        freshness=[
            row | {"status_label": STATUS_LABELS[row["status"]]} for row in data["freshness"]
        ],
        essay_exists=essay_exists,
        repo_url=repo_url,
    )
