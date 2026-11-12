"""Turn a staged results file into the markdown summary beside it. No model and no Spark.

python -m pipeline.staged.report selection/results/staged-<run_id>.json
"""

import json
import sys
from pathlib import Path

from pipeline.staged.runner import ARMS

NOTES = """## How to read this

- **Arms.** `full`: one call with the whole described schema, as in Phase 8.
  `full_narratives`: one call with the whole schema and every narrative. `staged`: a
  selector picks a lifecycle from the index, an interpreter writes a plan from that
  lifecycle's narrative, and a builder writes SQL from the plan and the schema of the
  plan's tables. `staged_hand`: the same, with the owner's lifecycle in place of the selector.
- **Fresh contexts.** Each stage is one model call that is given only its own inputs. The
  builder of the staged arms sees neither the request nor the narrative, only the plan.
- **Strict match** is the headline: the same rows as the reference answer, with row
  order, column order and column names ignored and extra columns allowed.
- **Values present** is the looser measure: every value of the reference answer is
  somewhere in the model's result, whatever its shape. It can pass by accident on a large
  result. Both measures were fixed in code before the run, and no run is rescored.
- **Answerable**: the tables the plan names include every table of at least one of the
  request's acceptable table sets.
- **Seen and held-out.** The seen requests existed when the narratives were written. The
  held-out ones were written after the narratives were frozen.
- **Outcome words.** `match`: strict match. `values`: not a strict match, but the values
  are present. `wrong`: the query ran and neither holds. `error`, `timeout`,
  `too_many_rows`, `rejected`: the query did not run. `no_sql`: no query in the builder's
  answer. `no_tables`: the plan named no known table. `no_lifecycle`: the selector named
  no known lifecycle. `model_error`: a model call failed.
"""


def outcome(record: dict) -> str:
    if record["sql_status"] != "ok":
        return record["sql_status"]
    if record["answer_matched"]:
        return "match"
    return "values" if record["values_present"] else "wrong"


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _shown(value) -> str:
    return "" if value is None else str(value)


