import inspect
from datetime import date

import pytest

from pipeline.jobs import staged_run
from pipeline.selection import builder as phase8_builder
from pipeline.selection import ollama
from pipeline.selection import runner as phase8_runner
from pipeline.selection.catalog import Column, Table
from pipeline.selection.evaluate import answers_match
from pipeline.selection.ollama import Reply
from pipeline.selection.request_file import Request
from pipeline.selection.sql import OK, QueryResult
from pipeline.staged import (
    interpreter,
    lifecycle_selector,
    narratives,
    plan_builder,
    predictions,
    request_file,
)
from pipeline.staged.evaluate import answerable, summarize, summarize_predictions, values_present
from pipeline.staged.narratives import Lifecycle
from pipeline.staged.report import outcome, render_report
from pipeline.staged.request_file import StagedRequest
from pipeline.staged.runner import ARMS, run_all, run_arm

# Fixtures only. The real narratives, requests and predictions are written elsewhere.
# Every kind of information carries its own marker, so a prompt can be searched for
# what it should and should not hold.
DAILY = Table(
    "gold.daily_trips",
    "TBLMARK_DAILY Daily trips.",
    [Column("trip_date", "date", "COLMARK_DAILY Pickup date."), Column("trips", "bigint", "n")],
)
SILVER = Table(
    "silver.trips",
    "TBLMARK_SILVER Every trip.",
    [Column("pickup_at", "timestamp_ntz", "COLMARK_SILVER")],
)
ENTRIES = Table(
    "gold.daily_entries",
    "TBLMARK_ENTRIES Entries.",
    [Column("crz_entries", "bigint", "COLMARK_ENTRIES")],
)
TABLES = {t.name: t for t in (DAILY, ENTRIES, SILVER)}
KNOWN = list(TABLES)

TRIPS = Lifecycle(
    "taxi-trips",
    "TITLEMARK_TRIPS Taxi trips",
    "IDXMARK_TRIPS how a trip is recorded.",
    ["gold.daily_trips", "silver.trips"],
    "NARRMARK_TRIPS A trip lands in silver.trips and is counted in gold.daily_trips.trips.",
)
ZONE = Lifecycle(
    "zone-entries",
    "TITLEMARK_ZONE Zone entries",
    "IDXMARK_ZONE how an entry is recorded.",
    ["gold.daily_entries"],
    "NARRMARK_ZONE An entry is counted in gold.daily_entries.crz_entries.",
)
LIFECYCLES = [TRIPS, ZONE]

REQUEST = StagedRequest(
    Request("one-day", "REQMARK how many trips?", "SELECT 7", ["gold.daily_trips"]),
    expected_lifecycle="taxi-trips",
    acceptable_table_sets=[["gold.daily_trips"], ["silver.trips"]],
    held_out=False,
)
HELD_OUT = StagedRequest(
    Request("new-one", "REQMARK how many entries?", "SELECT 7", ["gold.daily_entries"]),
    expected_lifecycle="zone-entries",
    acceptable_table_sets=[["gold.daily_entries"]],
    held_out=True,
)
REFERENCE = QueryResult(OK, ["trips"], [[7]])

PLAN_ANSWER = """TABLES: gold.daily_trips
FILTERS: PLANMARK trip_date = 2025-01-05
MEASURE: sum of trips
GRAIN: one row
DEFINITIONS: none"""


class FakeModel:
    """Answers each stage from fixed text and keeps every call it was given."""

    def __init__(self, lifecycle="LIFECYCLE: taxi-trips", plan=PLAN_ANSWER, sql="SELECT 7"):
        self.lifecycle, self.plan, self.sql, self.calls = lifecycle, plan, sql, []

    def __call__(self, model, system, prompt):
        self.calls.append({"model": model, "system": system, "prompt": prompt})
        if system == lifecycle_selector.SYSTEM:
            return Reply(self.lifecycle, 50, 4, 0.2)
        if system == interpreter.SYSTEM:
            return Reply(self.plan, 300, 40, 0.8)
        return Reply(f"```sql\n{self.sql}\n```", 900, 20, 1.5)


