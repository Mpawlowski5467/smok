import asyncio
import json
from dataclasses import replace

import pytest

from evals import run
from evals.reporting import compare_reports, paired
from evals.suite import (
    HERE,
    check_task,
    load_tasks,
    safe_name,
    scope_check,
    snapshot,
    write_fixture,
)
from smok.models.profiles import resolve_model
from smok.types import Event

TASKS = load_tasks()
SOLUTIONS = json.loads((HERE / "solutions.json").read_text())


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task["id"])
async def test_graders_reject_seed_and_accept_reference(task, tmp_path):
    write_fixture(tmp_path, task["files"])
    assert not (await check_task(task, tmp_path))[0], "Broken seed falsely passed"
    write_fixture(tmp_path, SOLUTIONS[task["id"]])
    passed, details = await check_task(task, tmp_path)
    assert passed, details
    assert scope_check(task, tmp_path)["passed"]


async def test_grader_rejects_early_exit_and_scope_tampering(tmp_path):
    assert not (await check_task({"check": "raise SystemExit(0)"}, tmp_path))[0]
    task = TASKS[0]
    write_fixture(tmp_path, task["files"])
    (tmp_path / "unexpected.py").write_text("x")
    assert scope_check(task, tmp_path)["outside_scope"] == ["unexpected.py"]
    (tmp_path / "external").symlink_to("/etc/passwd")
    assert snapshot(tmp_path)["external"] == {"kind": "symlink"}
    assert not scope_check(task, tmp_path)["passed"]


async def test_interval_grader_rejects_bridging_positive_gaps(tmp_path):
    task = next(task for task in TASKS if task["id"] == "merge-intervals")
    write_fixture(
        tmp_path,
        {
            "intervals.py": "def merge_intervals(intervals):\n"
            "    merged = []\n"
            "    for start, end in sorted(intervals):\n"
            "        if merged and start <= merged[-1][1] + 1:\n"
            "            merged[-1] = (merged[-1][0], max(merged[-1][1], end))\n"
            "        else:\n"
            "            merged.append((start, end))\n"
            "    return merged\n"
        },
    )
    assert not (await check_task(task, tmp_path))[0]


@pytest.mark.parametrize("path", ["../secret", "/tmp/x", ".smok/key", "a/../b", "a\\b", ""])
def test_fixture_paths_are_confined(path):
    with pytest.raises(ValueError):
        safe_name(path)


class RepairModel:
    def __init__(self, config):
        self.config = replace(config, repo_map_tokens=0, max_output_tokens=128)
        self.name = config.name
        self.calls = 0

    async def stream(self, system, messages, tools):
        self.calls += 1
        if self.calls == 1:
            data = {
                "id": "read",
                "name": "read_file",
                "arguments": json.dumps({"path": "calculator.py"}),
            }
            yield Event("tool_call", data)
        elif self.calls == 2:
            data = {
                "id": "write",
                "name": "write_file",
                "arguments": json.dumps(
                    {"path": "calculator.py", "content": SOLUTIONS["fix-addition"]["calculator.py"]}
                ),
            }
            yield Event("tool_call", data)
        else:
            yield Event("text_delta", {"text": "The change is ready."})
        yield Event("usage", {"input_tokens": 40, "output_tokens": 8})
        yield Event("stop", {"reason": "tool_calls" if self.calls <= 2 else "stop"})


@pytest.mark.parametrize("limit,passed", [(6, True), (2, False)])
async def test_runner_requires_completion_and_records_provider_usage(tmp_path, limit, passed):
    args = run.parser().parse_args(["--allow-tools", "--max-iterations", str(limit)])
    result = await run.evaluate(
        TASKS[0], resolve_model("local/fixture"), args, tmp_path / "attempt", factory=RepairModel
    )
    assert result["passed"] == passed
    assert result["check_passed"] is True
    assert result["usage"]["estimated_requests"] == 0
    assert result["input_tokens"] == 40 * result["usage"]["requests"]
    assert (tmp_path / "attempt/events.jsonl").is_file()
    assert (tmp_path / "attempt/session.jsonl").is_file()
    assert (tmp_path / "attempt/files/calculator.py").read_text() == SOLUTIONS["fix-addition"][
        "calculator.py"
    ]


