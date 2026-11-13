"""Stage 1, the selector: the lifecycle index and a request in, one lifecycle id out.

It sees the index lines and the request, and nothing else: no narrative, no table list,
no column.
"""

import re
from dataclasses import dataclass

PREFIX = "LIFECYCLE:"

SYSTEM = (
    "You choose which process recorded in a data warehouse an analyst's request is about. "
    "You do not write SQL and you do not answer the request."
)

PROMPT = """These are the processes the warehouse records, one per line, as id: description.

{index}
Request: {request}

Choose the one process whose data is needed to answer the request.

Answer with exactly one line in this format and nothing else:
{prefix} id"""


@dataclass(frozen=True)
class Choice:
    lifecycle: str | None  # a known id, or None
    named: str | None  # what the model wrote on the line, when it is not a known id
    format_ok: bool  # the answer had a `LIFECYCLE:` line that names a known id


def build_prompt(index: str, request: str) -> str:
    return PROMPT.format(index=index, request=request.strip(), prefix=PREFIX)


def parse(answer: str, known: list[str]) -> Choice:
    """The model's answer -> the lifecycle it chose.

    Reads the first `LIFECYCLE:` line. Quotes and backticks are dropped. If that line is
    missing, or names no known id, and exactly one known id appears anywhere in the
    answer, that id is taken and `format_ok` is False. Otherwise there is no choice.
    """
    line = next(
        (
            ln.strip()[len(PREFIX) :]
            for ln in answer.splitlines()
            if ln.strip().upper().startswith(PREFIX)
        ),
        None,
    )
    named = None
    if line is not None:
        named = line.strip().strip("`'\"[]().").strip().lower()
        if named in known:
            return Choice(named, None, True)
    mentioned = [
        name for name in known if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", answer)
    ]
    return Choice(mentioned[0] if len(mentioned) == 1 else None, named or None, False)
