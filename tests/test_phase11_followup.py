import asyncio
import json
import sys
from dataclasses import replace

import pytest
from test_loop import DONE, STOP, ScriptedModel, call

from evals import run, suite
from smok.loop import Agent
from smok.models.base import ModelError
from smok.models.profiles import resolve_model
from smok.permissions import allow
from smok.process import capture
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, ToolCall, messages_from_data
from smok.usage import RunBudget

EMPTY = [Event("stop", {"reason": "stop"})]


async def test_new_review_replaces_old_prompt_but_preserves_full_diff_and_commands(tmp_path):
    model = ScriptedModel(
        [
            [call("write_file", {"path": "a", "content": "one"}), STOP],
            [call("run_shell", {"command": "printf checked"}), STOP],
            [call("write_file", {"path": "b", "content": "two"}), STOP],
            DONE,
            DONE,
        ]
    )
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), approver=allow)
    events = [e async for e in agent.run("Create both files and verify")]
    assert events[-1].data["reason"] == "complete"
    assert sum(e.type == "self_check_started" for e in events) == 2
    history = model.histories[-1]
    reviews = [
        b.text
        for m in history
        for b in m.content
        if getattr(b, "text", "").startswith("Review this diff")
    ]
    assert len(reviews) == 1
    assert all(value in reviews[0] for value in ("+one", "+two", "printf checked", "Exit code: 0"))
    assert history[0].content[0].text == "Create both files and verify"
    assert sum(isinstance(b, ToolCall) for m in history for b in m.content) == 3
    assert messages_from_data(agent.state()["messages"]) == agent.messages


async def test_empty_completion_retries_without_replaying_tools_or_losing_review(tmp_path):
    model = ScriptedModel(
        [[call("write_file", {"path": "a", "content": "new"}), STOP], EMPTY, DONE, DONE]
    )
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), approver=allow)
    events = [e async for e in agent.run("Create a")]
    assert events[-1].data == {"reason": "complete", "iterations": 4}
    assert agent.usage.requests == agent.budget.requests == 4
    assert len([e for e in events if e.type == "model_retry"]) == 1
    assert len([e for e in events if e.type == "tool_call"]) == 1
    assert len([e for e in events if e.type == "permission_requested"]) == 1
    assert len([e for e in events if e.type == "self_check_started"]) == 1
    assert model.histories[1] == model.histories[2]
    assert messages_from_data(agent.state()["messages"]) == agent.messages
    assert (tmp_path / "a").read_text() == "new"


async def test_only_one_empty_retry_per_turn_and_a_new_turn_can_recover(tmp_path):
    model = ScriptedModel([EMPTY, [call("list_dir", {}), STOP], EMPTY, EMPTY, DONE])
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    first = [e async for e in agent.run("Look around")]
    assert first[-1].data["reason"] == "error"
    assert agent.usage.requests == 3
    assert len([e for e in first if e.type == "model_retry"]) == 1
    second = [e async for e in agent.run("Continue")]
    assert second[-1].data == {"reason": "complete", "iterations": 2}
    assert len([e for e in second if e.type == "model_retry"]) == 1
    assert agent.usage.requests == 5


@pytest.mark.parametrize("ending", ["length", "tool_calls", "", "content_filter"])
async def test_noncompletion_empty_response_is_not_retried(tmp_path, ending):
    model = ScriptedModel([[Event("stop", {"reason": ending})], DONE])
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    events = [e async for e in agent.run("Hello")]
    assert events[-1].data["reason"] == "error"
    assert agent.usage.requests == 1
    assert not any(e.type == "model_retry" for e in events)


async def test_transport_failure_is_not_treated_as_an_empty_completion(tmp_path):
    model = ScriptedModel([[ModelError("disconnected")], DONE])
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    events = [e async for e in agent.run("Hello")]
    assert events[-1].data["reason"] == "error" and agent.usage.requests == 1
    assert not any(e.type == "model_retry" for e in events)


@pytest.mark.parametrize("limit", ["iterations", "requests", "tokens"])
async def test_empty_retry_cannot_extend_call_or_token_limits(tmp_path, limit):
    model = ScriptedModel([EMPTY, DONE])
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    if limit == "iterations":
        agent.max_iterations = 1
    elif limit == "requests":
        agent.budget = RunBudget(max_requests=1)
    else:
        # Cap the shared ledger after the first request's real reservation settles.
        agent.budget = RunBudget()
    events = []
    async for event in agent.run("Hello"):
        events.append(event)
        if limit == "tokens" and event.type == "model_retry":
            agent.budget.tokens = agent.usage.input_tokens + agent.usage.output_tokens
    assert events[-1].data["reason"] == (
        "iteration_limit" if limit == "iterations" else "budget_limit"
    )
    assert agent.usage.requests == 1 and len(model.histories) == 1
    if limit == "iterations":
        assert not any(e.type == "model_retry" for e in events)