@pytest.mark.parametrize("shell,lsp", [(False, False), (False, True), (True, False), (True, True)])
def test_runner_advertises_only_authorizable_builtin_tools(shell, lsp):
    args = run.parser().parse_args(
        ["--allow-tools"] + (["--allow-shell"] if shell else []) + (["--allow-lsp"] if lsp else [])
    )
    names = run.available_tools(args)
    assert ("run_shell" in names) == shell
    assert ("lsp_diagnostics" in names) == lsp
    assert {"read_file", "write_file", "edit_file", "grep", "glob"} <= names
    assert not {"start_process", "mcp_call", "reload_extensions"} & names
    if not shell and not lsp:
        assert "runtime checks as not run" in run.execution_guidance(TASKS[0], args)


@pytest.mark.parametrize(
    "name,arguments,denials",
    [
        ("run_shell", {"command": "touch escaped"}, 0),
        ("start_process", {"command": "touch escaped"}, 0),
        ("write_file", {"path": "unexpected.py", "content": "outside scope"}, 1),
    ],
)
async def test_runner_enforces_permissions_even_when_model_guesses_tools(
    tmp_path, name, arguments, denials
):
    class Guessing(RepairModel):
        async def stream(self, system, messages, tools):
            names = {tool.name for tool in tools}
            assert "run_shell" not in names and "lsp_diagnostics" not in names
            assert "start_process" not in names
            assert "Shell execution is disabled" in system
            if not self.calls:
                self.calls += 1
                yield Event(
                    "tool_call", {"id": "guess", "name": name, "arguments": json.dumps(arguments)}
                )
                yield Event("stop", {"reason": "tool_calls"})
            else:
                yield Event("text_delta", {"text": "Blocked. No checks were run."})
                yield Event("stop", {"reason": "stop"})

    args = run.parser().parse_args(["--allow-tools"])
    destination = tmp_path / "attempt"
    result = await run.evaluate(
        TASKS[0], resolve_model("local/fixture"), args, destination, factory=Guessing
    )
    assert result["tool_errors"] == 1 and result["denials"] == denials
    assert result["scope"]["passed"] and not result["check_passed"] and not result["passed"]
    assert "run_shell" not in result["available_tools"]
    assert not (destination / "files/escaped").exists()
    assert not (destination / "files/unexpected.py").exists()


async def test_resume_preserves_consumption_and_completed_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "HERE", tmp_path)
    calls = []
    interrupt = True

    async def fake_evaluate(task, config, args, destination, *, budget):
        nonlocal interrupt
        calls.append(config.tool_set)
        budget.start_turn()
        booking = budget.reserve(config, 10)
        usage = {"input_tokens": 10, "output_tokens": 2, "source": "provider"}
        budget.settle(booking, config, usage)
        if len(calls) == 2 and interrupt:
            interrupt = False
            raise asyncio.CancelledError
        ledger = run.Ledger()
        ledger.record(config, usage)
        return {
            "task": task["id"],
            "task_fingerprint": task["fingerprint"],
            "model": config.name,
            "split": task["split"],
            "passed": True,
            "seconds": 1,
            "iterations": 1,
            "stop_reason": "complete",
            "usage": ledger.export(),
        }

    monkeypatch.setattr(run, "evaluate", fake_evaluate)
    flags = [
        "--allow-tools",
        "--model",
        "local/test",
        "--task",
        "fix-addition",
        "--variant",
        "baseline",
        "--variant",
        "coding",
    ]
    with pytest.raises(asyncio.CancelledError):
        await run.main(flags)
    directory = next((tmp_path / "results").iterdir())
    original = json.loads((directory / "report.json").read_text())
    assert original["status"] == "interrupted" and original["budget"]["requests"] == 2
    assert await run.main(flags + ["--resume", str(directory)]) == 0
    report = json.loads((directory / "report.json").read_text())
    assert len(report["results"]) == 2 and report["budget"]["requests"] == 3
    assert calls == ["full", "coding", "coding"]
    assert paired(report["results"])[0]["compared"] == 1
    assert "2/2" in (directory / "report.md").read_text()
    assert "complete" in compare_reports([directory / "report.json"])
    changed = json.loads(json.dumps(report))
    changed["results"][0]["task_fingerprint"] = "changed"
    (tmp_path / "changed.json").write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="not comparable"):
        compare_reports([directory / "report.json", tmp_path / "changed.json"])
    monkeypatch.setattr(run, "source_fingerprint", lambda: "changed")
    with pytest.raises(ValueError, match="unchanged source"):
        await run.main(flags + ["--resume", str(directory)])


def test_profile_report_strips_endpoint_query_secrets():
    config = replace(
        resolve_model("local/test"), base_url="http://127.0.0.1:1234/v1?key=secret#fragment"
    )
    assert run.profile_data(config)["base_url"] == "http://127.0.0.1:1234/v1"
