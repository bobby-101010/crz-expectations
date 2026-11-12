#!/bin/sh
# Lists the DAGs Airflow can load, and exits 1 if any DAG file fails to import.
# Run inside the Airflow image: `make airflow-check`.
set -e
airflow db migrate >/dev/null 2>&1
airflow dags reserialize >/dev/null 2>&1
airflow dags list -o plain 2>/dev/null
# An import error is reported with the path of its DAG file. Other lines are notices.
# `--local` parses the files now, where the plain command only reads what is in the database.
errors=$(airflow dags list-import-errors --local -o plain 2>/dev/null | grep '/dags/.*\.py' || true)
if [ -n "$errors" ]; then
    echo "$errors"
    exit 1
fi
