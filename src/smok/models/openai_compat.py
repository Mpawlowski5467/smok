import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any
from uuid import uuid4

import httpx

from smok.images import Image
from smok.models.base import ModelError
from smok.models.profiles import ModelConfig
from smok.models.sse import stream_json
from smok.types import Event, Message, Text, ToolCall, ToolResult, ToolSpec


def serialize_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        text = "\n".join(b.text for b in message.content if isinstance(b, Text))
        calls = [b for b in message.content if isinstance(b, ToolCall)]
        if message.role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                item["tool_calls"] = [
                    {
                        "id": b.id,
                        "type": "function",
                        "function": {"name": b.name, "arguments": b.arguments},
                    }
                    for b in calls
                ]
            result.append(item)
        else:
            for block in message.content:
                if isinstance(block, ToolResult):
                    result.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.tool_call_id,
                            "content": block.content,
                        }
                    )
            if any(isinstance(b, Image) for b in message.content):
                parts = []
                for b in message.content:
                    if isinstance(b, Text):
                        parts.append({"type": "text", "text": b.text})
                    elif isinstance(b, Image):
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{b.media_type};base64,{b.data}",
                                    "detail": "auto",
                                },
                            }
                        )
                result.append({"role": "user", "content": parts})
            elif text:
                result.append({"role": "user", "content": text})
    return result


class OpenAICompatibleAdapter:
    def __init__(self, config: ModelConfig, client: httpx.AsyncClient | None = None):
        self.config, self.client, self.name = config, client, config.name

    async def stream(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> AsyncIterator[Event]:
        key = self.config.api_key()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": serialize_messages(system, messages),
            "stream": True,
            "stream_options": {"include_usage": True},
            self.config.token_parameter: self.config.max_output_tokens,
        }
        for name in ("reasoning_effort", "temperature", "top_p"):
            value = getattr(self.config, name)
            if value is not None:
                payload[name] = value
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        calls: dict[int, dict[str, str]] = {}
        reason = ""
        done = False
        try:
            async with aclosing(
                stream_json(
                    f"{self.config.base_url}/chat/completions",
                    headers,
                    payload,
                    timeout=self.config.timeout_seconds,
                    client=self.client,
                )
            ) as chunks:
                async for chunk in chunks:
                    if chunk is None:
                        done = True
                        break
                    if "error" in chunk:
                        raise ModelError("Provider reported an error during streaming.")
                    if usage := chunk.get("usage"):
                        yield Event(
                            "usage",
                            {
                                "input_tokens": usage.get("prompt_tokens", 0),
                                "output_tokens": usage.get("completion_tokens", 0),
                                "cache_read_input_tokens": (
                                    usage.get("prompt_tokens_details") or {}
                                ).get("cached_tokens", 0),
                                "source": "provider",
                            },
                        )
                    for choice in chunk.get("choices", []):
                        if choice.get("index", 0) != 0:
                            continue
                        delta = choice.get("delta", {})
                        if text := delta.get("content"):
                            yield Event("text_delta", {"text": text})
                        for part in delta.get("tool_calls", []):
                            call = calls.setdefault(
                                part["index"], {"id": "", "name": "", "arguments": ""}
                            )
                            if part.get("id"):
                                call["id"] = part["id"]
                            function = part.get("function", {})
                            call["name"] += function.get("name") or ""
                            arguments = function.get("arguments") or ""
                            call["arguments"] += (
                                json.dumps(arguments) if isinstance(arguments, dict) else arguments
                            )
                        reason = choice.get("finish_reason") or reason
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise ModelError(
                "Provider sent an unexpected event shape; no tools were executed."
            ) from exc
        if not done or not reason:
            raise ModelError("Provider stream ended early; no tools were executed.")
        for index in sorted(calls):
            call = calls[index]
            call["id"] = call["id"] or f"call_{uuid4().hex}"
            yield Event("tool_call", call)
        yield Event("stop", {"reason": reason})
