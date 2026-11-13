"""Run the three arms with local models and write the results.

Refuses to start until the owner has filled in `expected_tables` for every request:
the answer key is recorded before the models are run.

Writes `selection/results/<run_id>.json` and `.md`, and appends to
`selection/precedents.jsonl`. Nothing is written to the warehouse.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from pyspark.sql import SparkSession

from pipeline.jobs import selection_reference
from pipeline.selection import ollama, precedents, request_file
from pipeline.selection.catalog import read_tables
from pipeline.selection.evaluate import render_summary, summarize
from pipeline.selection.report import render_report
from pipeline.selection.request_file import Request
from pipeline.selection.runner import ARMS, Generate, run_all
from pipeline.selection.sql import MAX_ROWS, TIME_LIMIT_SECONDS, Warehouse, execute
from pipeline.session import build_session

MODELS = ["llama3.2:3b", "qwen2.5:14b"]
RESULTS_DIR = request_file.REQUESTS_PATH.parent / "results"


def run(
    spark: SparkSession,
    requests: list[Request],
    models: list[str],
    generate: Generate,
    arms: tuple[str, ...] = ARMS,
    progress=None,
    execute_sql=None,
) -> tuple[list[dict], dict]:
    """Every model x request x arm. Returns (records, reference answers as JSON)."""
    waiting = request_file.without_expected_tables(requests)
    if waiting:
        raise ValueError(f"expected_tables is empty for {waiting}; the owner fills these in first")

    references = selection_reference.run(spark, requests)
    broken = [name for name, answer in references.items() if not answer.ran]
    if broken:
        raise ValueError(f"reference queries failed for {broken}")

    tables = read_tables(spark)
    bare = [name for name, table in tables.items() if not table.comment]
    if bare:
        raise ValueError(f"tables without comments: {bare}; run `make catalog-comments` first")

    records = run_all(
        requests,
        models,
        tables,
        references,
        generate,
        execute_sql or (lambda sql: execute(spark, sql)),
        arms,
        progress,
    )
    return records, selection_reference.as_json(requests, references)


def show(record: dict) -> None:
    selection = record["selection"]
    chosen = (
        "" if selection is None else f" missing {selection['missing']} extra {selection['extra']}"
    )
    print(
        f"{record['model']:<12} {record['request_id']:<32} {record['arm']:<9} "
        f"sql {record['sql_status']:<13} match {record['answer_matched']}{chosen}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=MODELS)
    parser.add_argument("--arms", nargs="+", default=list(ARMS), choices=ARMS)
    parser.add_argument("--only", nargs="+", default=None, help="request ids, for a pilot")
    args = parser.parse_args()
    pilot = args.only is not None

    requests = request_file.parse(request_file.read_raw())
    if pilot:
        unknown = sorted(set(args.only) - {request.id for request in requests})
        if unknown:
            sys.exit(f"no such request: {unknown}")
        requests = [request for request in requests if request.id in args.only]
    waiting = request_file.without_expected_tables(requests)
    if waiting:
        print(f"expected_tables is empty for {len(waiting)} requests: {waiting}")
        print("The owner fills these in and commits them before any model is run.")
        sys.exit(1)

    digests = {model: ollama.model_digest(model) for model in args.models}
    started = datetime.now(UTC)
    run_id = ("pilot-" if pilot else "") + started.strftime("%Y%m%dT%H%M%SZ")

    spark = build_session("selection_run")
    # The session is replaced after a query that hits the time limit: see `Warehouse`.
    warehouse = Warehouse(spark, lambda: build_session("selection_run"))
    records, references = run(
        spark,
        requests,
        args.models,
        ollama.generate,
        tuple(args.arms),
        progress=show,
        execute_sql=warehouse.execute,
    )
    warehouse.spark.stop()

    for record in records:
        record["run_id"] = run_id
        record["model_digest"] = digests[record["model"]]
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
        "references": references,
        "summary": summarize(records),
        "records": records,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    Path(RESULTS_DIR / f"{run_id}.json").write_text(json.dumps(result, indent=2) + "\n")
    Path(RESULTS_DIR / f"{run_id}.md").write_text(render_report(result))
    summary = render_summary(result["summary"], f"# Selection run {run_id}")
    # A pilot is a timing run on a few requests. It saves no precedents.
    saved = 0 if pilot else precedents.append(records, started.isoformat())
    print("\n" + summary)
    print(f"{len(records)} records in {RESULTS_DIR / (run_id + '.json')}; {saved} precedents saved")


if __name__ == "__main__":
    main()
