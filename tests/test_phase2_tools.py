import json
from types import SimpleNamespace

import pytest

from smok.cli import mode_bindings
from smok.instructions import Instructions
from smok.journal import Journal
from smok.permissions import PermissionPolicy, command_matches
from smok.settings import ProjectSettings
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import MUTATING, ToolRegistry
from smok.tools.search import Search
from smok.types import ToolCall


def prepare(registry, name, **arguments):
    return registry.prepare(ToolCall("call", name, json.dumps(arguments)))


def test_exact_edit_preserves_crlf_and_requires_fresh_read(tmp_path):
    file = tmp_path / "a.py"
    file.write_bytes(b"first\r\nvalue = 1\r\nlast\r\n")
    workspace = Workspace(tmp_path)
    with pytest.raises(ToolError, match="Read the file"):
        workspace.prepare_edit("a.py", "value = 1", "value = 2")
    workspace.read_file("a.py", offset=2, limit=1)
    edit = workspace.prepare_edit("a.py", "value = 1", "value = 2")
    assert "-value = 1" in edit.diff and "+value = 2" in edit.diff
    workspace.apply_write(edit)
    assert file.read_bytes() == b"first\r\nvalue = 2\r\nlast\r\n"
    workspace.apply_write(workspace.prepare_edit("a.py", "value = 2", "value = 3"))
    assert file.read_bytes() == b"first\r\nvalue = 3\r\nlast\r\n"
    file.write_bytes(b"external change\r\nvalue = 3\r\nlast\r\n")
    with pytest.raises(ToolError, match="Read the file"):
        workspace.prepare_edit("a.py", "value = 3", "value = 4")


@pytest.mark.parametrize("old", ["", "missing", "repeat"])
def test_edit_rejects_empty_missing_and_ambiguous_matches(tmp_path, old):
    (tmp_path / "a").write_text("repeat repeat")
    workspace = Workspace(tmp_path)
    workspace.read_file("a")
    with pytest.raises(ToolError):
        workspace.prepare_edit("a", old, "replacement")


async def test_search_handles_regex_ranges_ignore_files_and_protected_metadata(tmp_path):
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "file.txt").write_text("first\nneedle12\nNEEDLE34\n")
    (tmp_path / "ignored.txt").write_text("needle56")
    (tmp_path / ".hidden.txt").write_text("needle78")
    for directory in [".git", ".smok", ".venv", "node_modules", "nested/.smok"]:
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / "secret.txt").write_text("needle90")
    search = Search(Workspace(tmp_path))
    result = await search.grep(r"needle\d+", ignore_case=True)
    assert "file.txt:2:needle12" in result and "file.txt:3:NEEDLE34" in result
    assert ".hidden.txt" in result and "ignored.txt" not in result
    for pattern in ["*", "**/*", "*.txt", "**/.smok/**"]:
        result = await search.grep("needle", glob=pattern)
        listing = await search.glob(pattern)
        assert "secret" not in result + listing
    assert await search.grep("not-found") == "No matches."
    assert await search.glob("*.missing") == "No files."
    with pytest.raises(ToolError):
        await search.grep("[invalid")
    with pytest.raises(ToolError, match="outside"):
        await search.glob("*", path="..")
    # A pattern beginning with '-' remains a pattern, never another rg flag.
    assert await search.grep("--follow") == "No matches."


