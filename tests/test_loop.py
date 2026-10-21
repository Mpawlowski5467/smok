import asyncio
import json

import pytest

from smok.loop import Agent
from smok.models.base import ModelError
from smok.permissions import allow
from smok.tools.files import Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, ToolResult


class ScriptedModel:
    name = "fixture/coder"

    def __init__(self, turns):
        self.turns = iter(turns)
        self.histories = []

    async def stream(self, system, messages, tools):
        self.histories.append(list(messages))
        for event in next(self.turns):
            if isinstance(event, Exception):
                raise event
            yield event


def call(name, arguments, id="c1"):
    return Event("tool_call", {"id": id, "name": name, "arguments": json.dumps(arguments)})


STOP = Event("stop", {"reason": "tool_calls"})
DONE = [Event("text_delta", {"text": "Done."}), Event("stop", {"reason": "stop"})]


def agent(tmp_path, turns, **kwargs):
    kwargs.setdefault("self_check", False)
    return Agent(ScriptedModel(turns), ToolRegistry(Workspace(tmp_path)), **kwargs)


async def test_read_write_shell_and_followup_share_one_loop(tmp_path):
    (tmp_path / "a.txt").write_text("old")
    model_agent = agent(
        tmp_path,
        [
            [call("read_file", {"path": "a.txt"}), STOP],
            [call("write_file", {"path": "a.txt", "content": "new"}), STOP],
            [call("run_shell", {"command": "cat a.txt"}), STOP],
            DONE,
        ],
        approver=allow,
    )
    events = [e async for e in model_agent.run("Update it")]
    assert (tmp_path / "a.txt").read_text() == "new"
    assert sum(e.type == "permission_requested" for e in events) == 2
    assert events[-1].data == {"reason": "complete", "iterations": 4}
    assert "new" in [e.data["content"] for e in events if e.type == "tool_result"][-1]
    assert model_agent.model.histories[-1][-1].content[0].tool_call_id == "c1"


async def test_denial_is_returned_to_model(tmp_path):
    model_agent = agent(
        tmp_path,
        [
            [call("write_file", {"path": "a", "content": "no"}), STOP],
            DONE,
        ],
    )
    events = [e async for e in model_agent.run("Try")]
    assert not (tmp_path / "a").exists()
    result = next(e for e in events if e.type == "tool_result")
    assert result.data["is_error"]
    assert "Permission denied" in result.data["content"]


async def test_disconnect_immediately_after_turn_start_releases_agent(tmp_path):
    model_agent = agent(tmp_path, [DONE])
    stream = model_agent.run("Hello")
    assert (await anext(stream)).type == "turn_started"
    await stream.aclose()
    assert not model_agent.running


async def test_disconnect_during_text_closes_model_stream(tmp_path):
    class Model:
        name = "fixture/stream"
        closed = False

        async def stream(self, *args):
            try:
                yield Event("text_delta", {"text": "Hi"})
                await asyncio.Event().wait()
            finally:
                self.closed = True

    model = Model()
    model_agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    stream = model_agent.run("Hello")
    while (await anext(stream)).type != "text_delta":
        pass
    await stream.aclose()
    assert model.closed
    assert not model_agent.running


async def test_malformed_call_can_recover(tmp_path):
    model_agent = agent(
        tmp_path,
        [
            [Event("tool_call", {"id": "bad", "name": "read_file", "arguments": "{"}), STOP],
            DONE,
        ],
    )
    events = [e async for e in model_agent.run("Read")]
    result = next(e for e in events if e.type == "tool_result")
    assert "Invalid tool JSON" in result.data["content"]
    assert events[-1].data["reason"] == "complete"


async def test_iteration_cap_stops_looping(tmp_path):
    model_agent = agent(tmp_path, [[call("list_dir", {}), STOP]] * 3, max_iterations=2)
    events = [e async for e in model_agent.run("Loop")]
    assert events[-1].data == {"reason": "iteration_limit", "iterations": 2}
    assert len(model_agent.model.histories) == 2


@pytest.mark.parametrize(
    "ending", [ModelError("disconnected"), Event("stop", {"reason": "length"})]
)
async def test_failed_or_truncated_generation_cannot_execute_tools(tmp_path, ending):
    model_agent = agent(
        tmp_path,
        [[call("write_file", {"path": "bad", "content": "no"}), ending]] * 2,
        approver=allow,
    )
    events = [e async for e in model_agent.run("Do something")]
    assert not (tmp_path / "bad").exists()
    assert not any(e.type == "permission_requested" for e in events)
    assert events[-1].data["reason"] == "error"


async def test_switch_model_keeps_provider_neutral_history(tmp_path):
    model_agent = agent(tmp_path, [[call("list_dir", {}), STOP], DONE])
    _ = [e async for e in model_agent.run("Look around")]
    replacement = ScriptedModel([DONE])
    model_agent.model = replacement
    _ = [e async for e in model_agent.run("Continue")]
    assert len(replacement.histories[0]) == 5
    assert isinstance(replacement.histories[0][2].content[0], ToolResult)
    model_agent.clear()
    assert not model_agent.messages


async def test_cancellation_during_approval_keeps_valid_history(tmp_path):
    waiting = asyncio.Event()

    async def approve(_):
        waiting.set()
        await asyncio.Event().wait()

    model_agent = agent(
        tmp_path,
        [
            [
                call("write_file", {"path": "a", "content": "a"}, "a"),
                call("write_file", {"path": "b", "content": "b"}, "b"),
                STOP,
            ]
        ],
        approver=approve,
    )

    async def consume():
        return [e async for e in model_agent.run("Two writes")]

    task = asyncio.create_task(consume())
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not model_agent.running
    assert all(isinstance(b, ToolResult) and b.is_error for b in model_agent.messages[-1].content)
    assert [b.tool_call_id for b in model_agent.messages[-1].content] == ["a", "b"]
    assert not (tmp_path / "a").exists()
