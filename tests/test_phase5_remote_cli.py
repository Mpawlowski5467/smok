import asyncio
import base64
import io
import json
import tarfile
from pathlib import Path

import pytest
from test_loop import DONE
from test_phase5_lab import editing, repository
from test_phase5_team import config, model, setup

from smok.cli import parser, run_cli
from smok.process import ProcessResult
from smok.settings import Sandbox
from smok.team.remote import remote_run, run_request, ssh_command, unpack
from smok.tools.files import ToolError
from smok.usage import RunBudget


def archive(name="calc.py", *, link=None, duplicate=False):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        member = tarfile.TarInfo(name)
        content = b"answer = 0\n"
        if link:
            member.type, member.linkname = tarfile.SYMTYPE, link
        else:
            member.size = len(content)
        tar.addfile(member, None if link else io.BytesIO(content))
        if duplicate:
            tar.addfile(member, io.BytesIO(content))
    return base64.b64encode(buffer.getvalue()).decode()


@pytest.mark.parametrize(
    "name,link",
    [
        ("../escape", None),
        ("/tmp/escape", None),
        (".git/config", None),
        (".smok/settings.json", None),
        (".SMOK/settings.json", None),
        ("nested/.git/config", None),
        ("link", "../../outside"),
        ("a\\b", None),
    ],
)
def test_remote_archives_cannot_escape_or_set_permissions(tmp_path, name, link):
    with pytest.raises(ValueError, match="Unsafe"):
        unpack(archive(name, link=link), tmp_path)


def test_remote_duplicate_paths_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsafe"):
        unpack(archive(duplicate=True), tmp_path)


async def test_remote_protocol_edits_disposable_workspace_and_returns_patch(tmp_path):
    request = {
        "version": 1,
        "task": "Set 42",
        "archive": archive(),
        "tokens": 50000,
        "dollars": None,
        "requests": 8,
        "timeout_seconds": 30,
    }
    result = await run_request(
        request,
        config=config(),
        root=tmp_path,
        sandbox=Sandbox("docker"),
        factory=lambda c: editing(c.name, 42),
    )
    assert result["reason"] == "complete" and "+answer = 42" in result["patch"]
    # Read, edit, attempted completion, then the required review before completion.
    assert result["sandbox"] == "docker" and result["usage"]["requests"] == 4
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match="Docker"):
        await run_request(request, config=config(), root=tmp_path, sandbox=Sandbox())


async def test_remote_job_reserves_and_settles_shared_usage(tmp_path, monkeypatch):
    repository(tmp_path)
    agent, team = setup(
        tmp_path,
        budget=RunBudget(tokens=50000),
        settings={
            "remote_runners": {
                "lab": {
                    "host": "user@lab",
                    "command": ["smok", "--runner", "--runner-root", "/tmp/jobs"],
                }
            }
        },
    )

    async def transport(argv, root, **kwargs):
        request = json.loads(kwargs["input_data"])
        assert request["tokens"] == 50000 and request["requests"] == 8
        assert agent.budget.reservations and "StrictHostKeyChecking=yes" in argv
        assert request["archive"]
        return ProcessResult(
            0,
            json.dumps(
                {
                    "version": 1,
                    "reason": "complete",
                    "summary": "Done",
                    "patch": "",
                    "usage": {"requests": 1, "input_tokens": 10, "output_tokens": 2},
                }
            ).encode(),
            False,
            False,
        )

    monkeypatch.setattr("smok.team.remote.capture", transport)
    result = await remote_run(team, "lab", "Task")
    patch = Path(result["patch"])
    assert result["result"]["reason"] == "complete" and await asyncio.to_thread(patch.exists)
    assert agent.usage.input_tokens == 10 and agent.budget.usage.requests == 1
    assert agent.budget.requests == 8 and not agent.budget.reservations
    await agent.tools.close()


