import json
import time
import urllib.request

import pytest

from pipeline.selection import builder, ollama, precedents, request_file, selector
from pipeline.selection.catalog import (
    Column,
    Table,
    comment_statements,
    load_descriptions,
    owner_reviews,
    parse_describe,
    problems,
    quoted,
    render_index,
    render_schema,
    table_comment,
)
from pipeline.selection.evaluate import (
    answers_match,
    cells_match,
    render_summary,
    score_selection,
    summarize,
)
from pipeline.selection.ollama import Reply
from pipeline.selection.report import outcome, render_report
from pipeline.selection.request_file import Request
from pipeline.selection.runner import run_all, run_arm, tables_in_sql
from pipeline.selection.sql import OK, QueryResult, execute, rejection

WAREHOUSE_TABLES = [
    "checks.ingest_stats",
    "checks.results",
    "expectations.drivers",
    "expectations.verdicts",
    "gold.baselines",
    "gold.daily_entries",
    "gold.daily_trip_slices",
    "gold.daily_trips",
    "reference.cbd_zones",
    "reference.holidays",
    "silver.crz_entries",
    "silver.trips",
]

DESCRIBED = {
    "gold.daily_trips": {
        "summary": "Daily trips.",
        "grain": "one date x service.",
        "not_for": "single trips.",
        "columns": {
            "trip_date": "Pickup date.",
            "trips": {"description": "Trips that day.", "owner_review": "Is this right?"},
        },
    }
}
SCHEMAS = {"gold.daily_trips": ["trip_date", "trips"]}

DAILY = Table(
    "gold.daily_trips",
    "Daily trips.\nGrain: one date x service.\nDo not use for: single trips.",
    [Column("trip_date", "date", "Pickup date."), Column("trips", "bigint", "Trips that day.")],
    ["months(trip_date)"],
)
TRIPS = Table("silver.trips", "Every trip.", [Column("pickup_at", "timestamp_ntz", "Start.")])
TABLES = {"gold.daily_trips": DAILY, "silver.trips": TRIPS}


# --- catalog ---------------------------------------------------------------------------


def test_matching_descriptions_have_no_problems():
    assert problems(DESCRIBED, SCHEMAS) == []


def test_problems_name_every_gap_between_descriptions_and_tables():
    described = {
        "gold.daily_trips": {
            "summary": "Daily trips.",
            "grain": "",
            "not_for": "single trips.",
            "columns": {"trip_date": "Pickup date.", "trips": " ", "fares": "Not a column."},
        },
        "gold.gone": {"summary": "x", "grain": "x", "not_for": "x", "columns": {}},
    }
    schemas = {"gold.daily_trips": ["trip_date", "trips", "service"], "silver.trips": ["a"]}

    assert problems(described, schemas) == [
        "silver.trips: the table is not described",
        "gold.gone: described, but there is no such table",
        "gold.daily_trips: `grain` is missing or empty",
        "gold.daily_trips.trips: the description is empty",
        "gold.daily_trips.service: the column is not described",
        "gold.daily_trips.fares: described, but there is no such column",
    ]


def test_the_real_descriptions_cover_the_twelve_tables_and_say_when_not_to_use_each():
    descriptions = load_descriptions()

    assert sorted(descriptions) == WAREHOUSE_TABLES
    own_columns = {name: list(d["columns"]) for name, d in descriptions.items()}
    assert problems(descriptions, own_columns) == []
    assert "gold.daily_trips" in descriptions["silver.trips"]["summary"]
    assert "silver.crz_entries" in descriptions["gold.daily_entries"]["summary"]


def test_owner_review_marks_are_listed_and_kept_out_of_the_comment():
    assert owner_reviews(DESCRIBED) == {"gold.daily_trips.trips": "Is this right?"}
    statements = comment_statements(DESCRIBED, {"gold.daily_trips": Table(**_bare(DAILY))})
    assert not any("Is this right?" in statement for statement in statements)


