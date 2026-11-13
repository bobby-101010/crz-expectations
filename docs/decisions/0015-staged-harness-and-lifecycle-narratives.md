# 0015: A staged harness with lifecycle narratives, and what is fixed before its run

Status: accepted (Phase 9, 2026-11-13). The plan was approved by the owner before the build, and the inputs before the run. The results are in "What the run showed".

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

## Who wrote the inputs

- **Narratives.** Written by a session working from a copy of the repository without the requests or any results. A separate read-only check then compared them with the warehouse, and its corrections were applied. The owner approved them as written.
- **Lifecycle picks, acceptable table sets and predictions.** Drafted by the coordinating Claude session, which had seen the Phase 8 results, the narratives and all eighteen requests. The owner approved them as drafted. The predictions file says so (`author: ai_coordinator`). The report's heading "Against the owner's predictions" means these: predictions an AI drafted and the owner approved.
- **Held-out requests.** Six, written after the narratives were frozen. Four of their reference queries were trimmed by the coordinating session and carry `reference_trimmed: true`.

## Properties of the inputs known before the run, and left alone

- Four requests ask for a share. The reference holds a fraction, and a model may return a percentage. Such an answer does not match. The rule was not adjusted.
- Two requests need tables from two lifecycles: `ride-hail-trips-on-holidays-2025` and `ride-hail-load-vs-warehouse-2025`. The staged arms pass one narrative on, and were predicted to fail both.
- The trip narrative mentions the January 4 fee trips, which one seen request (`fee-trips-across-midnight`) asks about.

## Limits known before the run

- The builder of the staged arms never sees the request. Anything the plan leaves out, such as an ordering or a limit, is lost.
- The interpreter never sees the schema. A table or column the narrative does not name cannot reach the plan.
- A handful of lifecycles and twelve tables remain a toy. The index fits in a few lines.
- One run per model at temperature 0, and about eighteen requests.
- The seen requests were visible to whoever wrote the narratives. Only the held-out requests test whether a narrative carries meaning beyond the questions it was written beside.

## What the run showed

Run `20261113T054409Z`: 18 requests, 4 arms, 2 models, 144 records, 2 hours 15 minutes. Full tables are in `selection/results/staged-20261113T054409Z.md`.

Strict matches, out of 18 (12 seen, 6 held-out):

| Model | `full` | `full_narratives` | `staged` | `staged_hand` |
| --- | --- | --- | --- | --- |
| `llama3.2:3b` | 1 (1 seen, 0 held-out) | 0 | 0 | 0 |
| `qwen2.5:14b` | 8 (7, 1) | 10 (9, 1) | 8 (6, 2) | 8 (6, 2) |

- **The small model failed almost everything, in every arm.** One match in 72. Its queries ran 8, 7, 4 and 4 times out of 18. Most failures were columns or tables that do not exist. The narratives did not help it.
- **On the larger model the narratives added two matches in one call** (10 against 8). `full_narratives` matched `busiest-hour-yellow-from-zone` and `ride-hail-trips-on-holidays-2025`, which `full` did not. It lost nothing `full` had.
- **Staging matched as many as the plain full schema, but different ones.** The staged arms gained four requests `full` missed (`busiest-hour-yellow-from-zone`, `entries-by-vehicle-class-june-2025`, `busiest-ten-minutes-lincoln-tunnel`, and the held-out `ride-hail-zone-touch-share-by-operator`) and lost four it had (`yellow-trips-one-day`, `uber-lyft-trips-2025`, `zones-in-toll-zone-by-borough`, `checks-not-passing-now`).
- **The losses were plans that said more or less than the request.** For `yellow-trips-one-day` the plan asked for trips per hour, and the builder returned 24 rows where the answer is one number. For `checks-not-passing-now` the plan kept only failed checks, and the one check not passing was a warning. The builder cannot repair this, because it never sees the request.
- **Choosing the lifecycle was not the problem.** The larger model chose the owner's lifecycle 17 times of 18, the small one 16 of 18. `staged` and `staged_hand` gave the same outcome on every request but one. The exception is `zones-in-toll-zone-by-borough` on the larger model: the selector chose `zone-entry`, the plan then named no known table, and the arm stopped with `no_tables`.
- **The normal range stayed unsolved.** `entries-outside-normal-sept-2026` and `crossing-days-above-normal` matched in no arm on either model, with or without the narratives.
- **Requests across two lifecycles.** `ride-hail-load-vs-warehouse-2025` failed in all eight cells, each with a query that did not run. `ride-hail-trips-on-holidays-2025` matched only in `full_narratives` on the larger model. The staged plans for it named no holiday table, as predicted.
- **Shares.** On `ride-hail-zone-touch-share-by-operator` the larger model's `full_narratives` answer held the right numbers as percentages (33.10 where the reference holds 0.3310), so it did not match. Its staged arms returned fractions and matched. `excluded-roadway-share-by-crossing` matched nowhere, and not only for that reason: the staged arms and `full_narratives` returned 50.33 where the reference holds 0.3348, a different share.
- **Held-out requests were hard for every arm.** The larger model matched 1, 1, 2 and 2 of 6. Six requests are too few to say that staging carries over better.
- **The loose measure added almost nothing.** Values were present without a strict match in one record of 144 (`llama3.2:3b`, `full`, `largest-driver-latest-run`).
- **Format breaks.** The small model's selector answered with the bare id, such as `trip`, in all 18 requests, never `LIFECYCLE: trip`. The fallback read the id each time. The larger model broke format once, in the interpreter of the `no_tables` case above. No model call failed, and no answer lacked SQL.
- **Timeouts.** Two, both the small model on `entries-outside-normal-sept-2026` in the staged arms: a join of four tables with no join condition.

