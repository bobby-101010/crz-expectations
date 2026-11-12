"""Run the four arms of the staged harness with local models and write the results.

Refuses to start unless the narratives fit the warehouse, every request has the owner's
`expected_lifecycle` and `acceptable_table_sets`, and `selection/predictions.yaml` covers
every request, arm and model: what is expected is recorded before the models are run.

`--check` only checks those inputs. It calls no model and needs no warehouse.

Writes `selection/results/staged-<run_id>.json` and `.md`. Nothing is written to the
warehouse.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pyspark.sql import SparkSession

from pipeline.jobs import selection_reference
from pipeline.selection import ollama
from pipeline.selection import request_file as base_requests
from pipeline.selection.catalog import load_descriptions, read_tables, render_schema
from pipeline.selection.sql import MAX_ROWS, TIME_LIMIT_SECONDS, execute
from pipeline.session import build_session
from pipeline.staged import narratives, predictions, request_file
from pipeline.staged.evaluate import summarize, summarize_predictions
from pipeline.staged.report import outcome, render_report, summary_table
from pipeline.staged.runner import ARMS, Generate, run_all

MODELS = ["llama3.2:3b", "qwen2.5:14b"]
RESULTS_DIR = base_requests.REQUESTS_PATH.parent / "results"
CHARACTERS_PER_TOKEN = 3.5  # a low guess, so the size check errs towards refusing
OUTPUT_ROOM = 1024  # tokens left for the model's answer


@dataclass(frozen=True)
class Inputs:
    """Everything the run reads that someone else wrote, as it is on disk."""

    requests: list[dict]
    index: list[dict]
    texts: dict[str, str]
    predictions: dict


def load_inputs() -> Inputs:
    index = narratives.read_index() if (narratives.NARRATIVES_DIR / "index.yaml").exists() else []
    return Inputs(base_requests.read_raw(), index, narratives.read_texts(), predictions.read_raw())


def input_problems(
    inputs: Inputs, known_tables: list[str], arms: list[str], models: list[str]
) -> list[str]:
    """Everything that stops a run. Empty when the run may start."""
    if not inputs.index:
        return ["narratives/index.yaml is missing or empty"]
    found = narratives.problems(inputs.index, inputs.texts, known_tables)
    ids = [item.get("id") for item in inputs.index]
    found += request_file.problems(inputs.requests, known_tables, ids)
    request_ids = [item["id"] for item in inputs.requests if item.get("id")]
    found += predictions.problems(inputs.predictions, request_ids, arms, models)
    return found


def prompt_too_long(schema_characters: int, inputs: Inputs) -> str | None:
    """Why the largest prompt would not fit the model's context, or None if it fits."""
    longest = max((len(str(item.get("request", ""))) for item in inputs.requests), default=0)
    characters = schema_characters + sum(len(text) for text in inputs.texts.values()) + longest
    tokens = characters / CHARACTERS_PER_TOKEN
    room = ollama.OPTIONS["num_ctx"] - OUTPUT_ROOM
    if tokens > room:
        return (
            f"the full schema with every narrative is about {tokens:,.0f} tokens, "
            f"more than the {room:,} that fit the context"
        )
    return None


def run(
    spark: SparkSession,
    inputs: Inputs,
    models: list[str],
    generate: Generate,
    arms: tuple[str, ...] = ARMS,
    only: list[str] | None = None,
    progress=None,
) -> tuple[list[dict], list[dict]]:
    """Every model x request x arm. Returns (records, reference answers as JSON)."""
    tables = read_tables(spark)
    found = input_problems(inputs, list(tables), list(arms), models)
    if found:
        raise ValueError("the run may not start: " + "; ".join(found))
    bare = [name for name, table in tables.items() if not table.comment]
    if bare:
        raise ValueError(f"tables without comments: {bare}; run `make catalog-comments` first")

    lifecycles = narratives.parse(inputs.index, inputs.texts)
    requests = request_file.parse(inputs.requests)
    if only is not None:
        requests = [request for request in requests if request.id in only]
    references = selection_reference.run(spark, [request.base for request in requests])
    broken = [name for name, answer in references.items() if not answer.ran]
    if broken:
        raise ValueError(f"reference queries failed for {broken}")

    records = run_all(
        requests,
        models,
        lifecycles,
        tables,
        references,
        generate,
        lambda sql: execute(spark, sql),
        arms,
        progress,
    )
    return records, selection_reference.as_json([r.base for r in requests], references)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=MODELS)
    parser.add_argument("--arms", nargs="+", default=list(ARMS), choices=ARMS)
    parser.add_argument("--only", nargs="+", default=None, help="request ids, for a pilot")
    parser.add_argument("--check", action="store_true", help="check the inputs and stop")
    args = parser.parse_args()
    pilot = args.only is not None

    inputs = load_inputs()
    known = list(load_descriptions())
    found = input_problems(inputs, known, args.arms, args.models)
    if pilot:
        unknown = sorted(set(args.only) - {item.get("id") for item in inputs.requests})
        found += [f"no such request: {name}" for name in unknown]
    if found:
        print("\n".join(found))
        print(f"\n{len(found)} problems. The run may not start until they are settled.")
        sys.exit(1)
    held = sum(bool(item.get("held_out")) for item in inputs.requests)
    print(
        f"{len(inputs.requests)} requests ({held} held-out), {len(inputs.index)} lifecycles, "
        f"predictions dated {inputs.predictions.get('predicted_on')}: the inputs are complete"
    )
    if args.check:
        return

    digests = {model: ollama.model_digest(model) for model in args.models}
    started = datetime.now(UTC)
    run_id = ("pilot-" if pilot else "") + started.strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    partial = RESULTS_DIR / f"staged-{run_id}.partial.jsonl"

    def show(record: dict) -> None:
        # Each record is saved as it finishes, so a run that dies leaves what it had done.
        with open(partial, "a") as out:
            out.write(json.dumps(record) + "\n")
        print(
            f"{record['model']:<12} {record['request_id']:<34} {record['arm']:<16} "
            f"{outcome(record):<13} {record['seconds']:>7.1f}s",
            flush=True,
        )

    spark = build_session("staged_run")
    schema_characters = len(render_schema(list(read_tables(spark).values())))
    too_long = prompt_too_long(schema_characters, inputs)
    if too_long:
        spark.stop()
        sys.exit(f"the run may not start: {too_long}")
    records, references = run(
        spark, inputs, args.models, ollama.generate, tuple(args.arms), args.only, progress=show
    )
    spark.stop()

    for record in records:
        record["run_id"] = run_id
        record["model_digest"] = digests[record["model"]]
    comparison = predictions.compare(inputs.predictions, records)
    result = {
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "requests_commit": os.environ.get("REQUESTS_COMMIT", "unknown"),
        "models": digests,
        "ollama_options": ollama.OPTIONS,
        "sql_time_limit_seconds": TIME_LIMIT_SECONDS,
        "sql_max_rows": MAX_ROWS,
        "arms": args.arms,
        "lifecycles": len(inputs.index),
        "predicted_on": str(inputs.predictions.get("predicted_on")),
        "references": references,
        "summary": summarize(records),
        "prediction_comparison": comparison,
        "prediction_summary": summarize_predictions(comparison),
        "records": records,
    }
    target = RESULTS_DIR / f"staged-{run_id}.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    Path(target.with_suffix(".md")).write_text(render_report(result))
    partial.unlink(missing_ok=True)
    print("\n" + summary_table(result["summary"]))
    print(f"{len(records)} records in {target}")


if __name__ == "__main__":
    main()
