"""Table and column descriptions: the YAML, the warehouse comments, and the text a model sees.

The YAML in `catalog/tables.yaml` is the source. The comments in the warehouse are what
is exported, so the schema a model reads is the one the warehouse really carries.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pyspark.sql import SparkSession

DESCRIPTIONS_PATH = Path(__file__).resolve().parents[3] / "catalog" / "tables.yaml"
CATALOG = "local"
TABLE_FIELDS = ("summary", "grain", "not_for")  # required; `details` is optional

GRAIN, DETAILS, NOT_FOR = "Grain: ", "Details: ", "Do not use for: "


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    comment: str | None


@dataclass(frozen=True)
class Table:
    """One warehouse table as it is: its columns, partitioning and comments."""

    name: str  # 'gold.daily_trips'
    comment: str | None
    columns: list[Column]
    partitioning: list[str] = field(default_factory=list)


def load_descriptions(path: Path | None = None) -> dict:
    """Table name -> its description entry, as written in the YAML."""
    with open(path or DESCRIPTIONS_PATH) as source:
        return yaml.safe_load(source)["tables"]


def column_description(entry) -> str:
    """A column entry is a string, or a mapping with `description`."""
    text = entry.get("description") if isinstance(entry, dict) else entry
    return " ".join(str(text or "").split())


def owner_reviews(descriptions: dict) -> dict[str, str]:
    """'table.column' -> the open question, for every column marked for the owner."""
    return {
        f"{table}.{name}": " ".join(str(entry["owner_review"]).split())
        for table, described in descriptions.items()
        for name, entry in (described.get("columns") or {}).items()
        if isinstance(entry, dict) and entry.get("owner_review")
    }


def problems(descriptions: dict, schemas: dict[str, list[str]]) -> list[str]:
    """Everything that keeps the descriptions from matching the real tables.

    `schemas` is table name -> its column names, read from the warehouse. Every table
    and column must be described, and nothing may be described that does not exist.
    """
    found = []
    for table in sorted(set(schemas) - set(descriptions)):
        found.append(f"{table}: the table is not described")
    for table in sorted(set(descriptions) - set(schemas)):
        found.append(f"{table}: described, but there is no such table")
    for table in sorted(set(descriptions) & set(schemas)):
        described = descriptions[table] or {}
        for name in TABLE_FIELDS:
            if not str(described.get(name) or "").strip():
                found.append(f"{table}: `{name}` is missing or empty")
        if "\n" in str(described.get("summary") or "").strip():
            found.append(f"{table}: `summary` must be one line")
        columns = described.get("columns") or {}
        for column in schemas[table]:
            if column not in columns:
                found.append(f"{table}.{column}: the column is not described")
            elif not column_description(columns[column]):
                found.append(f"{table}.{column}: the description is empty")
        for column in columns:
            if column not in schemas[table]:
                found.append(f"{table}.{column}: described, but there is no such column")
    return found


def table_comment(described: dict) -> str:
    """The table comment: the summary line, then grain, details, and when not to use it."""

    def flat(name: str) -> str:
        return " ".join(str(described.get(name) or "").split())

    lines = [flat("summary"), GRAIN + flat("grain")]
    if flat("details"):
        lines.append(DETAILS + flat("details"))
    lines.append(NOT_FOR + flat("not_for"))
    return "\n".join(lines)


def quoted(text: str) -> str:
    """A Spark SQL string literal, with backslashes, quotes and line breaks escaped."""
    escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    return f"'{escaped}'"


def comment_statements(descriptions: dict, current: dict[str, Table]) -> list[str]:
    """The statements that bring the warehouse comments in line with the descriptions.

    Only comments that differ get a statement, so a second run returns nothing.
    Every statement changes metadata only.
    """
    statements = []
    for name, described in descriptions.items():
        table = current[name]
        wanted = table_comment(described)
        if table.comment != wanted:
            statements.append(f"COMMENT ON TABLE {CATALOG}.{name} IS {quoted(wanted)}")
        for column in table.columns:
            wanted = column_description(described["columns"][column.name])
            if column.comment != wanted:
                statements.append(
                    f"ALTER TABLE {CATALOG}.{name} ALTER COLUMN {column.name} "
                    f"COMMENT {quoted(wanted)}"
                )
    return statements


def table_names(spark: SparkSession) -> list[str]:
    """Every table in the catalog, as 'namespace.table', sorted."""
    names = []
    for namespace in spark.sql(f"SHOW NAMESPACES IN {CATALOG}").collect():
        for row in spark.sql(f"SHOW TABLES IN {CATALOG}.{namespace[0]}").collect():
            names.append(f"{namespace[0]}.{row['tableName']}")
    return sorted(names)


def parse_describe(name: str, rows: list[tuple]) -> Table:
    """The rows of DESCRIBE TABLE EXTENDED -> a Table.

    Columns come first. `# Partitioning` lists the partition fields, and the table
    comment is the `Comment` row under `# Detailed Table Information`.
    """
    columns, partitioning, comment, section = [], [], None, "columns"
    for col_name, data_type, col_comment in rows:
        if col_name.startswith("#"):
            section = col_name
        elif not col_name.strip():
            continue
        elif section == "columns":
            columns.append(Column(col_name, data_type, col_comment or None))
        elif section == "# Partitioning" and col_name.startswith("Part "):
            partitioning.append(data_type)
        elif section == "# Detailed Table Information" and col_name == "Comment":
            comment = data_type or None
    return Table(name, comment, columns, partitioning)


def read_table(spark: SparkSession, name: str) -> Table:
    rows = spark.sql(f"DESCRIBE TABLE EXTENDED {CATALOG}.{name}").collect()
    return parse_describe(name, [tuple(row) for row in rows])


def read_tables(spark: SparkSession) -> dict[str, Table]:
    """Every warehouse table with the comments it carries now."""
    return {name: read_table(spark, name) for name in table_names(spark)}


def index_line(table: Table) -> str:
    """One line for the selector: the table's name and the first line of its comment."""
    summary = (table.comment or "").split("\n")[0] or "(no description)"
    return f"- {table.name}: {summary}"


def render_index(tables: list[Table]) -> str:
    """The one-line-per-table index."""
    return "\n".join(index_line(table) for table in tables) + "\n"


def render_table(table: Table) -> str:
    """One table in full, as markdown: its comment, partitioning, and every column."""
    lines = [f"## {table.name}", "", *(table.comment or "(no description)").split("\n")]
    if table.partitioning:
        lines.append("Partitioned by: " + ", ".join(table.partitioning))
    lines += ["", "| Column | Type | Description |", "| --- | --- | --- |"]
    for column in table.columns:
        comment = (column.comment or "").replace("|", "\\|")
        lines.append(f"| {column.name} | {column.type} | {comment} |")
    return "\n".join(lines) + "\n"


def render_schema(tables: list[Table]) -> str:
    """The described schema of the given tables, as markdown."""
    return "\n".join(render_table(table) for table in tables)
