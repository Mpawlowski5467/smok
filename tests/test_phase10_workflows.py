import asyncio
import json
import sys

import pytest

from evals import run, suite
from evals.evidence import AttemptEvidence
from evals.reporting import markdown
from smok.process import capture
from smok.reliability import deadline_guidance, within_deadline
from smok.types import Event

TASKS = suite.load_tasks("phase10")
SOLUTIONS = json.loads((suite.HERE / "phase10_solutions.json").read_text())


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task["id"])
async def test_project_seeds_fail_and_references_pass_both_checks(task, tmp_path):
    suite.write_fixture(tmp_path, task["files"])
    argv = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"]
    seeded = await capture(argv, tmp_path)
    assert seeded.code != 0 and not seeded.timed_out, seeded.output
    assert not (await suite.check_task(task, tmp_path))[0]
    suite.write_fixture(tmp_path, SOLUTIONS[task["id"]])
    repaired = await capture(argv, tmp_path)
    assert repaired.code == 0 and not repaired.timed_out, repaired.output
    passed, output = await suite.check_task(task, tmp_path)
    assert passed, output
    assert suite.scope_check(task, tmp_path)["passed"]


def event(kind, **data):
    return Event(kind, data)


def shell(evidence, command="python3 check.py", ok=True, at=1):
    evidence.observe(
        event("tool_call", id="cmd", name="run_shell", arguments=json.dumps({"command": command})),
        at,
    )
    evidence.observe(event("tool_result", id="cmd", name="run_shell", is_error=not ok), at + 1)


def recorder(root):
    (root / "app.py").write_text("value = 1\n")
    return AttemptEvidence({"verification_commands": ["python3 check.py"]}, root, 0.5)


@pytest.mark.parametrize(
    "scenario", ["missing", "failed", "different", "stale", "later-failure", "changed-during-check"]
)
def test_project_check_cannot_pass_without_success_on_final_bytes(tmp_path, scenario):
    evidence = recorder(tmp_path)
    if scenario == "changed-during-check":
        evidence.observe(
            event(
                "tool_call", id="cmd", name="run_shell", arguments='{"command":"python3 check.py"}'
            ),
            1,
        )
        (tmp_path / "app.py").write_text("value = 2\n")
        evidence.observe(event("tool_result", id="cmd", name="run_shell", is_error=False), 2)
    elif scenario != "missing":
        shell(
            evidence,
            "echo different" if scenario == "different" else "python3 check.py",
            ok=scenario != "failed",
        )
        if scenario == "stale":
            (tmp_path / "app.py").write_text("value = 2\n")
        if scenario == "later-failure":
            shell(evidence, ok=False, at=3)
    evidence.finish_work(5)
    assert not evidence.verification()["passed"]


def test_check_evidence_keeps_failures_and_accepts_a_fresh_success(tmp_path):
    evidence = recorder(tmp_path)
    shell(evidence, ok=False)
    (tmp_path / "app.py").write_text("value = 2\n")
    shell(evidence, at=3)
    result = evidence.verification()
    assert result["passed"] and len(result["commands"]) == 2
    assert not result["commands"][0]["ok"]
    assert result["commands"][1]["matches_final_files"]


def test_timing_accounts_for_interruption_and_approval_without_double_counting(tmp_path):
    evidence = recorder(tmp_path)
    evidence.observe(event("model_started", iteration=1, purpose="task"), 1)
    evidence.observe(event("usage"), 3)
    evidence.observe(
        event("tool_call", id="cmd", name="run_shell", arguments='{"command":"python3 check.py"}'),
        3.5,
    )
    evidence.observe(event("permission_requested"), 4)
    timing = evidence.finish_work(6)
    assert timing["work_seconds"] == 5.5
    assert timing["model_seconds"] == 2
    assert timing["tool_seconds"] == 2.5
    assert timing["approval_seconds"] == 2
    assert timing["other_work_seconds"] == 1
    assert timing["tool_calls"][-1]["outcome"] == "interrupted"
    assert not evidence.verification()["passed"]