### Against the predictions

The predictions agreed with the run in 118 of 144 cells.

| Model | Arm | Agreed, of 18 | Predicted to match | Did match |
| --- | --- | --- | --- | --- |
| `llama3.2:3b` | `full` | 18 | 1 | 1 |
| `llama3.2:3b` | `full_narratives` | 18 | 0 | 0 |
| `llama3.2:3b` | `staged` | 15 | 3 | 0 |
| `llama3.2:3b` | `staged_hand` | 15 | 3 | 0 |
| `qwen2.5:14b` | `full` | 18 | 8 | 8 |
| `qwen2.5:14b` | `full_narratives` | 14 | 14 | 10 |
| `qwen2.5:14b` | `staged` | 10 | 8 | 8 |
| `qwen2.5:14b` | `staged_hand` | 10 | 8 | 8 |

- **Right:** `full` in all 36 cells, including that the seen requests would repeat Phase 8. That the narratives would not help the small model. That the staged arms would fail both two-lifecycle requests. That `staged` and `staged_hand` would behave alike.
- **Wrong, too hopeful:** the small model's three predicted staged matches did not happen. `full_narratives` on the larger model was predicted to match 14 and matched 10: the narratives did not fix `entries-by-vehicle-class-june-2025`, `busiest-ten-minutes-lincoln-tunnel` or either normal-range request.
- **Wrong, in both directions, for the staged arms on the larger model:** the count was right (8 predicted, 8 observed) but only 10 of 18 cells were. Predicted to match and did not: `yellow-trips-one-day`, `entries-outside-normal-sept-2026`, `checks-not-passing-now`, `crossing-days-above-normal`. Predicted to fail and matched: `busiest-hour-yellow-from-zone`, `busiest-ten-minutes-lincoln-tunnel`, `largest-driver-latest-run`, `ride-hail-zone-touch-share-by-operator`. The prediction that an ordering or limit would be lost in the plan was wrong for the three of these that need one. The prediction that a share would not match was wrong here.

## The first full run was thrown away

The first full run (`20261112T232528Z`) is invalid from its 27th record on, and is kept only as a record of the failure.

- **What happened.** A query that hits the 120-second limit is cancelled. Cancelling did not stop its tasks when they were inside a join with no condition. They ran on and kept their task slots. After the second such query all 10 slots were held, and almost every later query waited until it was cancelled too. Queries that ran in under half a second in the pilot timed out. The run took 5 hours 55 minutes.
- **The fix** (commit `20e34ab`). After any timeout the harness kills the JVM behind the Spark session and builds a new session. It was checked on the real warehouse: after three forced timeouts in a row, a small query ran in 1.5 seconds each time.
- **What did not change.** No prompt, format, parser, scoring rule, request, narrative or prediction. The pilot was run again after the fix and gave the same SQL, status and match in all 16 records.
- **Why a rerun is fair.** Temperature is 0 and the seed is fixed. The first 26 records of the invalid run, made before the first timeout, have the same outcome in the rerun.
- **Phase 8 is not affected.** Its run had no timeout.

## Limits after the run

- One run per model. Eighteen requests, six of them held-out.
- The answer to "does staging help" here is "it moves the failures": the same count, different requests. A design where the builder also sees the request was not tested. The owner chose to keep the request from the builder for this run.
