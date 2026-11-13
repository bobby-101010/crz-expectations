"""Run a model's query through the existing Spark session: read-only, with a time limit.

A model's SQL is untrusted. It must be a single SELECT, it is cancelled after the time
limit, and only a capped number of rows is brought back.
"""

import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from pyspark import SparkContext
from pyspark.sql import SparkSession

TIME_LIMIT_SECONDS = 120
MAX_ROWS = 1000
CATALOG = "local"

OK, REJECTED, ERROR, TIMEOUT, TOO_MANY_ROWS = "ok", "rejected", "error", "timeout", "too_many_rows"

LITERALS = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`", re.DOTALL)
COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
WRITES = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|OVERWRITE)\b", re.IGNORECASE)


@dataclass(frozen=True)
class QueryResult:
    status: str  # ok, rejected, error, timeout or too_many_rows
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    error: str | None = None
    seconds: float | None = None

    @property
    def ran(self) -> bool:
        return self.status == OK


def rejection(sql: str) -> str | None:
    """Why a query may not run, or None if it is a single read-only SELECT."""
    bare = LITERALS.sub("''", COMMENTS.sub(" ", sql)).strip().rstrip(";").strip()
    if not bare:
        return "the query is empty"
    if ";" in bare:
        return "more than one statement"
    if not re.match(r"(SELECT|WITH)\b", bare, re.IGNORECASE):
        return "the query does not start with SELECT or WITH"
    write = WRITES.search(bare)
    if write:
        return f"the query contains {write.group(1).upper()}"
    return None


def plain(value):
    """A cell as something JSON can hold."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    return str(value)


def execute(
    spark: SparkSession,
    sql: str,
    time_limit: float = TIME_LIMIT_SECONDS,
    max_rows: int = MAX_ROWS,
) -> QueryResult:
    """Run one query and bring back at most `max_rows` rows. Never raises for a bad query."""
    reason = rejection(sql)
    if reason:
        return QueryResult(REJECTED, error=reason)

    context = spark.sparkContext
    group = f"selection-{uuid.uuid4().hex}"
    timed_out = threading.Event()

    def cancel() -> None:
        timed_out.set()
        context.cancelJobGroup(group)

    timer = threading.Timer(time_limit, cancel)
    started = datetime.now()
    context.setJobGroup(group, "selection harness query", interruptOnCancel=True)
    timer.start()
    try:
        frame = spark.sql(sql)
        columns = list(frame.columns)
        rows = frame.limit(max_rows + 1).collect()
    except Exception as failure:  # any failure of a model's query is a result, not a crash
        seconds = (datetime.now() - started).total_seconds()
        if timed_out.is_set():
            return QueryResult(TIMEOUT, error=f"cancelled after {time_limit:.0f}s", seconds=seconds)
        message = str(failure).strip().splitlines()[0][:500] if str(failure).strip() else ""
        return QueryResult(ERROR, error=f"{type(failure).__name__}: {message}", seconds=seconds)
    finally:
        timer.cancel()
        context.setLocalProperty("spark.jobGroup.id", None)

    seconds = (datetime.now() - started).total_seconds()
    if len(rows) > max_rows:
        return QueryResult(
            TOO_MANY_ROWS, columns, error=f"more than {max_rows} rows", seconds=seconds
        )
    return QueryResult(OK, columns, [[plain(v) for v in row] for row in rows], seconds=seconds)


def use_warehouse(spark: SparkSession) -> None:
    """Make `gold.daily_trips` resolve without the catalog name in front."""
    spark.catalog.setCurrentCatalog(CATALOG)


def replace_jvm(spark: SparkSession, build: Callable[[], SparkSession]) -> SparkSession:
    """Stop the session, kill the JVM behind it and build a new session in a new JVM."""
    gateway = SparkContext._gateway
    spark.stop()
    gateway.shutdown()
    gateway.proc.kill()
    gateway.proc.wait()
    SparkContext._gateway = None
    SparkContext._jvm = None
    fresh = build()
    use_warehouse(fresh)
    return fresh


class Warehouse:
    """The session the models' queries run in. It is replaced after every timeout.

    Cancelling a query does not stop its tasks when they are inside a long generated
    loop, such as a join with no condition. They run on and keep their task slots, and
    once the slots are gone every later query waits until it times out too. Killing the
    JVM is the only thing that ends them, so a timeout costs one new session.
    """

    def __init__(self, spark: SparkSession, build: Callable[[], SparkSession]):
        self.spark = spark
        self.restarts = 0
        self._build = build

    def execute(self, sql: str, time_limit: float = TIME_LIMIT_SECONDS) -> QueryResult:
        result = execute(self.spark, sql, time_limit=time_limit)
        if result.status == TIMEOUT:
            self.spark = replace_jvm(self.spark, self._build)
            self.restarts += 1
        return result