def test_interrupted_model_remains_measured(tmp_path):
    evidence = recorder(tmp_path)
    evidence.observe(event("model_started", iteration=1, purpose="task"), 1)
    timing = evidence.finish_work(4)
    assert timing["model_seconds"] == 3
    assert timing["model_requests"][0]["outcome"] == "interrupted"


@pytest.mark.parametrize(
    "changes",
    [
        {"shell_commands": "python3 check.py"},
        {"shell_commands": [1]},
        {"verification_commands": ["unapproved"]},
        {"verification_commands": [" "]},
        {"shell_commands": ["a", "a"]},
    ],
)
def test_invalid_command_contracts_are_rejected(tmp_path, monkeypatch, changes):
    task = {**TASKS[0], **changes}
    (tmp_path / "phase10_tasks.json").write_text(json.dumps([task]))
    monkeypatch.setattr(suite, "HERE", tmp_path)
    with pytest.raises(ValueError):
        suite.load_tasks("phase10")


async def test_project_suite_requires_explicit_shell_opt_in_before_model_access(monkeypatch):
    def no_model(*args, **kwargs):
        pytest.fail("Model accessed before command permission validation")

    monkeypatch.setattr(run, "resolve_model", no_model)
    assert await run.main(["--suite", "phase10", "--list", "--split", "all"]) == 0
    with pytest.raises(SystemExit) as failure:
        await run.main(["--suite", "phase10", "--allow-tools"])
    assert failure.value.code == 2


def test_exact_command_constraints_are_visible_and_empty_allowlist_hides_shell():
    args = run.parser().parse_args(["--allow-shell"])
    assert TASKS[0]["shell_commands"][0] in run.execution_guidance(TASKS[0], args)
    assert "run_shell" not in run.available_tools(args, {"shell_commands": []})


async def test_runner_does_not_count_a_correct_but_unverified_project(tmp_path):
    from test_phase7_evals import RepairModel

    task = {
        **suite.load_tasks()[0],
        "shell_commands": ["python3 check.py"],
        "verification_commands": ["python3 check.py"],
    }
    args = run.parser().parse_args(["--allow-tools", "--allow-shell"])
    result = await run.evaluate(
        task, run.resolve_model("local/fixture"), args, tmp_path / "attempt", factory=RepairModel
    )
    assert result["check_passed"] and result["stop_reason"] == "complete"
    assert not result["passed"] and not result["verification"]["passed"]
    assert result["timing"]["model_requests"]
    events = [
        json.loads(line) for line in (tmp_path / "attempt/events.jsonl").read_text().splitlines()
    ]
    assert all("elapsed_seconds" in e for e in events)
    row = {**result, "variant": "baseline", "repeat": 1, "evidence": "attempt"}
    rendered = markdown({"status": "complete", "results": [row], "plan": [{}]})
    assert "Observed time" in rendered and "Project checks" in rendered
    assert "FAIL" in rendered


async def test_runner_accepts_real_project_check_on_final_files(tmp_path):
    from test_phase7_evals import RepairModel

    command = 'python3 -B -c "from calculator import add; assert add(2, 3) == 5"'

    class VerifiedRepair(RepairModel):
        async def stream(self, system, messages, tools):
            if self.calls == 2:
                self.calls += 1
                yield event(
                    "tool_call",
                    id="verify",
                    name="run_shell",
                    arguments=json.dumps({"command": command}),
                )
                yield event("stop", reason="tool_calls")
            else:
                async for value in super().stream(system, messages, tools):
                    yield value

    task = {
        **suite.load_tasks()[0],
        "shell_commands": [command],
        "verification_commands": [command],
    }
    args = run.parser().parse_args(["--allow-tools", "--allow-shell"])
    result = await run.evaluate(
        task, run.resolve_model("local/fixture"), args, tmp_path / "attempt", factory=VerifiedRepair
    )
    assert result["passed"] and result["verification"]["passed"]
    assert result["tools"]["run_shell"] == 1
    assert result["verification"]["commands"][0]["matches_final_files"]


def test_workflow_suite_has_separate_held_out_cases_and_no_private_graders_in_fixtures():
    assert {t["id"] for t in TASKS} == set(SOLUTIONS)
    assert sum(t["split"] == "holdout" for t in TASKS) == 2
    for task in TASKS:
        assert "tests/test_project.py" not in task["allowed_changes"]
        assert task["check_file"] not in task["files"]
        assert task["verification_commands"] == task["shell_commands"]