def _bare(table: Table) -> dict:
    columns = [Column(c.name, c.type, None) for c in table.columns]
    return {"name": table.name, "comment": None, "columns": columns}


def test_table_comment_starts_with_the_summary_line():
    assert table_comment(DESCRIBED["gold.daily_trips"]) == DAILY.comment
    with_details = DESCRIBED["gold.daily_trips"] | {"details": "From  2023.\n"}
    assert table_comment(with_details).split("\n")[2] == "Details: From 2023."


def test_comment_statements_cover_what_differs_and_nothing_once_applied():
    statements = comment_statements(DESCRIBED, {"gold.daily_trips": Table(**_bare(DAILY))})

    assert statements == [
        "COMMENT ON TABLE local.gold.daily_trips IS "
        "'Daily trips.\\nGrain: one date x service.\\nDo not use for: single trips.'",
        "ALTER TABLE local.gold.daily_trips ALTER COLUMN trip_date COMMENT 'Pickup date.'",
        "ALTER TABLE local.gold.daily_trips ALTER COLUMN trips COMMENT 'Trips that day.'",
    ]
    assert comment_statements(DESCRIBED, {"gold.daily_trips": DAILY}) == []
    assert all(s.startswith(("COMMENT ON TABLE", "ALTER TABLE")) for s in statements)


def test_quoted_escapes_quotes_and_backslashes(spark):
    text = "it's 'yellow' \\ and\nmore"

    assert spark.sql(f"SELECT {quoted(text)} AS t").first()["t"] == text


def test_parse_describe_splits_columns_from_partitioning():
    rows = [
        ("trip_date", "date", "Pickup date."),
        ("trips", "bigint", None),
        ("", "", ""),
        ("# Partitioning", "", ""),
        ("Part 0", "months(trip_date)", ""),
        ("", "", ""),
        ("# Metadata Columns", "", ""),
        ("_file", "string", ""),
        ("# Detailed Table Information", "", ""),
        ("Name", "local.gold.daily_trips", ""),
        ("Comment", "Daily trips.", ""),
    ]

    table = parse_describe("gold.daily_trips", rows)

    assert table.columns == [
        Column("trip_date", "date", "Pickup date."),
        Column("trips", "bigint", None),
    ]
    assert table.partitioning == ["months(trip_date)"]
    assert table.comment == "Daily trips."
    assert parse_describe("gold.daily_trips", rows[:2]).comment is None


def test_index_has_one_line_per_table_and_schema_has_every_column():
    assert render_index([DAILY, TRIPS]) == (
        "- gold.daily_trips: Daily trips.\n- silver.trips: Every trip.\n"
    )
    schema = render_schema([DAILY])
    assert "## gold.daily_trips" in schema
    assert "Do not use for: single trips." in schema
    assert "Partitioned by: months(trip_date)" in schema
    assert "| trips | bigint | Trips that day. |" in schema
    assert "silver.trips" not in schema


# --- selector and builder --------------------------------------------------------------


def test_selector_prompt_holds_the_index_the_request_and_the_format():
    prompt = selector.build_prompt(render_index([DAILY, TRIPS]), " How many trips? ")

    assert "- gold.daily_trips: Daily trips." in prompt
    assert "Request: How many trips?" in prompt
    assert "TABLES: schema.table, schema.table" in prompt
    assert "Include a table when in" in prompt


@pytest.mark.parametrize(
    "answer, tables, unknown, format_ok",
    [
        ("TABLES: gold.daily_trips, silver.trips", ["gold.daily_trips", "silver.trips"], [], True),
        ("Sure!\ntables: `local.gold.daily_trips`.", ["gold.daily_trips"], [], True),
        ("TABLES: gold.daily_trips, gold.trips", ["gold.daily_trips"], ["gold.trips"], True),
        ("TABLES: silver.trips; silver.trips", ["silver.trips"], [], True),
        ("I would use silver.trips for this.", ["silver.trips"], [], False),
        ("TABLES:", [], [], True),
        ("No idea.", [], [], False),
    ],
)
def test_selector_parse(answer, tables, unknown, format_ok):
    chosen = selector.parse(answer, list(TABLES))

    assert (chosen.tables, chosen.unknown, chosen.format_ok) == (tables, unknown, format_ok)


