"""Turn a results file into the markdown summary beside it. No model and no Spark.

python -m pipeline.selection.report selection/results/<run_id>.json
"""

import json
import sys
from pathlib import Path

from pipeline.selection.evaluate import render_summary

ARM_ORDER = ("full", "selector", "hand")

NOTES = """## How to read this

- **Arms.** `full`: the builder saw the whole described schema. `selector`: a selector picked
  tables from the one-line index and the builder saw only those. `hand`: the builder saw the
  owner's tables.
- **Selection is scored twice,** against the owner's tables and against the tables the
  reference query reads. For these 12 requests the two lists are the same, because the owner's
  tables were drafted from the reference queries and then approved by the owner. Both measures
  are kept so that they can differ later.
- **An answer matches** when it has the same rows as the reference answer. Row order, column
  order and column names are ignored, and extra columns are allowed. Whole numbers must be
  equal; other numbers may differ by 0.1%.
- **Outcome words.** `match`: the query ran and the answer matched. `wrong`: it ran and the
  answer did not match. `error`: Spark refused the query. `timeout`: cancelled at the time
  limit. `too_many_rows`: more rows than the cap. `rejected`: not a single SELECT.
  `no_sql`: no query could be read from the model's answer. `no_tables`: the selector chose
  no known table, so the builder was not called.
- **Known properties of the data, kept in the reference answers.** Trip counts include
  reversal rows (a reversed yellow trip is two rows). `crz_entries` leaves out vehicles that
  stayed on excluded roadways.
- **Limits.** Twelve tables fit in one prompt, so this is not selection at scale. Twelve
  requests and one run per model at temperature 0 is a small sample: a difference of one or
  two requests is not evidence.
"""


def outcome(record: dict) -> str:
    if record["sql_status"] == "ok":
        return "match" if record["answer_matched"] else "wrong"
    return record["sql_status"]


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _names(tables: list[str]) -> str:
    return ", ".join(tables) if tables else "(none)"


def outcome_table(records: list[dict]) -> str:
    """One row per request, one column per model and arm."""
    models = list(dict.fromkeys(r["model"] for r in records))
    arms = [arm for arm in ARM_ORDER if any(r["arm"] == arm for r in records)]
    requests = list(dict.fromkeys(r["request_id"] for r in records))
    by_key = {(r["request_id"], r["model"], r["arm"]): outcome(r) for r in records}
    columns = [(model, arm) for model in models for arm in arms]
    lines = [
        "| Request | " + " | ".join(f"{model} {arm}" for model, arm in columns) + " |",
        "| --- |" + " --- |" * len(columns),
    ]
    for request in requests:
        cells = [by_key.get((request, model, arm), "") for model, arm in columns]
        lines.append(f"| {request} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def selection_table(records: list[dict]) -> str:
    """What the selector chose, per model and request."""
    lines = [
        "| Model | Request | Owner's tables | Selected | Missing | Extra | Format kept |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        if record["arm"] != "selector":
            continue
        chosen, score = record["selector"], record["selection"]
        kept = "yes" if chosen["format_ok"] else "NO"
        if chosen["unknown"]:
            kept += f"; named unknown tables: {_names(chosen['unknown'])}"
        lines.append(
            f"| {record['model']} | {record['request_id']} | {_names(record['expected_tables'])} "
            f"| {_names(chosen['tables'])} | {_names(score['missing'])} "
            f"| {_names(score['extra'])} | {_cell(kept)} |"
        )
    return "\n".join(lines) + "\n"


def problem_list(records: list[dict]) -> str:
    """Every query that did not run, with Spark's first line."""
    lines = []
    for record in records:
        if record["sql_status"] == "ok":
            continue
        detail = record["sql_error"] or "the model's answer held no query"
        if record["sql_status"] == "no_tables":
            detail = "the selector chose no known table"
        lines.append(
            f"- `{record['model']}` / `{record['request_id']}` / `{record['arm']}`: "
            f"{record['sql_status']}. {_cell(detail)[:300]}"
        )
    return "\n".join(lines) + "\n" if lines else "None.\n"


def not_given_list(records: list[dict]) -> str:
    lines = [
        f"- `{r['model']}` / `{r['request_id']}` / `{r['arm']}`: used "
        f"{_names(r['tables_not_given'])}; was given {_names(r['tables_given'])}. "
        f"Outcome: {outcome(r)}."
        for r in records
        if r["tables_not_given"]
    ]
    return "\n".join(lines) + "\n" if lines else "None.\n"


def timing_table(records: list[dict]) -> str:
    """Model seconds per call kind, and prompt sizes, per model and arm."""
    lines = [
        "| Model | Arm | Mean seconds per request | Mean builder prompt tokens "
        "| Largest prompt tokens |",
        "| --- | --- | --- | --- | --- |",
    ]
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        groups.setdefault((record["model"], record["arm"]), []).append(record)
    for (model, arm), group in sorted(groups.items()):
        prompts = [r["builder"]["prompt_tokens"] for r in group if r["builder"]]
        prompts = [p for p in prompts if p is not None]
        every = prompts + [
            r["selector"]["prompt_tokens"]
            for r in group
            if r["selector"] and r["selector"]["prompt_tokens"] is not None
        ]
        mean_seconds = sum(r["seconds"] for r in group) / len(group)
        mean_prompt = f"{sum(prompts) / len(prompts):,.0f}" if prompts else ""
        largest = f"{max(every):,}" if every else ""
        lines.append(f"| {model} | {arm} | {mean_seconds:.1f} | {mean_prompt} | {largest} |")
    return "\n".join(lines) + "\n"


def render_report(result: dict) -> str:
    records = result["records"]
    models = ", ".join(f"`{name}` (`{digest[:12]}`)" for name, digest in result["models"].items())
    options = result["ollama_options"]
    requests = len({r["request_id"] for r in records})
    header = (
        f"# Selection run {result['run_id']}\n\n"
        f"- Requests file at commit `{result['requests_commit']}`, {requests} requests, "
        f"arms: {', '.join(result['arms'])}.\n"
        f"- Models: {models}. Temperature {options['temperature']}, seed {options['seed']}, "
        f"context {options['num_ctx']:,} tokens.\n"
        f"- Started {result['started_at']}, finished {result['finished_at']}.\n"
        f"- A query is cancelled after {result['sql_time_limit_seconds']} seconds and may "
        f"return at most {result['sql_max_rows']:,} rows.\n\n"
        "## Summary"
    )
    parts = [
        render_summary(result["summary"], header),
        "The selection columns apply to the selector arm only. Seconds are the total for the "
        "arm over all requests, model calls and query together.\n",
        "## Outcome of every request\n",
        outcome_table(records),
        "## What the selector chose\n",
        selection_table(records),
        "## Queries that did not run\n",
        problem_list(records),
        "## Queries that used a table the builder was not shown\n",
        not_given_list(records),
        "## Timings and prompt sizes\n",
        timing_table(records),
        NOTES,
    ]
    return "\n".join(parts)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m pipeline.selection.report selection/results/<run_id>.json")
    source = Path(sys.argv[1])
    target = source.with_suffix(".md")
    target.write_text(render_report(json.loads(source.read_text())))
    print(target)


if __name__ == "__main__":
    main()
