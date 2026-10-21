import asyncio
import json
from dataclasses import replace

import pytest
from test_loop import DONE, STOP, ScriptedModel, call

from smok.loop import Agent
from smok.models.profiles import ModelConfig
from smok.permissions import PermissionPolicy
from smok.team.config import READ_TOOLS, TeamConfig
from smok.team.coordinator import Team
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, Message, Text, ToolCall
from smok.usage import BudgetExceeded, RunBudget


def config(name="local/main", local=True):
    return ModelConfig(
        name,
        name.split("/")[-1],
        "openai_compat",
        "http://localhost",
        "TEST_KEY",
        local=local,
        repo_map_tokens=0,
        max_output_tokens=128,
    )


def model(name="local/main", turns=None, local=True):
    result = ScriptedModel(turns or [DONE])
    result.name, result.config = name, config(name, local)
    return result


def setup(root, *, settings=None, factory=None, primary=None, full_auto=False, budget=None):
    registry = ToolRegistry(Workspace(root))
    agent = Agent(
        primary or model(),
        registry,
        self_check=False,
        budget=budget,
        policy=PermissionPolicy(registry.settings, "full-auto" if full_auto else "ask"),
    )
    team = Team(
        agent,
        TeamConfig.parse(settings or {}),
        resolver=lambda n: config(n, n.startswith("local/")),
        factory=factory or (lambda c: model(c.name)),
    )
    return agent, team


def prepared(registry, name, **args):
    return registry.prepare(ToolCall("t", name, json.dumps(args)))


@pytest.mark.parametrize(
    "settings",
    [
        {"routes": {"typo": "local/x"}},
        {"routes": []},
        {"max_workers": True},
        {"max_workers": 4},
        {"ladder": ["local/a", "local/a"]},
        {"typo": 1},
        {"remote_runners": {"lab": {"host": "-oops", "command": ["smok"]}}},
    ],
)
def test_settings_are_explicit_and_bounded(settings):
    with pytest.raises(ValueError):
        TeamConfig.parse(settings)


def test_parallel_reservations_include_pending_cost_and_tokens():
    cfg = replace(config(local=False), prices={"input": 10, "output": 20})
    budget = RunBudget(tokens=300, dollars=0.01, max_requests=3)
    reservation = budget.reserve(cfg, 100)
    with pytest.raises(BudgetExceeded, match="Token"):
        budget.reserve(cfg, 100)
    budget.settle(reservation, cfg, {"input_tokens": 10, "output_tokens": 1, "source": "provider"})
    second = budget.reserve(cfg, 100)
    assert second == 2
    priced = RunBudget(dollars=0.005)
    priced.reserve(cfg, 100)
    with pytest.raises(BudgetExceeded, match="Dollar"):
        priced.reserve(cfg, 100)


async def test_workers_run_concurrently_with_fresh_context_and_restrictions(tmp_path):
    arrived, release = 0, asyncio.Event()
    seen = []

    class Worker:
        def __init__(self, cfg):
            self.name, self.config = cfg.name, cfg

        async def stream(self, system, messages, tools):
            nonlocal arrived
            arrived += 1
            seen.append((list(messages), {t.name for t in tools}))
            if arrived == 2:
                release.set()
            await asyncio.wait_for(release.wait(), 2)
            yield Event("text_delta", {"text": "concise answer"})
            yield Event("usage", {"input_tokens": 10, "output_tokens": 2})
            yield Event("stop", {"reason": "stop"})

    agent, team = setup(tmp_path, factory=Worker)
    agent.messages = [Message("user", [Text("private parent history")])]
    result = json.loads(
        await team.execute(
            "delegate",
            {"tasks": [{"task": "Find A", "role": "explore"}, {"task": "Find B", "role": "plan"}]},
        )
    )
    assert len(result["workers"]) == 2 and arrived == 2
    assert all(len(messages) == 1 and tools == READ_TOOLS for messages, tools in seen)
    assert all("private parent history" not in repr(messages) for messages, _ in seen)
    assert agent.usage.requests == agent.budget.usage.requests == 2
    assert agent.budget.turns == 0 and not agent.budget.reservations
    assert len(agent.messages) == 1
    await agent.tools.close()


async def test_worker_cannot_call_hidden_tools_or_delegate_recursively(tmp_path):
    child = model(
        turns=[
            [
                call("write_file", {"path": "forbidden", "content": "bad"}),
                call("delegate", {"tasks": [{"task": "escape", "role": "edit"}]}, "t2"),
                STOP,
            ],
            DONE,
        ]
    )
    agent, team = setup(tmp_path, factory=lambda c: child, full_auto=True)
    result = await team.worker("Explore only", "explore")
    assert result["reason"] == "complete" and not (tmp_path / "forbidden").exists()
    errors = child.histories[-1][-1].content
    assert all(e.is_error and "restricted" in e.content for e in errors)
    await agent.tools.close()


async def test_plan_and_approval_cannot_be_bypassed_by_isolated_workers(tmp_path):
    agent, team = setup(tmp_path)
    agent.set_mode("plan")
    with pytest.raises(ToolError, match="Plan mode"):
        prepared(agent.tools, "delegate", tasks=[{"task": "edit", "role": "edit"}])
    item = prepared(agent.tools, "oracle", question="Review")
    with pytest.raises(ToolError, match="Permission denied"):
        await agent.tools.execute(item)
    agent.set_mode("build")
    item = prepared(agent.tools, "delegate", tasks=[{"task": "edit", "role": "edit"}])
    agent.set_mode("plan")
    with pytest.raises(ToolError, match="Plan mode"):
        await agent.tools.execute(item, approved=True)
    await agent.tools.close()


