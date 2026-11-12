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

## Alternatives

- An agent framework or tool calling: closer to how a production agent is built, but it adds a dependency and a failure mode (a malformed tool call) that has nothing to do with selection.
- Embedding search over table descriptions: the usual answer at scale. With 12 tables it would measure the embedding model, and an index a person can read is the thing the essay argues for.
- A hosted model: stronger, but it needs a key, costs money to rerun, and cannot be pinned by digest.
- Scoring only the final answer: simpler, but it cannot tell a selection failure from a SQL failure.
- Comparing SQL text with the reference query: many different queries give the right answer.
- Keeping descriptions only in YAML: the warehouse would then not carry them, and other tools that read comments would not see them.