async def test_disconnected_runner_conservatively_charges_allowance(tmp_path, monkeypatch):
    repository(tmp_path)
    agent, team = setup(
        tmp_path,
        budget=RunBudget(tokens=20000),
        settings={"remote_runners": {"lab": {"host": "lab", "command": ["smok", "--runner"]}}},
    )

    async def transport(*args, **kwargs):
        return ProcessResult(255, b"connection lost", False, False)

    monkeypatch.setattr("smok.team.remote.capture", transport)
    with pytest.raises(ToolError, match="allocation remains charged"):
        await remote_run(team, "lab", "Task")
    assert agent.budget.usage.input_tokens == 20000 and not agent.budget.reservations
    assert agent.usage.estimated_requests == 8
    await agent.tools.close()


def test_ssh_quotes_remote_argv_and_does_not_auto_accept_hosts():
    args = ssh_command({"host": "lab", "command": ["/path with spaces/smok", "--runner", "$(no)"]})
    assert "BatchMode=yes" in args and "StrictHostKeyChecking=yes" in args
    assert args[-1] == "'/path with spaces/smok' --runner '$(no)'"


async def test_cli_worker_reports_and_json_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("smok.cli.create_adapter", lambda c: model(c.name, [DONE]))
    common = ["-C", str(tmp_path), "--no-log", "--no-checkpoints", "--json"]
    args = parser().parse_args(common + ["--delegate", "Explore", "--yes"])
    assert await run_cli(args) == 0
    events = [json.loads(s) for s in capsys.readouterr().out.splitlines()]
    result = next(e["data"] for e in events if e["type"] == "team_report")
    assert result["workers"][0]["reason"] == "complete"
    assert events[-1]["data"]["reason"] == "complete"


@pytest.mark.parametrize(
    "args",
    [
        ["--council", "Task", "-p", "Other"],
        ["--check", "true", "-p", "Task"],
        ["--remote-task", "missing runner"],
        ["--replay-base", "HEAD", "--oracle", "Question"],
        ["--runner"],
    ],
)
async def test_cli_conflicting_team_options_fail(tmp_path, args):
    with pytest.raises(ValueError):
        await run_cli(parser().parse_args(["-C", str(tmp_path), *args]))


async def test_prompt_is_jsonl_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("smok.cli.create_adapter", lambda c: model(c.name, [DONE]))
    args = parser().parse_args(["-C", str(tmp_path), "-p", "Hello", "--no-log", "--no-checkpoints"])
    assert await run_cli(args) == 0
    events = [json.loads(s) for s in capsys.readouterr().out.splitlines()]
    assert events[0]["type"] == "turn_started"
    assert events[-1]["data"]["reason"] == "complete"


async def test_remote_batch_dispatches_concurrently_with_separate_allowances(tmp_path, monkeypatch):
    repository(tmp_path)
    agent, team = setup(
        tmp_path,
        budget=RunBudget(tokens=100000),
        settings={"remote_runners": {"lab": {"host": "lab", "command": ["smok", "--runner"]}}},
    )
    arrived, ready = [], asyncio.Event()

    async def transport(argv, root, **kwargs):
        payload = json.loads(kwargs["input_data"])
        arrived.append(payload)
        if len(arrived) == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 3)
        return ProcessResult(
            0,
            json.dumps(
                {
                    "version": 1,
                    "reason": "complete",
                    "summary": "Done",
                    "patch": "",
                    "usage": {"requests": 1, "input_tokens": 10, "output_tokens": 2},
                }
            ).encode(),
            False,
            False,
        )

    monkeypatch.setattr("smok.team.remote.capture", transport)
    report = json.loads(
        await team.execute(
            "remote_batch",
            {"jobs": [{"runner": "lab", "task": "First"}, {"runner": "lab", "task": "Second"}]},
        )
    )
    assert [r["reason"] for r in report["workers"]] == ["complete", "complete"]
    assert [p["tokens"] for p in arrived] == [50000, 50000]
    assert agent.budget.usage.requests == 2 and not agent.budget.reservations
    await agent.tools.close()
