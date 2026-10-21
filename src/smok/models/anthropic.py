import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

import httpx

from smok.images import Image
from smok.models.base import ModelError
from smok.models.profiles import ModelConfig
from smok.models.sse import stream_json
from smok.types import Event, Message, RuntimeHint, Text, ToolCall, ToolResult, ToolSpec


def serialize_messages(messages: list[Message], *, cache_last=False) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    cache_target, cache_open = None, True

    def add(block, *, transient=False):
        nonlocal cache_target, cache_open
        blocks.append(block)
        cache_open = cache_open and not transient
        if cache_open:
            cache_target = block

    for message in messages:
        blocks: list[dict[str, Any]] = []
        # Anthropic requires tool results before any text in a user message.
        for b in message.content:
            if isinstance(b, ToolResult):
                add(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.tool_call_id,
                        "content": b.content,
                        "is_error": b.is_error,
                    }
                )
        for b in message.content:
            if isinstance(b, Text) and b.text:
                add({"type": "text", "text": b.text}, transient=isinstance(b, RuntimeHint))
            elif isinstance(b, Image):
                add(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": b.media_type, "data": b.data},
                    }
                )
            elif isinstance(b, ToolCall):
                try:
                    args = json.loads(b.arguments)
                except json.JSONDecodeError:
                    args = {"_invalid_json": b.arguments}
                if not isinstance(args, dict):
                    args = {"_invalid_input": args}
                add({"type": "tool_use", "id": b.id, "name": b.name, "input": args})
        if blocks:
            if result and result[-1]["role"] == message.role:
                result[-1]["content"].extend(blocks)
            else:
                result.append({"role": message.role, "content": blocks})
    if cache_last and cache_target is not None:
        cache_target["cache_control"] = {"type": "ephemeral"}
    return result


class AnthropicAdapter:
    def __init__(self, config: ModelConfig, client: httpx.AsyncClient | None = None):
        self.config, self.client, self.name = config, client, config.name

    def payload(self, system, messages, tools):
        payload = {
            "model": self.config.model,
            "system": system,
            "messages": serialize_messages(messages, cache_last=self.config.prompt_cache),
        }
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        if self.config.prompt_cache:
            marker = {"type": "ephemeral"}
            if system:
                stable, separator, runtime = system.partition("\n\nRuntime context:\n")
                payload["system"] = [{"type": "text", "text": stable, "cache_control": marker}]
                if separator:
                    payload["system"].append({"type": "text", "text": separator + runtime})
            if tools:
                payload["tools"][-1]["cache_control"] = marker
        return payload

    async def count_input(self, system, messages, tools):
        headers = {"anthropic-version": "2023-06-01"}
        if key := self.config.api_key():
            headers["x-api-key"] = key

        async def request(client):
            response = await client.post(
                f"{self.config.base_url}/messages/count_tokens",
                headers=headers,
                json=self.payload(system, messages, tools),
                timeout=self.config.timeout_seconds,
            )
            if response.status_code != 200:
                raise ModelError(f"Token counting failed (HTTP {response.status_code}).")
            value = response.json().get("input_tokens")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ModelError("Invalid token-count response.")
            return value

        try:
            if self.client is not None:
                return await request(self.client)
            async with httpx.AsyncClient() as client:
                return await request(client)
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise ModelError("Token counting failed; no generation was sent.") from exc

    async def stream(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> AsyncIterator[Event]:
        key = self.config.api_key()
        headers = {"anthropic-version": "2023-06-01"}
        if key:
            headers["x-api-key"] = key
        payload = self.payload(system, messages, tools)
        payload.update(stream=True, max_tokens=self.config.max_output_tokens)
        calls: dict[int, dict[str, str]] = {}
        complete: set[int] = set()
        usage = {"input_tokens": 0, "output_tokens": 0}
        reason = ""
        done = False
        try:
            async with aclosing(
                stream_json(
                    f"{self.config.base_url}/messages",
                    headers,
                    payload,
                    timeout=self.config.timeout_seconds,
                    client=self.client,
                )
            ) as chunks:
                async for chunk in chunks:
                    if chunk is None:
                        continue
                    kind = chunk.get("type")
                    if kind == "error":
                        raise ModelError("Anthropic reported an error during streaming.")
                    if kind == "message_start":
                        usage.update(chunk.get("message", {}).get("usage", {}))
                    elif kind == "content_block_start":
                        block = chunk["content_block"]
                        if block["type"] == "tool_use":
                            calls[chunk["index"]] = {
                                "id": block["id"],
                                "name": block["name"],
                                "arguments": json.dumps(block["input"])
                                if block.get("input")
                                else "",
                            }
                        elif block["type"] == "text" and block.get("text"):
                            yield Event("text_delta", {"text": block["text"]})
                    elif kind == "content_block_delta":
                        delta = chunk["delta"]
                        if delta["type"] == "text_delta":
                            yield Event("text_delta", {"text": delta["text"]})
                        elif delta["type"] == "input_json_delta":
                            if chunk["index"] not in calls:
                                raise ModelError(
                                    "Tool input arrived without a matching tool block."
                                )
                            calls[chunk["index"]]["arguments"] += delta["partial_json"]
                    elif kind == "content_block_stop":
                        complete.add(chunk["index"])
                    elif kind == "message_delta":
                        reason = chunk.get("delta", {}).get("stop_reason") or reason
                        usage.update(chunk.get("usage", {}))
                    elif kind == "message_stop":
                        done = True
                        break
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise ModelError(
                "Provider sent an unexpected event shape; no tools were executed."
            ) from exc
        if not done or not reason or not calls.keys() <= complete:
            raise ModelError("Anthropic stream ended early; no tools were executed.")
        for index in sorted(calls):
            call = calls[index]
            call["arguments"] = call["arguments"] or "{}"
            yield Event("tool_call", call)
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            value = usage.get(field, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ModelError("Provider returned invalid usage counters.")
        usage["uncached_input_tokens"] = usage["input_tokens"]
        usage["input_tokens"] += usage.get("cache_creation_input_tokens", 0) + usage.get(
            "cache_read_input_tokens", 0
        )
        usage["source"] = "provider"
        yield Event("usage", usage)
        yield Event("stop", {"reason": reason})
