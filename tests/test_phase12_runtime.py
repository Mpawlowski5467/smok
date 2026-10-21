import asyncio
import json
from dataclasses import replace

import pytest
from test_loop import DONE, STOP, ScriptedModel, call

from smok.checkpoints import Checkpoints
from smok.context import SUMMARY_PROMPT, message_tokens
from smok.loop import Agent
from smok.models.anthropic import AnthropicAdapter, serialize_messages
from smok.models.base import ModelError
from smok.models.openai_compat import serialize_messages as openai_messages
from smok.models.profiles import resolve_model
from smok.permissions import allow
from smok.reliability import within_deadline
from smok.tools.files import Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, Message, RuntimeHint, Text, ToolCall, ToolResult, messages_to_data


@pytest.mark.parametrize("count_tokens", [False, True])
async def test_countdown_only_changes_request_tail_and_is_counted_once(tmp_path, count_tokens):
    class Recording(ScriptedModel):
        def __init__(self):
            super().__init__([DONE, DONE])
            self.config = replace(resolve_model("local/fixture"), count_tokens=count_tokens)
            self.systems, self.counts = [], []

        async def count_input(self, system, messages, tools):
            self.counts.append((system, messages))
            return 100

        async def stream(self, system, messages, tools):
            self.systems.append(system)
            async for event in super().stream(system, messages, tools):
                yield event

    model = Recording()
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    agent.context.map_text = "Stable repository context"
    agent.messages = [
        Message("user", [Text("Repair this module")]),
        Message("assistant", [ToolCall("read", "read_file", '{"path":"a.py"}')]),
        Message("user", [ToolResult("read", "Saved file content")]),
    ]
    before = messages_to_data(agent.messages)
    reports = []

    async def request():
        system = agent.context.system(agent.base_system(), [])
        async for event in agent._request(
            system, agent.messages, agent.tools.specs, report=agent.context_report()
        ):
            if event.type == "context_usage":
                reports.append(event.data)
            yield event

    for seconds in (30, 10):
        _ = [
            event
            async for event in within_deadline(
                request(), asyncio.get_running_loop().time() + seconds
            )
        ]
    assert model.systems[0] == model.systems[1]
    assert "TURN TIME BUDGET" not in model.systems[0]
    assert messages_to_data(agent.messages) == before
    assert "TURN TIME BUDGET" not in json.dumps(agent.state())
    assert model.histories[0][:-1] == model.histories[1][:-1] == agent.messages[:-1]
    assert model.histories[0][-1].content[:-1] == agent.messages[-1].content
    assert model.histories[1][-1].content[:-1] == agent.messages[-1].content
    first, second = [history[-1].content[-1] for history in model.histories]
    assert isinstance(first, RuntimeHint) and first != second
    assert "30 seconds" in first.text and "10 seconds" in second.text
    serialized = [
        openai_messages(system, messages)
        for system, messages in zip(model.systems, model.histories, strict=True)
    ]
    assert serialized[0][:-1] == serialized[1][:-1]
    assert serialized[0][-1] != serialized[1][-1]
    assert serialized[0][-2]["role"] == "tool" and serialized[0][-1]["role"] == "user"
    for report, history in zip(reports, model.histories, strict=True):
        breakdown = report["breakdown_estimated_tokens"]
        assert breakdown["time_budget"] == message_tokens(history) - message_tokens(agent.messages)
        if count_tokens:
            assert report["input_tokens"] == 100 and report["source"] == "provider_count"
        else:
            assert report["input_tokens"] == sum(breakdown.values()) + 32
    if count_tokens:
        assert model.counts == list(zip(model.systems, model.histories, strict=True))
    assert agent.turn_requests == agent.budget.requests == 2


@pytest.mark.parametrize("with_report", [False, True])
async def test_transient_countdown_cannot_bypass_context_limit(tmp_path, with_report):
    model = ScriptedModel([DONE])
    model.config = replace(resolve_model("local/fixture"), context_window=600, max_output_tokens=8)
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    messages = [Message("user", [Text("x" * 1400)])]

    async def request():
        report = (
            agent.context.report(model.config, "system", messages, [], []) if with_report else None
        )
        async for event in agent._request("system", messages, [], report=report):
            yield event

    _ = [event async for event in request()]
    with pytest.raises(ModelError, match="context limit"):
        _ = [
            event
            async for event in within_deadline(request(), asyncio.get_running_loop().time() + 30)
        ]
    assert len(model.histories) == agent.turn_requests == agent.budget.requests == 1


