import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_loop import DONE, STOP, call
from test_phase3_sessions import configured

from smok.context import COMPACTION_NOTICE, SUMMARY_PREFIX, SUMMARY_PROMPT, Context, groups
from smok.journal import Journal
from smok.loop import Agent
from smok.models.base import ModelError
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, Message, Text, ToolCall, ToolResult
from smok.usage import RunBudget

SUMMARY = {
    "goal": "Repair the API",
    "files_touched": ["api.py"],
    "decisions": ["Keep all existing public names"],
    "open_todos": ["Run tests"],
    "notes": ["No tests have run yet"],
}
SUMMARIZED = [
    Event("text_delta", {"text": json.dumps(SUMMARY)}),
    Event("usage", {"input_tokens": 700, "output_tokens": 80}),
    Event("stop", {"reason": "stop"}),
]


def agent_with_history(tmp_path, responses, **config):
    agent = Agent(
        configured(responses, **config), ToolRegistry(Workspace(tmp_path)), self_check=False
    )
    agent.messages = [
        Message("user", [Text("Repair the API. Keep all existing public names. " + "old " * 1200)]),
        Message("assistant", [ToolCall("read", "read_file", '{"path":"api.py"}')]),
        Message("user", [ToolResult("read", "older implementation " * 300)]),
        Message("assistant", [Text("Investigated. " * 100)]),
        Message("user", [Text("Continue with tests")]),
    ]
    return agent


async def test_compaction_retains_complete_recent_groups_and_constraints(tmp_path):
    agent = agent_with_history(tmp_path, [SUMMARIZED], keep_recent=2)
    (tmp_path / "api.py").write_text("api = 1")
    agent.tools.workspace.read_file("api.py")
    tail = agent.messages[-2:]
    events = [e async for e in agent.compact()]
    assert events[-1].type == "compaction_finished"
    assert agent.messages[1:-1] == tail
    assert agent.messages[-1] == Message("user", [Text(COMPACTION_NOTICE)])
    assert "Keep all existing public names" in agent.messages[0].content[0].text
    transcript = json.loads(agent.model.histories[0][0].content[0].text)["transcript"]
    assert transcript[-2]["content"][0]["type"] == "tool_call"
    assert transcript[-1]["content"][0]["type"] == "tool_result"
    assert not agent.tools.workspace.read_hashes
    with pytest.raises(ToolError, match="read_file"):
        agent.tools.workspace.prepare_edit("api.py", "1", "2")
    assert agent.usage.requests == agent.budget.usage.requests == 1
    assert agent.usage.input_tokens == 700


@pytest.mark.parametrize(
    "response",
    [
        [Event("text_delta", {"text": "invalid json"}), Event("stop", {"reason": "stop"})],
        [call("write_file", {"path": "bad", "content": "x"}), STOP],
        [Event("text_delta", {"text": json.dumps(SUMMARY)}), Event("stop", {"reason": "length"})],
        [ModelError("disconnected")],
    ],
)
async def test_bad_compaction_keeps_original_history_and_runs_no_tools(tmp_path, response):
    agent = agent_with_history(tmp_path, [response], keep_recent=2)
    (tmp_path / "api.py").write_text("api = 1")
    agent.tools.workspace.read_file("api.py")
    reads = dict(agent.tools.workspace.read_hashes)
    before = list(agent.messages)
    with pytest.raises(ModelError):
        _ = [e async for e in agent.compact()]
    assert agent.messages == before
    assert agent.tools.workspace.read_hashes == reads
    assert not (tmp_path / "bad").exists()
    assert agent.usage.requests == 1


async def test_automatic_compaction_then_continuation_within_call_cap(tmp_path):
    agent = agent_with_history(
        tmp_path, [SUMMARIZED, DONE], keep_recent=2, context_window=8000, max_output_tokens=512
    )
    events = [e async for e in agent.run("Finish the requested repair")]
    assert any(e.type == "compaction_finished" for e in events)
    assert events[-1].data == {"reason": "complete", "iterations": 2}
    assert agent.model.histories[-1][0].content[0].text.startswith(SUMMARY_PREFIX)


async def test_summary_alone_is_not_recompacted_above_soft_limit(tmp_path):
    agent = agent_with_history(tmp_path, [DONE], keep_recent=2)
    agent.messages = [
        Message("user", [Text(SUMMARY_PREFIX + json.dumps(SUMMARY))]),
        Message("assistant", [Text("Ready")]),
    ]
    used = agent.context_report()["input_tokens"]
    agent.model.config = replace(
        agent.config, context_window=used + 800, max_output_tokens=512, compact_at=0.5
    )
    events = [e async for e in agent.run("Continue")]
    assert events[-1].data["reason"] == "complete"
    assert not any(e.type == "compaction_started" for e in events)
    assert agent.usage.requests == 1


