import asyncio
from contextlib import aclosing

import pytest
from fastapi.testclient import TestClient
from test_gui import ORIGIN, login, setup, wait_for
from test_loop import DONE, STOP, ScriptedModel, call

from smok.checkpoints import Checkpoints
from smok.cli import parser, run_cli
from smok.journal import Journal
from smok.loop import Agent
from smok.permissions import allow
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, messages_from_data


async def test_followup_edits_use_known_written_bytes_without_an_extra_read(tmp_path):
    (tmp_path / "a.py").write_text("value = 0\n")
    model = ScriptedModel(
        [
            [call("read_file", {"path": "a.py"}), STOP],
            [call("edit_file", {"path": "a.py", "old_text": "0", "new_text": "1"}), STOP],
            [call("write_file", {"path": "a.py", "content": "value = 2\n"}), STOP],
            DONE,
            DONE,
        ]
    )
    agent = Agent(
        model, ToolRegistry(Workspace(tmp_path)), approver=allow, checkpoints=Checkpoints(tmp_path)
    )
    events = [e async for e in agent.run("Repair and review")]
    assert events[-1].data["reason"] == "complete" and agent.usage.requests == 5
    assert (tmp_path / "a.py").read_text() == "value = 2\n"
    assert not any(e.data.get("is_error") for e in events)
    assert sum(e.type == "permission_requested" for e in events) == 2
    assert sum(e.type == "self_check_started" for e in events) == 1
    await agent.undo()
    assert (tmp_path / "a.py").read_text() == "value = 0\n"


def test_known_write_does_not_authorize_unobserved_or_concurrently_changed_files(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.apply_write(workspace.prepare_write("a", "first"))
    pending = workspace.prepare_write("a", "second")
    (tmp_path / "a").write_text("external")
    with pytest.raises(ToolError, match="while waiting"):
        workspace.apply_write(pending)
    with pytest.raises(ToolError, match="Read the file"):
        workspace.prepare_write("a", "third")
    (tmp_path / "b").write_text("unobserved")
    with pytest.raises(ToolError, match="Read the file"):
        workspace.prepare_write("b", "overwrite")
    assert (tmp_path / "a").read_text() == "external"
    assert (tmp_path / "b").read_text() == "unobserved"


@pytest.mark.parametrize("reset", ["clear", "restore"])
def test_context_reset_invalidates_known_writes(tmp_path, reset):
    agent = Agent(ScriptedModel([]), ToolRegistry(Workspace(tmp_path)))
    workspace = agent.tools.workspace
    workspace.apply_write(workspace.prepare_write("a", "known"))
    if reset == "clear":
        agent.clear()
    else:
        agent.restore(agent.state())
    with pytest.raises(ToolError, match="Read the file"):
        workspace.prepare_write("a", "replacement")


@pytest.mark.parametrize("checkpoints", [False, True])
async def test_review_precedes_the_first_final_response(tmp_path, checkpoints):
    model = ScriptedModel([[call("write_file", {"path": "a", "content": "new"}), STOP], DONE, DONE])
    agent = Agent(
        model,
        ToolRegistry(Workspace(tmp_path)),
        approver=allow,
        checkpoints=Checkpoints(tmp_path) if checkpoints else None,
    )
    events = [e async for e in agent.run("Implement")]
    assert events[-1].data["reason"] == "complete"
    assert agent.usage.requests == 3
    assert sum(e.type == "self_check_started" for e in events) == 1
    assert next(i for i, e in enumerate(events) if e.type == "self_check_started") < next(
        i for i, e in enumerate(events) if e.type == "text_delta"
    )
    assert "+new" in model.histories[-1][-1].content[0].text
    messages_from_data(agent.state()["messages"])


async def test_review_detects_changes_during_a_model_response(tmp_path):
    class Changed(ScriptedModel):
        async def stream(self, *args):
            if len(self.histories) == 1:
                (tmp_path / "a").write_text("changed while responding")
            async for event in super().stream(*args):
                yield event

    model = Changed([[call("write_file", {"path": "a", "content": "new"}), STOP], DONE, DONE])
    agent = Agent(
        model, ToolRegistry(Workspace(tmp_path)), approver=allow, checkpoints=Checkpoints(tmp_path)
    )
    events = [e async for e in agent.run("Implement")]
    assert events[-1].data["reason"] == "complete"
    assert sum(e.type == "self_check_started" for e in events) == 1
    assert "+changed while responding" in model.histories[-1][-1].content[0].text


async def test_denied_command_is_not_requested_twice_and_resets_next_turn(tmp_path):
    requests = []

    async def approve(request):
        requests.append(request)
        return False

    command = "printf denied > should-not-exist"
    model = ScriptedModel(
        [
            [call("run_shell", {"command": command, "timeout_seconds": 1}), STOP],
            [call("run_shell", {"command": command, "timeout_seconds": 30}), STOP],
            DONE,
            [call("run_shell", {"command": command}), STOP],
            DONE,
        ]
    )
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), approver=approve)
    events = [e async for e in agent.run("Try the command")]
    assert len(requests) == 1
    assert sum(e.type == "permission_requested" for e in events) == 1
    resolutions = [e.data for e in events if e.type == "permission_resolved"]
    assert len(resolutions) == 2 and not any(e["approved"] for e in resolutions)
    assert resolutions[-1]["source"] == "denied earlier in this turn"
    assert not (tmp_path / "should-not-exist").exists()
    _ = [e async for e in agent.run("Reconsider this command")]
    assert len(requests) == 2


