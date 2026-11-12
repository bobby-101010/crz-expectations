"""Airflow DAGs for the pipeline. The steps themselves are in `pipeline.orchestration`.

`crz_monthly` runs on the 1st of each month and processes the month two months back,
which is when TLC has published it. Catch-up is on, so a missed month is run when the
scheduler comes back. Its start date keeps catch-up to recent months: older history
is loaded with `make backfill`.

`crz_entries_weekly` follows the MTA's weekly update. Only its latest run matters, so
catch-up is off.

Neither DAG commits or pushes. The site export writes `site/`, and publishing it
stays a manual step.
"""

from datetime import datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

from pipeline.orchestration import REPO, Step, monthly_steps, weekly_steps


def chain(steps: list[Step]) -> None:
    """One task per step, each after the one before it."""
    previous = None
    for step in steps:
        task = BashOperator(task_id=step.task_id, bash_command=step.command, cwd=REPO)
        if previous is not None:
            previous >> task
        previous = task


with DAG(
    "crz_monthly",
    description="One month of TLC trips and MTA entries, from download to the status page.",
    schedule="0 6 1 * *",
    start_date=datetime(2026, 10, 1),
    catchup=True,
    max_active_runs=1,
    tags=["crz"],
):
    chain(monthly_steps())

with DAG(
    "crz_entries_weekly",
    description="The MTA's weekly entries update, then baselines, scoring and the status page.",
    schedule="0 6 * * 5",
    start_date=datetime(2026, 11, 6),
    catchup=False,
    max_active_runs=1,
    tags=["crz"],
):
    chain(weekly_steps())
