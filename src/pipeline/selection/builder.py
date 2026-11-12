"""The builder: a described schema and a request in, one SQL query out."""

import re

SYSTEM = (
    "You write one Spark SQL query that answers an analyst's request. "
    "You use only the tables and columns you are given."
)

PROMPT = """These are the tables you may use, with their columns:

{schema}
Request: {request}

Write one Spark SQL SELECT query that answers the request.
- Use only the tables and columns above, with the table names exactly as written.
- Return only the rows and columns the request asks for.
- Dates are written like DATE '2025-01-05'.

Answer with the query alone, inside one ```sql block."""

FENCE = re.compile(r"```(?:sql)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
STARTS = re.compile(r"\b(WITH|SELECT)\b", re.IGNORECASE)


def build_prompt(schema: str, request: str) -> str:
    return PROMPT.format(schema=schema, request=request.strip())


def extract_sql(answer: str) -> str | None:
    """The query in the model's answer, or None if it holds none.

    Takes the first fenced block. Without one, takes the text from the first SELECT or
    WITH. A trailing semicolon is dropped.
    """
    fenced = FENCE.search(answer)
    if fenced:
        text = fenced.group(1)
    else:
        start = STARTS.search(answer)
        if not start:
            return None
        text = answer[start.start() :].split("```")[0]
    text = text.strip().rstrip(";").strip()
    return text or None
