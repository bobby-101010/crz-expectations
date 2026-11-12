# 0014: A toy selection loop on local models, and the choices that keep it honest

Status: accepted (Phase 8, 2026-11-12). The plan was approved by the owner before work began. The change of scope in spec section 12 still needs the owner's confirmation.

## Context

Giving a model context about a warehouse is the easy part: a schema with good descriptions, pasted into the prompt, works. The open problem is selection, which is choosing the part of the schema to give the model for one request. The owner does that by hand today.

Phase 8 builds a rudimentary version of a loop that would do it: a selector model reads a one-line-per-table index and a request and picks tables, a builder model writes SQL from only those tables, and the request is saved with the tables used. It runs against this repo's own warehouse.

Spec section 12 rules out an LLM feature inside the pipeline. This harness sits beside the pipeline. No job, check, verdict or page reads a model's output.

## Decision

- **Plain Python, one small module per piece.** No agent framework, no vector search, no new dependency. The harness runs in the existing container on the existing Spark session.
- **Local models through Ollama on the host,** called over HTTP with the standard library: `llama3.2:3b` and `qwen2.5:14b`. Temperature 0 and seed 0. The model name, its digest and the options are recorded in every results file.
- **`num_ctx` is set to 16,384.** Ollama's default context is smaller than the full described schema (about 23,000 characters), and it cuts a longer prompt without an error. Each call's prompt token count is recorded, so a cut would show.
- **No tool calling.** The selector answers with one line, `TABLES: schema.table, ...`. Small models are unreliable at tool calling, and a fixed line can be parsed and scored. An answer without that line is recorded as a format break. The parser then takes any known table named in the text, and the record says so.
- **The selector is told to over-include.** Leaving out a needed table makes the request unanswerable. An extra table only costs prompt space. So extras are counted, not failed.
- **The model is shown what the warehouse carries.** Descriptions are written as Iceberg comments and exported back from them. The comment job changes metadata only, checks that no snapshot id moved, and writes nothing on a second run.
- **Selection and SQL are scored separately,** because a small model can pick the right tables and still write a wrong query.
  - Selection is scored against two lists: the tables the owner approved, and the tables the reference query reads. It reports whether each list was fully included and how many extra tables came with it.
  - SQL is scored on whether the query ran, and whether its answer matches the reference answer.
- **The matching rule.** A model's answer matches when it has the same number of rows as the reference answer and some choice of its columns, one per reference column, gives the reference rows. Row order, column order and column names are ignored, and extra columns are allowed. A whole number must be equal. Any other number may differ by 0.1%. Text is compared without regard to case.
- **Three arms on the same requests:** the full schema, the selector's tables, and the owner's tables.
- **The answer key comes first.** `expected_tables` was committed (`9023ba9`) before any model was run against the requests, and the run refuses to start while any list is empty. This mirrors the registry: write the expectation down before the outcome.
- **A model's SQL is untrusted.** It must be a single statement that starts with SELECT or WITH and contains no INSERT, UPDATE, DELETE or MERGE. It is cancelled after 120 seconds, and at most 1,000 rows are brought back.
- **Every precedent is saved with its outcome.** One line per request per model from the selector arm, flagged with whether the query ran and whether the answer matched. Only matched ones would be reused. Reuse is not built.
- **Results are files.** `selection/results/<run_id>.json` holds every prompt answer, query, error and result. Nothing but comments is written to the warehouse.

## Limits, stated plainly

- **Twelve tables fit in one prompt.** The full-schema arm is always possible here, so this does not test selection at scale. It shows the method and the look-alike decision, such as `silver.trips` against `gold.daily_trips`.
- **The owner's tables were not picked blind.** Claude Code drafted `expected_tables` at the owner's request, as the tables each reference query reads, and the owner reviewed and committed them. So the two selection measures are equal for all 12 requests, and the `hand` arm is "the reference query's tables, approved by the owner", not an independent human pick.
- **The requests and reference queries were drafted by Claude Code** after it had written the table descriptions. The descriptions may suit these requests better than they would suit a stranger's.
- **A builder can name a table it was not shown.** The query runs against the whole warehouse, so a guessed table name resolves. This is recorded per query as `tables_not_given`, not blocked.
- **One run per model.** Temperature 0 with a fixed seed makes a run repeatable on one machine. It says nothing about variance across seeds or hardware.
- **Twelve requests is a small sample.** A difference of one or two requests between arms is not evidence of anything.
- **Known properties of the data that the reference answers keep:** trip counts include reversal rows (a reversed yellow trip is two rows), and `crz_entries` leaves out vehicles that stayed on excluded roadways. The reference answers were not changed for either.
- **Three requests ask about "the latest" run or load,** so their reference answers move when the pipeline runs again. The model run recomputes every reference answer in its own session.
- **`make reference` drops the comments** of the two reference tables, because it rebuilds them with `createOrReplace`. Run `make catalog-comments` after it.

