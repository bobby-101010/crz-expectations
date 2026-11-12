"""A small Ollama client on the standard library. No tool calling, no streaming.

From the container the host's Ollama is at `host.docker.internal:11434`.
"""

import json
import os
import urllib.request
from dataclasses import dataclass

DEFAULT_URL = "http://host.docker.internal:11434"
TIMEOUT_SECONDS = 600

# Fixed for every call and recorded with every result. Ollama's default context is
# small and it cuts a longer prompt without saying so, so the size is set here.
OPTIONS = {"temperature": 0, "seed": 0, "num_ctx": 16384}


@dataclass(frozen=True)
class Reply:
    text: str
    prompt_tokens: int | None
    output_tokens: int | None
    seconds: float | None


def base_url() -> str:
    return os.environ.get("OLLAMA_URL", DEFAULT_URL).rstrip("/")


def _call(path: str, payload: dict | None = None, timeout: float = TIMEOUT_SECONDS) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base_url() + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def generate_payload(model: str, system: str, prompt: str) -> dict:
    return {"model": model, "system": system, "prompt": prompt, "stream": False, "options": OPTIONS}


def parse_reply(body: dict) -> Reply:
    nanoseconds = body.get("total_duration")
    return Reply(
        text=body.get("response", ""),
        prompt_tokens=body.get("prompt_eval_count"),
        output_tokens=body.get("eval_count"),
        seconds=None if nanoseconds is None else nanoseconds / 1e9,
    )


def generate(model: str, system: str, prompt: str) -> Reply:
    """One completion at temperature 0."""
    return parse_reply(_call("/api/generate", generate_payload(model, system, prompt)))


def digest_of(models: list[dict], model: str) -> str:
    """The digest of a model in the body of /api/tags. Raises if it is not installed."""
    for entry in models:
        if model in (entry.get("name"), entry.get("model")):
            return entry["digest"]
    installed = sorted(entry.get("name", "?") for entry in models)
    raise LookupError(f"model {model} is not installed in Ollama; installed: {installed}")


def model_digest(model: str) -> str:
    """The digest of an installed model. This never downloads one."""
    return digest_of(_call("/api/tags", timeout=30)["models"], model)
