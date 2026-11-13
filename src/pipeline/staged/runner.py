"""The four arms, run on the same requests.

- `full`: one call with the whole described schema. This is Phase 8's `full` arm, with
  the same system text and prompt.
- `full_narratives`: one call with the whole described schema and every narrative.
- `staged`: selector, then interpreter, then builder, each in a context of its own.
- `staged_hand`: the owner's lifecycle in place of the selector, then the same two stages.

Each stage is one call to `generate(model, system, prompt)`. Nothing else goes to the
model: no earlier answer, no conversation state. What a stage passes on is the parsed
hand-off, written out again in a fixed form.
"""

import time
from collections.abc import Callable
from dataclasses import asdict

from pipeline.selection import builder
from pipeline.selection.catalog import Table, render_schema
from pipeline.selection.evaluate import RELATIVE_TOLERANCE, answers_match
from pipeline.selection.ollama import Reply
from pipeline.selection.runner import ROWS_KEPT, tables_in_sql
from pipeline.selection.sql import QueryResult
from pipeline.staged import interpreter, lifecycle_selector, narratives, plan_builder
from pipeline.staged.evaluate import answerable, values_present
from pipeline.staged.narratives import Lifecycle
from pipeline.staged.request_file import StagedRequest

ARMS = ("full", "full_narratives", "staged", "staged_hand")

NO_LIFECYCLE, NO_TABLES, NO_SQL, MODEL_ERROR = "no_lifecycle", "no_tables", "no_sql", "model_error"

Generate = Callable[[str, str, str], Reply]  # (model, system, prompt) -> Reply
Execute = Callable[[str], QueryResult]


class StageFailed(Exception):
    """A stage could not hand anything on. The record keeps the reason as its status."""

    def __init__(self, status: str, detail: str | None = None):
        super().__init__(status)
        self.status, self.detail = status, detail


def call_stage(
    record: dict, name: str, model: str, system: str, prompt: str, generate: Generate
) -> dict:
    """One model call. Its prompt, answer, token counts and seconds are kept on the record."""
    stage = {
        "stage": name,
        "system": system,
        "prompt": prompt,
        "answer": None,
        "parsed": None,
        "format_ok": None,
        "prompt_tokens": None,
        "output_tokens": None,
        "seconds": None,
    }
    record["stages"].append(stage)
    started = time.monotonic()
    try:
        reply = generate(model, system, prompt)
    except Exception as failure:  # an unreachable or timed-out model is a result, not a crash
        stage["seconds"] = round(time.monotonic() - started, 3)
        raise StageFailed(MODEL_ERROR, f"{name}: {type(failure).__name__}: {failure}") from failure
    stage |= {
        "answer": reply.text,
        "prompt_tokens": reply.prompt_tokens,
        "output_tokens": reply.output_tokens,
        "seconds": reply.seconds,
    }
    return stage


def select_lifecycle(
    record: dict,
    model: str,
    request: StagedRequest,
    lifecycles: list[Lifecycle],
    generate: Generate,
) -> Lifecycle:
    """Stage 1. Prompt: the index lines and the request."""
    prompt = lifecycle_selector.build_prompt(narratives.render_index(lifecycles), request.request)
    stage = call_stage(record, "selector", model, lifecycle_selector.SYSTEM, prompt, generate)
    choice = lifecycle_selector.parse(stage["answer"], [lc.id for lc in lifecycles])
    stage |= {"parsed": asdict(choice), "format_ok": choice.format_ok}
    record["lifecycle"] = choice.lifecycle
    record["lifecycle_correct"] = choice.lifecycle == request.expected_lifecycle
    if choice.lifecycle is None:
        raise StageFailed(NO_LIFECYCLE)
    return next(lc for lc in lifecycles if lc.id == choice.lifecycle)


def interpret(
    record: dict,
    model: str,
    request: StagedRequest,
    lifecycle: Lifecycle,
    known: list[str],
    generate: Generate,
) -> interpreter.Plan:
    """Stage 2. Prompt: one narrative and the request."""
    prompt = interpreter.build_prompt(lifecycle.narrative, request.request)
    stage = call_stage(record, "interpreter", model, interpreter.SYSTEM, prompt, generate)
    plan = interpreter.parse(stage["answer"], known)
    stage |= {"parsed": asdict(plan) | {"hand_off": plan.text()}, "format_ok": plan.format_ok}
    record |= {
        "plan": plan.text(),
        "plan_tables": plan.tables,
        "plan_tables_outside_lifecycle": [t for t in plan.tables if t not in lifecycle.tables],
        "answerable": answerable(request.acceptable_table_sets, plan.tables),
    }
    if not plan.tables:
        raise StageFailed(NO_TABLES)
    return plan