async def test_denied_write_cannot_be_retried_via_exact_edit_or_policy_change(tmp_path):
    (tmp_path / "a").write_text("before")
    requests = []

    async def approve(request):
        requests.append(request)
        agent.policy.mode = "full-auto"
        return False

    model = ScriptedModel(
        [
            [call("read_file", {"path": "a"}), STOP],
            [call("write_file", {"path": "a", "content": "after"}), STOP],
            [call("edit_file", {"path": "a", "old_text": "before", "new_text": "after"}), STOP],
            DONE,
        ]
    )
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), approver=approve)
    events = [e async for e in agent.run("Edit")]
    assert len(requests) == 1
    assert (tmp_path / "a").read_text() == "before"
    assert len([e for e in events if e.type == "tool_result" and e.data["is_error"]]) == 2


async def test_different_action_remains_reviewable_after_denial(tmp_path):
    requests = []

    async def approve(request):
        requests.append(request)
        return len(requests) == 2

    model = ScriptedModel(
        [
            [call("write_file", {"path": "a", "content": "first"}), STOP],
            [call("write_file", {"path": "a", "content": "revised"}), STOP],
            DONE,
            DONE,
        ]
    )
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), approver=approve)
    _ = [e async for e in agent.run("Create")]
    assert len(requests) == 2 and (tmp_path / "a").read_text() == "revised"


async def test_deadline_retains_edits_usage_valid_history_and_undo(tmp_path):
    class Hanging:
        name = "fixture/hanging"
        calls = 0
        closed = False

        async def stream(self, *args):
            self.calls += 1
            if self.calls == 1:
                yield call("write_file", {"path": "a", "content": "saved work"})
                yield Event("usage", {"input_tokens": 10, "output_tokens": 4})
                yield STOP
            else:
                try:
                    yield Event("text_delta", {"text": "Reviewing"})
                    await asyncio.Event().wait()
                finally:
                    self.closed = True

    journal = Journal(tmp_path)
    model = Hanging()
    agent = Agent(
        model,
        ToolRegistry(Workspace(tmp_path)),
        approver=allow,
        checkpoints=Checkpoints(tmp_path),
        journal=journal,
        turn_timeout=0.5,
    )
    try:
        events = [e async for e in agent.run("Create and check")]
        assert events[-1].data["reason"] == "time_limit"
        assert sum(e.type == "turn_finished" for e in events) == 1
        assert model.closed and not agent.running and agent.checkpoints.lock is None
        assert (tmp_path / "a").read_text() == "saved work"
        assert agent.usage.requests == agent.budget.usage.requests == 2
        assert agent.usage.estimated_requests == 1
        messages_from_data(agent.state()["messages"])
        assert "Work may be incomplete" in agent.messages[-1].content[0].text
        await agent.undo()
        assert not (tmp_path / "a").exists()
    finally:
        journal.close()


async def test_deadline_during_approval_never_grants_pending_batch(tmp_path):
    async def approve(_):
        await asyncio.Event().wait()

    model = ScriptedModel(
        [
            [
                call("write_file", {"path": "a", "content": "no"}, "a"),
                call("write_file", {"path": "b", "content": "no"}, "b"),
                STOP,
            ]
        ]
    )
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), approver=approve, turn_timeout=0.1)
    events = [e async for e in agent.run("Two writes")]
    assert events[-1].data["reason"] == "time_limit"
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()
    assert not any(e.type == "permission_resolved" for e in events)
    messages_from_data(agent.state()["messages"])


