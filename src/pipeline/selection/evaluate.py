"""Scoring. Selection and SQL are scored separately.

Selection: were the expected tables all included, and how many extra came with them.
SQL: did the query run, and does its answer match the reference answer.
"""

import re
from dataclasses import dataclass
from itertools import permutations
from numbers import Number

RELATIVE_TOLERANCE = 1e-3  # for non-integer numbers; integers must be equal
MAX_COLUMNS = 8  # more than this is not searched for a column match
TIMESTAMP_T = re.compile(r"(\d{4}-\d{2}-\d{2})t(\d{2}:)")


@dataclass(frozen=True)
class SelectionScore:
    all_included: bool
    missing: list[str]
    extra: list[str]


def score_selection(expected: list[str], selected: list[str]) -> SelectionScore:
    """The selector is told to over-include, so extras are counted, not failed."""
    missing = sorted(set(expected) - set(selected))
    extra = sorted(set(selected) - set(expected))
    return SelectionScore(not missing, missing, extra)


def is_number(value) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def cells_match(reference, value, tolerance: float) -> bool:
    """One cell of the reference answer against one cell of a model's answer.

    A whole number must be equal. Any other number may differ by the relative
    tolerance. Text is compared without regard to case or outer spaces, and a
    timestamp matches whether it is written with a space or a `T`.
    """
    if reference is None or value is None:
        return reference is None and value is None
    if is_number(reference):
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                return False
        if not is_number(value):
            return False
        if float(reference).is_integer():
            return float(value) == float(reference)
        return abs(float(value) - float(reference)) <= tolerance * abs(float(reference))
    if is_number(value):
        return False
    return _text(reference) == _text(value)


def _text(value) -> str:
    text = TIMESTAMP_T.sub(r"\1 \2", str(value).strip().lower())
    return text.removesuffix(".000000").removesuffix(" 00:00:00")


def _sort_key(row: list) -> tuple:
    def key(value):
        if value is None:
            return (0, 0.0, "")
        if is_number(value):
            return (1, float(f"{float(value):.6g}"), "")
        return (2, 0.0, _text(value))

    return tuple(key(value) for value in row)


def _rows_match(reference: list[list], rows: list[list], tolerance: float) -> bool:
    ordered = zip(sorted(reference, key=_sort_key), sorted(rows, key=_sort_key), strict=True)
    return all(
        all(cells_match(a, b, tolerance) for a, b in zip(ref, got, strict=True))
        for ref, got in ordered
    )


def answers_match(
    reference: list[list], rows: list[list], tolerance: float = RELATIVE_TOLERANCE
) -> bool:
    """Does a model's result hold the reference answer?

    The two must have the same number of rows. Row order, column order and column names
    are ignored, and the model may return extra columns: it matches if some choice of
    its columns, one per reference column, gives the reference rows.
    """
    if len(reference) != len(rows):
        return False
    if not reference:
        return True
    width, got_width = len(reference[0]), len(rows[0])
    if got_width < width or got_width > MAX_COLUMNS:
        return False
    for chosen in permutations(range(got_width), width):
        projected = [[row[i] for i in chosen] for row in rows]
        if _rows_match(reference, projected, tolerance):
            return True
    return False


def summarize(records: list[dict]) -> list[dict]:
    """One line per model and arm: how selection and SQL went over all requests."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        groups.setdefault((record["model"], record["arm"]), []).append(record)
    lines = []
    for (model, arm), group in sorted(groups.items()):
        selections = [r["selection"] for r in group if r.get("selection")]
        by_reference = [r["selection_reference"] for r in group if r.get("selection_reference")]
        format_broken = [r for r in group if r.get("selector") and not r["selector"]["format_ok"]]
        lines.append(
            {
                "model": model,
                "arm": arm,
                "requests": len(group),
                "selection_all_included": sum(s["all_included"] for s in selections)
                if selections
                else None,
                "selection_mean_extra": sum(len(s["extra"]) for s in selections) / len(selections)
                if selections
                else None,
                "selection_reference_all_included": sum(s["all_included"] for s in by_reference)
                if by_reference
                else None,
                "selector_format_broken": len(format_broken) if selections else None,
                "sql_ran": sum(r["sql_status"] == "ok" for r in group),
                "answer_matched": sum(bool(r["answer_matched"]) for r in group),
                "used_tables_not_given": sum(bool(r["tables_not_given"]) for r in group),
                "seconds": round(sum(r.get("seconds") or 0 for r in group), 1),
            }
        )
    return lines


def render_summary(lines: list[dict], header: str) -> str:
    """The summary as a markdown table. Selection columns are empty outside the selector arm."""

    def shown(value, digits: int | None = None) -> str:
        if value is None:
            return ""
        return f"{value:.{digits}f}" if digits is not None else str(value)

    out = [
        header,
        "",
        "| Model | Arm | Requests | Owner's tables all included | Reference query's tables "
        "all included | Mean extra tables | Selector broke the format | SQL ran "
        "| Answer matched | Used a table not given | Seconds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for line in lines:
        out.append(
            f"| {line['model']} | {line['arm']} | {line['requests']} "
            f"| {shown(line['selection_all_included'])} "
            f"| {shown(line['selection_reference_all_included'])} "
            f"| {shown(line['selection_mean_extra'], 1)} "
            f"| {shown(line['selector_format_broken'])} "
            f"| {line['sql_ran']} | {line['answer_matched']} "
            f"| {line['used_tables_not_given']} | {shown(line['seconds'], 0)} |"
        )
    return "\n".join(out) + "\n"