async def test_deadline_hint_is_current_in_nested_work_and_absent_from_consumer():
    hints = []

    async def child():
        hints.append(deadline_guidance())
        yield Event("child")

    async def parent():
        hints.append(deadline_guidance())
        async for value in within_deadline(child(), None):
            yield value

    async for _ in within_deadline(parent(), asyncio.get_running_loop().time() + 30):
        assert deadline_guidance() == ""
    assert all("approximately 30 seconds remain" in hint for hint in hints)
    assert all("Do not skip necessary checks" in hint for hint in hints)
    assert deadline_guidance() == ""


async def test_deadline_guidance_reaches_model_without_becoming_saved_history(tmp_path):
    from test_loop import DONE, ScriptedModel

    from smok.loop import Agent
    from smok.tools.files import Workspace
    from smok.tools.registry import ToolRegistry

    class Recording(ScriptedModel):
        def __init__(self):
            super().__init__([DONE, DONE])
            self.systems = []

        async def stream(self, system, *args):
            self.systems.append(system)
            async for value in super().stream(system, *args):
                yield value

    model = Recording()
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), turn_timeout=30)
    events = [e async for e in agent.run("Hello")]
    assert events[-1].data["reason"] == "complete"
    assert "TURN TIME BUDGET" not in model.systems[-1]
    assert "TURN TIME BUDGET" in model.histories[-1][-1].content[-1].text
    assert "TURN TIME BUDGET" not in json.dumps(agent.state())
    agent.turn_timeout = None
    _ = [e async for e in agent.run("Another turn")]
    assert "TURN TIME BUDGET" not in model.systems[-1]
    assert "TURN TIME BUDGET" not in model.histories[-1][-1].content[0].text
    assert deadline_guidance() == ""


async def test_expiring_deadline_hint_is_cleared():
    async def wait():
        assert deadline_guidance()
        await asyncio.Event().wait()
        yield Event("unreachable")

    from smok.reliability import TurnDeadlineExceeded

    with pytest.raises(TurnDeadlineExceeded):
        _ = [e async for e in within_deadline(wait(), asyncio.get_running_loop().time() + 0.01)]
    assert deadline_guidance() == ""


async def test_countdown_stays_outside_anthropic_stable_cache_block(tmp_path):
    from smok.context import Context
    from smok.models.anthropic import AnthropicAdapter
    from smok.models.profiles import resolve_model
    from smok.tools.files import Workspace
    from smok.types import Message, RuntimeHint, Text

    context = Context(Workspace(tmp_path))
    adapter = AnthropicAdapter(resolve_model("anthropic/fixture"))
    payloads = []
    reports = []

    async def request():
        system = context.system("Stable project guidance", [])
        messages = [
            Message("user", [Text("Stable request")]),
            Message("user", [RuntimeHint(deadline_guidance())]),
        ]
        payloads.append(adapter.payload(system, messages, []))
        reports.append(context.report(adapter.config, "Stable project guidance", [], [], []))
        yield Event("ready")

    for seconds in (30, 10):
        _ = [
            e async for e in within_deadline(request(), asyncio.get_running_loop().time() + seconds)
        ]
    assert payloads[0]["system"][0] == payloads[1]["system"][0]
    assert "cache_control" in payloads[0]["system"][0]
    assert "TURN TIME BUDGET" not in payloads[0]["system"][0]["text"]
    assert "TURN TIME BUDGET" not in payloads[0]["system"][1]["text"]
    assert "cache_control" not in payloads[0]["system"][1]
    assert payloads[0]["system"] == payloads[1]["system"]
    first, second = [p["messages"][-1]["content"] for p in payloads]
    assert first[:-1] == second[:-1] and "cache_control" in first[-2]
    assert "TURN TIME BUDGET" in first[-1]["text"]
    assert "cache_control" not in first[-1] and first[-1] != second[-1]
    assert all(r["breakdown_estimated_tokens"]["time_budget"] > 0 for r in reports)
