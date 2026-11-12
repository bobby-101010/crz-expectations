# 0015: A staged harness with lifecycle narratives, and what is fixed before its run

Status: draft (Phase 9, 2026-11-13). The plan was approved by the owner. No model has been run. The results section is written after the run.

## Context

Phase 8 (decision 0014) found that selection was not the bottleneck on this warehouse. Three requests failed in every arm with the right tables present. The model lacked meaning, not tables: what "inside the zone" or "the normal range" is here.

Phase 9 tests two things. First, a lifecycle narrative: about a page of prose on how one process writes its rows, in the warehouse's own table and column names, given to the model with the schema. Second, dividing the work across fresh contexts, so each model call sees only what its step needs.

## Decision

- **Three stages, each one model call with a context of its own.**
  1. The selector sees the lifecycle index lines and the request. It answers `LIFECYCLE: id`.
  2. The interpreter sees that lifecycle's narrative and the request. It answers with a plan in five labelled parts: `TABLES`, `FILTERS`, `MEASURE`, `GRAIN`, `DEFINITIONS`. It writes no SQL.
  3. The builder sees the plan and the described schema of the tables the plan names. It answers with one SQL query. It sees neither the request nor the narrative.
- **Only the written hand-off crosses a stage.** The hand-off is the parsed answer written out again in a fixed form. No conversation state is sent back to Ollama: the client sends a system text and a prompt and never a `context`.
- **A test fails if a prompt holds another stage's information.** Fixture inputs carry a marker per kind of information (index, chosen narrative, other narrative, schema of the plan's tables, other schema, request, plan), and each stage's prompt must hold exactly its own kinds.
- **The selector's index line has no table names.** It is the lifecycle's id, title and one-line description. The selector chooses a process, not tables.
- **Four arms:** `full` (Phase 8's full-schema arm, same system text and prompt, checked by a test), `full_narratives` (the full schema and every narrative in one call), `staged`, and `staged_hand` (the owner's lifecycle in place of the selector).
- **Two answer measures, both fixed in code before any run.**
  - Strict, the headline: Phase 8's rule, unchanged.
  - Loose, `values_present`: every non-null value of the reference answer is matched by a cell of its own somewhere in the model's result, under the same cell rule, whatever the shape. A strict match always passes it. It can pass by accident when a large result happens to hold the reference's values.
  - A run is never rescored.
- **Selection is scored twice.** The lifecycle the selector chose equals the owner's. And the plan is "answerable": the tables it names include every table of at least one of the request's acceptable table sets.
- **A broken format is a result.** Each parser's leniency is written in its docstring and was fixed before the run: a `LIFECYCLE:` line that names no known id falls back to the one known id mentioned in the answer, if there is exactly one; markdown marks around a plan label are ignored; a missing plan part is passed on as `(not given)`. Each case sets `format_ok` to false on the stage, and the report counts them. A stage that hands on nothing (no lifecycle, no known table, no query) stops the arm with that status.
- **A failed model call is a result too,** recorded as `model_error`, so one timeout does not lose a long run. Each record is also appended to a partial file as it finishes.
- **Every stage is saved:** its system text, prompt, raw answer, parsed hand-off, token counts and seconds, per request, arm and model.
- **Expectations first.** The run refuses to start unless the narratives fit the warehouse, every request has `expected_lifecycle` and `acceptable_table_sets`, and `selection/predictions.yaml` holds a prediction (`match` or `no_match`, on the strict measure) for every request, arm and model. It also refuses if the largest prompt would not fit the model's context.
- **Results are reported split** by seen requests (the twelve that existed when the narratives were written) and held-out requests (written after the narratives were frozen), and compared with the owner's predictions.
- **Separation of authors.** The session that built the harness knows which Phase 8 requests failed. It wrote no narrative, request, reference query, expected value or prediction. Those come from other contexts and from the owner.

## Limits known before the run

- The builder of the staged arms never sees the request. Anything the plan leaves out, such as an ordering or a limit, is lost.
- The interpreter never sees the schema. A table or column the narrative does not name cannot reach the plan.
- A handful of lifecycles and twelve tables remain a toy. The index fits in a few lines.
- One run per model at temperature 0, and about eighteen requests.
- The seen requests were visible to whoever wrote the narratives. Only the held-out requests test whether a narrative carries meaning beyond the questions it was written beside.