def test_builder_prompt_holds_only_the_schema_it_is_given():
    prompt = builder.build_prompt(render_schema([DAILY]), "How many trips?")

    assert "## gold.daily_trips" in prompt
    assert "silver.trips" not in prompt
    assert "Request: How many trips?" in prompt


@pytest.mark.parametrize(
    "answer, sql",
    [
        ("```sql\nSELECT 1;\n```", "SELECT 1"),
        ("Here you go:\n```\nSELECT a\nFROM t\n```\nDone.", "SELECT a\nFROM t"),
        ("The query is select 1 from t;", "select 1 from t"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "WITH x AS (SELECT 1) SELECT * FROM x"),
        ("I cannot answer that.", None),
        ("```sql\n```", None),
    ],
)
def test_extract_sql(answer, sql):
    assert builder.extract_sql(answer) == sql


# --- ollama client ---------------------------------------------------------------------


def test_generate_sends_temperature_zero_and_reads_the_reply(monkeypatch):
    sent = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            body = {"response": "TABLES: a.b", "prompt_eval_count": 40, "eval_count": 5}
            return json.dumps(body | {"total_duration": 2_500_000_000}).encode()

    def fake_urlopen(request, timeout):
        sent["url"], sent["body"] = request.full_url, json.loads(request.data)
        return Response()

    monkeypatch.setenv("OLLAMA_URL", "http://ollama.test:1/")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    reply = ollama.generate("llama3.2:3b", "system text", "prompt text")

    assert sent["url"] == "http://ollama.test:1/api/generate"
    assert sent["body"] == {
        "model": "llama3.2:3b",
        "system": "system text",
        "prompt": "prompt text",
        "stream": False,
        "options": {"temperature": 0, "seed": 0, "num_ctx": 16384},
    }
    assert reply == Reply("TABLES: a.b", 40, 5, 2.5)


def test_digest_of_finds_an_installed_model_and_refuses_a_missing_one():
    models = [{"name": "llama3.2:3b", "model": "llama3.2:3b", "digest": "a80c"}]

    assert ollama.digest_of(models, "llama3.2:3b") == "a80c"
    with pytest.raises(LookupError, match="not installed"):
        ollama.digest_of(models, "qwen2.5:14b")


# --- running SQL -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("SELECT 1", None),
        ("  with x as (select 1) select * from x;", None),
        ("SELECT 'DROP; DELETE' AS note -- insert", None),
        ("", "the query is empty"),
        ("DROP TABLE gold.daily_trips", "the query does not start with SELECT or WITH"),
        ("SELECT 1; DROP TABLE t", "more than one statement"),
        ("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x", "the query contains INSERT"),
        ("/* hi */ DELETE FROM t", "the query does not start with SELECT or WITH"),
    ],
)
def test_only_a_single_select_may_run(sql, reason):
    assert rejection(sql) == reason


def test_execute_returns_plain_rows(spark):
    result = execute(spark, "SELECT DATE '2025-01-05' AS d, 2 AS n, CAST(1.5 AS DECIMAL(3,1)) AS x")

    assert (result.status, result.columns) == (OK, ["d", "n", "x"])
    assert result.rows == [["2025-01-05", 2, 1.5]]


def test_execute_reports_a_bad_query_a_write_and_too_many_rows(spark):
    assert execute(spark, "SELECT nope FROM missing_table").status == "error"
    assert execute(spark, "DROP TABLE x").status == "rejected"
    assert execute(spark, "SELECT id FROM range(10)", max_rows=5).status == "too_many_rows"