def fake_execute(sql):
    return QueryResult(OK, ["n"], [[7]], seconds=0.1)


def arm(name, model=None, request=REQUEST, execute=fake_execute):
    model = model or FakeModel()
    record = run_arm(name, "m", request, LIFECYCLES, TABLES, REFERENCE, model, execute)
    return record, model


# --- inputs ----------------------------------------------------------------------------

INDEX = [
    {"id": "taxi-trips", "title": "Taxi trips", "one_line": "A trip.", "tables": ["silver.trips"]},
    {
        "id": "zone-entries",
        "title": "Entries",
        "one_line": "An entry.",
        "tables": ["gold.daily_entries"],
    },
]
TEXTS = {"taxi-trips": "A trip is written.", "zone-entries": "An entry is written."}


def test_a_fitting_index_has_no_problems_and_parses():
    assert narratives.problems(INDEX, TEXTS, KNOWN) == []
    parsed = narratives.parse(INDEX, TEXTS)
    assert [lc.id for lc in parsed] == ["taxi-trips", "zone-entries"]
    assert parsed[0].narrative == "A trip is written."


def test_narrative_problems_name_every_misfit():
    index = [
        {"id": "taxi-trips", "title": "", "one_line": "a\nb", "tables": ["silver.nope"]},
        {"id": "taxi-trips", "title": "T", "one_line": "x", "tables": []},
        {"id": "Bad Id", "title": "T", "one_line": "x", "tables": ["silver.trips"]},
        {"title": "T"},
    ]
    texts = {"taxi-trips": "text", "stray": "text"}

    assert narratives.problems(index, texts, KNOWN) == [
        "taxi-trips: `title` is missing or empty",
        "taxi-trips: `one_line` must be one line",
        "taxi-trips: table silver.nope is not a warehouse table",
        "taxi-trips: the id is used twice",
        "taxi-trips: `tables` must be a list with at least one table",
        "Bad Id: the id must be lower-case words joined by hyphens",
        "Bad Id: narratives/Bad Id.md is missing or empty",
        "lifecycle 4: no id",
        "stray: narratives/stray.md has no entry in the index",
    ]


def test_narratives_are_read_from_a_folder(tmp_path):
    (tmp_path / "index.yaml").write_text(
        "- id: taxi-trips\n  title: Taxi trips\n  one_line: A trip.\n  tables: [silver.trips]\n"
    )
    (tmp_path / "taxi-trips.md").write_text("# Taxi trips\n\nA trip is written.\n")

    (loaded,) = narratives.load(tmp_path)

    assert (loaded.id, loaded.tables) == ("taxi-trips", ["silver.trips"])
    assert loaded.narrative.endswith("A trip is written.")
    (tmp_path / "index.yaml").write_text("lifecycles:\n" + (tmp_path / "index.yaml").read_text())
    assert [lc.id for lc in narratives.load(tmp_path)] == ["taxi-trips"]


def test_the_index_line_has_no_table_names():
    line = narratives.index_line(TRIPS)

    assert line == "- taxi-trips: TITLEMARK_TRIPS Taxi trips. IDXMARK_TRIPS how a trip is recorded."
    assert "silver.trips" not in narratives.render_index(LIFECYCLES)


RAW_REQUEST = {
    "id": "one-day",
    "request": "How many?",
    "reference_sql": "SELECT 1",
    "expected_tables": ["gold.daily_trips"],
    "expected_lifecycle": "taxi-trips",
    "acceptable_table_sets": [["gold.daily_trips"], ["silver.trips"]],
}


def test_staged_request_fields_are_read_and_default_to_seen():
    (parsed,) = request_file.parse([RAW_REQUEST])
    (held,) = request_file.parse([RAW_REQUEST | {"held_out": True}])

    assert request_file.problems([RAW_REQUEST], KNOWN, ["taxi-trips"]) == []
    assert (parsed.id, parsed.expected_lifecycle, parsed.held_out) == (
        "one-day",
        "taxi-trips",
        False,
    )
    assert parsed.acceptable_table_sets == [["gold.daily_trips"], ["silver.trips"]]
    assert held.held_out is True


