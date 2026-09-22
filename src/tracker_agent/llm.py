"""Single wrapper around the Anthropic SDK.

Every LLM call in this codebase must go through call_llm() so tokens,
latency, and cost are logged to run_log. Retries once on schema validation
failure, then raises for the caller to skip-and-log the row.
"""

from __future__ import annotations

import sqlite3
import time

import anthropic
from pydantic import BaseModel, ValidationError

from tracker_agent import state


class LlmOutputError(ValueError):
    """Raised when the model's output fails schema validation twice."""


def call_llm[T: BaseModel](
    *,
    client: anthropic.Anthropic,
    model: str,
    system: str,
    prompt: str,
    output_schema: type[T],
    command: str,
    conn: sqlite3.Connection,
    max_tokens: int = 1024,
) -> T:
    last_error: Exception | None = None

    for attempt in range(2):
        start = time.monotonic()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = (time.monotonic() - start) * 1000
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )

        try:
            parsed = output_schema.model_validate_json(text)
        except ValidationError as exc:
            last_error = exc
            state.log_run(
                conn,
                command=command,
                model=model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=latency_ms,
                status="validation_error" if attempt == 0 else "failed",
                detail=str(exc)[:500],
            )
            continue

        state.log_run(
            conn,
            command=command,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
            status="ok",
        )
        return parsed

    raise LlmOutputError(
        f"LLM output failed validation twice for command={command!r}"
    ) from last_error
