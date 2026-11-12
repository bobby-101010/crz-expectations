"""Precedents: each request with the tables that were used for it.

One JSON object per line, appended. Reading them back into the selector is a later
step; this only saves them. Every outcome is saved with its flags, so a reader can
keep only the ones whose query ran and matched.
"""

import json
from pathlib import Path

PRECEDENTS_PATH = Path(__file__).resolve().parents[3] / "selection" / "precedents.jsonl"
ARM = "selector"  # precedents come from the loop itself, not from the comparison arms


def precedent(record: dict, saved_at: str) -> dict:
    """One run record of the selector arm -> the precedent kept for it."""
    return {
        "saved_at": saved_at,
        "run_id": record["run_id"],
        "model": record["model"],
        "request_id": record["request_id"],
        "request": record["request"],
        "tables_selected": record["tables_given"],
        "tables_used": record["tables_in_sql"],
        "sql": record["sql"],
        "sql_ran": record["sql_status"] == "ok",
        "answer_matched": record["answer_matched"],
    }


def append(records: list[dict], saved_at: str, path: Path | None = None) -> int:
    """Append a precedent for every selector-arm record. Returns how many were written."""
    kept = [precedent(record, saved_at) for record in records if record["arm"] == ARM]
    if not kept:
        return 0
    target = path or PRECEDENTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a") as out:
        for item in kept:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(kept)