def test_missing_owner_fields_are_problems_for_a_staged_run():
    bare = {k: v for k, v in RAW_REQUEST.items() if not k.startswith(("expected_l", "accept"))}
    wrong = RAW_REQUEST | {
        "id": "two",
        "expected_lifecycle": "nope",
        "acceptable_table_sets": [["gold.nope"], []],
        "held_out": "yes",
    }

    assert request_file.problems([bare, wrong], KNOWN, ["taxi-trips"]) == [
        "one-day: `expected_lifecycle` is missing",
        "one-day: `acceptable_table_sets` is missing",
        "two: expected lifecycle nope is not in the narrative index",
        "two: acceptable table gold.nope is not a warehouse table",
        "two: every acceptable table set must be a list of tables",
        "two: `held_out` must be true or false",
    ]


# --- predictions -----------------------------------------------------------------------

PREDICTIONS = {
    "predicted_on": date(2026, 11, 13),
    "predictions": {
        "one-day": {
            "full": "match",
            "full_narratives": "match",
            "staged": "no_match",
            "staged_hand": {"small": "no_match", "large": "match"},
        }
    },
}


def test_predictions_cover_every_request_arm_and_model():
    assert predictions.problems(PREDICTIONS, ["one-day"], list(ARMS), ["small", "large"]) == []
    assert predictions.predicted(PREDICTIONS, "one-day", "staged", "small") == "no_match"
    assert predictions.predicted(PREDICTIONS, "one-day", "staged_hand", "large") == "match"
    assert predictions.predicted(PREDICTIONS, "one-day", "staged_hand", "other") is None


def test_prediction_problems_name_every_gap():
    raw = {
        "predictions": {
            "one-day": {"full": "maybe", "staged_hand": {"small": "match"}},
            "gone": {"full": "match"},
        }
    }

    assert predictions.problems(
        raw, ["one-day", "new-one"], ["full", "staged_hand"], ["small", "large"]
    ) == [
        "`predicted_on` is missing",
        "gone: predicted, but there is no such request",
        "one-day / full: 'maybe' is not `match` or `no_match`",
        "one-day / staged_hand / large: no valid prediction",
        "new-one / full: no prediction",
        "new-one / staged_hand: no prediction",
    ]
    assert predictions.problems({}, ["one-day"], ["full"], ["small"]) == [
        "selection/predictions.yaml is missing or empty"
    ]
    assert predictions.read_raw(predictions.PREDICTIONS_PATH.parent / "no-such-file.yaml") == {}


# --- the three stages ------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, lifecycle, named, format_ok",
    [
        ("LIFECYCLE: taxi-trips", "taxi-trips", None, True),
        ("Sure.\nlifecycle: `Zone-Entries`.", "zone-entries", None, True),
        ("LIFECYCLE: trips", None, "trips", False),
        ("I would pick zone-entries here.", "zone-entries", None, False),
        ("Either taxi-trips or zone-entries.", None, None, False),
        ("LIFECYCLE:", None, None, False),
        ("No idea.", None, None, False),
    ],
)
def test_lifecycle_selector_parse(answer, lifecycle, named, format_ok):
    choice = lifecycle_selector.parse(answer, ["taxi-trips", "zone-entries"])

    assert (choice.lifecycle, choice.named, choice.format_ok) == (lifecycle, named, format_ok)


def test_interpreter_parses_the_five_parts_and_writes_the_hand_off():
    plan = interpreter.parse(PLAN_ANSWER, KNOWN)

    assert (plan.tables, plan.unknown_tables, plan.format_ok) == (["gold.daily_trips"], [], True)
    assert plan.parts["FILTERS"] == "PLANMARK trip_date = 2025-01-05"
    assert plan.text() == PLAN_ANSWER


