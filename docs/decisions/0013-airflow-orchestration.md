# 0013: Orchestration with Airflow, and the choices that keep it small

Status: accepted (Phase 6, 2026-11-12). Approved by the owner in the Phase 6 plan.

## Context

Phases 0 to 5 run through Make. Each job handles one month of one source and overwrites only that month's partitions, so order and reruns are safe but manual. Two sources now update on their own schedules: TLC monthly, about two months late, and the MTA weekly.

Spec section 7.9 asks for Airflow in standalone mode with its own virtual environment, one DAG named `crz_monthly`, and tasks that call the existing jobs through `BashOperator`.

## Decision

- **Airflow 3.4.0**, the latest stable release, in `Dockerfile.airflow` on top of the project image. It is installed with the release's constraints file into `/opt/airflow-venv`. Spark and the pipeline stay in `/opt/venv`, and `uv.lock` is untouched. The two environments hold different versions of shared packages (pydantic 2.14.2 and 2.14.3), which is the reason for separating them.
- **The steps live in `src/pipeline/orchestration.py`**, as an ordered list of task ids and shell commands with no Airflow import. It is unit-tested with everything else. `dags/crz_pipeline.py` only turns the list into a chain of `BashOperator` tasks.
- **`crz_monthly`** runs on the 1st of each month and processes the month two months before its run date, because that is when TLC has published it. Catch-up is on, and one run is active at a time.
- **Its start date is 2026-10-01**, so catch-up reaches back to the August 2026 data and no further. Older history is loaded with `make backfill`. With a start date of 2023 the first unpause would queue every month and rewrite all of silver.
- **`crz_entries_weekly`** was added beyond the spec. It runs on Fridays, pulls the entries for the month the last published week ended in and the month before, then reruns checks, baselines, scoring, drivers and the site export. Catch-up is off, because only the latest pull matters.
- **The registry commit is read with git inside the task**, with the mounted repo marked safe for that command only. The spec avoided git in the container because of ownership checks on the mount, but an orchestrated run has no host shell to ask.
- **A tree is `-dirty` when anything but `site/` has uncommitted changes.** The site export rewrites `site/` on every run, so counting it would mark every later run dirty. `make score` uses the same rule.
- **No DAG commits or pushes.** The site export writes `site/`, and publishing it stays a manual commit.
- **`make airflow-check`** parses the DAG files inside the Airflow image and fails on an import error. It is not part of CI, which does not install Airflow.

## Alternatives

- Calling the jobs as Python functions inside Airflow's process: fewer process starts, but Airflow's environment would have to import Spark, which the separate environments exist to avoid.
- One DAG for everything on a weekly schedule: simpler to read, but it would rewrite a month of silver every week for nothing.
- A sensor that waits for the TLC file: closer to how a production DAG would behave. The fixed two-month lag is simpler, and the ingest task fails loudly if the file is not there.
- Running the Airflow check in CI: it would need a second job that installs Airflow. The task list is already tested in CI without it.

## Consequences

- Each task starts its own Spark session, which costs a few seconds per task.
- The weekly DAG checks only the latest month of entries. A gap in the month before is caught by the monthly run or by `make checks`.
- The scheduler only runs while the laptop and the `airflow` service are up. Catch-up covers the gaps.

## Acceptance (2026-11-12)

Before any DAG run, the September 2026 rows of silver and gold, all of `gold.baselines`, the latest verdicts, and their drivers were fingerprinted (row count and a sum of row hashes).

- **One month reproduces `make`.** `airflow dags test crz_monthly 2026-11-01` rendered the month as 2026-09 and ran all 12 tasks in 98 seconds. Every fingerprint and all 13 verdicts were identical afterwards.
- **A missed month is caught up.** With the scheduler running and the DAG unpaused, it created the two outstanding runs itself, for run dates 2026-10-01 and 2026-11-01, and ran them one after the other in 3 minutes 20 seconds. They processed 2026-08 and 2026-09. Every task succeeded, the fingerprints were still identical, and the scoring runs recorded a clean registry commit.

`crz_entries_weekly` loads and is left paused. It has not been run.
