import json
import sys
from dataclasses import replace

import pytest
from test_loop import DONE, STOP, ScriptedModel, call

from evals import suite
from smok.checkpoints import Checkpoints
from smok.loop import Agent
from smok.models.profiles import resolve_model
from smok.permissions import allow
from smok.process import capture
from smok.tools.files import Workspace
from smok.tools.registry import ToolRegistry
from smok.types import messages_from_data


@pytest.mark.parametrize("style", ["full", "lean"])
async def test_review_retains_current_contract_when_history_is_dropped(tmp_path, style):
    model = ScriptedModel(
        [
            [call("write_file", {"path": "config.py", "content": "port = 8000\n"}), STOP],
            DONE,  # A skipped check still requires the final-response review guard.
            DONE,
        ]
    )
    model.config = replace(resolve_model("local/fixture"), prompt_style=style, repo_map_tokens=0)
    agent = Agent(
        model, ToolRegistry(Workspace(tmp_path)), approver=allow, checkpoints=Checkpoints(tmp_path)
    )
    request = (
        "Preserve defaults; validate ports from every input source in the inclusive range 1..65535."
    )
    events = []
    async for event in agent.run(request):
        events.append(event)
        if event.type == "tool_result":
            # Context dropping and compaction can remove the verbatim request from history.
            agent.context.drop("group:1", agent.messages)
    review = model.histories[-1][-1].content[0].text
    assert request in review and "+port = 8000" in review
    assert events[-1].data["reason"] == "complete" and agent.turn_requests == 3
    assert sum(e.type == "self_check_started" for e in events) == 1
    messages_from_data(agent.state()["messages"])


async def test_batched_edits_keep_individual_approvals_and_review_actual_changes(tmp_path):
    requests = []

    async def approve(request):
        requests.append(request.arguments["path"])
        return request.arguments["path"] == "allowed.py"

    model = ScriptedModel(
        [
            [
                call("write_file", {"path": "allowed.py", "content": "value = 1\n"}, "first"),
                call("write_file", {"path": "denied.py", "content": "value = 2\n"}, "second"),
                STOP,
            ],
            DONE,
            DONE,
        ]
    )
    agent = Agent(
        model,
        ToolRegistry(Workspace(tmp_path)),
        approver=approve,
        checkpoints=Checkpoints(tmp_path),
    )
    events = [e async for e in agent.run("Update both files if permitted.")]
    assert requests == ["allowed.py", "denied.py"]
    assert (tmp_path / "allowed.py").read_text() == "value = 1\n"
    assert not (tmp_path / "denied.py").exists()
    review = next(e for e in events if e.type == "self_check_started")
    assert review.data["paths"] == ["allowed.py"]
    assert "Actions denied this turn: 1" in model.histories[-1][-1].content[0].text
    assert events[-1].data["reason"] == "complete" and agent.turn_requests == 3
    messages_from_data(agent.state()["messages"])


async def test_project_checks_and_grader_reject_cli_override_omission(tmp_path):
    task = next(t for t in suite.load_tasks("phase10") if t["id"] == "config-precedence")
    solutions = json.loads((suite.HERE / "phase10_solutions.json").read_text())
    suite.write_fixture(tmp_path, task["files"])
    suite.write_fixture(tmp_path, solutions[task["id"]])
    # Preserve the missed-validation pattern from the original generated repair.
    (tmp_path / "launch/cli.py").write_text(
        "import argparse\n"
        "from .config import load_config\n\n"
        "def options(argv, env):\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--host', default=None)\n"
        "    parser.add_argument('--port', type=int, default=None)\n"
        "    parser.add_argument('--debug', action='store_true', default=None)\n"
        "    parser.add_argument('--no-debug', action='store_false', dest='debug')\n"
        "    args = parser.parse_args(argv)\n"
        "    result = load_config(env)\n"
        "    result.update({k: v for k, v in vars(args).items() if v is not None})\n"
        "    return result\n"
    )
    public = await capture(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"], tmp_path
    )
    assert public.code != 0 and b"ValueError not raised" in public.output
    passed, output = await suite.check_task(task, tmp_path)
    assert not passed and "invalid CLI port accepted" in output
    assert suite.scope_check(task, tmp_path)["passed"]
