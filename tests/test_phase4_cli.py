import json

import pytest
from test_loop import DONE, STOP, ScriptedModel, call
from test_phase4_extensions import document, recipe

from smok.cli import parser, run_cli
from smok.tools.files import ToolError


async def test_extension_listing_requires_no_model_or_key(tmp_path, capsys):
    document(tmp_path, "skills/local/SKILL.md", "local", "Instructions")
    args = parser().parse_args(["-C", str(tmp_path), "--extensions", "--json"])
    assert await run_cli(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["data"]["skills"][0]["name"] == "local"


async def test_headless_command_parameters_use_normal_agent_loop(tmp_path, monkeypatch, capsys):
    document(
        tmp_path,
        "commands/check.md",
        "check",
        "Inspect {{path}}. {{args}}",
        parameters={"path": None},
    )
    model = ScriptedModel([DONE])
    monkeypatch.setattr("smok.cli.create_adapter", lambda config: model)
    args = parser().parse_args(
        [
            "-C",
            str(tmp_path),
            "-m",
            "ollama/fixture",
            "--command",
            "check",
            "--param",
            "path=a.py",
            "--arguments",
            "read only",
            "--json",
            "--no-log",
            "--no-checkpoints",
            "--no-self-check",
        ]
    )
    assert await run_cli(args) == 0
    assert "Inspect a.py. read only" in model.histories[0][0].content[0].text
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["data"]["reason"] == "complete"


async def test_headless_recipe_returns_failure_on_denied_action(tmp_path, monkeypatch, capsys):
    recipe(tmp_path)
    model = ScriptedModel([[call("run_shell", {"command": "touch forbidden"}), STOP], DONE])
    monkeypatch.setattr("smok.cli.create_adapter", lambda config: model)
    args = parser().parse_args(
        [
            "-C",
            str(tmp_path),
            "-m",
            "ollama/fixture",
            "--recipe",
            "check",
            "--param",
            "target=x",
            "--json",
            "--no-log",
            "--no-checkpoints",
            "--no-self-check",
        ]
    )
    assert await run_cli(args) == 2
    assert not (tmp_path / "forbidden").exists()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["data"]["reason"] == "recipe_step_failed"


@pytest.mark.parametrize(
    "flags",
    [
        ["--review", "--prompt", "conflict"],
        ["--extensions", "--recipe", "x"],
        ["--param", "a=b", "--prompt", "no extension"],
    ],
)
async def test_cli_rejects_conflicting_extension_actions(tmp_path, flags):
    with pytest.raises(ValueError):
        await run_cli(parser().parse_args(["-C", str(tmp_path), *flags]))


async def test_missing_required_command_parameter_never_calls_model(tmp_path, monkeypatch):
    document(tmp_path, "commands/check.md", "check", "Inspect {{path}}", parameters={"path": None})
    model = ScriptedModel([])
    monkeypatch.setattr("smok.cli.create_adapter", lambda config: model)
    args = parser().parse_args(["-C", str(tmp_path), "--command", "check", "--json", "--no-log"])
    with pytest.raises(ToolError, match="Missing required"):
        await run_cli(args)
    assert not model.histories
