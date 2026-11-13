"""Lifecycle narratives: `narratives/index.yaml` and one `narratives/<id>.md` each.

A lifecycle is a business process that writes rows in the warehouse. Its narrative is
about a page of prose that says how, in the warehouse's own table and column names.
The files are written and frozen by the owner's side. This module only reads them.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

NARRATIVES_DIR = Path(__file__).resolve().parents[3] / "narratives"
INDEX_FILE = "index.yaml"
ID_FORMAT = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")


@dataclass(frozen=True)
class Lifecycle:
    id: str
    title: str
    one_line: str
    tables: list[str]
    narrative: str


def read_index(directory: Path | None = None) -> list[dict]:
    """The index as written: a list of lifecycles (a `lifecycles:` key around it is accepted)."""
    with open((directory or NARRATIVES_DIR) / INDEX_FILE) as source:
        content = yaml.safe_load(source) or []
    return content["lifecycles"] if isinstance(content, dict) else content


def read_texts(directory: Path | None = None) -> dict[str, str]:
    """Lifecycle id -> the text of its `.md` file, for every `.md` file in the folder."""
    folder = directory or NARRATIVES_DIR
    return {path.stem: path.read_text() for path in sorted(folder.glob("*.md"))}


def problems(index: list[dict], texts: dict[str, str], known_tables: list[str]) -> list[str]:
    """What keeps the index and the narrative files from fitting each other and the warehouse."""
    found, seen = [], set()
    for position, item in enumerate(index, start=1):
        name = item.get("id") or f"lifecycle {position}"
        if not item.get("id"):
            found.append(f"{name}: no id")
            continue
        if not ID_FORMAT.fullmatch(str(item["id"])):
            found.append(f"{name}: the id must be lower-case words joined by hyphens")
        if item["id"] in seen:
            found.append(f"{name}: the id is used twice")
        seen.add(item["id"])
        for required in ("title", "one_line"):
            text = str(item.get(required) or "").strip()
            if not text:
                found.append(f"{name}: `{required}` is missing or empty")
            elif "\n" in text:
                found.append(f"{name}: `{required}` must be one line")
        tables = item.get("tables")
        if not isinstance(tables, list) or not tables:
            found.append(f"{name}: `tables` must be a list with at least one table")
        else:
            for table in tables:
                if table not in known_tables:
                    found.append(f"{name}: table {table} is not a warehouse table")
        if not str(texts.get(item["id"]) or "").strip():
            found.append(f"{name}: narratives/{item['id']}.md is missing or empty")
    for stem in sorted(set(texts) - seen):
        found.append(f"{stem}: narratives/{stem}.md has no entry in the index")
    return found


def parse(index: list[dict], texts: dict[str, str]) -> list[Lifecycle]:
    return [
        Lifecycle(
            id=item["id"],
            title=" ".join(str(item["title"]).split()),
            one_line=" ".join(str(item["one_line"]).split()),
            tables=list(item["tables"]),
            narrative=texts[item["id"]].strip(),
        )
        for item in index
    ]


def load(directory: Path | None = None) -> list[Lifecycle]:
    return parse(read_index(directory), read_texts(directory))


def index_line(lifecycle: Lifecycle) -> str:
    """One line for the selector: the id, the title and the one-line description.

    The table list is left out. The selector chooses a process, not tables.
    """
    return f"- {lifecycle.id}: {lifecycle.title}. {lifecycle.one_line}"


def render_index(lifecycles: list[Lifecycle]) -> str:
    return "\n".join(index_line(lifecycle) for lifecycle in lifecycles) + "\n"


def render_all(lifecycles: list[Lifecycle]) -> str:
    """Every narrative, one after the other, for the arm that is given all of them."""
    return "\n\n".join(lifecycle.narrative for lifecycle in lifecycles) + "\n"