def test_execute_cancels_a_query_at_the_time_limit(spark):
    started = time.monotonic()

    result = execute(
        spark, "SELECT count(*) FROM range(1000000000000) WHERE rand() < 0.5", time_limit=2
    )

    assert result.status == "timeout"
    assert time.monotonic() - started < 60
    assert execute(spark, "SELECT 1 AS one").rows == [[1]]


# --- scoring ---------------------------------------------------------------------------


def test_selection_score_counts_missing_and_extra_separately():
    score = score_selection(["gold.daily_trips"], ["silver.trips", "gold.daily_trips"])
    assert (score.all_included, score.missing, score.extra) == (True, [], ["silver.trips"])

    score = score_selection(["gold.daily_trips", "reference.holidays"], ["silver.trips"])
    assert score.all_included is False
    assert score.missing == ["gold.daily_trips", "reference.holidays"]


@pytest.mark.parametrize(
    "reference, value, same",
    [
        (79624, 79624.0, True),
        (79624, 79625, False),
        (79624, "79624", True),
        (4.9933, 4.99, True),
        (4.9933, 4.9, False),
        ("Yellow", " yellow ", True),
        ("2025-06-10T08:10:00", "2025-06-10 08:10:00", True),
        ("2025-01-05", "2025-01-05T00:00:00", True),
        (None, None, True),
        (None, 0, False),
        ("yellow", 1, False),
        (True, True, True),
    ],
)
def test_cells_match(reference, value, same):
    assert cells_match(reference, value, 1e-3) is same


def test_answers_match_ignores_order_names_and_extra_columns():
    reference = [["HV0003", 100], ["HV0005", 40]]

    assert answers_match(reference, [[40, "HV0005"], [100, "HV0003"]])
    assert answers_match(reference, [["Lyft", "HV0005", 40], ["Uber", "HV0003", 100]])
    assert not answers_match(reference, [["HV0003", 100]])
    assert not answers_match(reference, [["HV0003", 40], ["HV0005", 100]])
    assert not answers_match(reference, [[100], [40]])
    assert answers_match([], [])
    assert not answers_match([[1]], [])


# --- the three arms --------------------------------------------------------------------

REQUEST = Request(
    "yellow-one-day", "How many trips?", "SELECT trips FROM gold.daily_trips", ["gold.daily_trips"]
)
REFERENCE = QueryResult(OK, ["trips"], [[79624]])


class FakeModel:
    """Answers the selector and the builder from fixed text, and keeps the prompts."""

    def __init__(self, selection="TABLES: gold.daily_trips, silver.trips", sql="SELECT 79624"):
        self.selection, self.sql, self.prompts = selection, sql, []

    def __call__(self, model, system, prompt):
        self.prompts.append((system, prompt))
        if system == selector.SYSTEM:
            return Reply(self.selection, 100, 8, 0.5)
        return Reply(f"```sql\n{self.sql}\n```", 900, 20, 1.5)


def fake_execute(sql):
    return QueryResult(OK, ["trips"], [[79624]], seconds=0.1)


def test_full_arm_gives_the_builder_every_table():
    model = FakeModel()

    record = run_arm("full", "m", REQUEST, TABLES, REFERENCE, model, fake_execute)

    assert record["tables_given"] == ["gold.daily_trips", "silver.trips"]
    assert len(model.prompts) == 1 and "## silver.trips" in model.prompts[0][1]
    assert record["selection"] is None
    assert (record["sql_status"], record["answer_matched"]) == ("ok", True)


def test_hand_arm_gives_the_builder_the_owners_tables_only():
    model = FakeModel()

    record = run_arm("hand", "m", REQUEST, TABLES, REFERENCE, model, fake_execute)

    assert record["tables_given"] == ["gold.daily_trips"]
    assert "silver.trips" not in model.prompts[0][1]