def test_interpreter_parse_keeps_what_it_can_and_flags_the_rest():
    answer = (
        "Here is the plan.\n**Tables:** `local.gold.daily_trips`, gold.trips\n"
        "- FILTERS: service = 'yellow'\n  and trip_date in 2025\nMEASURE: sum(trips)\n"
        "FILTERS: a second one\n"
    )

    plan = interpreter.parse(answer, KNOWN)

    assert (plan.tables, plan.unknown_tables, plan.format_ok) == (
        ["gold.daily_trips"],
        ["gold.trips"],
        False,
    )
    assert plan.parts["FILTERS"] == "service = 'yellow' and trip_date in 2025"
    assert plan.text().splitlines()[3:] == ["GRAIN: (not given)", "DEFINITIONS: (not given)"]
    assert interpreter.parse("No plan.", KNOWN) == interpreter.Plan([], [], {}, False)
    no_tables = interpreter.parse(PLAN_ANSWER.replace("gold.daily_trips", "the trips table"), KNOWN)
    assert (no_tables.tables, no_tables.format_ok) == ([], False)


def test_the_plan_format_asks_for_no_sql_and_names_the_five_parts():
    prompt = interpreter.build_prompt("NARRATIVE", "REQUEST")

    assert [label for label in interpreter.PARTS if f"\n{label}: " in prompt] == list(
        interpreter.PARTS
    )
    assert "Do not write SQL" in prompt


# --- scoring ---------------------------------------------------------------------------


def test_values_present_accepts_another_shape_and_strict_does_not():
    reference = [["HV0003", 100], ["HV0005", 40]]
    pivoted = [[100, 40]]
    labelled = [["uber", "HV0003", 100], ["lyft", "HV0005", 40], ["other", None, 3]]

    assert not answers_match(reference, pivoted)
    assert not values_present(reference, pivoted)  # the labels are not there
    assert values_present([[100], [40]], pivoted) and not answers_match([[100], [40]], pivoted)
    assert values_present(reference, labelled) and not answers_match(reference, labelled)
    assert values_present(reference, reference) and answers_match(reference, reference)


def test_values_present_needs_a_cell_for_each_value_and_ignores_nulls():
    assert not values_present([[5], [5]], [[5]])
    assert values_present([[5], [5]], [[5, 5]])
    assert not values_present([[397]], [[0]])
    assert not values_present([[397]], [])
    assert values_present([[None, 4.9933]], [[4.99]])
    assert values_present([], [[1]])


def test_answerable_needs_every_table_of_one_acceptable_set():
    sets = [["gold.daily_entries", "gold.baselines"], ["silver.crz_entries", "gold.baselines"]]

    assert answerable(sets, ["gold.baselines", "silver.crz_entries", "silver.trips"])
    assert not answerable(sets, ["gold.daily_entries"])
    assert not answerable(sets, [])
    assert not answerable([], ["gold.daily_entries"])


# --- the four arms ---------------------------------------------------------------------


def test_each_arm_makes_the_calls_it_should_and_no_more():
    calls = {name: [c["system"] for c in arm(name)[1].calls] for name in ARMS}

    assert calls == {
        "full": [phase8_builder.SYSTEM],
        "full_narratives": [phase8_builder.SYSTEM],
        "staged": [lifecycle_selector.SYSTEM, interpreter.SYSTEM, plan_builder.SYSTEM],
        "staged_hand": [interpreter.SYSTEM, plan_builder.SYSTEM],
    }


def test_the_full_arm_sends_exactly_the_phase_8_prompt():
    _, staged_model = arm("full")
    phase8_model = FakeModel()
    phase8_runner.run_arm("full", "m", REQUEST.base, TABLES, REFERENCE, phase8_model, fake_execute)

    assert staged_model.calls == phase8_model.calls


