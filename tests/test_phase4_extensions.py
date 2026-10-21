import asyncio
import json
import shlex
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from test_loop import DONE, STOP, ScriptedModel, call

from smok.extensions.catalog import Catalog
from smok.extensions.workflows import invocation, run_extension, run_review
from smok.loop import Agent
from smok.permissions import PermissionPolicy, allow
from smok.process import ProcessResult
from smok.settings import ProjectSettings, Sandbox
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, ToolCall


def document(root, path, name, body, **metadata):
    target = root / ".smok-extensions" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\n"
        + yaml.safe_dump({"name": name, "description": "Useful guidance", **metadata})
        + "---\n"
        + body
    )
    return target


def hooks(root, items):
    path = root / ".smok-extensions/hooks.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(items))
    return path


def prepare(tools, name, **args):
    return tools.prepare(ToolCall("test", name, json.dumps(args)))


def python(code):
    return shlex.join([sys.executable, "-c", code])


def test_skills_disclose_metadata_only_and_detect_stale_body(tmp_path):
    path = document(tmp_path, "skills/python/SKILL.md", "python", "Unique hidden instructions")
    tools = ToolRegistry(Workspace(tmp_path))
    agent = Agent(ScriptedModel([]), tools)
    assert "Useful guidance" in agent.base_system()
    assert "Unique hidden instructions" not in agent.base_system()
    assert "Unique hidden instructions" in tools.extensions.catalog.render("skills", "python")[0]
    path.write_text(path.read_text().replace("hidden", "changed"))
    with pytest.raises(ToolError, match="changed on disk"):
        tools.extensions.catalog.render("skills", "python")


def test_permission_save_preserves_externally_updated_extension_settings(tmp_path):
    settings = ProjectSettings(tmp_path)
    path = tmp_path / ".smok/settings.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"mcp_servers": {"new": {"command": "new-server"}}}))
    settings.set_permissions("auto-edit")
    data = json.loads(path.read_text())
    assert data["mcp_servers"]["new"]["command"] == "new-server"
    assert data["permissions"] == "auto-edit"


