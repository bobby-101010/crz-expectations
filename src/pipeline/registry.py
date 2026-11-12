"""The expectation registry: its model, validation, and the append-only rule (spec 7.5).

Run `python -m pipeline.registry validate` to check the registry against the metric
catalog, and `python -m pipeline.registry append-only --base FILE` to compare it with
an earlier version.
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pipeline.metrics import Catalog, load_catalog

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "expectations" / "registry.yaml"

# Once an entry is on main, these never change. A revision is a new entry with `supersedes`.
FROZEN_FIELDS = [
    "metric",
    "filters",
    "comparison",
    "window",
    "comparison_window",
    "expected",
    "confidence",
    "recorded",
]

UNIT_FOR = {"change_vs_period": "percent", "within_baseline": "percent_of_days"}
DEFAULT_SHIFT_DAYS = 364  # keeps weekdays aligned


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Window(Strict):
    start: date
    end: date

    @model_validator(mode="after")
    def ends_after_it_starts(self):
        if self.end < self.start:
            raise ValueError("window ends before it starts")
        return self

    def shifted(self, days: int) -> "Window":
        return Window(start=self.start + timedelta(days=days), end=self.end + timedelta(days=days))

    def overlaps(self, start: date, end: date) -> bool:
        return self.start <= end and start <= self.end

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class Expected(Strict):
    low: float
    high: float
    unit: str

    @model_validator(mode="after")
    def low_is_not_above_high(self):
        if self.low > self.high:
            raise ValueError("expected low is above high")
        return self


class ReportedOutcome(Strict):
    value: float
    unit: str
    source: str
    note: str | None = None


class Entry(Strict):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    statement: str = Field(min_length=1)
    origin: Literal["official", "derived", "prospective", "retrospective"]
    author: Literal["agency", "ai_sme", "human"]
    elicited_in: str | None = None
    recorded: date
    recorded_note: str | None = None
    approved_by: str = Field(min_length=1)
    approved_on: date
    metric: str | None = None
    filters: dict[str, str | int] = Field(default_factory=dict)
    comparison: Literal["change_vs_period", "within_baseline", "value_range"] | None = None
    window: Window
    comparison_window: Window | None = None
    expected: Expected | None = None
    confidence: int | None = Field(default=None, ge=50, le=99)
    measurable: bool = True
    not_measurable_reason: str | None = None
    drivers: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    note: str | None = None
    sources: list[str] = Field(default_factory=list)
    reported_outcome: ReportedOutcome | None = None
    supersedes: str | None = None

    @model_validator(mode="after")
    def fields_agree(self):
        if self.author == "ai_sme" and not self.elicited_in:
            raise ValueError("ai_sme entries need elicited_in")
        if self.origin in ("official", "derived") and not self.sources:
            raise ValueError("official and derived entries need sources")
        if not self.measurable:
            if not self.not_measurable_reason:
                raise ValueError("not measurable without a reason")
            return self
        for name in ("metric", "comparison", "expected", "confidence"):
            if getattr(self, name) is None:
                raise ValueError(f"a measurable entry needs {name}")
        unit = UNIT_FOR.get(self.comparison)
        if unit and self.expected.unit != unit:
            raise ValueError(f"expected.unit must be {unit!r} for {self.comparison}")
        if self.comparison == "change_vs_period":
            if self.effective_comparison_window().end >= self.window.start:
                raise ValueError("comparison window overlaps the window")
        elif self.comparison_window is not None:
            raise ValueError(f"{self.comparison} takes no comparison_window")
        return self

    def effective_comparison_window(self) -> Window | None:
        """The stated comparison window, or the window shifted back 364 days."""
        if self.comparison != "change_vs_period":
            return None
        return self.comparison_window or self.window.shifted(-DEFAULT_SHIFT_DAYS)


def read_raw(path: Path) -> list[dict]:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, list):
        raise ValueError(f"{path} must hold a list of entries")
    return raw


def catalog_problems(entry: Entry, catalog: Catalog) -> list[str]:
    """Where a measurable entry disagrees with the metric catalog."""
    if not entry.measurable:
        return []
    metric = catalog.metrics.get(entry.metric)
    if metric is None:
        return [f"unknown metric {entry.metric!r}"]
    problems = [
        f"{kind} {name!r} is not a dimension of {metric.name}"
        for kind, names in (("filter", entry.filters), ("driver", entry.drivers))
        for name in names
        if name not in metric.dimensions
    ]
    known_classes = set(catalog.vehicle_classes)
    vehicle_class = entry.filters.get("vehicle_class")
    if vehicle_class is not None and vehicle_class not in known_classes:
        problems.append(f"vehicle_class {vehicle_class!r} is not a canonical label")
    return problems


def validate(raw: list[dict], catalog: Catalog) -> tuple[list[Entry], dict[str, list[str]]]:
    """Raw registry -> (entries that parsed, problems by entry id). No problems means valid."""
    entries: list[Entry] = []
    problems: dict[str, list[str]] = {}
    for position, item in enumerate(raw):
        label = str(item.get("id", f"entry {position + 1}")) if isinstance(item, dict) else "?"
        found: list[str] = []
        if "TODO" in yaml.safe_dump(item):
            found.append("contains a TODO")
        try:
            entry = Entry.model_validate(item)
        except ValidationError as error:
            found.extend(
                f"{'.'.join(str(part) for part in e['loc']) or 'entry'}: {e['msg']}"
                for e in error.errors()
            )
        else:
            entries.append(entry)
            found.extend(catalog_problems(entry, catalog))
        if found:
            problems.setdefault(label, []).extend(found)

    ids = [entry.id for entry in entries]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        problems.setdefault(duplicate, []).append("id is used more than once")
    for entry in entries:
        if entry.supersedes and entry.supersedes not in ids:
            problems.setdefault(entry.id, []).append(f"supersedes unknown id {entry.supersedes!r}")
    return entries, problems


def load_registry(path: Path | None = None, catalog: Catalog | None = None) -> list[Entry]:
    """Read and validate the registry. Raises ValueError listing every problem."""
    path = path or Path(os.environ.get("REGISTRY", REGISTRY_PATH))
    entries, problems = validate(read_raw(path), catalog or load_catalog())
    if problems:
        lines = [f"{entry_id}: {'; '.join(found)}" for entry_id, found in problems.items()]
        raise ValueError("registry is not valid:\n" + "\n".join(lines))
    return entries


def append_only_violations(base: list[dict], head: list[dict]) -> list[str]:
    """Ways `head` breaks the append-only rule against `base`. Empty means it holds.

    Compared as written, so adding an explicit value where a default applied also counts.
    """
    current = {item.get("id"): item for item in head}
    violations = []
    for old in base:
        entry_id = old.get("id")
        new = current.get(entry_id)
        if new is None:
            violations.append(f"{entry_id}: the entry was removed")
            continue
        for name in FROZEN_FIELDS:
            if old.get(name) != new.get(name):
                violations.append(
                    f"{entry_id}: {name} changed from {old.get(name)!r} to {new.get(name)!r}"
                )
    return violations


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "append-only"):
        command = commands.add_parser(name)
        command.add_argument("--registry", type=Path, default=None)
        if name == "append-only":
            command.add_argument("--base", type=Path, required=True)
    args = parser.parse_args()
    path = args.registry or Path(os.environ.get("REGISTRY", REGISTRY_PATH))

    if args.command == "validate":
        entries, problems = validate(read_raw(path), load_catalog())
        for entry_id, found in problems.items():
            print(f"{entry_id}: {'; '.join(found)}")
        print(f"{len(read_raw(path))} entries, {'INVALID' if problems else 'valid'}")
        sys.exit(1 if problems else 0)

    violations = append_only_violations(read_raw(args.base), read_raw(path))
    for violation in violations:
        print(violation)
    print("append-only rule " + ("BROKEN" if violations else "holds"))
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
