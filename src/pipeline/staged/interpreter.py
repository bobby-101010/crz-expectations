"""Stage 2, the interpreter: one lifecycle's narrative and a request in, a written plan out.

It sees that narrative and the request, and nothing else: no index, no other narrative,
no schema. It writes no SQL. The plan is the whole hand-off to the builder, which sees
neither the narrative nor the request.
"""

import re
from dataclasses import dataclass, field

PARTS = ("TABLES", "FILTERS", "MEASURE", "GRAIN", "DEFINITIONS")
MISSING = "(not given)"

SYSTEM = (
    "You turn an analyst's request into a short written plan for one query. "
    "You do not write SQL and you do not answer the request."
)

PROMPT = """This describes how one process writes its rows in a data warehouse:

{narrative}

Request: {request}

Write a plan that another person could turn into one SQL query without seeing the
description above or the request. Use the table and column names exactly as they are
written in the description. Do not write SQL.

Answer with exactly these five parts, each starting on its own line, and nothing else:
TABLES: the tables to read, as namespace.table, separated by commas
FILTERS: the rows to keep, with the column names and the values
MEASURE: what to compute, and from which columns
GRAIN: what one row of the answer is, and which rows to return
DEFINITIONS: any definition from the description that the plan relies on, or none"""

LABEL = re.compile(rf"^\s*[*#>\-\s]*({'|'.join(PARTS)})\s*\**\s*:\s*\**", re.IGNORECASE)


@dataclass(frozen=True)
class Plan:
    tables: list[str]  # known tables on the TABLES line, in order, no repeats
    unknown_tables: list[str]  # names on that line that are not tables
    parts: dict[str, str] = field(default_factory=dict)  # label -> text, as the model wrote it
    format_ok: bool = False  # all five parts were present and TABLES named a known table

    def text(self) -> str:
        """The hand-off: the five parts in a fixed order. This is all the builder is given."""
        return "\n".join(f"{label}: {self.parts.get(label) or MISSING}" for label in PARTS)


def build_prompt(narrative: str, request: str) -> str:
    return PROMPT.format(narrative=narrative.strip(), request=request.strip())


def parse(answer: str, known: list[str]) -> Plan:
    """The model's answer -> the plan.

    A part starts at a line that begins with its label and runs to the next label.
    Markdown marks around a label (`**TABLES:**`, `- TABLES:`) are ignored. Text
    before the first label is dropped. A part given twice keeps its first text. A missing
    part is rendered as `(not given)` in the hand-off, and `format_ok` is False.
    """
    parts: dict[str, list[str]] = {}
    current = None
    for line in answer.splitlines():
        found = LABEL.match(line)
        if found:
            label = found.group(1).upper()
            current = label if label not in parts else None
            if current:
                parts[current] = [line[found.end() :].strip()]
        elif current:
            parts[current].append(line.strip())
    texts = {label: " ".join(" ".join(lines).split()) for label, lines in parts.items()}
    texts = {label: text for label, text in texts.items() if text}

    tables, unknown = [], []
    for piece in re.split(r"[,;\s]+", texts.get("TABLES", "")):
        name = piece.strip("`'\"[]().").lower().removeprefix("local.")
        if not name:
            continue
        target = tables if name in known else unknown
        if name not in target:
            target.append(name)
    complete = all(label in texts for label in PARTS)
    return Plan(tables, unknown, texts, complete and bool(tables))