def test_shipped_example_bundle_loads_without_executing_hooks(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples/extensions"
    shutil.copytree(source, tmp_path / ".smok-extensions")
    catalog = Catalog(Workspace(tmp_path))
    assert "dev/verify" in catalog.skills and "dev/check" in catalog.commands
    assert "dev/change" in catalog.recipes and not catalog.hooks
    assert len(catalog.render("recipes", "dev/change", {"task": "a change"})) == 3


async def test_agent_authors_and_reloads_extension_in_same_turn(tmp_path):
    model = ScriptedModel(
        [
            [
                call(
                    "write_file",
                    {
                        "path": ".smok-extensions/skills/hello/SKILL.md",
                        "content": "---\nname: hello\ndescription: Say hello\n---\n"
                        "Say hello in Polish.",
                    },
                ),
                STOP,
            ],
            [call("reload_extensions", {}), STOP],
            [call("load_skill", {"name": "hello"}), STOP],
            DONE,
        ]
    )
    tools = ToolRegistry(Workspace(tmp_path))
    agent = Agent(model, tools, approver=allow, self_check=False)
    events = [e async for e in agent.run("Create a greeting skill and load it.")]
    assert not any(e.data.get("is_error") for e in events)
    assert "hello" in tools.extensions.catalog.skills
    assert "Say hello in Polish." in next(
        e.data["content"]
        for e in events
        if e.type == "tool_result" and e.data["name"] == "load_skill"
    )


async def test_failed_reload_preserves_prior_catalog(tmp_path):
    document(tmp_path, "commands/good.md", "good", "A command")
    tools = ToolRegistry(Workspace(tmp_path))
    document(tmp_path, "commands/bad.md", "review", "Must not override builtin")
    with pytest.raises(ToolError, match="reserved"):
        await tools.extensions.reload()
    assert list(tools.extensions.catalog.commands) == ["good"]
    assert tools.extensions.generation == 0


def test_plugin_namespaces_and_safe_text_parameters(tmp_path):
    base = tmp_path / ".smok-extensions/plugins/team"
    base.mkdir(parents=True)
    (base / "plugin.yaml").write_text("name: team\ndescription: Team workflows\n")
    document(
        tmp_path,
        "plugins/team/commands/check.md",
        "check",
        "Check {{target}}. {{args}}",
        parameters={"target": None},
    )
    document(tmp_path, "commands/check.md", "check", "Local command")
    catalog = Catalog(Workspace(tmp_path))
    assert set(catalog.commands) == {"check", "team/check"}
    key, values, args = invocation('team/check target="a b.py" $(touch nope)')
    prompt = catalog.render("commands", key, values, args)[0]
    assert "a b.py" in prompt and "$(touch nope)" in prompt
    assert not (tmp_path / "nope").exists()
    with pytest.raises(ToolError, match="Missing required"):
        catalog.render("commands", key)


@pytest.mark.parametrize("location", ["skills/link", "plugins/link", "commands/link.md"])
def test_extension_symlinks_rejected(tmp_path, location):
    path = tmp_path / ".smok-extensions" / location
    path.parent.mkdir(parents=True)
    path.symlink_to(tmp_path)
    with pytest.raises(ToolError, match="symlinks"):
        Catalog(Workspace(tmp_path))


@pytest.mark.parametrize(
    "body",
    [
        "---\nname: bad\ndescription: Test\n---\n{{missing}}",
        "no front matter",
        "---\nname: ../bad\ndescription: Test\n---\ntext",
    ],
)
def test_invalid_extension_documents_rejected(tmp_path, body):
    path = tmp_path / ".smok-extensions/commands/bad.md"
    path.parent.mkdir(parents=True)
    path.write_text(body)
    with pytest.raises(ToolError):
        Catalog(Workspace(tmp_path))


async def test_hooks_require_separate_scope_even_under_auto_edit(tmp_path):
    hooks(
        tmp_path,
        [
            {
                "name": "format",
                "event": "after_tool",
                "tools": ["write_file"],
                "command": python(
                    "import json,sys; from pathlib import Path; "
                    "p=Path(json.load(sys.stdin)['arguments']['path']); "
                    "p.write_text(p.read_text().upper())"
                ),
            }
        ],
    )
    tools = ToolRegistry(Workspace(tmp_path))
    prepared = prepare(tools, "write_file", path="a.txt", content="hello")
    policy = PermissionPolicy(tools.settings, "auto-edit")
    assert not policy.allowed(prepared)
    with pytest.raises(ToolError, match="denied"):
        await tools.execute(prepared)
    assert not (tmp_path / "a.txt").exists()
    policy.remember(prepared)
    assert PermissionPolicy(ProjectSettings(tmp_path)).allowed(prepared)
    result = await tools.execute(prepared, approved=True)
    assert (tmp_path / "a.txt").read_text() == "HELLO"
    assert "Hook format" in result and tools.shell_evidence[-1]["ok"]
    assert not tools.workspace.read_hashes
    changed = prepare(tools, "write_file", path="b.txt", content="hello")
    assert not policy.allowed(changed)


async def test_before_hook_blocks_command_and_post_failure_does_not_claim_rollback(tmp_path):
    hooks(
        tmp_path,
        [
            {
                "name": "guard",
                "event": "before_tool",
                "tools": ["run_shell"],
                "command": "echo blocked; exit 2",
            }
        ],
    )
    tools = ToolRegistry(Workspace(tmp_path))
    with pytest.raises(ToolError, match="blocked before execution"):
        await tools.execute(prepare(tools, "run_shell", command="touch forbidden"), approved=True)
    assert not (tmp_path / "forbidden").exists()
    hooks(
        tmp_path,
        [{"name": "broken", "event": "after_tool", "tools": ["write_file"], "command": "exit 3"}],
    )
    await tools.extensions.reload()
    with pytest.raises(ToolError, match="already finished"):
        await tools.execute(
            prepare(tools, "write_file", path="exists", content="saved"), approved=True
        )
    assert (tmp_path / "exists").read_text() == "saved"


async def test_hook_arguments_are_stdin_data_not_shell_interpolation(tmp_path):
    hooks(
        tmp_path,
        [
            {
                "name": "capture",
                "event": "before_tool",
                "tools": ["list_dir"],
                "command": python("import json,sys; print(json.load(sys.stdin)['arguments'])"),
            }
        ],
    )
    directory = "$(touch injected)"
    (tmp_path / directory).mkdir()
    tools = ToolRegistry(Workspace(tmp_path))
    await tools.execute(prepare(tools, "list_dir", path=directory), approved=True)
    assert not (tmp_path / "injected").exists()


async def test_hooks_suspended_in_plan_and_stale_approval_rejected(tmp_path):
    (tmp_path / "a").write_text("text")
    hooks(
        tmp_path,
        [
            {
                "name": "marker",
                "event": "before_tool",
                "tools": ["read_file"],
                "command": "touch marker",
            }
        ],
    )
    tools = ToolRegistry(Workspace(tmp_path))
    prepared = prepare(tools, "read_file", path="a")
    tools.set_mode("plan")
    with pytest.raises(ToolError, match="Plan mode"):
        await tools.execute(prepared, approved=True)
    await tools.execute(prepare(tools, "read_file", path="a"))
    assert not (tmp_path / "marker").exists()
    tools.set_mode("build")
    await tools.extensions.reload()
    with pytest.raises(ToolError, match="reloaded"):
        await tools.execute(prepared, approved=True)


async def test_hook_timeout_blocks_action(tmp_path):
    hooks(
        tmp_path,
        [
            {
                "name": "slow",
                "event": "before_tool",
                "tools": ["write_file"],
                "command": python("import time; time.sleep(20)"),
                "timeout_seconds": 1,
            }
        ],
    )
    tools = ToolRegistry(Workspace(tmp_path))
    with pytest.raises(ToolError, match="Timed out"):
        await tools.execute(prepare(tools, "write_file", path="a", content="x"), approved=True)
    assert not (tmp_path / "a").exists()


async def test_hook_uses_docker_stdin_and_cleanup(tmp_path, monkeypatch):
    hooks(
        tmp_path,
        [
            {
                "name": "formatter",
                "event": "after_tool",
                "tools": ["write_file"],
                "command": "python formatter.py",
            }
        ],
    )
    calls = []
    monkeypatch.setattr("smok.tools.shell.shutil.which", lambda _: "/docker")

    async def capture(argv, root, **kwargs):
        calls.append((argv, kwargs))
        return ProcessResult(0, b"formatted", False, False)

    monkeypatch.setattr("smok.tools.shell.capture", capture)
    tools = ToolRegistry(Workspace(tmp_path))
    tools.sandbox = Sandbox(backend="docker")
    await tools.execute(prepare(tools, "write_file", path="a.py", content="x = 1"), approved=True)
    assert calls[0][0][:3] == ["docker", "run", "--interactive"]
    assert calls[0][0][-2:] == ["-c", "python formatter.py"]
    payload = json.loads(calls[0][1]["input_data"])
    assert payload["tool"] == "write_file" and payload["arguments"]["path"] == "a.py"
    assert calls[1][0][:3] == ["docker", "rm", "-f"]


def recipe(root):
    path = root / ".smok-extensions/recipes/check.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "name": "check",
                "description": "Two-step task",
                "parameters": {"target": None},
                "steps": ["Inspect {{target}}", "Verify {{target}}"],
            }
        )
    )