def summary_table(lines: list[dict]) -> str:
    out = [
        "| Model | Arm | Requests | Split | Lifecycle correct | Answerable | Format breaks "
        "| SQL ran | Strict match | Values present | Seconds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    order = {arm: position for position, arm in enumerate(ARMS)}
    for line in sorted(lines, key=lambda x: (x["model"], order.get(x["arm"], 99))):
        out.append(
            f"| {line['model']} | {line['arm']} | {line['requests']} | {line['split']} "
            f"| {_shown(line['lifecycle_correct'])} | {_shown(line['answerable'])} "
            f"| {line['format_broken']} | {line['sql_ran']} | {line['answer_matched']} "
            f"| {line['values_present']} | {line['seconds']:.0f} |"
        )
    return "\n".join(out) + "\n"


def outcome_table(records: list[dict]) -> str:
    """One row per request, one column per model and arm."""
    models = list(dict.fromkeys(r["model"] for r in records))
    arms = [arm for arm in ARMS if any(r["arm"] == arm for r in records)]
    by_key = {(r["request_id"], r["model"], r["arm"]): outcome(r) for r in records}
    held_out = {r["request_id"]: r["held_out"] for r in records}
    columns = [(model, arm) for model in models for arm in arms]
    lines = [
        "| Request | Split | " + " | ".join(f"{model} {arm}" for model, arm in columns) + " |",
        "| --- | --- |" + " --- |" * len(columns),
    ]
    for request, held in held_out.items():
        cells = [by_key.get((request, model, arm), "") for model, arm in columns]
        split = "held-out" if held else "seen"
        lines.append(f"| {request} | {split} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def stage_table(records: list[dict]) -> str:
    """What the selector chose and what the plan named, for the staged arms."""
    lines = [
        "| Model | Arm | Request | Owner's lifecycle | Lifecycle used | Plan's tables "
        "| Answerable | Formats kept | Outcome |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        if not record["arm"].startswith("staged"):
            continue
        broken = [s["stage"] for s in record["stages"] if s["format_ok"] is False]
        kept = "yes" if not broken else "NO: " + ", ".join(broken)
        lines.append(
            f"| {record['model']} | {record['arm']} | {record['request_id']} "
            f"| {record['expected_lifecycle']} | {_shown(record['lifecycle']) or '(none)'} "
            f"| {', '.join(record['plan_tables']) or '(none)'} "
            f"| {_shown(record['answerable'])} | {kept} | {outcome(record)} |"
        )
    return "\n".join(lines) + "\n"


def problem_list(records: list[dict]) -> str:
    """Every record whose query did not run, with the reason."""
    lines = [
        f"- `{r['model']}` / `{r['request_id']}` / `{r['arm']}`: {r['sql_status']}. "
        f"{_cell(r['sql_error'] or '')[:300]}"
        for r in records
        if r["sql_status"] != "ok"
    ]
    return "\n".join(lines) + "\n" if lines else "None.\n"


def prediction_tables(summary: list[dict], comparison: list[dict]) -> str:
    if not comparison:
        return "No predictions were compared.\n"
    out = [
        "| Model | Arm | Predictions | Agreed with the run | Predicted to match | Did match |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    order = {arm: position for position, arm in enumerate(ARMS)}
    for line in sorted(summary, key=lambda x: (x["model"], order.get(x["arm"], 99))):
        out.append(
            f"| {line['model']} | {line['arm']} | {line['predictions']} | {line['agreed']} "
            f"| {line['predicted_match']} | {line['observed_match']} |"
        )
    out += ["", "Where the prediction and the run disagree:", ""]
    missed = [line for line in comparison if not line["agreed"]]
    out += [
        f"- `{line['model']}` / `{line['request_id']}` / `{line['arm']}`: predicted "
        f"{line['predicted']}, observed {line['observed']}."
        for line in missed
    ] or ["None."]
    return "\n".join(out) + "\n"


def timing_table(records: list[dict]) -> str:
    """Seconds and prompt sizes per model, arm and stage."""
    lines = [
        "| Model | Arm | Stage | Calls | Mean seconds | Mean prompt tokens "
        "| Largest prompt tokens |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for record in records:
        for stage in record["stages"]:
            groups.setdefault((record["model"], record["arm"], stage["stage"]), []).append(stage)
    order = {arm: position for position, arm in enumerate(ARMS)}
    stage_order = {"selector": 0, "interpreter": 1, "builder": 2}
    for (model, arm, name), stages in sorted(
        groups.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1], 99), stage_order[kv[0][2]])
    ):
        seconds = [s["seconds"] for s in stages if s["seconds"] is not None]
        prompts = [s["prompt_tokens"] for s in stages if s["prompt_tokens"] is not None]
        mean_seconds = f"{sum(seconds) / len(seconds):.1f}" if seconds else ""
        mean_prompt = f"{sum(prompts) / len(prompts):,.0f}" if prompts else ""
        largest = f"{max(prompts):,}" if prompts else ""
        lines.append(
            f"| {model} | {arm} | {name} | {len(stages)} | {mean_seconds} | {mean_prompt} "
            f"| {largest} |"
        )
    return "\n".join(lines) + "\n"


def render_report(result: dict) -> str:
    records = result["records"]
    models = ", ".join(f"`{name}` (`{digest[:12]}`)" for name, digest in result["models"].items())
    options = result["ollama_options"]
    requests = {r["request_id"]: r["held_out"] for r in records}
    held = sum(requests.values())
    header = (
        f"# Staged selection run {result['run_id']}\n\n"
        f"- Inputs at commit `{result['requests_commit']}`: {len(requests)} requests "
        f"({len(requests) - held} seen, {held} held-out), {result['lifecycles']} lifecycles, "
        f"predictions dated {result['predicted_on']}.\n"
        f"- Arms: {', '.join(result['arms'])}.\n"
        f"- Models: {models}. Temperature {options['temperature']}, seed {options['seed']}, "
        f"context {options['num_ctx']:,} tokens.\n"
        f"- Started {result['started_at']}, finished {result['finished_at']}.\n"
        f"- A query is cancelled after {result['sql_time_limit_seconds']} seconds and may "
        f"return at most {result['sql_max_rows']:,} rows.\n"
    )
    parts = [
        header,
        "## Summary\n",
        summary_table(result["summary"]),
        "Lifecycle correct applies to the `staged` arm, and answerable to both staged arms. "
        "Format breaks count stage answers that did not keep their fixed format. Seconds are "
        "the total over the requests, model calls and query together.\n",
        "## Outcome of every request\n",
        outcome_table(records),
        "## The staged arms, stage by stage\n",
        stage_table(records),
        "## Against the owner's predictions\n",
        prediction_tables(result["prediction_summary"], result["prediction_comparison"]),
        "## Queries that did not run\n",
        problem_list(records),
        "## Timings and prompt sizes\n",
        timing_table(records),
        NOTES,
    ]
    return "\n".join(parts)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m pipeline.staged.report selection/results/staged-<run_id>.json")
    source = Path(sys.argv[1])
    target = source.with_suffix(".md")
    target.write_text(render_report(json.loads(source.read_text())))
    print(target)


if __name__ == "__main__":
    main()
