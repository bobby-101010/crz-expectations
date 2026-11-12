"""The three arms, run on the same requests.

- `full`: the builder gets the whole described schema.
- `selector`: a selector picks tables from the one-line index, and the builder gets those.
- `hand`: the builder gets the tables the owner picked.

The model call and the query execution are passed in, so tests need neither.
"""

import re
from collections.abc import Callable
from dataclasses import asdict

from pipeline.selection import builder, selector
from pipeline.selection.catalog import Table, render_index, render_schema
from pipeline.selection.evaluate import RELATIVE_TOLERANCE, answers_match, score_selection
from pipeline.selection.ollama import Reply
from pipeline.selection.request_file import Request
from pipeline.selection.sql import QueryResult

ARMS = ("full", "selector", "hand")
ROWS_KEPT = 50  # result rows saved per record; the match is judged on all of them

NO_TABLES, NO_SQL = "no_tables", "no_sql"

Generate = Callable[[str, str, str], Reply]  # (model, system, prompt) -> Reply
Execute = Callable[[str], QueryResult]


def tables_in_sql(sql: str | None, known: list[str]) -> list[str]:
    """The known tables a query names, with or without `local.` in front."""
    if not sql:
        return []
    return [
        name
        for name in known
        if re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", sql.replace("local.", ""), re.I)
    ]


def _call(reply: Reply) -> dict:
    return {"answer": reply.text} | {k: v for k, v in asdict(reply).items() if k != "text"}


def run_arm(
    arm: str,
    model: str,
    request: Request,
    tables: dict[str, Table],
    reference: QueryResult,
    generate: Generate,
    execute: Execute,
) -> dict:
    """One request through one arm with one model -> its record."""
    known = list(tables)
    record = {
        "model": model,
        "arm": arm,
        "request_id": request.id,
        "request": request.request,
        "expected_tables": request.expected_tables,
        "selector": None,
        "selection": None,
        "builder": None,
        "sql": None,
        "sql_status": None,
        "sql_error": None,
        "sql_seconds": None,
        "tables_in_sql": [],
        "tables_not_given": [],  # named in the SQL although the builder was not shown them
        "result_columns": [],
        "result_rows": [],
        "result_row_count": None,
        "answer_matched": False,
    }

    if arm == "full":
        given = known
    elif arm == "hand":
        given = [name for name in known if name in request.expected_tables]
    elif arm == "selector":
        reply = generate(
            model,
            selector.SYSTEM,
            selector.build_prompt(render_index(tables.values()), request.request),
        )
        chosen = selector.parse(reply.text, known)
        given = [name for name in known if name in chosen.tables]
        record["selector"] = _call(reply) | asdict(chosen)
        record["selection"] = asdict(score_selection(request.expected_tables, chosen.tables))
    else:
        raise ValueError(f"unknown arm {arm}")
    record["tables_given"] = given

    if not given:
        record["sql_status"] = NO_TABLES
        return record

    schema = render_schema([tables[name] for name in given])
    reply = generate(model, builder.SYSTEM, builder.build_prompt(schema, request.request))
    record["builder"] = _call(reply)
    sql = builder.extract_sql(reply.text)
    if sql is None:
        record["sql_status"] = NO_SQL
        return record

    result = execute(sql)
    tolerance = RELATIVE_TOLERANCE if request.tolerance is None else request.tolerance
    record |= {
        "sql": sql,
        "sql_status": result.status,
        "sql_error": result.error,
        "sql_seconds": result.seconds,
        "tables_in_sql": tables_in_sql(sql, known),
        "tables_not_given": [t for t in tables_in_sql(sql, known) if t not in given],
        "result_columns": result.columns,
        "result_rows": result.rows[:ROWS_KEPT],
        "result_row_count": len(result.rows) if result.ran else None,
        "answer_matched": result.ran and answers_match(reference.rows, result.rows, tolerance),
    }
    return record


def run_all(
    requests: list[Request],
    models: list[str],
    tables: dict[str, Table],
    references: dict[str, QueryResult],
    generate: Generate,
    execute: Execute,
    arms: tuple[str, ...] = ARMS,
    progress: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Every model x request x arm, in that order."""
    records = []
    for model in models:
        for request in requests:
            for arm in arms:
                record = run_arm(
                    arm, model, request, tables, references[request.id], generate, execute
                )
                records.append(record)
                if progress:
                    progress(record)
    return records
