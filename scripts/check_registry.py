"""Validate expectations/registry.yaml against SPEC.md section 7.5 (v1.1)."""
import sys
from datetime import date, timedelta

import yaml

METRICS = {
    "crz_entries": {"vehicle_class", "detection_group", "time_period"},
    "excluded_roadway_entries": {"vehicle_class", "detection_group", "time_period"},
    "tlc_trips": {"service", "operator_code", "zone_relation", "pickup_hour"},
    "tlc_cbd_touch_trips": {"service", "operator_code", "zone_relation", "pickup_hour"},
    "tlc_fee_trips": {"service", "operator_code", "zone_relation", "pickup_hour"},
    "fhvhv_per_yellow": set(),
}
ORIGINS = {"official", "derived", "prospective", "retrospective"}
AUTHORS = {"agency", "ai_sme", "human"}
COMPARISONS = {"change_vs_period", "within_baseline", "value_range"}
UNITS = {"change_vs_period": "percent", "within_baseline": "percent_of_days"}
REQUIRED = ["id", "statement", "origin", "author", "recorded", "window", "rationale", "approved_by", "approved_on"]


def as_date(value, where):
    if not isinstance(value, date):
        raise ValueError(f"{where} must be a YYYY-MM-DD date, got {value!r}")
    return value


def check(entry):
    eid = entry.get("id", "<no id>")
    errors = []
    for field in REQUIRED:
        if field not in entry or entry[field] in (None, ""):
            errors.append(f"missing {field}")
    if "TODO" in yaml.safe_dump(entry):
        errors.append("contains a TODO")
    if entry.get("origin") not in ORIGINS:
        errors.append(f"origin {entry.get('origin')!r}")
    if entry.get("author") not in AUTHORS:
        errors.append(f"author {entry.get('author')!r}")
    if entry.get("author") == "ai_sme" and not entry.get("elicited_in"):
        errors.append("ai_sme entries need elicited_in")
    if entry.get("origin") in {"official", "derived"} and not entry.get("sources"):
        errors.append("official and derived entries need sources")
    try:
        as_date(entry.get("recorded"), "recorded")
        as_date(entry.get("approved_on"), "approved_on")
        window = entry["window"]
        start, end = as_date(window["start"], "window.start"), as_date(window["end"], "window.end")
        if end < start:
            errors.append("window ends before it starts")
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
        return errors

    if entry.get("measurable", True) is False:
        if not entry.get("not_measurable_reason"):
            errors.append("not measurable without a reason")
        return errors

    metric, comparison = entry.get("metric"), entry.get("comparison")
    if metric not in METRICS:
        errors.append(f"unknown metric {metric!r}")
    if comparison not in COMPARISONS:
        errors.append(f"unknown comparison {comparison!r}")
    for dim in (entry.get("filters") or {}):
        if dim not in METRICS.get(metric, set()):
            errors.append(f"filter {dim!r} is not a dimension of {metric}")
    for dim in entry.get("drivers") or []:
        if dim not in METRICS.get(metric, set()):
            errors.append(f"driver {dim!r} is not a dimension of {metric}")
    expected = entry.get("expected") or {}
    low, high = expected.get("low"), expected.get("high")
    if not all(isinstance(v, (int, float)) for v in (low, high)):
        errors.append("expected low and high must be numbers")
    elif low > high:
        errors.append("expected low is above high")
    unit = UNITS.get(comparison)
    if unit and expected.get("unit") != unit:
        errors.append(f"expected.unit must be {unit!r} for {comparison}")
    if comparison == "change_vs_period":
        cw = entry.get("comparison_window") or {
            "start": start - timedelta(days=364), "end": end - timedelta(days=364)}
        cs, ce = as_date(cw["start"], "comparison_window.start"), as_date(cw["end"], "comparison_window.end")
        if ce >= start:
            errors.append("comparison window overlaps the window")
    if not isinstance(entry.get("confidence"), int) or not 50 <= entry["confidence"] <= 99:
        errors.append("confidence must be an integer percent")
    return errors


def main(path):
    entries = yaml.safe_load(open(path))
    ids = [e.get("id") for e in entries]
    problems = {i: check(e) for i, e in zip(ids, entries)}
    dupes = {i for i in ids if ids.count(i) > 1}
    ok = True
    for eid, errs in problems.items():
        status = "ok" if not errs else "; ".join(errs)
        ok &= not errs
        print(f"{eid}: {status}")
    if dupes:
        ok = False
        print("duplicate ids:", dupes)
    print(f"{len(entries)} entries, {'valid' if ok else 'INVALID'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1])
