import copy
import sys
from collections import Counter
from datetime import date

import pytest
import yaml

from pipeline import registry
from pipeline.metrics import load_catalog
from pipeline.registry import Entry, append_only_violations, load_registry, read_raw, validate

CATALOG = load_catalog()

GOOD = {
    "id": "prospective-yellow-example",
    "statement": "Yellow trips fall.",
    "origin": "prospective",
    "author": "ai_sme",
    "elicited_in": "docs/elicitation/example.md",
    "recorded": date(2026, 11, 11),
    "approved_by": "owner",
    "approved_on": date(2026, 11, 11),
    "metric": "tlc_trips",
    "filters": {"service": "yellow"},
    "comparison": "change_vs_period",
    "window": {"start": date(2026, 10, 1), "end": date(2026, 10, 31)},
    "expected": {"low": -11.0, "high": 1.0, "unit": "percent"},
    "confidence": 80,
    "drivers": ["zone_relation"],
    "rationale": "Because.",
}


def problems_of(**changes):
    item = copy.deepcopy(GOOD) | changes
    return " | ".join(
        found for found_list in validate([item], CATALOG)[1].values() for found in found_list
    )


def test_the_real_registry_is_valid_and_holds_the_13_recorded_entries():
    entries = load_registry()

    assert len(entries) == 13
    assert Counter(entry.origin for entry in entries) == {
        "official": 1,
        "prospective": 7,
        "derived": 1,
        "retrospective": 4,
    }
    assert Counter(entry.author for entry in entries) == {"agency": 1, "ai_sme": 12}
    week = next(e for e in entries if e.id == "prospective-crz-entries-2026-11-08-week")
    assert (week.expected.low, week.expected.high, week.confidence) == (-7.5, -1.0, 80)


def test_comparison_window_defaults_to_364_days_earlier():
    entry = Entry.model_validate(GOOD)

    window = entry.effective_comparison_window()
    assert (window.start, window.end) == (date(2025, 10, 2), date(2025, 11, 1))
    assert window.start.weekday() == entry.window.start.weekday()


@pytest.mark.parametrize(
    ("changes", "expected_problem"),
    [
        ({"rationale": "TODO(human)"}, "contains a TODO"),
        ({"metric": "tlc_miles"}, "unknown metric"),
        ({"filters": {"vehicle_class": "buses"}}, "is not a dimension of tlc_trips"),
        ({"drivers": ["detection_group"]}, "driver 'detection_group' is not a dimension"),
        ({"expected": {"low": -11.0, "high": 1.0, "unit": "ratio"}}, "expected.unit must be"),
        ({"expected": {"low": 2.0, "high": 1.0, "unit": "percent"}}, "low is above high"),
        (
            {"comparison_window": {"start": date(2026, 9, 15), "end": date(2026, 10, 15)}},
            "comparison window overlaps",
        ),
        ({"window": {"start": date(2026, 10, 31), "end": date(2026, 10, 1)}}, "ends before"),
        ({"elicited_in": None}, "ai_sme entries need elicited_in"),
        ({"confidence": None}, "a measurable entry needs confidence"),
        ({"confidence": 100}, "less than or equal to 99"),
        ({"id": "Not Kebab"}, "id"),
        ({"surprise": 1}, "Extra inputs are not permitted"),
        ({"origin": "derived"}, "official and derived entries need sources"),
        ({"supersedes": "no-such-entry"}, "supersedes unknown id"),
    ],
)
def test_a_broken_entry_is_rejected_with_a_reason(changes, expected_problem):
    assert expected_problem in problems_of(**changes)


def test_a_good_entry_has_no_problems_and_ids_must_be_unique():
    assert validate([GOOD], CATALOG)[1] == {}
    assert "used more than once" in str(validate([GOOD, GOOD], CATALOG)[1])


def test_vehicle_class_filters_must_use_canonical_labels():
    entries_metric = GOOD | {"metric": "crz_entries", "drivers": [], "filters": {}}

    good = entries_metric | {"filters": {"vehicle_class": "tlc_taxi_fhv"}}
    assert validate([good], CATALOG)[1] == {}
    bad = entries_metric | {"filters": {"vehicle_class": "TLC Taxi/FHV"}}
    assert "is not a canonical label" in str(validate([bad], CATALOG)[1])


def test_append_only_allows_new_entries_and_edits_to_unfrozen_fields():
    base = [copy.deepcopy(GOOD)]
    head = [GOOD | {"rationale": "Reworded.", "note": "Added."}, GOOD | {"id": "another-entry"}]

    assert append_only_violations(base, head) == []


def test_append_only_rejects_changed_values_and_removed_entries():
    base = [copy.deepcopy(GOOD), GOOD | {"id": "second-entry"}]
    widened = GOOD | {"expected": {"low": -20.0, "high": 1.0, "unit": "percent"}}

    violations = append_only_violations(base, [widened])

    assert len(violations) == 2
    assert violations[0].startswith("prospective-yellow-example: expected changed from")
    assert violations[1] == "second-entry: the entry was removed"

    for name, value in (
        ("confidence", 90),
        ("recorded", date(2026, 11, 12)),
        ("metric", "tlc_fee_trips"),
        ("filters", {"service": "fhvhv"}),
        ("window", {"start": date(2026, 10, 1), "end": date(2026, 10, 30)}),
        ("comparison_window", {"start": date(2025, 10, 2), "end": date(2025, 11, 1)}),
    ):
        changed = append_only_violations([GOOD], [GOOD | {name: value}])
        assert len(changed) == 1 and f": {name} changed" in changed[0]


def test_the_append_only_command_exits_1_when_an_expected_range_is_edited(
    tmp_path, monkeypatch, capsys
):
    real = read_raw(registry.REGISTRY_PATH)
    base, head = tmp_path / "base.yaml", tmp_path / "head.yaml"
    base.write_text(yaml.safe_dump(real))

    head.write_text(yaml.safe_dump(real))
    monkeypatch.setattr(
        sys, "argv", ["registry", "append-only", "--base", str(base), "--registry", str(head)]
    )
    with pytest.raises(SystemExit) as unchanged:
        registry.main()
    assert unchanged.value.code == 0

    edited = copy.deepcopy(real)
    target = next(item for item in edited if item.get("expected"))
    target["expected"]["high"] = target["expected"]["high"] + 5
    head.write_text(yaml.safe_dump(edited))
    with pytest.raises(SystemExit) as broken:
        registry.main()
    assert broken.value.code == 1
    assert "expected changed" in capsys.readouterr().out