MARKS = {
    "index": ["IDXMARK_TRIPS", "IDXMARK_ZONE", "TITLEMARK_TRIPS", "TITLEMARK_ZONE"],
    "narrative_chosen": ["NARRMARK_TRIPS"],
    "narrative_other": ["NARRMARK_ZONE"],
    "schema_of_plan": ["TBLMARK_DAILY", "COLMARK_DAILY"],
    "schema_other": ["TBLMARK_SILVER", "COLMARK_SILVER", "TBLMARK_ENTRIES", "COLMARK_ENTRIES"],
    "request": ["REQMARK"],
    "plan": ["PLANMARK"],
}
# What each stage's prompt must hold, by kind of information. Everything else is forbidden.
ALLOWED = {
    "selector": {"index", "request"},
    "interpreter": {"narrative_chosen", "request"},
    "builder": {"plan", "schema_of_plan"},
}


@pytest.mark.parametrize("name", ["staged", "staged_hand"])
def test_no_stage_prompt_holds_information_assigned_to_another_stage(name):
    record, model = arm(name)

    assert [stage["stage"] for stage in record["stages"]] == (
        ["selector", "interpreter", "builder"] if name == "staged" else ["interpreter", "builder"]
    )
    for stage, call in zip(record["stages"], model.calls, strict=True):
        assert stage["prompt"] == call["prompt"]  # what is saved is what was sent
        for kind, marks in MARKS.items():
            for mark in marks:
                held = mark in call["prompt"]
                wanted = kind in ALLOWED[stage["stage"]]
                assert held == wanted, f"{stage['stage']} prompt: {mark} ({kind}) held={held}"
        assert not any(mark in call["system"] for marks in MARKS.values() for mark in marks)
    # The selector is shown no table or column of the schema, and the builder no lifecycle id.
    by_stage = {stage["stage"]: stage["prompt"] for stage in record["stages"]}
    if "selector" in by_stage:
        assert not any(name in by_stage["selector"] for name in [*KNOWN, "trip_date", "pickup_at"])
    assert not any(lc.id in by_stage["builder"] for lc in LIFECYCLES)
    assert "silver.trips" not in by_stage["builder"]


def test_the_one_call_arms_hold_what_they_are_meant_to():
    full = arm("full")[1].calls[0]["prompt"]
    everything = arm("full_narratives")[1].calls[0]["prompt"]

    for prompt in (full, everything):
        assert all(
            m in prompt for m in MARKS["schema_of_plan"] + MARKS["schema_other"] + MARKS["request"]
        )
        assert not any(m in prompt for m in MARKS["index"])
    assert not any(m in full for m in ["NARRMARK_TRIPS", "NARRMARK_ZONE"])
    assert all(m in everything for m in ["NARRMARK_TRIPS", "NARRMARK_ZONE"])


def test_a_stage_is_given_only_its_prompt_and_ollama_is_sent_no_earlier_context():
    _, model = arm("staged")

    assert all(set(call) == {"model", "system", "prompt"} for call in model.calls)
    payload = ollama.generate_payload("m", "system", "prompt")
    assert set(payload) == {"model", "system", "prompt", "stream", "options"}
    assert "context" not in inspect.signature(ollama.generate).parameters
    assert "context" not in Reply.__dataclass_fields__


def test_staged_record_keeps_every_hand_off_and_scores_selection_and_answer():
    record, _ = arm("staged")

    selector, interpret, build = record["stages"]
    assert selector["parsed"] == {"lifecycle": "taxi-trips", "named": None, "format_ok": True}
    assert interpret["parsed"]["hand_off"] == PLAN_ANSWER == record["plan"]
    assert build["parsed"] == {"sql": "SELECT 7"}
    assert (selector["prompt_tokens"], interpret["output_tokens"], build["seconds"]) == (
        50,
        40,
        1.5,
    )
    assert (record["lifecycle"], record["lifecycle_correct"]) == ("taxi-trips", True)
    assert (record["plan_tables"], record["answerable"]) == (["gold.daily_trips"], True)
    assert record["tables_given"] == ["gold.daily_trips"]
    assert (record["sql_status"], record["answer_matched"], record["values_present"]) == (
        "ok",
        True,
        True,
    )