async def test_oversized_recent_input_is_rejected_before_generation(tmp_path):
    agent = agent_with_history(tmp_path, [], context_window=4000, max_output_tokens=512)
    agent.messages = []
    events = [e async for e in agent.run("x" * 24000)]
    assert events[-1].data["reason"] == "error"
    assert "context limit" in next(e.data["message"] for e in events if e.type == "error")
    assert agent.model.histories == []


async def test_compaction_respects_token_budget_before_request(tmp_path):
    agent = agent_with_history(tmp_path, [], keep_recent=2)
    agent.budget = RunBudget(tokens=50)
    with pytest.raises(Exception, match="Token budget"):
        _ = [e async for e in agent.compact()]
    assert not agent.model.histories


def test_pins_refresh_and_group_drop_never_leaves_orphan_tools(tmp_path):
    file = tmp_path / "api.py"
    file.write_text("old = 1")
    context = Context(Workspace(tmp_path))
    context.pin("api.py")
    file.write_text("new = 2")
    context.refresh_pins()
    assert context.pins["api.py"] == "new = 2"
    messages = [
        Message("assistant", [ToolCall("a", "read_file", "{}")]),
        Message("user", [ToolResult("a", "old = 1")]),
        Message("user", [Text("Next")]),
    ]
    context.drop("group:1", messages)
    assert len(groups(messages)) == 1 and messages[0].content[0].text == "Next"
    file.unlink()
    context.refresh_pins()
    assert "unavailable" in context.pins["api.py"]
    context.drop("api.py", messages)
    with pytest.raises(ToolError):
        context.pin("../outside")


async def test_handoff_exports_editable_summary_without_mutating_history(tmp_path):
    agent = agent_with_history(tmp_path, [SUMMARIZED])
    before = list(agent.messages)
    events = [e async for e in agent.handoff()]
    path = Path(events[-1].data["path"])
    assert json.loads(await asyncio.to_thread(path.read_text)) == SUMMARY
    assert (await asyncio.to_thread(path.stat)).st_mode & 0o777 == 0o600
    assert agent.messages == before and agent.usage.requests == 1
    assert next(e for e in events if e.type == "model_started").data["purpose"] == "handoff"


async def test_handoff_folds_long_history_without_dropping_suffix(tmp_path):
    agent = agent_with_history(
        tmp_path, [SUMMARIZED] * 5, context_window=4000, max_output_tokens=512
    )
    agent.messages = [Message("user", [Text(f"part-{i}: " + "details " * 700)]) for i in range(4)]
    before = list(agent.messages)
    events = [e async for e in agent.handoff()]
    assert events[-1].type == "handoff_created"
    assert agent.usage.requests > 1 and agent.messages == before
    assert "part-3" in str(agent.model.histories[-1])


async def test_manual_compaction_excludes_overlapping_turns_and_releases_on_cancel(tmp_path):
    agent = agent_with_history(tmp_path, [SUMMARIZED], keep_recent=2)
    stream = agent.compact()
    assert (await anext(stream)).type == "compaction_started"
    with pytest.raises(RuntimeError, match="running turn"):
        _ = [e async for e in agent.run("Overlapping")]
    with pytest.raises(RuntimeError, match="between turns"):
        agent.set_mode("plan")
    await stream.aclose()
    assert not agent.running and not agent.model.histories


async def test_twenty_turns_survive_repeated_compaction_and_resume(tmp_path):
    calls = {"compaction": 0, "task": 0}

    class LongSessionModel:
        config = configured([], context_window=7000, max_output_tokens=512, keep_recent=2).config
        name = config.name

        async def stream(self, system, messages, tools):
            if system == SUMMARY_PROMPT:
                calls["compaction"] += 1
                text = json.dumps(SUMMARY)
            else:
                calls["task"] += 1
                assert "Keep all existing public names" in str(messages)
                text = "Inspection observations for future reference. " * 70
            yield Event("text_delta", {"text": text})
            yield Event("usage", {"input_tokens": 1000, "output_tokens": 100})
            yield Event("stop", {"reason": "stop"})

    journal = Journal(tmp_path)
    agent = Agent(
        LongSessionModel(), ToolRegistry(Workspace(tmp_path)), journal=journal, self_check=False
    )
    for i in range(20):
        prompt = "Keep all existing public names. Repair the API." if i == 0 else f"Continue {i}"
        events = [e async for e in agent.run(prompt)]
        assert events[-1].data["reason"] == "complete"
        if (i + 1) % 5 == 0:
            identifier = journal.id
            journal.close()
            journal = Journal(tmp_path, resume=identifier)
            agent = Agent(
                LongSessionModel(),
                ToolRegistry(Workspace(tmp_path)),
                journal=journal,
                self_check=False,
            )
            agent.restore(journal.loaded)
    assert agent.turns == 20 and calls["task"] == 20 and calls["compaction"] >= 4
    assert agent.usage.requests == sum(calls.values())
    assert agent.context_report()["fraction_with_output"] < 1
    journal.close()
