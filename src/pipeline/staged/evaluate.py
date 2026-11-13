"""Scoring for the staged harness. Both answer measures are fixed here, before any run.

- Strict (the headline): Phase 8's `answers_match`. Same rows, some choice of columns.
- Loose: `values_present`. Every value of the reference answer is somewhere in the
  model's result, whatever its shape.

A run is never rescored. If a measure turns out to be badly chosen, a later run with a
new measure says so.
"""

from pipeline.selection.evaluate import RELATIVE_TOLERANCE, cells_match

SPLITS = ("all", "seen", "held_out")


def values_present(
    reference: list[list], rows: list[list], tolerance: float = RELATIVE_TOLERANCE
) -> bool:
    """Are all the reference answer's values in the model's result, in any shape?

    Each non-null reference cell must be matched by a cell of the result of its own,
    under the same cell rule as the strict measure: whole numbers equal, other numbers
    within the tolerance, text without regard to case. Rows and columns are ignored, so
    a pivoted answer, or one with rows the reference lacks, still passes. It is weaker
    than the strict measure on purpose: a strict match always passes it, and a large
    result can pass it by accident when the reference values are small numbers.
    """
    wanted = [cell for row in reference for cell in row if cell is not None]
    available = [cell for row in rows for cell in row if cell is not None]
    for cell in wanted:
        position = next(
            (i for i, value in enumerate(available) if cells_match(cell, value, tolerance)), None
        )
        if position is None:
            return False
        del available[position]
    return True


def answerable(table_sets: list[list[str]], tables: list[str]) -> bool:
    """Do the tables include every table of at least one acceptable set?"""
    return any(set(wanted) <= set(tables) for wanted in table_sets)


def _count(group: list[dict], key: str) -> int | None:
    values = [record[key] for record in group if record[key] is not None]
    return sum(bool(value) for value in values) if values else None


def summarize(records: list[dict]) -> list[dict]:
    """One line per model, arm and split (all, seen, held-out)."""
    lines = []
    keys = sorted({(record["model"], record["arm"]) for record in records})
    for model, arm in keys:
        of_arm = [r for r in records if (r["model"], r["arm"]) == (model, arm)]
        for split in SPLITS:
            group = [r for r in of_arm if split == "all" or r["held_out"] == (split == "held_out")]
            if not group:
                continue
            stages = [stage for record in group for stage in record["stages"]]
            lines.append(
                {
                    "model": model,
                    "arm": arm,
                    "split": split,
                    "requests": len(group),
                    "lifecycle_correct": _count(group, "lifecycle_correct"),
                    "answerable": _count(group, "answerable"),
                    "format_broken": sum(stage["format_ok"] is False for stage in stages),
                    "sql_ran": sum(record["sql_status"] == "ok" for record in group),
                    "answer_matched": sum(bool(record["answer_matched"]) for record in group),
                    "values_present": sum(bool(record["values_present"]) for record in group),
                    "seconds": round(sum(record["seconds"] for record in group), 1),
                }
            )
    return lines


def summarize_predictions(comparison: list[dict]) -> list[dict]:
    """One line per model and arm: how many of the owner's predictions agreed with the run."""
    lines = []
    for model, arm in sorted({(line["model"], line["arm"]) for line in comparison}):
        group = [line for line in comparison if (line["model"], line["arm"]) == (model, arm)]
        lines.append(
            {
                "model": model,
                "arm": arm,
                "predictions": len(group),
                "agreed": sum(line["agreed"] for line in group),
                "predicted_match": sum(line["predicted"] == "match" for line in group),
                "observed_match": sum(line["observed"] == "match" for line in group),
            }
        )
    return lines