def test_the_hand_arm_uses_the_owners_lifecycle_and_has_no_selector_score():
    record, model = arm(
        "staged_hand",
        request=HELD_OUT,
        model=FakeModel(plan=PLAN_ANSWER.replace("gold.daily_trips", "gold.daily_entries")),
    )

    assert (record["lifecycle"], record["lifecycle_correct"]) == ("zone-entries", None)
    assert "NARRMARK_ZONE" in model.calls[0]["prompt"]
    assert record["held_out"] is True


def test_a_wrong_lifecycle_and_a_plan_outside_it_are_recorded():
    model = FakeModel(lifecycle="LIFECYCLE: zone-entries")

    record, _ = arm("staged", model=model)

    assert (record["lifecycle"], record["lifecycle_correct"]) == ("zone-entries", False)
    assert "NARRMARK_ZONE" in model.calls[1]["prompt"]
    assert record["plan_tables_outside_lifecycle"] == ["gold.daily_trips"]


@pytest.mark.parametrize(
    "model, status, stages",
    [
        (FakeModel(lifecycle="No idea."), "no_lifecycle", 1),
        (FakeModel(plan="I cannot plan this."), "no_tables", 2),
        (FakeModel(sql=""), "no_sql", 3),
    ],
)
def test_a_stage_that_hands_nothing_on_stops_the_arm_and_is_recorded(model, status, stages):
    record, _ = arm("staged", model=model)

    assert (record["sql_status"], len(record["stages"])) == (status, stages)
    assert record["stages"][-1]["format_ok"] is False
    assert (record["answer_matched"], record["values_present"]) == (False, False)


def test_a_failed_model_call_is_a_result_not_a_crash():
    def unreachable(model, system, prompt):
        raise TimeoutError("timed out")

    record = run_arm("full", "m", REQUEST, LIFECYCLES, TABLES, REFERENCE, unreachable, fake_execute)

    assert record["sql_status"] == "model_error"
    assert record["sql_error"] == "builder: TimeoutError: timed out"
    assert record["stages"][0]["answer"] is None


def test_strict_and_loose_measures_are_recorded_separately():
    def pivoted(sql):
        return QueryResult(OK, ["label", "n"], [["yellow", 7], ["fhvhv", 9]])

    record, _ = arm("full", execute=pivoted)

    assert (record["answer_matched"], record["values_present"], outcome(record)) == (
        False,
        True,
        "values",
    )


# --- summary, predictions and report ---------------------------------------------------


def run_fixture():
    records = run_all(
        [REQUEST, HELD_OUT],
        ["small"],
        LIFECYCLES,
        TABLES,
        {"one-day": REFERENCE, "new-one": REFERENCE},
        FakeModel(),
        fake_execute,
    )
    for record in records:
        record["run_id"] = "run-1"
    return records


def test_summary_splits_seen_from_held_out():
    lines = summarize(run_fixture())

    staged = {line["split"]: line for line in lines if line["arm"] == "staged"}
    assert [line["split"] for line in lines if line["arm"] == "full"] == ["all", "seen", "held_out"]
    assert (staged["all"]["requests"], staged["seen"]["requests"]) == (2, 1)
    assert (staged["all"]["lifecycle_correct"], staged["held_out"]["lifecycle_correct"]) == (1, 0)
    assert (staged["all"]["answerable"], staged["held_out"]["answerable"]) == (1, 0)
    assert (staged["all"]["answer_matched"], staged["all"]["values_present"]) == (2, 2)
    full = next(line for line in lines if (line["arm"], line["split"]) == ("full", "all"))
    assert (full["lifecycle_correct"], full["answerable"], full["format_broken"]) == (None, None, 0)


