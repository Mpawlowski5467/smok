import json
from pathlib import Path

import httpx
import pytest

from smok.models.anthropic import AnthropicAdapter
from smok.models.anthropic import serialize_messages as anthropic_messages
from smok.models.base import ModelError
from smok.models.openai_compat import OpenAICompatibleAdapter
from smok.models.openai_compat import serialize_messages as openai_messages
from smok.models.profiles import ModelConfig
from smok.tools.registry import SPECS
from smok.types import Message, Text, ToolCall, ToolResult

FIXTURES = Path(__file__).parent / "fixtures"


class FragmentedStream(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content

    async def __aiter__(self):
        for start in range(0, len(self.content), 7):
            yield self.content[start : start + 7]

    async def aclose(self):
        self.closed = True


def config(adapter="openai_compat"):
    return ModelConfig("test/coder", "coder", adapter, "http://model.test/v1", "SMOK_TEST_KEY")


@pytest.mark.parametrize(
    "family,cls",
    [
        ("openai", OpenAICompatibleAdapter),
        ("anthropic", AnthropicAdapter),
    ],
)
async def test_streaming_protocol(family, cls, monkeypatch):
    monkeypatch.setenv("SMOK_TEST_KEY", "test-only-secret")
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            stream=FragmentedStream((FIXTURES / f"{family}_tool.sse").read_bytes()),
            headers={"content-type": "text/event-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = cls(config(), client)
        events = [e async for e in adapter.stream("system", [Message("user", [Text("hi")])], SPECS)]
    assert events[0].data == {"text": "Inspecting. "}
    tool = next(e for e in events if e.type == "tool_call")
    assert tool.data == {
        "id": "call_read",
        "name": "read_file",
        "arguments": '{"path":"README.md"}',
    }
    usage = [e for e in events if e.type == "usage"]
    assert len(usage) == 1
    assert usage[0].data["input_tokens"] == 21
    assert usage[0].data["output_tokens"] == 9  # cumulative Anthropic counts must not be added
    assert events[-1].type == "stop"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "coder"
    assert len(payload["tools"]) == len(SPECS)
    if family == "openai":
        assert requests[0].url.path == "/v1/chat/completions"
        assert requests[0].headers["authorization"] == "Bearer test-only-secret"
    else:
        assert requests[0].url.path == "/v1/messages"
        assert requests[0].headers["x-api-key"] == "test-only-secret"
        assert payload["system"] == "system"


@pytest.mark.parametrize(
    "family,cls",
    [
        ("openai", OpenAICompatibleAdapter),
        ("anthropic", AnthropicAdapter),
    ],
)
async def test_truncated_stream_never_yields_a_tool(family, cls):
    raw = (FIXTURES / f"{family}_tool.sse").read_text()
    raw = raw[: raw.rfind("event: message_stop" if family == "anthropic" else "data: [DONE]")]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=raw))
    ) as client:
        yielded = []
        with pytest.raises(ModelError, match="ended early"):
            async for event in cls(config(), client).stream("s", [], []):
                yielded.append(event)
    assert not any(e.type == "tool_call" for e in yielded)


@pytest.mark.parametrize("cls", [OpenAICompatibleAdapter, AnthropicAdapter])
async def test_http_errors_do_not_leak_body(cls):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(401, text="private-key-or-prompt"))
    ) as client:
        with pytest.raises(ModelError, match="HTTP 401") as error:
            _ = [e async for e in cls(config(), client).stream("s", [], [])]
    assert "private-key" not in str(error.value)


@pytest.mark.parametrize(
    "raw", ["data: nope\n\n", "data: []\n\n", 'data: {"error":{"message":"private"}}\n\n']
)
async def test_invalid_provider_events(raw):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=raw))
    ) as client:
        with pytest.raises(ModelError):
            _ = [e async for e in OpenAICompatibleAdapter(config(), client).stream("s", [], [])]


def test_tool_history_can_switch_provider_families():
    messages = [
        Message("user", [Text("Read it")]),
        Message(
            "assistant",
            [
                Text("Checking"),
                ToolCall("a", "read_file", '{"path":"a.py"}'),
                ToolCall("b", "list_dir", "{}"),
            ],
        ),
        Message("user", [ToolResult("a", "hello"), ToolResult("b", "denied", True)]),
    ]
    compatible = openai_messages("s", messages)
    assert compatible[-2] == {"role": "tool", "tool_call_id": "a", "content": "hello"}
    assert len(compatible[2]["tool_calls"]) == 2
    anthropic = anthropic_messages(messages)
    assert anthropic[-1]["content"][1]["is_error"] is True
    assert anthropic[1]["content"][1]["input"] == {"path": "a.py"}


async def test_interleaved_parallel_call_fragments():
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "b",
                                "function": {"name": "list_dir", "arguments": "{"},
                            },
                            {
                                "index": 0,
                                "id": "a",
                                "function": {"name": "read_file", "arguments": '{"path":'},
                            },
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '"hi"}'}},
                            {"index": 1, "function": {"arguments": "}"}},
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    raw = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=raw))
    ) as client:
        events = [e async for e in OpenAICompatibleAdapter(config(), client).stream("s", [], [])]
    calls = [e.data for e in events if e.type == "tool_call"]
    assert [c["id"] for c in calls] == ["a", "b"]
    assert [json.loads(c["arguments"]) for c in calls] == [{"path": "hi"}, {}]


async def test_adapter_closes_transport_on_completion():
    transport_stream = FragmentedStream((FIXTURES / "openai_tool.sse").read_bytes())
    transport_stream.closed = False
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=transport_stream))
    ) as client:
        _ = [e async for e in OpenAICompatibleAdapter(config(), client).stream("s", [], [])]
        assert transport_stream.closed


@pytest.mark.parametrize(
    "raw",
    [
        'data: {"choices":[{"delta":{"tool_calls":[{}]}}]}\n\n',
        'data: {"choices":[{"delta":null}]}\n\n',
    ],
)
async def test_malformed_event_shapes_are_provider_errors(raw):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=raw))
    ) as client:
        with pytest.raises(ModelError, match="unexpected event shape"):
            _ = [e async for e in OpenAICompatibleAdapter(config(), client).stream("s", [], [])]