async def test_slow_event_consumer_is_not_cancelled_and_can_continue(tmp_path):
    agent = Agent(ScriptedModel([DONE]), ToolRegistry(Workspace(tmp_path)), turn_timeout=0.01)
    async with aclosing(agent.run("Hello")) as events:
        assert (await anext(events)).type == "turn_started"
        await asyncio.sleep(0.03)
        rest = [e async for e in events]
    assert rest[-1].data["reason"] == "time_limit" and not agent.running
    agent.turn_timeout = None
    events = [e async for e in agent.run("Continue")]
    assert events[-1].data["reason"] == "complete"


async def test_complete_outcome_is_not_replaced_after_client_delay(tmp_path):
    agent = Agent(ScriptedModel([DONE]), ToolRegistry(Workspace(tmp_path)), turn_timeout=0.1)
    async with aclosing(agent.run("Hello")) as events:
        async for event in events:
            if event.type == "turn_finished":
                assert event.data["reason"] == "complete"
                await asyncio.sleep(0.15)
                with pytest.raises(StopAsyncIteration):
                    await anext(events)
    assert not agent.running


@pytest.mark.parametrize("value", [True, 0, -1, float("inf"), float("nan"), "5", 86401])
def test_invalid_deadline_rejected(tmp_path, value):
    with pytest.raises(ValueError, match="Turn timeout"):
        Agent(ScriptedModel([]), ToolRegistry(Workspace(tmp_path)), turn_timeout=value)


def test_deadline_restores_and_old_sessions_still_load(tmp_path):
    agent = Agent(ScriptedModel([]), ToolRegistry(Workspace(tmp_path)), turn_timeout=30)
    saved = agent.state()
    agent.turn_timeout = None
    agent.restore(saved)
    assert agent.turn_timeout == 30
    saved.pop("turn_timeout")
    agent.restore(saved)
    assert agent.turn_timeout is None


def test_gui_deadline_applies_to_routed_turn_and_closes_pending_approval(tmp_path):
    (tmp_path / "hello.py").write_text("before")
    service, app = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        login(client)
        view = client.post("/api/sessions", json={}).json()
        identifier = view["id"]
        path = f"/api/sessions/{identifier}"
        response = client.patch(path, json={"turn_timeout": 1})
        assert response.status_code == 200
        assert response.json()["state"]["turn_timeout"] == 1
        assert client.patch(path, json={"turn_timeout": 0}).status_code == 422
        assert (
            client.post(
                path + "/actions", json={"action": "prompt", "data": {"prompt": "edit"}}
            ).status_code
            == 202
        )
        view = wait_for(client, identifier, lambda v: not v["busy"])
        assert not view["pending"]
        finishes = [e for e in view["events"] if e["type"] == "turn_finished"]
        assert len(finishes) == 1 and finishes[0]["data"]["reason"] == "time_limit"
        assert (tmp_path / "hello.py").read_text() == "before"
        assert not service.sessions[identifier].team.driving
        assert service.sessions[identifier].agent.checkpoints.lock is None
        response = client.patch(path, json={"turn_timeout": None})
        assert response.json()["state"]["turn_timeout"] is None


async def test_cli_deadline_returns_failure_and_can_clear_saved_limit(
    tmp_path, monkeypatch, capsys
):
    class Hanging:
        def __init__(self, config):
            self.name, self.config = config.name, config

        async def stream(self, *args):
            yield Event("text_delta", {"text": "Working"})
            await asyncio.Event().wait()

    monkeypatch.setattr("smok.cli.create_adapter", Hanging)
    args = parser().parse_args(
        [
            "-C",
            str(tmp_path),
            "--model",
            "local/test",
            "--no-input",
            "--turn-timeout",
            "0.1",
            "-p",
            "Wait",
        ]
    )
    assert await run_cli(args) == 2
    output = capsys.readouterr().out
    assert '"reason": "time_limit"' in output

    class Complete(Hanging):
        async def stream(self, *args):
            for event in DONE:
                yield event

    monkeypatch.setattr("smok.cli.create_adapter", Complete)
    args = parser().parse_args(
        [
            "-C",
            str(tmp_path),
            "--continue",
            "--no-input",
            "--turn-timeout",
            "0",
            "-p",
            "Continue",
        ]
    )
    assert await run_cli(args) == 0
