"""The owner's predictions: `selection/predictions.yaml`, committed before the run.

For every request and arm, the owner says whether the answer will match under the strict
rule. The file is the owner's. This module reads it, checks that it covers the run, and
compares it with what happened.

Format:

    predicted_on: 2026-11-13
    predictions:
      yellow-trips-one-day:
        full: match
        full_narratives: match
        staged: no_match
        staged_hand: {"llama3.2:3b": no_match, "qwen2.5:14b": match}

A value is `match` or `no_match`. A plain value is the prediction for every model. A
mapping gives one prediction per model, and must then name every model that is run.
"""

from pathlib import Path

import yaml

PREDICTIONS_PATH = Path(__file__).resolve().parents[3] / "selection" / "predictions.yaml"
MATCH, NO_MATCH = "match", "no_match"
OUTCOMES = (MATCH, NO_MATCH)


def read_raw(path: Path | None = None) -> dict:
    """The file's content, or an empty dict when the owner has not written it yet."""
    target = path or PREDICTIONS_PATH
    if not target.exists():
        return {}
    with open(target) as source:
        return yaml.safe_load(source) or {}


def predicted(raw: dict, request_id: str, arm: str, model: str) -> str | None:
    """The predicted outcome for one request, arm and model, or None if there is none."""
    value = ((raw.get("predictions") or {}).get(request_id) or {}).get(arm)
    if isinstance(value, dict):
        value = value.get(model)
    return value if value in OUTCOMES else None


def problems(raw: dict, request_ids: list[str], arms: list[str], models: list[str]) -> list[str]:
    """Why the predictions do not cover the run. Empty when every case has a valid one."""
    if not raw:
        return ["selection/predictions.yaml is missing or empty"]
    found = []
    if not raw.get("predicted_on"):
        found.append("`predicted_on` is missing")
    entries = raw.get("predictions") or {}
    for request_id in sorted(set(entries) - set(request_ids)):
        found.append(f"{request_id}: predicted, but there is no such request")
    for request_id in request_ids:
        for arm in arms:
            value = (entries.get(request_id) or {}).get(arm)
            if value is None:
                found.append(f"{request_id} / {arm}: no prediction")
            elif isinstance(value, dict):
                for model in models:
                    if value.get(model) not in OUTCOMES:
                        found.append(f"{request_id} / {arm} / {model}: no valid prediction")
            elif value not in OUTCOMES:
                found.append(f"{request_id} / {arm}: {value!r} is not `match` or `no_match`")
    return found


def observed(record: dict) -> str:
    """What happened, in the predictions' words. The strict match is the one predicted."""
    return MATCH if record["answer_matched"] else NO_MATCH


def compare(raw: dict, records: list[dict]) -> list[dict]:
    """One line per record that has a prediction: predicted, observed, and whether they agree."""
    lines = []
    for record in records:
        forecast = predicted(raw, record["request_id"], record["arm"], record["model"])
        if forecast is None:
            continue
        lines.append(
            {
                "model": record["model"],
                "arm": record["arm"],
                "request_id": record["request_id"],
                "held_out": record["held_out"],
                "predicted": forecast,
                "observed": observed(record),
                "agreed": forecast == observed(record),
            }
        )
    return lines
