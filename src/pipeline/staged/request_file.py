"""What the staged harness needs from `selection/requests.yaml`, beyond Phase 8's fields.

- `expected_lifecycle`: the owner's pick. The `staged_hand` arm uses it in place of the
  selector, and the selector is scored against it.
- `acceptable_table_sets`: a list of table lists. A plan is "answerable" if the tables it
  names include every table of at least one of them.
- `held_out: true`: the request was written after the narratives were frozen.

The requests themselves are written by other contexts. This module only reads them.
"""

from dataclasses import dataclass

from pipeline.selection import request_file
from pipeline.selection.request_file import Request


@dataclass(frozen=True)
class StagedRequest:
    base: Request
    expected_lifecycle: str | None
    acceptable_table_sets: list[list[str]]
    held_out: bool

    @property
    def id(self) -> str:
        return self.base.id

    @property
    def request(self) -> str:
        return self.base.request


def problems(raw: list[dict], known_tables: list[str], lifecycle_ids: list[str]) -> list[str]:
    """What is wrong with the file for a staged run. Missing owner's fields are problems here."""
    found = request_file.problems(raw, known_tables)
    for position, item in enumerate(raw, start=1):
        name = item.get("id") or f"request {position}"
        lifecycle = item.get("expected_lifecycle")
        if not lifecycle:
            found.append(f"{name}: `expected_lifecycle` is missing")
        elif lifecycle not in lifecycle_ids:
            found.append(f"{name}: expected lifecycle {lifecycle} is not in the narrative index")
        sets = item.get("acceptable_table_sets")
        if not isinstance(sets, list) or not sets:
            found.append(f"{name}: `acceptable_table_sets` is missing")
            continue
        for tables in sets:
            if not isinstance(tables, list) or not tables:
                found.append(f"{name}: every acceptable table set must be a list of tables")
                continue
            for table in tables:
                if table not in known_tables:
                    found.append(f"{name}: acceptable table {table} is not a warehouse table")
        if not isinstance(item.get("held_out", False), bool):
            found.append(f"{name}: `held_out` must be true or false")
    return found


def parse(raw: list[dict]) -> list[StagedRequest]:
    return [
        StagedRequest(
            base=base,
            expected_lifecycle=item.get("expected_lifecycle"),
            acceptable_table_sets=[
                list(tables) for tables in item.get("acceptable_table_sets") or []
            ],
            held_out=bool(item.get("held_out", False)),
        )
        for item, base in zip(raw, request_file.parse(raw), strict=True)
    ]
