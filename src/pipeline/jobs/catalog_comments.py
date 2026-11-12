"""Write the descriptions in catalog/tables.yaml into Iceberg as table and column comments.

Metadata only: no data file is read or written, and no snapshot is added. Running it
again changes nothing. `--check` only compares the YAML with the real tables.

`make reference` rebuilds the two reference tables with `createOrReplace`, which drops
their comments. Run this job again after it.
"""

import argparse
import sys

from pyspark.sql import SparkSession

from pipeline.selection.catalog import (
    comment_statements,
    load_descriptions,
    owner_reviews,
    problems,
    read_tables,
)
from pipeline.session import build_session


def snapshot_ids(spark: SparkSession, names: list[str]) -> dict[str, str | None]:
    """Table -> its current snapshot id. A data change would move it."""
    ids = {}
    for name in names:
        rows = spark.sql(f"SHOW TBLPROPERTIES local.{name}").collect()
        ids[name] = {r["key"]: r["value"] for r in rows}.get("current-snapshot-id")
    return ids


def check(spark: SparkSession, descriptions: dict | None = None) -> list[str]:
    """Problems between the descriptions and the tables as they are. Empty when they match."""
    descriptions = load_descriptions() if descriptions is None else descriptions
    schemas = {name: [c.name for c in t.columns] for name, t in read_tables(spark).items()}
    return problems(descriptions, schemas)


def run(spark: SparkSession, descriptions: dict | None = None) -> list[str]:
    """Apply the comments that differ. Returns the statements that were run."""
    descriptions = load_descriptions() if descriptions is None else descriptions
    tables = read_tables(spark)
    found = problems(
        descriptions, {name: [c.name for c in t.columns] for name, t in tables.items()}
    )
    if found:
        raise ValueError("the descriptions do not match the warehouse: " + "; ".join(found))

    before = snapshot_ids(spark, list(tables))
    statements = comment_statements(descriptions, tables)
    for statement in statements:
        spark.sql(statement)
    after = snapshot_ids(spark, list(tables))
    if before != after:
        moved = sorted(name for name in before if before[name] != after[name])
        raise RuntimeError(f"a snapshot changed while writing comments: {moved}")
    return statements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare only, write nothing")
    args = parser.parse_args()

    descriptions = load_descriptions()
    spark = build_session("catalog_comments")
    if args.check:
        found = check(spark, descriptions)
        for problem in found:
            print(problem)
        for column, question in owner_reviews(descriptions).items():
            print(f"for the owner: {column}: {question}")
        columns = sum(len(d["columns"]) for d in descriptions.values())
        state = "DO NOT MATCH" if found else "match"
        print(f"{len(descriptions)} tables, {columns} columns: descriptions {state} the warehouse")
        spark.stop()
        sys.exit(1 if found else 0)

    statements = run(spark, descriptions)
    print(f"{len(statements)} comments written; no snapshot changed")
    spark.stop()


if __name__ == "__main__":
    main()
