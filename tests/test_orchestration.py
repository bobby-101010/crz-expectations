import importlib.util
import re

from pipeline.orchestration import (
    MONTHLY_MONTH,
    PYTHON,
    REGISTRY_COMMIT,
    after_gold,
    monthly_steps,
    weekly_steps,
)


def modules(steps):
    return [re.search(r"-m (pipeline\.jobs\.\w+)", step.command).group(1) for step in steps]


def test_monthly_steps_follow_the_order_in_the_spec():
    steps = monthly_steps("2026-09")

    assert [step.task_id for step in steps] == [
        "ingest_yellow",
        "ingest_fhvhv",
        "silver_yellow",
        "silver_fhvhv",
        "entries",
        "checks",
        "gold",
        "slices",
        "baselines",
        "score",
        "drivers",
        "site_export",
    ]
    assert steps[0].command == f"{PYTHON} -m pipeline.jobs.ingest --service yellow --month 2026-09"
    assert steps[4].command.endswith("backfill_entries --start 2026-09 --end 2026-09")
    assert steps[5].command.endswith("checks --month 2026-09")


def test_every_step_calls_a_job_that_exists_with_the_projects_python():
    for step in [*monthly_steps("2026-09"), *weekly_steps("2026-10", "2026-11")]:
        assert f"{PYTHON} -m pipeline.jobs." in step.command
    for module in set(modules(monthly_steps("2026-09"))):
        assert importlib.util.find_spec(module) is not None, module


def test_the_default_month_is_a_template_two_months_before_the_run_date():
    assert MONTHLY_MONTH == "{{ logical_date.subtract(months=2).strftime('%Y-%m') }}"
    assert MONTHLY_MONTH in monthly_steps()[0].command


def test_weekly_steps_pull_entries_then_rerun_what_depends_on_them():
    steps = weekly_steps("2026-10", "2026-11")

    assert [step.task_id for step in steps] == [
        "entries",
        "checks",
        "baselines",
        "score",
        "drivers",
        "site_export",
    ]
    assert steps[0].command.endswith("backfill_entries --start 2026-10 --end 2026-11")
    assert steps[1].command.endswith("checks --month 2026-11")
    assert steps[2:] == after_gold()


def test_scoring_is_given_the_registry_commit_and_ignores_the_generated_site():
    score = next(step for step in after_gold() if step.task_id == "score")

    assert score.command.startswith(f"REGISTRY_COMMIT={REGISTRY_COMMIT} ")
    assert "safe.directory=/app" in REGISTRY_COMMIT
    assert "':!site'" in REGISTRY_COMMIT and "echo -dirty" in REGISTRY_COMMIT