def test_predictions_are_compared_with_the_strict_outcome():
    records = run_fixture()

    comparison = predictions.compare(PREDICTIONS, records)

    assert {(c["arm"], c["predicted"], c["observed"], c["agreed"]) for c in comparison} == {
        ("full", "match", "match", True),
        ("full_narratives", "match", "match", True),
        ("staged", "no_match", "match", False),
        ("staged_hand", "no_match", "match", False),
    }
    assert len(comparison) == 4  # the held-out request has no prediction in this fixture
    staged = next(s for s in summarize_predictions(comparison) if s["arm"] == "staged")
    assert staged == {
        "model": "small",
        "arm": "staged",
        "predictions": 1,
        "agreed": 0,
        "predicted_match": 0,
        "observed_match": 1,
    }


def test_report_shows_the_splits_the_stages_and_the_predictions():
    records = run_fixture()
    comparison = predictions.compare(PREDICTIONS, records)
    result = {
        "run_id": "run-1",
        "requests_commit": "abc1234",
        "arms": list(ARMS),
        "lifecycles": 2,
        "predicted_on": "2026-11-13",
        "models": {"small": "a" * 64},
        "ollama_options": {"temperature": 0, "seed": 0, "num_ctx": 16384},
        "started_at": "t0",
        "finished_at": "t1",
        "sql_time_limit_seconds": 120,
        "sql_max_rows": 1000,
        "summary": summarize(records),
        "prediction_comparison": comparison,
        "prediction_summary": summarize_predictions(comparison),
        "records": records,
    }

    report = render_report(result)

    assert "2 requests (1 seen, 1 held-out), 2 lifecycles, predictions dated 2026-11-13" in report
    assert "| small | staged | 1 | held_out | 0 | 0 | 0 | 1 | 1 | 1 |" in report
    assert "| new-one | held-out | match | match | match | match |" in report
    row = "| small | staged | new-one | zone-entries | taxi-trips | gold.daily_trips | False "
    assert row + "| yes | match |" in report
    assert "- `small` / `one-day` / `staged`: predicted no_match, observed match." in report
    assert "| small | staged | interpreter | 2 | 0.8 | 300 | 300 |" in report


# --- the run's refusals ----------------------------------------------------------------


def complete_inputs():
    raw = [RAW_REQUEST]
    forecast = {
        "predicted_on": "2026-11-13",
        "predictions": {"one-day": dict.fromkeys(ARMS, "match")},
    }
    return staged_run.Inputs(raw, INDEX, TEXTS, forecast)


def test_complete_inputs_may_run():
    assert staged_run.input_problems(complete_inputs(), KNOWN, list(ARMS), ["m"]) == []


def test_the_run_refuses_without_narratives_owner_fields_or_predictions():
    full = complete_inputs()
    no_fields = [
        {
            k: v
            for k, v in RAW_REQUEST.items()
            if k in ("id", "request", "reference_sql", "expected_tables")
        }
    ]

    assert staged_run.input_problems(
        staged_run.Inputs(full.requests, [], {}, full.predictions), KNOWN, list(ARMS), ["m"]
    ) == ["narratives/index.yaml is missing or empty"]
    assert staged_run.input_problems(
        staged_run.Inputs(no_fields, INDEX, TEXTS, full.predictions), KNOWN, list(ARMS), ["m"]
    ) == ["one-day: `expected_lifecycle` is missing", "one-day: `acceptable_table_sets` is missing"]
    assert staged_run.input_problems(
        staged_run.Inputs(full.requests, INDEX, TEXTS, {}), KNOWN, list(ARMS), ["m"]
    ) == ["selection/predictions.yaml is missing or empty"]
    partial = {"predicted_on": "2026-11-13", "predictions": {"one-day": {"full": "match"}}}
    assert staged_run.input_problems(
        staged_run.Inputs(full.requests, INDEX, TEXTS, partial), KNOWN, ["full", "staged"], ["m"]
    ) == ["one-day / staged: no prediction"]


def test_the_run_refuses_a_prompt_that_would_not_fit_the_context():
    inputs = complete_inputs()

    assert staged_run.prompt_too_long(20_000, inputs) is None
    assert "more than the 15,360 that fit" in staged_run.prompt_too_long(60_000, inputs)