## What the run showed (2026-11-12, run `20261112T212530Z`, requests at commit `5d53f34`)

A timed pilot came first: two requests through the three arms on both models took 5 minutes 22 seconds, which put the full run at about 32 minutes. The owner approved a run of that length. The full run took 39 minutes 23 seconds: 12 requests, 3 arms, 2 models, 72 records. The full report is `selection/results/20261112T212530Z.md`, and every prompt answer, query and error is in the `.json` beside it.

| Model | Arm | Owner's tables all included | Mean extra tables | SQL ran | Answer matched | Mean seconds per request |
| --- | --- | --- | --- | --- | --- | --- |
| `llama3.2:3b` | full | | | 7 of 12 | 1 | 21.6 |
| `llama3.2:3b` | selector | 10 of 12 | 1.3 | 8 | 4 | 11.5 |
| `llama3.2:3b` | hand | | | 8 | 3 | 3.3 |
| `qwen2.5:14b` | full | | | 9 of 12 | 7 | 106.6 |
| `qwen2.5:14b` | selector | 11 of 12 | 0.8 | 11 | 5 | 40.0 |
| `qwen2.5:14b` | hand | | | 12 | 5 | 13.2 |

What can be said from it:

- **The format held.** Both selectors answered with the `TABLES:` line on all 24 calls, and named no table that does not exist. Every builder answer held a query. No output was discarded or left unparsed.
- **Selection mostly worked from one line per table.** `qwen2.5:14b` included every needed table on 11 of 12 requests, with fewer than one extra table on average. `llama3.2:3b` did so on 10 of 12, with more extras, and often added the silver table beside the gold one.
- **The misses were look-alikes.** `qwen2.5:14b` chose `gold.daily_trip_slices` where the reference query used `gold.daily_trips`, and its query then returned more than 1,000 rows. `llama3.2:3b` chose `gold.daily_trips` and `silver.trips` where the operator breakdown needed `gold.daily_trip_slices`, and left out `gold.baselines` on the request about the normal range.
- **A smaller schema made queries run more often and much faster.** For `qwen2.5:14b`, 9 queries ran with the full schema, 11 with the selector's tables and 12 with the owner's. A full-schema prompt was about 6,000 tokens and took 107 seconds per request on this laptop, against 13 seconds with the owner's tables.
- **A smaller schema did not make answers more correct here.** `qwen2.5:14b` matched 7 answers with the full schema and 5 with either subset. `llama3.2:3b` matched 1, 4 and 3. With 12 requests and one run, neither difference is evidence. What the run does show is that picking the right tables and writing the right query are separate skills: with the owner's tables in hand, the larger model still got 7 of 12 wrong under the rule.
- **Where the wrong answers came from.** Most were SQL errors of meaning, not of selection: `count(distinct ...)` where a sum was needed (the small model, repeatedly); taking the largest single row where the 10-minute total needed a sum over vehicle classes (the larger model, in all three arms); comparing a timestamp with a date by equality; joining the baseline without `slice_key = 'all'`.
- **Four records hold the reference numbers and still count as wrong.** `qwen2.5:14b` returned the Uber and Lyft totals as one row with two columns, where the reference answer has two rows, and it left the `Unknown` and `N/A` boroughs out of the zone count. Both happened in the selector and hand arms. A person would accept the first and might accept the second. The rule was fixed before the run and the scores were not changed.
- **Naming a table that was not shown happened twice,** both by `llama3.2:3b`, and both queries failed for other reasons.
- **The prompt was never cut.** The largest prompt was 5,983 tokens against a context of 16,384.

## Follow-ons, not built

- A fourth arm: the owner's tables plus a look-alike table added on purpose, to measure what an extra look-alike costs the builder.
- Reading matched precedents back into the selector.
- An independent pick of `expected_tables` by someone who has not seen the reference queries.
- More than one run per model, and more requests, before any comparison between arms is quoted as a result.

## Alternatives

- An agent framework or tool calling: closer to how a production agent is built, but it adds a dependency and a failure mode (a malformed tool call) that has nothing to do with selection.
- Embedding search over table descriptions: the usual answer at scale. With 12 tables it would measure the embedding model, and an index a person can read is the thing the essay argues for.
- A hosted model: stronger, but it needs a key, costs money to rerun, and cannot be pinned by digest.
- Scoring only the final answer: simpler, but it cannot tell a selection failure from a SQL failure.
- Comparing SQL text with the reference query: many different queries give the right answer.
- Keeping descriptions only in YAML: the warehouse would then not carry them, and other tools that read comments would not see them.
