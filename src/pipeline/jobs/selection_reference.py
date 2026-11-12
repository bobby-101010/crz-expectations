"""Run every request's reference query and save the answers for review.

Writes `selection/reference_answers.json`. No model is called. The model run computes
the reference answers again itself, so this file is a record, not an input.
"""

import json
import sys
from pathlib import Path

from pyspark.sql import SparkSession

from pipeline.selection import request_file
from pipeline.selection.catalog import table_names
from pipeline.selection.request_file import Request
from pipeline.selection.sql import QueryResult, execute, use_warehouse
from pipeline.session import build_session

ANSWERS_PATH = request_file.REQUESTS_PATH.parent / "reference_answers.json"


def run(spark: SparkSession, requests: list[Request]) -> dict[str, QueryResult]:
    """Request id -> the result of its reference query."""
    use_warehouse(spark)
    return {request.id: execute(spark, request.reference_sql) for request in requests}


def as_json(requests: list[Request], answers: dict[str, QueryResult]) -> list[dict]:
    return [
        {
            "id": request.id,
            "request": request.request,
            "status": answers[request.id].status,
            "error": answers[request.id].error,
            "columns": answers[request.id].columns,
            "rows": answers[request.id].rows,
        }
        for request in requests
    ]


def main() -> None:
    spark = build_session("selection_reference")
    raw = request_file.read_raw()
    found = request_file.problems(raw, table_names(spark))
    if found:
        print("\n".join(found))
        spark.stop()
        sys.exit(1)

    requests = request_file.parse(raw)
    answers = run(spark, requests)
    Path(ANSWERS_PATH).write_text(json.dumps(as_json(requests, answers), indent=2) + "\n")
    failed = 0
    for request in requests:
        answer = answers[request.id]
        failed += not answer.ran
        print(f"\n{request.id} [{answer.status}, {answer.seconds:.1f}s] {request.request}")
        print(f"  {answer.columns}" if answer.ran else f"  {answer.error}")
        for row in answer.rows[:20]:
            print(f"  {row}")
    waiting = request_file.without_expected_tables(requests)
    print(f"\n{len(requests)} requests, {failed} reference queries failed")
    print(f"{len(waiting)} requests still need the owner's expected_tables")
    spark.stop()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