async def test_role_routing_ladder_handoff_and_single_user_turn(tmp_path):
    local = model(turns=[[call("run_shell", {"command": "exit 1"}), STOP]])
    frontier = model("frontier/editor", [DONE], local=False)
    agent, team = setup(
        tmp_path,
        primary=local,
        full_auto=True,
        settings={"ladder": ["local/main", "frontier/editor"], "stall_threshold": 1},
        factory=lambda c: frontier if not c.local else local,
    )
    events = [e async for e in agent.run("Fix failure")]
    assert events[0].type == "turn_started"
    escalated = next(e for e in events if e.type == "escalation")
    assert "exit 1" in escalated.data["handoff"]
    assert len(frontier.histories[0]) == 1
    assert "Prior attempt summary" in frontier.histories[0][0].content[0].text
    assert events[-1].data["reason"] == "complete" and agent.budget.turns == 1
    assert agent.budget.requests == 2
    await agent.tools.close()


async def test_denial_does_not_escalate_or_retry_with_frontier(tmp_path):
    local = model(turns=[[call("run_shell", {"command": "echo no"}), STOP]])
    created = []
    agent, team = setup(
        tmp_path,
        primary=local,
        settings={"ladder": ["local/main", "frontier/editor"], "stall_threshold": 1},
        factory=lambda c: created.append(c),
    )
    events = [e async for e in agent.run("Do it")]
    assert not created and not any(e.type == "escalation" for e in events)
    await agent.tools.close()


async def test_mode_routes_and_shared_request_cap(tmp_path):
    created = []

    def factory(c):
        created.append(c.name)
        return model(c.name)

    agent, team = setup(
        tmp_path, settings={"routes": {"plan": "local/planner"}, "max_requests": 1}, factory=factory
    )
    agent.set_mode("plan")
    assert [e async for e in agent.run("Plan")][-1].data["reason"] == "complete"
    assert created == ["local/planner"]
    result = await team.worker("More", "explore")
    assert result["reason"] == "budget_limit" and agent.budget.usage.requests == 1
    await agent.tools.close()


async def test_request_cancellation_settles_reserved_budget(tmp_path):
    agent, _ = setup(tmp_path)
    stream = agent._request("system", [], [])
    assert (await anext(stream)).type == "context_usage"
    assert agent.budget.reservations
    await stream.aclose()
    assert not agent.budget.reservations and agent.budget.usage.requests == 1
    await agent.tools.close()


async def test_background_jobs_poll_limit_stop_and_plan(tmp_path):
    agent, team = setup(tmp_path)
    with pytest.raises(ToolError, match="Permission denied"):
        await agent.tools.execute(prepared(agent.tools, "start_process", command="echo blocked"))
    result = json.loads(
        await agent.tools.execute(
            prepared(agent.tools, "start_process", command="printf 'ready\\n'; sleep 30"),
            approved=True,
        )
    )
    id = result["id"]
    for _ in range(40):
        data = json.loads(agent.tools.jobs.poll(id))
        if "ready" in data["output"]:
            break
        await asyncio.sleep(0.01)
    assert "ready" in data["output"] and data["status"] == "running"
    agent.set_mode("plan")
    with pytest.raises(ToolError, match="Plan mode"):
        prepared(agent.tools, "start_process", command="echo bad")
    await agent.tools.close()
    assert json.loads(agent.tools.jobs.poll(id))["status"] == "stopped"
    assert agent.tools.jobs.get(id)["process"].returncode is not None


async def test_background_output_ring_and_deadline(tmp_path):
    agent, _ = setup(tmp_path)
    import shlex
    import sys

    command = shlex.join(
        [sys.executable, "-c", "print('x'*100000, flush=True); import time; time.sleep(30)"]
    )
    result = json.loads(await agent.tools.jobs.start(command, timeout_seconds=0.15))
    await agent.tools.jobs.get(result["id"])["task"]
    data = json.loads(agent.tools.jobs.poll(result["id"]))
    assert data["status"] == "timed_out" and data["lost_bytes"] > 0
    assert len(agent.tools.jobs.get(result["id"])["output"]) == 65536
    await agent.tools.close()


async def test_parent_mode_change_blocks_an_already_prepared_child_write(tmp_path):
    parent = ToolRegistry(Workspace(tmp_path))
    child = ToolRegistry(Workspace(tmp_path))
    child.mode_ceiling = lambda: parent.mode
    item = prepared(child, "write_file", path="blocked", content="no")
    parent.set_mode("plan")
    assert "write_file" not in {s.name for s in child.specs}
    with pytest.raises(ToolError, match="Plan mode"):
        await child.execute(item, approved=True)
    assert not (tmp_path / "blocked").exists()
    await parent.close()
    await child.close()


def test_worker_policy_tracks_parent_permission_changes(tmp_path):
    from smok.team.coordinator import WorkerPolicy

    parent = ToolRegistry(Workspace(tmp_path))
    policy = PermissionPolicy(parent.settings, "full-auto")
    worker = WorkerPolicy(parent.settings, policy)
    request = prepared(parent, "run_shell", command="echo allowed")
    assert worker.allowed(request)
    policy.mode = "ask"
    assert not worker.allowed(request)