def test_selector_arm_selects_first_and_scores_the_selection_on_its_own():
    model = FakeModel(selection="TABLES: silver.trips", sql="SELECT count(*) FROM silver.trips")

    record = run_arm(
        "selector",
        "m",
        REQUEST,
        TABLES,
        REFERENCE,
        model,
        lambda sql: QueryResult(OK, ["n"], [[5]]),
    )

    assert [system for system, _ in model.prompts] == [selector.SYSTEM, builder.SYSTEM]
    assert "## gold.daily_trips" not in model.prompts[1][1]
    assert record["selection"] == {
        "all_included": False,
        "missing": ["gold.daily_trips"],
        "extra": ["silver.trips"],
    }
    assert record["reference_tables"] == ["gold.daily_trips"]
    assert record["selection_reference"] == record["selection"]
    assert record["seconds"] >= 0
    assert record["tables_in_sql"] == ["silver.trips"]
    assert (record["sql_status"], record["answer_matched"]) == ("ok", False)


def test_an_empty_selection_or_an_answer_without_sql_is_recorded_not_raised():
    nothing = run_arm(
        "selector", "m", REQUEST, TABLES, REFERENCE, FakeModel(selection="TABLES:"), fake_execute
    )
    assert (nothing["sql_status"], nothing["answer_matched"]) == ("no_tables", False)

    def refuses(model, system, prompt):
        return Reply("I cannot.", 1, 1, 0.1)

    no_sql = run_arm("full", "m", REQUEST, TABLES, REFERENCE, refuses, fake_execute)
    assert (no_sql["sql_status"], no_sql["sql"]) == ("no_sql", None)


def test_tables_in_sql_finds_known_names_with_or_without_the_catalog():
    sql = "SELECT * FROM local.gold.daily_trips d JOIN silver.trips_old t ON true"

    assert tables_in_sql(sql, list(TABLES)) == ["gold.daily_trips"]
    assert tables_in_sql(None, list(TABLES)) == []


def test_run_all_summary_and_precedents(tmp_path):
    records = run_all(
        [REQUEST], ["small", "large"], TABLES, {REQUEST.id: REFERENCE}, FakeModel(), fake_execute
    )
    for record in records:
        record["run_id"] = "run-1"

    assert [(r["model"], r["arm"]) for r in records] == [
        ("small", "full"),
        ("small", "selector"),
        ("small", "hand"),
        ("large", "full"),
        ("large", "selector"),
        ("large", "hand"),
    ]
    lines = summarize(records)
    assert lines[2] | {"seconds": 0} == {
        "model": "large",
        "arm": "selector",
        "requests": 1,
        "selection_all_included": 1,
        "selection_mean_extra": 1.0,
        "selection_reference_all_included": 1,
        "selector_format_broken": 0,
        "sql_ran": 1,
        "answer_matched": 1,
        "used_tables_not_given": 0,
        "seconds": 0,
    }
    assert lines[0]["selection_all_included"] is None
    assert "| large | selector | 1 | 1 | 1 | 1.0 | 0 | 1 | 1 | 0 |" in render_summary(
        lines, "# Run"
    )
    assert "| large | full | 1 |  |  |  |  | 1 | 1 | 0 |" in render_summary(lines, "# Run")

    path = tmp_path / "precedents.jsonl"
    assert precedents.append(records, "2026-11-12T00:00:00+00:00", path) == 2
    assert precedents.append(records, "2026-11-12T00:00:00+00:00", path) == 2
    saved = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(saved) == 4
    assert saved[0]["tables_selected"] == ["gold.daily_trips", "silver.trips"]
    assert saved[0]["tables_used"] == []
    assert saved[0]["request"] == "How many trips?"


# --- the requests file -----------------------------------------------------------------


