"""Stage 3, the builder: a plan and the schema of the plan's tables in, one SQL query out.

It sees the plan and the described schema of the tables the plan names, and nothing
else: no request, no narrative, no index. `full_narratives` is the one-call arm that is
given everything at once, for comparison.
"""

from pipeline.selection.builder import extract_sql

SYSTEM = (
    "You write one Spark SQL query that carries out a written plan. "
    "You use only the tables and columns you are given."
)

PROMPT = """These are the tables you may use, with their columns:

{schema}
This is the plan for the query:

{plan}

Write one Spark SQL SELECT query that carries out the plan.
- Use only the tables and columns above, with the table names exactly as written.
- Return only the rows and columns the plan asks for.
- Dates are written like DATE '2025-01-05'.

Answer with the query alone, inside one ```sql block."""

# The one-call arm with everything: the Phase 8 builder prompt with the narratives added.
FULL_NARRATIVES_PROMPT = """These are the tables you may use, with their columns:

{schema}
These describe how each process writes its rows in those tables:

{narratives}
Request: {request}

Write one Spark SQL SELECT query that answers the request.
- Use only the tables and columns above, with the table names exactly as written.
- Return only the rows and columns the request asks for.
- Dates are written like DATE '2025-01-05'.

Answer with the query alone, inside one ```sql block."""

__all__ = ["SYSTEM", "build_prompt", "build_full_narratives_prompt", "extract_sql"]


def build_prompt(schema: str, plan: str) -> str:
    return PROMPT.format(schema=schema, plan=plan.strip())


def build_full_narratives_prompt(schema: str, narratives: str, request: str) -> str:
    return FULL_NARRATIVES_PROMPT.format(
        schema=schema, narratives=narratives, request=request.strip()
    )
