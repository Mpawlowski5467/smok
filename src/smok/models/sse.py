"""Small SSE transport shared by both provider adapters."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from smok.models.base import ModelError


async def stream_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    timeout: float,  # noqa: ASYNC109 -- this configures httpx's per-read timeout
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[dict[str, Any] | None]:
    """Yield data objects, or None for [DONE]; do not expose request credentials."""
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10))
    try:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.is_error:
                # Error bodies can echo prompts or credentials; keep diagnostics neutral.
                raise ModelError(
                    f"Provider returned HTTP {response.status_code}. Check model and key."
                )
            lines: list[str] = []
            size = 0
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    value = line[5:].lstrip(" ")
                    size += len(value)
                    if size > 1_048_576:
                        raise ModelError("Provider sent an oversized streaming event.")
                    lines.append(value)
                elif line == "" and lines:
                    yield decode_event("\n".join(lines))
                    lines, size = [], 0
            if lines:
                yield decode_event("\n".join(lines))
    except httpx.TimeoutException as exc:
        raise ModelError(
            "Provider timed out. Check the server or increase timeout_seconds."
        ) from exc
    except httpx.HTTPError as exc:
        raise ModelError("Cannot reach the model endpoint. Check the server and base URL.") from exc
    finally:
        if owned:
            await client.aclose()


def decode_event(raw: str) -> dict[str, Any] | None:
    if raw == "[DONE]":
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelError("Provider sent invalid JSON in its stream.") from exc
    if not isinstance(data, dict):
        raise ModelError("Provider stream events must be JSON objects.")
    return data