@pytest.mark.parametrize("cache", [False, True])
def test_anthropic_marks_stable_tool_result_before_merged_hint(cache):
    adapter = AnthropicAdapter(replace(resolve_model("anthropic/fixture"), prompt_cache=cache))
    messages = [
        Message("assistant", [ToolCall("read", "read_file", "{}")]),
        Message("user", [ToolResult("read", "unchanged content")]),
        Message("user", [RuntimeHint("TURN TIME BUDGET: 10 seconds")]),
    ]
    before = messages_to_data(messages)
    payload = adapter.payload("Stable system", messages, [])
    blocks = payload["messages"][-1]["content"]
    assert [b["type"] for b in blocks] == ["tool_result", "text"]
    assert ("cache_control" in blocks[0]) is cache
    assert "cache_control" not in blocks[1]
    assert messages_to_data(messages) == before


def test_only_typed_runtime_notes_stop_cache_boundaries():
    text = Text("TURN TIME BUDGET: user-supplied text")
    payload = serialize_messages([Message("user", [text])], cache_last=True)
    assert "cache_control" in payload[0]["content"][0]
    messages = [Message("user", [text, RuntimeHint("runtime"), Text("later text")])]
    blocks = serialize_messages(messages, cache_last=True)[0]["content"]
    assert "cache_control" in blocks[0]
    assert all("cache_control" not in b for b in blocks[1:])


async def test_compaction_keeps_its_machine_readable_request_without_task_hint(tmp_path):
    model = ScriptedModel([DONE])
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    messages = [Message("user", [Text('{"transcript": [], "current_todos": []}')])]
    _ = [
        event
        async for event in within_deadline(
            agent._request(SUMMARY_PROMPT, messages, [], purpose="compaction"),
            asyncio.get_running_loop().time() + 30,
        )
    ]
    assert model.histories == [messages]
    assert agent.turn_requests == agent.budget.requests == 1


@pytest.mark.parametrize("checkpoints", [False, True])
async def test_review_waits_for_related_edits_and_their_check(tmp_path, checkpoints):
    model = ScriptedModel(
        [
            [call("write_file", {"path": "a", "content": "first"}), STOP],
            [
                Event("text_delta", {"text": "Editing the second module"}),
                call("write_file", {"path": "b", "content": "second"}),
                STOP,
            ],
            [call("run_shell", {"command": "test -f a && test -f b"}), STOP],
            DONE,
        ]
    )
    agent = Agent(
        model,
        ToolRegistry(Workspace(tmp_path)),
        approver=allow,
        checkpoints=Checkpoints(tmp_path) if checkpoints else None,
    )
    events = [event async for event in agent.run("Repair both modules and check them")]
    assert events[-1].data["reason"] == "complete" and agent.turn_requests == 4
    assert any(e.type == "text_delta" and "second module" in e.data["text"] for e in events)
    for history in model.histories[1:3]:
        assert not any(
            isinstance(block, Text) and block.text.startswith("Review this diff")
            for message in history
            for block in message.content
        )
    review = model.histories[3][-1].content[0].text
    assert "+first" in review and "+second" in review and "Exit code: 0" in review
    review_index = next(i for i, e in enumerate(events) if e.type == "self_check_started")
    check_index = next(
        i for i, e in enumerate(events) if e.type == "tool_result" and e.data["name"] == "run_shell"
    )
    assert check_index < review_index
    assert sum(e.type == "self_check_started" for e in events) == 1


@pytest.mark.parametrize("iterations", [2, 3])
async def test_skipped_check_still_reviews_before_exposing_completion(tmp_path, iterations):
    model = ScriptedModel(
        [
            [call("write_file", {"path": "a", "content": "new"}), STOP],
            [Event("text_delta", {"text": "Unreviewed completion"}), STOP],
            [Event("text_delta", {"text": "Reviewed completion"}), STOP],
        ]
    )
    agent = Agent(
        model, ToolRegistry(Workspace(tmp_path)), approver=allow, max_iterations=iterations
    )
    events = [event async for event in agent.run("Implement")]
    text = "".join(e.data["text"] for e in events if e.type == "text_delta")
    assert "Unreviewed completion" not in text
    assert "Unreviewed completion" not in json.dumps(agent.state())
    assert ("Reviewed completion" in text) is (iterations == 3)
    assert events[-1].data["reason"] == ("complete" if iterations == 3 else "iteration_limit")
    assert agent.turn_requests == iterations
    assert sum(e.type == "self_check_started" for e in events) == 1
    assert "+new" in agent.messages[-(2 if iterations == 3 else 1)].content[0].text


async def test_no_check_tool_keeps_immediate_review(tmp_path):
    model = ScriptedModel([[call("write_file", {"path": "a", "content": "new"}), STOP], DONE])
    tools = ToolRegistry(Workspace(tmp_path))
    tools.allowed_tools = {"write_file"}
    agent = Agent(model, tools, approver=allow)
    events = [event async for event in agent.run("Implement")]
    assert events[-1].data == {"reason": "complete", "iterations": 2}
    assert model.histories[1][-1].content[0].text.startswith("Review this diff")
    assert sum(e.type == "self_check_started" for e in events) == 1