async def test_recipe_runs_steps_with_shared_history_and_stops_on_denial(tmp_path):
    recipe(tmp_path)
    tools = ToolRegistry(Workspace(tmp_path))
    agent = Agent(ScriptedModel([DONE, DONE]), tools, self_check=False)
    events = [e async for e in run_extension(agent, "recipes", "check", {"target": "a.py"})]
    assert agent.budget.turns == 2
    assert len([e for e in events if e.type == "recipe_step_finished"]) == 2
    assert "Inspect a.py" in agent.model.histories[1][0].content[0].text
    denied = Agent(
        ScriptedModel([[call("write_file", {"path": "x", "content": "no"}), STOP], DONE]),
        ToolRegistry(Workspace(tmp_path)),
        self_check=False,
    )
    events = [e async for e in run_extension(denied, "recipes", "check", {"target": "x"})]
    assert any(e.type == "recipe_stopped" for e in events)
    assert denied.budget.turns == 1 and not denied.running
    assert not (tmp_path / "x").exists()


async def test_review_enforces_plan_and_restores_mode(tmp_path):
    tools = ToolRegistry(Workspace(tmp_path))
    agent = Agent(
        ScriptedModel([[call("write_file", {"path": "x", "content": "no"}), STOP], DONE]),
        tools,
        approver=allow,
        self_check=False,
    )
    events = [e async for e in run_review(agent)]
    assert any(e.type == "tool_result" and e.data["is_error"] for e in events)
    assert tools.mode == "build" and not (tmp_path / "x").exists()


async def test_recipe_cancellation_cleans_up_running_turn(tmp_path):
    recipe(tmp_path)

    class Waiting:
        name = "fixture/waiting"

        async def stream(self, *args):
            yield Event("text_delta", {"text": "start"})
            await asyncio.Event().wait()

    agent = Agent(Waiting(), ToolRegistry(Workspace(tmp_path)), self_check=False)
    stream = run_extension(agent, "recipes", "check", {"target": "file"})
    while (await anext(stream)).type != "text_delta":
        pass
    await stream.aclose()
    assert not agent.running
