"""The descriptions in catalog/tables.yaml against the tables the jobs really create."""

import pytest

from pipeline.checks import core, ingest_stats
from pipeline.jobs import (
    baselines,
    catalog_comments,
    catalog_export,
    daily_entries,
    daily_trip_slices,
    drivers,
    score,
    selection_reference,
    selection_run,
    silver_entries,
)
from pipeline.selection.catalog import load_descriptions, read_tables, table_comment
from pipeline.selection.ollama import Reply
from pipeline.selection.request_file import Request

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def all_tables(lake, loaded, reference_tables):
    """Every warehouse table, created by the DDL of the job that owns it."""
    core.ensure_results_table(lake)
    ingest_stats.ensure_table(lake)
    for job in (silver_entries, daily_entries, daily_trip_slices, baselines, score, drivers):
        job.ensure_table(lake)
    return lake


def test_the_descriptions_match_the_tables_the_jobs_create(all_tables):
    assert catalog_comments.check(all_tables) == []


def test_comments_are_written_once_and_no_data_changes(all_tables):
    before = catalog_comments.snapshot_ids(all_tables, ["silver.trips", "gold.daily_trips"])
    rows = all_tables.table("local.silver.trips").count()

    first = catalog_comments.run(all_tables)
    second = catalog_comments.run(all_tables)

    descriptions = load_descriptions()
    columns = sum(len(d["columns"]) for d in descriptions.values())
    assert len(first) == len(descriptions) + columns
    assert second == []
    assert catalog_comments.snapshot_ids(all_tables, list(before)) == before
    assert all_tables.table("local.silver.trips").count() == rows

    tables = read_tables(all_tables)
    assert tables["silver.trips"].comment == table_comment(descriptions["silver.trips"])
    assert tables["silver.trips"].partitioning == ["service", "months(pickup_at)"]
    assert all(column.comment for table in tables.values() for column in table.columns)


def test_export_writes_the_schema_and_the_index_from_the_warehouse(all_tables, tmp_path):
    catalog_comments.run(all_tables)

    schema_path, index_path = catalog_export.run(all_tables, tmp_path)

    index = [line for line in index_path.read_text().splitlines() if line.startswith("- ")]
    assert len(index) == 12
    assert any(line.startswith("- silver.trips: Every yellow taxi") for line in index)
    schema = schema_path.read_text()
    assert schema.count("\n## ") == 12
    assert "| cbd_fee_trips | bigint | Number of those trips with a congestion fee" in schema


def test_the_three_arms_run_end_to_end_with_a_stand_in_model(all_tables):
    catalog_comments.run(all_tables)
    request = Request(
        "yellow-one-day",
        "How many yellow taxi trips were picked up on January 5, 2025?",
        "SELECT trips FROM gold.daily_trips "
        "WHERE service = 'yellow' AND trip_date = DATE '2025-01-05'",
        ["gold.daily_trips"],
    )

    def stand_in(model, system, prompt):
        if "one per line" in prompt:
            return Reply("TABLES: silver.trips, gold.daily_trips", 1, 1, 0.1)
        sql = (
            "SELECT count(*) FROM silver.trips WHERE service = 'yellow' "
            "AND pickup_at >= '2025-01-05' AND pickup_at < '2025-01-06'"
        )
        return Reply(f"```sql\n{sql}\n```", 1, 1, 0.1)

    records, references = selection_run.run(all_tables, [request], ["stand-in"], stand_in)

    assert references[0]["rows"] == [[2]]
    assert [(r["arm"], r["sql_status"], r["answer_matched"]) for r in records] == [
        ("full", "ok", True),
        ("selector", "ok", True),
        ("hand", "ok", True),
    ]
    # Nothing stops a query from naming a table the builder was not shown. It is recorded.
    assert [r["tables_not_given"] for r in records] == [[], [], ["silver.trips"]]
    assert records[1]["selection"] == {
        "all_included": True,
        "missing": [],
        "extra": ["silver.trips"],
    }


def test_the_run_refuses_to_start_without_the_owners_tables(all_tables):
    request = Request("draft", "How many?", "SELECT 1", [])

    with pytest.raises(ValueError, match="expected_tables is empty"):
        selection_run.run(all_tables, [request], ["stand-in"], lambda *_: None)
    assert selection_reference.run(all_tables, [request])["draft"].rows == [[1]]