async def test_search_never_follows_symlinks_outside_workspace(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside").write_text("secret")
    (root / "link").symlink_to(tmp_path / "outside")
    search = Search(Workspace(root))
    assert await search.grep("secret") == "No matches."
    with pytest.raises(ToolError, match="outside"):
        await search.grep("secret", path="link")


async def test_missing_ripgrep_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr("smok.tools.search.shutil.which", lambda _: None)
    with pytest.raises(ToolError, match="Install ripgrep"):
        await Search(Workspace(tmp_path)).glob("*")


async def test_plan_mode_blocks_mutations_even_after_approval(tmp_path):
    tools = ToolRegistry(Workspace(tmp_path))
    pending = prepare(tools, "write_file", path="a", content="blocked")
    tools.set_mode("plan")
    assert not MUTATING & {s.name for s in tools.specs}
    for name in MUTATING:
        with pytest.raises(ToolError, match="Plan mode"):
            prepare(tools, name)
    with pytest.raises(ToolError, match="Plan mode"):
        await tools.execute(pending, approved=True)
    assert not (tmp_path / "a").exists()
    assert "empty" in await tools.execute(prepare(tools, "list_dir"))


def test_tab_toggles_mode_and_refreshes_toolbar(tmp_path):
    from smok.loop import Agent

    agent = Agent(SimpleNamespace(name="fixture/model"), ToolRegistry(Workspace(tmp_path)))
    events, refreshes = [], []
    bindings = mode_bindings(agent, events.append)
    event = SimpleNamespace(app=SimpleNamespace(invalidate=lambda: refreshes.append(True)))
    for expected in ["plan", "build"]:
        bindings.get_bindings_for_keys(("c-i",))[0].handler(event)
        assert agent.tools.mode == expected
        assert events[-1].data["mode"] == expected
    assert len(refreshes) == 2


@pytest.mark.parametrize(
    "command,pattern,allowed",
    [
        ("git status", "git status", True),
        ("pytest tests/test_a.py", "pytest tests/*", True),
        ("git status --short", "git status", False),
        ("git status; touch bad", "git status*", False),
        ("git status && touch bad", "git *", False),
        ("echo $(touch bad)", "echo *", False),
        ("echo `touch bad`", "echo *", False),
        ("git status\ntouch bad", "git *", False),
        ("echo value > bad", "echo *", False),
        ("git status | cat", "git *", False),
        ('echo "hello world"', "echo *", True),
        ('echo "unterminated', "echo *", False),
    ],
)
def test_permission_patterns_match_whole_argv(command, pattern, allowed):
    assert command_matches(command, pattern) is allowed


def test_permission_modes_and_saved_exact_file_rules(tmp_path):
    settings = ProjectSettings(tmp_path)
    tools = ToolRegistry(Workspace(tmp_path), settings=settings)
    edit = prepare(tools, "write_file", path="[a].txt", content="one")
    other = prepare(tools, "write_file", path="a.txt", content="two")
    shell = prepare(tools, "run_shell", command="git status")
    assert not PermissionPolicy(settings).allowed(edit)
    auto = PermissionPolicy(settings, "auto-edit")
    assert auto.allowed(edit) and not auto.allowed(shell)
    assert PermissionPolicy(settings, "full-auto").allowed(shell)
    auto.remember(edit)
    auto.remember(shell)
    loaded = PermissionPolicy(ProjectSettings(tmp_path))
    assert loaded.allowed(edit) and loaded.allowed(shell)
    assert not loaded.allowed(other)
    assert not loaded.allowed(prepare(tools, "run_shell", command="git status; echo changed"))
    settings.set_permissions("auto-edit")
    assert ProjectSettings(tmp_path).permission_mode == "auto-edit"
    assert (tmp_path / ".smok/settings.json").stat().st_mode & 0o777 == 0o600


def test_invalid_settings_and_redirected_metadata_are_rejected(tmp_path):
    directory = tmp_path / ".smok"
    directory.mkdir()
    path = directory / "settings.json"
    path.write_text('{"allow_rules": [{"tool": "run_shell", "command": "ls", "match": "prefix"}]}')
    with pytest.raises(ValueError, match="Invalid allow rule"):
        ProjectSettings(tmp_path)
    path.unlink()
    directory.rmdir()
    (tmp_path / "other").mkdir()
    directory.symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="symlink"):
        ProjectSettings(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        Journal(tmp_path)
    assert not list((tmp_path / "other").iterdir())


async def test_scoped_instructions_block_unseen_and_changed_guidance(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Root instructions.")
    (tmp_path / "src").mkdir()
    local = tmp_path / "src/AGENTS.md"
    local.write_text("Use local conventions.")
    tools = ToolRegistry(Workspace(tmp_path))
    assert "Root instructions" in tools.instructions.build()
    with pytest.raises(ToolError, match="Read src/AGENTS.md"):
        prepare(tools, "write_file", path="src/new.py", content="first")
    prompt = tools.instructions.build()
    assert "Use local conventions" in prompt and "apply within src" in prompt
    pending = prepare(tools, "write_file", path="src/new.py", content="first")
    local.write_text("New instructions.")
    with pytest.raises(ToolError, match="new or changed"):
        await tools.execute(pending, approved=True)
    assert not (tmp_path / "src/new.py").exists()
    assert "New instructions" in tools.instructions.build()
    await tools.execute(
        prepare(tools, "write_file", path="src/new.py", content="first"), approved=True
    )


def test_instruction_budget_is_enforced(tmp_path):
    (tmp_path / "AGENTS.md").write_text("x" * 32769)
    with pytest.raises(ToolError, match="32 KiB"):
        Instructions(Workspace(tmp_path)).build()


def test_exact_edit_rejects_overlapping_occurrences(tmp_path):
    (tmp_path / "a").write_text("aaa")
    workspace = Workspace(tmp_path)
    workspace.read_file("a")
    with pytest.raises(ToolError, match="multiple matches"):
        workspace.prepare_edit("a", "aa", "b")


def test_large_file_range_stays_bounded_and_detects_changes_outside_range(tmp_path):
    file = tmp_path / "large"
    file.write_text("unchanged\n" * 200_000 + "target\n")
    workspace = Workspace(tmp_path)
    result = workspace.read_file("large", offset=200_001, limit=1)
    assert len(result) < 200 and "200001 | target" in result
    edit = workspace.prepare_edit("large", "target", "new target")
    file.write_text(file.read_text().replace("unchanged", "modified", 1))
    with pytest.raises(ToolError, match="while waiting"):
        workspace.apply_write(edit)


async def test_headless_plan_blocks_full_auto_and_cli_undo_restores_files(
    tmp_path, monkeypatch, capsys
):
    from test_loop import DONE, STOP, ScriptedModel, call

    from smok.cli import parser, run_cli

    model = ScriptedModel(
        [
            [call("write_file", {"path": "a", "content": "new"}), STOP],
            [call("run_shell", {"command": "touch bad"}), STOP],
            DONE,
        ]
    )
    monkeypatch.setattr("smok.cli.create_adapter", lambda _: model)
    base = ["-C", str(tmp_path), "--json", "--permissions", "full-auto"]
    assert await run_cli(parser().parse_args([*base, "--mode", "plan", "-p", "Plan"])) == 0
    assert not (tmp_path / "a").exists() and not (tmp_path / "bad").exists()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    results = [e["data"] for e in events if e["type"] == "tool_result"]
    assert all(r["is_error"] and "Plan mode" in r["content"] for r in results)
    model = ScriptedModel([[call("write_file", {"path": "a", "content": "new"}), STOP], DONE, DONE])
    assert await run_cli(parser().parse_args([*base, "-p", "Create"])) == 0
    assert (tmp_path / "a").read_text() == "new"
    assert await run_cli(parser().parse_args([*base, "--undo"])) == 0
    assert not (tmp_path / "a").exists()


async def test_always_approval_is_saved_and_reused(tmp_path):
    from test_loop import DONE, STOP, ScriptedModel, call

    from smok.loop import Agent

    approvals = []

    async def always(request):
        approvals.append(request)
        return "always"

    model = ScriptedModel(
        [
            [call("run_shell", {"command": "true"}), STOP],
            [call("run_shell", {"command": "true"}), STOP],
            DONE,
        ]
    )
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), approver=always)
    _ = [e async for e in agent.run("Check")]
    assert len(approvals) == 1
    assert ProjectSettings(tmp_path).rules == [
        {"tool": "run_shell", "command": "true", "match": "exact"}
    ]


def test_changed_symlink_target_cannot_redirect_an_approved_edit_or_saved_rule(tmp_path):
    for name in ["a", "b"]:
        (tmp_path / name).write_text("same original")
    link = tmp_path / "link"
    link.symlink_to("a")
    tools = ToolRegistry(Workspace(tmp_path))
    tools.workspace.read_file("link")
    prepared = prepare(tools, "edit_file", path="link", old_text="original", new_text="changed")
    link.unlink()
    link.symlink_to("b")
    policy = PermissionPolicy(tools.settings)
    policy.remember(prepared)
    assert tools.settings.rules[0]["path"] == "a"
    with pytest.raises(ToolError, match="File path changed"):
        tools.workspace.apply_write(prepared.write)
    assert (tmp_path / "b").read_text() == "same original"
