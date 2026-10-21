import json
from dataclasses import replace

import pytest
from test_loop import DONE, STOP, ScriptedModel, call

from smok.cli import parser, run_cli
from smok.journal import Journal
from smok.loop import Agent
from smok.models.anthropic import serialize_messages as anthropic_messages
from smok.models.openai_compat import serialize_messages as openai_messages
from smok.models.profiles import resolve_model
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import (
    Event,
    Message,
    ToolCall,
    ToolResult,
    messages_from_data,
    messages_to_data,
)


def configured(turns, **overrides):
    model = ScriptedModel(turns)
    model.config = replace(resolve_model("ollama/fixture"), repo_map_tokens=0, **overrides)
    model.name = model.config.name
    return model


def create_agent(root, turns, journal=None, **kwargs):
    return Agent(
        configured(turns),
        ToolRegistry(Workspace(root)),
        journal=journal,
        self_check=False,
        **kwargs,
    )


async def test_resume_preserves_history_todos_pins_mode_and_usage_but_not_read_grants(tmp_path):
    (tmp_path / "a.py").write_text("old = 1\n")
    journal = Journal(tmp_path)
    first = create_agent(tmp_path, [[call("read_file", {"path": "a.py"}), STOP], DONE], journal)
    _ = [e async for e in first.run("Keep the API stable")]
    first.tools.todos = [{"id": "test", "text": "Verify unchanged API", "status": "pending"}]
    first.context.pin("a.py")
    first.set_mode("plan")
    first.save()
    journal.close()
    (tmp_path / "a.py").write_text("externally_changed = 2\n")
    resumed = Journal(tmp_path, resume=journal.id)
    second = create_agent(tmp_path, [DONE], resumed)
    second.restore(resumed.loaded)
    second.context.refresh_pins()
    assert second.tools.mode == "plan" and second.turns == 1
    assert second.tools.todos == first.tools.todos
    assert "externally_changed" in second.context.pins["a.py"]
    assert second.usage.requests == 2 and second.budget.usage.requests == 0
    assert not second.tools.workspace.read_hashes
    with pytest.raises(ToolError, match="Read the file"):
        second.tools.workspace.prepare_edit("a.py", "externally_changed", "new")
    assert anthropic_messages(second.messages)[2]["content"][0]["type"] == "tool_result"
    assert openai_messages("s", second.messages)[3]["role"] == "tool"
    _ = [e async for e in second.run("Continue investigating")]
    assert "Keep the API stable" in second.model.histories[0][0].content[0].text
    assert second.usage.requests == 3
    resumed.close()


async def test_interrupted_tool_boundary_resumes_without_replay_or_approval_grants(tmp_path):
    journal = Journal(tmp_path)
    first = create_agent(
        tmp_path, [[call("write_file", {"path": "new", "content": "x"}), STOP]], journal
    )
    stream = first.run("Write it")
    while (await anext(stream)).type != "permission_requested":
        pass
    await stream.aclose()
    journal.close()
    resumed = Journal(tmp_path, resume=journal.id)
    second = create_agent(tmp_path, [DONE], resumed)
    second.restore(resumed.loaded)
    assert isinstance(second.messages[-1].content[0], ToolResult)
    assert second.messages[-1].content[0].is_error
    assert "outcome may be unknown" in second.messages[-1].content[0].content
    _ = [e async for e in second.run("Explain status")]
    assert not (tmp_path / "new").exists()
    assert second.policy.mode == "ask"
    resumed.close()


def test_session_lock_and_crash_tail_repair(tmp_path):
    journal = Journal(tmp_path)
    journal.save(create_agent(tmp_path, []).state())
    with pytest.raises(ValueError, match="already open"):
        Journal(tmp_path, resume=journal.id)
    journal.close()
    with journal.path.open("ab") as stream:
        stream.write(b'{"type":"partial')
    resumed = Journal(tmp_path, resume=journal.id)
    resumed.close()
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert rows[-1]["type"] == "session_resumed"
    assert Journal.latest(tmp_path) == journal.id
    with journal.path.open("ab") as stream:
        stream.write(b"broken complete record\n")
    with pytest.raises(ValueError, match="damaged complete"):
        Journal(tmp_path, resume=journal.id)


