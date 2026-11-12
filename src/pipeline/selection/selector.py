"""The selector: the table index and a request in, a list of tables out.

The model answers with one plain line in a fixed format. Tool calling is not used,
because small models are unreliable at it.
"""

import re
from dataclasses import dataclass

PREFIX = "TABLES:"

SYSTEM = (
    "You choose which tables of a data warehouse an analyst needs to answer a request. "
    "You do not write SQL and you do not answer the request."
)

PROMPT = """These are all the tables in the warehouse, one per line:

{index}
Request: {request}

Choose every table that could be needed to answer the request. Include a table when in
doubt: leaving out a needed table is worse than including an extra one. Do not include
tables that are plainly unrelated.

Answer with exactly one line in this format and nothing else:
{prefix} schema.table, schema.table"""


@dataclass(frozen=True)
class Selection:
    tables: list[str]  # known tables, in the order the model gave them, no repeats
    unknown: list[str]  # names the model gave that are not tables
    format_ok: bool  # the answer had the `TABLES:` line


def build_prompt(index: str, request: str) -> str:
    return PROMPT.format(index=index, request=request.strip(), prefix=PREFIX)


def parse(answer: str, known: list[str]) -> Selection:
    """The model's answer -> the tables it chose.

    Reads the first `TABLES:` line. A `local.` prefix, quotes and backticks are dropped.
    With no such line, any known table named anywhere in the answer is taken, and
    `format_ok` is False.
    """
    line = next(
        (
            ln.strip()[len(PREFIX) :]
            for ln in answer.splitlines()
            if ln.strip().upper().startswith(PREFIX)
        ),
        None,
    )
    if line is None:
        mentioned = [name for name in known if re.search(rf"\b{re.escape(name)}\b", answer)]
        return Selection(mentioned, [], False)

    tables, unknown = [], []
    for part in re.split(r"[,;\s]+", line):
        name = part.strip("`'\"[]().").lower().removeprefix("local.")
        if not name:
            continue
        target = tables if name in known else unknown
        if name not in target:
            target.append(name)
    return Selection(tables, unknown, True)