async def test_empty_retry_keeps_the_original_deadline_and_closes_stream(tmp_path):
    class EmptyThenWait:
        name = "fixture/empty"
        calls = 0
        closed = False

        async def stream(self, *args):
            self.calls += 1
            if self.calls == 1:
                yield EMPTY[0]
            else:
                try:
                    await asyncio.Event().wait()
                finally:
                    self.closed = True

    model = EmptyThenWait()
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), turn_timeout=0.2)
    events = [e async for e in agent.run("Hello")]
    assert events[-1].data["reason"] == "time_limit"
    assert model.calls == agent.usage.requests == 2
    assert model.closed and not agent.running
    assert messages_from_data(agent.state()["messages"]) == agent.messages


def test_focused_profile_removes_planning_tools_without_granting_permissions(tmp_path):
    baseline = resolve_model("local/fixture")
    model = ScriptedModel([])
    model.config = replace(baseline, **run.VARIANTS["focused-repair"])
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    assert model.config.reasoning_effort == "none" and baseline.reasoning_effort is None
    assert model.config.max_output_tokens == baseline.max_output_tokens
    assert model.config.timeout_seconds == baseline.timeout_seconds
    assert agent.context_report()["input_tokens"] < agent.context_report(baseline)["input_tokens"]
    assert {t.name for t in agent.tools.specs} == {
        "read_file",
        "read_output",
        "list_dir",
        "write_file",
        "edit_file",
        "run_shell",
    }
    with pytest.raises(ToolError, match="tool set"):
        agent.tools.prepare(ToolCall("x", "write_todos", '{"items":[]}'))
    write = agent.tools.prepare(ToolCall("x", "write_file", '{"path":"a","content":"b"}'))
    assert write.requires_approval and not agent.policy.allowed(write)
    agent.set_mode("plan")
    with pytest.raises(ToolError, match="Plan mode"):
        agent.tools.prepare(ToolCall("x", "run_shell", '{"command":"true"}'))


@pytest.mark.parametrize(
    "defect",
    [
        "newline",
        "unicode_digits",
        "leading_zero_rc",
        "missing_version",
        "yanked_type",
        "stable_order",
        "last_tie",
        "tuple_catalog",
        "shared_right",
        "shallow_copy",
        "right_container",
    ],
)
async def test_public_regressions_reject_known_wrong_repairs(defect, tmp_path):
    task_id = (
        "table-joins"
        if defect in {"shared_right", "shallow_copy", "right_container"}
        else "release-selection"
    )
    task = next(t for t in suite.load_tasks("phase11") if t["id"] == task_id)
    repairs = json.loads((suite.HERE / "phase11_solutions.json").read_text())[task_id]
    if defect == "newline":
        repairs["releases/versions.py"] = repairs["releases/versions.py"].replace(
            "match = PATTERN.fullmatch(value)",
            "match = re.match('^' + PATTERN.pattern + '$', value)",
        )
    elif defect == "unicode_digits":
        repairs["releases/versions.py"] = repairs["releases/versions.py"].replace("[0-9]*", r"\d*")
    elif defect == "leading_zero_rc":
        repairs["releases/versions.py"] = repairs["releases/versions.py"].replace(
            "r'(?:-rc\\.' + NUMBER + r')?'", "r'(?:-rc\\.([0-9]+))?'"
        )
    elif defect in {"missing_version", "yanked_type", "stable_order", "last_tie", "tuple_catalog"}:
        before, after = {
            "missing_version": ("row.get('version')", "row['version']"),
            "yanked_type": ("type(row.get('yanked', False)) is not bool", "False"),
            "stable_order": ("rc is None", "rc is not None"),
            "last_tie": ("key > best", "key >= best"),
            "tuple_catalog": ("isinstance(records, list)", "isinstance(records, (list, tuple))"),
        }[defect]
        repairs["releases/catalog.py"] = repairs["releases/catalog.py"].replace(before, after)
    elif defect == "shared_right":
        repairs["tables/joining.py"] = repairs["tables/joining.py"].replace(
            "deepcopy(match)", "match"
        )
    elif defect == "right_container":
        repairs["tables/joining.py"] = repairs["tables/joining.py"].replace(
            "index_rows(right, key)", "index_rows([row for row in right], key)"
        )
    else:
        repairs = {name: code.replace("deepcopy", "copy") for name, code in repairs.items()}
    suite.write_fixture(tmp_path, {**task["files"], **repairs})
    public = await capture(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"], tmp_path
    )
    assert public.code != 0 and b"SyntaxError" not in public.output
    assert any(error in public.output for error in (b"AssertionError", b"KeyError", b"TypeError"))
    assert suite.scope_check(task, tmp_path)["passed"]
    # The original grader remains a separate check; Unicode trailing digits and tuple catalogs add
    # public coverage beyond its original invalid-input examples.
    if defect not in {"unicode_digits", "tuple_catalog"}:
        assert not (await suite.check_task(task, tmp_path))[0]
