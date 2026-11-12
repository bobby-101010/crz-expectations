"""The requests the harness is run on: `selection/requests.yaml`.

Each request has a plain-language question, a reference query, and `expected_tables`:
the tables the owner would hand an agent for it. That list is both the hand-picked arm
and the answer key for the selector, so it comes from the owner and is committed before
any model run. The harness refuses to run while any of them is empty.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

REQUESTS_PATH = Path(__file__).resolve().parents[3] / "selection" / "requests.yaml"


@dataclass(frozen=True)
class Request:
    id: str
    request: str
    reference_sql: str
    expected_tables: list[str]
    tolerance: float | None = None


def read_raw(path: Path | None = None) -> list[dict]:
    with open(path or REQUESTS_PATH) as source:
        return yaml.safe_load(source)["requests"]


def problems(raw: list[dict], known_tables: list[str]) -> list[str]:
    """What is wrong with the file. Empty `expected_tables` is not a problem here."""
    found, seen = [], set()
    for position, item in enumerate(raw, start=1):
        name = item.get("id") or f"request {position}"
        if not item.get("id"):
            found.append(f"{name}: no id")
        elif item["id"] in seen:
            found.append(f"{name}: the id is used twice")
        seen.add(item.get("id"))
        for required in ("request", "reference_sql"):
            if not str(item.get(required) or "").strip():
                found.append(f"{name}: `{required}` is missing or empty")
        expected = item.get("expected_tables")
        if not isinstance(expected, list):
            found.append(f"{name}: `expected_tables` must be a list")
            continue
        for table in expected:
            if table not in known_tables:
                found.append(f"{name}: expected table {table} is not a warehouse table")
    return found


def parse(raw: list[dict]) -> list[Request]:
    return [
        Request(
            id=item["id"],
            request=" ".join(item["request"].split()),
            reference_sql=item["reference_sql"].strip(),
            expected_tables=list(item.get("expected_tables") or []),
            tolerance=item.get("tolerance"),
        )
        for item in raw
    ]


def without_expected_tables(requests: list[Request]) -> list[str]:
    """Ids of the requests the owner has not picked tables for yet."""
    return [request.id for request in requests if not request.expected_tables]
