"""The pipeline's steps, in order, as shell commands an orchestrator can run.

This module imports nothing from Airflow, so it is tested with everything else.
`dags/` turns these lists into DAGs. Each command calls an existing job with the
project's own Python, so Airflow's environment never has to import Spark.
"""

from dataclasses import dataclass

PYTHON = "/opt/venv/bin/python"
REPO = "/app"
SERVICES = ("yellow", "fhvhv")

# TLC publishes a month about two months after it ends, so the run on the 1st of a
# month processes the month two months before it.
TLC_LAG_MONTHS = 2
MONTHLY_MONTH = f"{{{{ logical_date.subtract(months={TLC_LAG_MONTHS}).strftime('%Y-%m') }}}}"

# The MTA publishes a week (Sunday to Saturday) a few days after it ends. A weekly run
# pulls the month that week ended in, and the month before in case the week straddled two.
WEEKLY_LAST_MONTH = "{{ logical_date.subtract(days=6).strftime('%Y-%m') }}"
WEEKLY_FIRST_MONTH = "{{ logical_date.subtract(days=6).subtract(months=1).strftime('%Y-%m') }}"

# The registry commit, with `-dirty` if anything but the generated site has uncommitted
# changes. The repo is mounted from the host, so git is told to trust it for this command.
GIT = f"git -c safe.directory={REPO} -C {REPO}"
REGISTRY_COMMIT = (
    f"$({GIT} rev-parse --short HEAD)"
    f"$(test -z \"$({GIT} status --porcelain -- . ':!site')\" || echo -dirty)"
)


@dataclass(frozen=True)
class Step:
    task_id: str
    command: str


def job(module: str, arguments: str = "") -> str:
    return f"{PYTHON} -m pipeline.jobs.{module} {arguments}".strip()


def after_gold() -> list[Step]:
    """Steps that read gold as a whole: the same after a monthly or a weekly load."""
    return [
        Step("baselines", job("baselines")),
        Step("score", f"REGISTRY_COMMIT={REGISTRY_COMMIT} {job('score')}"),
        Step("drivers", job("drivers")),
        Step("site_export", job("site")),
    ]


def monthly_steps(month: str = MONTHLY_MONTH) -> list[Step]:
    """One month, end to end, in the order of spec section 7.9."""
    return [
        *[Step(f"ingest_{s}", job("ingest", f"--service {s} --month {month}")) for s in SERVICES],
        *[
            Step(f"silver_{s}", job("silver_trips", f"--service {s} --month {month}"))
            for s in SERVICES
        ],
        Step("entries", job("backfill_entries", f"--start {month} --end {month}")),
        Step("checks", job("checks", f"--month {month}")),
        Step("gold", job("daily_trips", f"--month {month}")),
        Step("slices", job("daily_trip_slices", f"--month {month}")),
        *after_gold(),
    ]


def weekly_steps(
    first_month: str = WEEKLY_FIRST_MONTH, last_month: str = WEEKLY_LAST_MONTH
) -> list[Step]:
    """The MTA's weekly update: pull the entries again, then everything that depends on them."""
    return [
        Step("entries", job("backfill_entries", f"--start {first_month} --end {last_month}")),
        Step("checks", job("checks", f"--month {last_month}")),
        *after_gold(),
    ]
