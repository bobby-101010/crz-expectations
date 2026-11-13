"""A staged version of the selection harness: lifecycle narratives and fresh contexts.

Three model calls, each with a context of its own. A selector picks one lifecycle from
an index. An interpreter reads that lifecycle's narrative and writes a plan. A builder
writes SQL from the plan and the schema of the tables the plan names. Nothing passes
from one call to the next except the written hand-off.

`narratives` loads the lifecycle index and texts. `lifecycle_selector`, `interpreter`
and `plan_builder` hold one stage each: its prompt and its parser. `runner` runs the
four arms. `evaluate` scores them. `predictions` holds the owner's forecasts.
"""