def build(record: dict, model: str, system: str, prompt: str, generate: Generate) -> str:
    """The last call of every arm: a prompt in, one SQL query out."""
    stage = call_stage(record, "builder", model, system, prompt, generate)
    sql = builder.extract_sql(stage["answer"])
    stage |= {"parsed": {"sql": sql}, "format_ok": sql is not None}
    if sql is None:
        raise StageFailed(NO_SQL)
    return sql


def run_arm(
    arm: str,
    model: str,
    request: StagedRequest,
    lifecycles: list[Lifecycle],
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
        "held_out": request.held_out,
        "expected_lifecycle": request.expected_lifecycle,
        "acceptable_table_sets": request.acceptable_table_sets,
        "stages": [],
        "lifecycle": None,  # the lifecycle whose narrative the interpreter was given
        "lifecycle_correct": None,  # staged arm only: the selector chose the owner's
        "plan": None,  # the hand-off the builder was given
        "plan_tables": [],
        "plan_tables_outside_lifecycle": [],
        "answerable": None,  # staged arms: the plan's tables cover an acceptable set
        "tables_given": [],  # the tables whose schema the builder was shown
        "sql": None,
        "sql_status": None,
        "sql_error": None,
        "sql_seconds": None,
        "tables_in_sql": [],
        "tables_not_given": [],
        "result_columns": [],
        "result_rows": [],
        "result_row_count": None,
        "answer_matched": False,  # strict, the headline
        "values_present": False,  # loose
    }
    started = time.monotonic()
    try:
        if arm == "full":
            given = known
            schema = render_schema(list(tables.values()))
            system, prompt = builder.SYSTEM, builder.build_prompt(schema, request.request)
        elif arm == "full_narratives":
            given = known
            schema = render_schema(list(tables.values()))
            system = builder.SYSTEM
            prompt = plan_builder.build_full_narratives_prompt(
                schema, narratives.render_all(lifecycles), request.request
            )
        elif arm in ("staged", "staged_hand"):
            if arm == "staged":
                lifecycle = select_lifecycle(record, model, request, lifecycles, generate)
            else:
                lifecycle = next(lc for lc in lifecycles if lc.id == request.expected_lifecycle)
                record["lifecycle"] = lifecycle.id
            plan = interpret(record, model, request, lifecycle, known, generate)
            given = plan.tables
            schema = render_schema([tables[name] for name in given])
            system, prompt = plan_builder.SYSTEM, plan_builder.build_prompt(schema, plan.text())
        else:
            raise ValueError(f"unknown arm {arm}")
        record["tables_given"] = given
        sql = build(record, model, system, prompt, generate)

        result = execute(sql)
        tolerance = RELATIVE_TOLERANCE if request.base.tolerance is None else request.base.tolerance
        named = tables_in_sql(sql, known)
        record |= {
            "sql": sql,
            "sql_status": result.status,
            "sql_error": result.error,
            "sql_seconds": result.seconds,
            "tables_in_sql": named,
            "tables_not_given": [t for t in named if t not in given],
            "result_columns": result.columns,
            "result_rows": result.rows[:ROWS_KEPT],
            "result_row_count": len(result.rows) if result.ran else None,
            "answer_matched": result.ran and answers_match(reference.rows, result.rows, tolerance),
            "values_present": result.ran and values_present(reference.rows, result.rows, tolerance),
        }
    except StageFailed as stopped:
        record["sql_status"], record["sql_error"] = stopped.status, stopped.detail
    record["seconds"] = round(time.monotonic() - started, 3)
    return record


def run_all(
    requests: list[StagedRequest],
    models: list[str],
    lifecycles: list[Lifecycle],
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
                    arm,
                    model,
                    request,
                    lifecycles,
                    tables,
                    references[request.id],
                    generate,
                    execute,
                )
                records.append(record)
                if progress:
                    progress(record)
    return records