def test_old_logs_foreign_workspace_and_redirected_session_are_not_resumed(tmp_path):
    journal = Journal(tmp_path)
    journal.close()
    with pytest.raises(ValueError, match="event-only"):
        Journal(tmp_path, resume=journal.id)
    assert not Journal.list(tmp_path)[0]["resumable"]
    header = json.loads(journal.path.read_text())
    header["data"]["workspace"] = "/unrelated"
    journal.path.write_text(json.dumps(header) + "\n")
    with pytest.raises(ValueError, match="different workspace"):
        Journal(tmp_path, resume=journal.id)
    assert Journal.list(tmp_path) == []
    journal.path.unlink()
    journal.path.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        Journal(tmp_path, resume=journal.id)


@pytest.mark.parametrize(
    "bad",
    [
        [Message("assistant", [ToolCall("a", "x", "{}")])],
        [Message("user", [ToolResult("a", "orphan")])],
        [
            Message("assistant", [ToolCall("a", "x", "{}"), ToolCall("b", "x", "{}")]),
            Message("user", [ToolResult("a", "partial")]),
            Message("user", [ToolResult("b", "late")]),
        ],
    ],
)
def test_invalid_saved_tool_groups_rejected(bad):
    with pytest.raises(ValueError):
        messages_from_data(messages_to_data(bad))


def test_invalid_saved_block_is_actionable():
    with pytest.raises(ValueError, match="block"):
        messages_from_data(
            [
                {
                    "role": "assistant",
                    "content": [{"type": "tool_call", "id": "a", "name": "x", "arguments": "{}"}],
                },
                {"role": "user", "content": [None]},
            ]
        )


async def test_cli_continue_and_handoff_create_distinct_histories(tmp_path, monkeypatch, capsys):
    created = []

    def adapter(config):
        model = configured([DONE])
        model.config, model.name = config, config.name
        created.append(model)
        return model

    monkeypatch.setattr("smok.cli.create_adapter", adapter)
    common = ["-C", str(tmp_path), "--no-checkpoints", "--no-self-check", "--json"]
    assert (
        await run_cli(parser().parse_args(common + ["--model", "ollama/fixture", "-p", "First"]))
        == 0
    )
    original_id = Journal.latest(tmp_path)
    assert await run_cli(parser().parse_args(common + ["--continue", "-p", "Second"])) == 0
    assert Journal.latest(tmp_path) == original_id
    assert len(created[1].histories[0]) == 3
    handoff = tmp_path / "summary.md"
    handoff.write_text("Finish the remaining API test. User constraint: no new dependencies.")
    assert (
        await run_cli(
            parser().parse_args(
                common + ["--model", "ollama/fixture", "--handoff", str(handoff), "-p", "Continue"]
            )
        )
        == 0
    )
    assert Journal.latest(tmp_path) != original_id
    assert len(created[2].histories[0]) == 2
    assert "no new dependencies" in created[2].histories[0][0].content[0].text
    assert "First" not in str(created[2].histories[0])
    assert await run_cli(parser().parse_args(common + ["--sessions"])) == 0
    assert len(created) == 3  # Listing sessions never invokes the model.
    assert '"resumable": true' in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        ["--continue", "--no-log", "-p", "x"],
        ["--compact"],
        ["--export-handoff"],
        ["--sessions", "-p", "x"],
        ["--budget-usd", "nan", "-p", "x"],
    ],
)
async def test_cli_invalid_session_actions_fail_without_creating_state(tmp_path, extra):
    with pytest.raises(ValueError):
        await run_cli(parser().parse_args(["-C", str(tmp_path), *extra]))
    assert not (tmp_path / ".smok").exists()


async def test_clear_preserves_ledger_and_turn_budget(tmp_path):
    from smok.usage import RunBudget

    agent = create_agent(tmp_path, [DONE], budget=RunBudget(max_turns=1))
    _ = [e async for e in agent.run("One")]
    agent.clear()
    assert not agent.messages and agent.usage.requests == 1
    events = [e async for e in agent.run("Two")]
    assert events[-1] == Event("turn_finished", {"reason": "budget_limit"})
    assert not agent.messages