def test_the_real_requests_file_is_well_formed():
    raw = request_file.read_raw()

    assert request_file.problems(raw, WAREHOUSE_TABLES) == []
    requests = request_file.parse(raw)
    assert len(requests) >= 12
    used = {t for r in requests for t in tables_in_sql(r.reference_sql, WAREHOUSE_TABLES)}
    assert used == set(WAREHOUSE_TABLES)
    assert all(rejection(r.reference_sql) is None for r in requests)


def test_request_problems_and_the_wait_for_expected_tables():
    raw = [
        {"id": "a", "request": "Q?", "reference_sql": "SELECT 1", "expected_tables": []},
        {"id": "a", "request": "", "reference_sql": "SELECT 1", "expected_tables": ["gold.nope"]},
        {"request": "Q?", "reference_sql": "SELECT 1"},
    ]

    assert request_file.problems(raw, WAREHOUSE_TABLES) == [
        "a: the id is used twice",
        "a: `request` is missing or empty",
        "a: expected table gold.nope is not a warehouse table",
        "request 3: no id",
        "request 3: `expected_tables` must be a list",
    ]
    assert request_file.without_expected_tables(request_file.parse(raw[:1])) == ["a"]


# --- the report ------------------------------------------------------------------------


def test_report_shows_outcomes_selection_and_every_failure():
    def failing(sql):
        return QueryResult("error", error="AnalysisException: no such column `trip_date`")

    good = run_all([REQUEST], ["small"], TABLES, {REQUEST.id: REFERENCE}, FakeModel(), fake_execute)
    model = FakeModel(selection="I think silver.trips", sql="SELECT 1 FROM gold.daily_trips")
    bad = run_all([REQUEST], ["tiny"], TABLES, {REQUEST.id: REFERENCE}, model, failing)
    records = good + bad
    result = {
        "run_id": "run-1",
        "requests_commit": "abc1234",
        "arms": ["full", "selector", "hand"],
        "models": {"small": "a" * 64, "tiny": "b" * 64},
        "ollama_options": {"temperature": 0, "seed": 0, "num_ctx": 16384},
        "started_at": "t0",
        "finished_at": "t1",
        "sql_time_limit_seconds": 120,
        "sql_max_rows": 1000,
        "summary": summarize(records),
        "records": records,
    }

    report = render_report(result)

    assert [outcome(r) for r in records] == ["match"] * 3 + ["error"] * 3
    assert "| yellow-one-day | match | match | match | error | error | error |" in report
    assert "| tiny | yellow-one-day | gold.daily_trips | silver.trips | gold.daily_trips " in report
    assert "| silver.trips | NO |" in report
    assert (
        "- `tiny` / `yellow-one-day` / `hand`: error. AnalysisException: no such column" in report
    )
    assert (
        "- `tiny` / `yellow-one-day` / `selector`: used gold.daily_trips; was given silver.trips."
        in report
    )
    assert "`small` (`aaaaaaaaaaaa`)" in report


def test_the_session_is_replaced_after_a_timeout_and_only_then(monkeypatch):
    # A cancelled query can leave tasks running that hold every task slot, so the
    # queries after it would time out too. The real replacement kills the JVM, which
    # the shared test session cannot survive, so it is stood in for here.
    from pipeline.selection import sql as sql_module

    statuses = {"slow": "timeout", "fast": "ok"}
    ran_in = []

    def fake_execute(session, sql, time_limit):
        ran_in.append((session, sql))
        return QueryResult(statuses[sql])

    monkeypatch.setattr(sql_module, "execute", fake_execute)
    monkeypatch.setattr(sql_module, "replace_jvm", lambda session, build: build())
    built = iter(["second", "third"])
    warehouse = sql_module.Warehouse("first", lambda: next(built))

    assert warehouse.execute("fast").status == "ok"
    assert warehouse.execute("slow").status == "timeout"
    assert warehouse.execute("fast").status == "ok"

    assert ran_in == [("first", "fast"), ("first", "slow"), ("second", "fast")]
    assert warehouse.restarts == 1
