import asyncio
import json
import os
import shlex
import sys

import pytest

from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.tools.shell import run_shell
from smok.types import ToolCall


def test_reads_have_ranges_and_line_numbers(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n")
    result = Workspace(tmp_path).read_file("a.txt", offset=2, limit=1)
    assert "2 | two" in result
    assert "1 | one" not in result


def test_write_requires_read_and_refuses_stale_contents(tmp_path):
    file = tmp_path / "a.py"
    file.write_text("old\n")
    workspace = Workspace(tmp_path)
    with pytest.raises(ToolError, match="Read the file"):
        workspace.prepare_write("a.py", "new\n")
    workspace.read_file("a.py")
    file.write_text("other person's edit\n")
    with pytest.raises(ToolError, match="Read the file"):
        workspace.prepare_write("a.py", "new\n")


def test_file_changed_during_approval_is_not_overwritten(tmp_path):
    file = tmp_path / "a.py"
    file.write_text("old\n")
    workspace = Workspace(tmp_path)
    workspace.read_file("a.py")
    pending = workspace.prepare_write("a.py", "new\n")
    assert "-old" in pending.diff and "+new" in pending.diff
    file.write_text("concurrent change\n")
    with pytest.raises(ToolError, match="while waiting"):
        workspace.apply_write(pending)
    assert file.read_text() == "concurrent change\n"


def test_new_file_and_existing_permissions(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.apply_write(workspace.prepare_write("src/new.py", "print('hi')\n"))
    path = tmp_path / "src/new.py"
    path.chmod(0o755)
    workspace.read_file("src/new.py")
    workspace.apply_write(workspace.prepare_write("src/new.py", "print('bye')\n"))
    assert path.read_text() == "print('bye')\n"
    assert path.stat().st_mode & 0o777 == 0o755
    assert not list(path.parent.glob(".smok-write-*"))


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", ".git/config", ".smok/config"])
def test_paths_cannot_escape_or_modify_metadata(tmp_path, path):
    with pytest.raises(ToolError):
        Workspace(tmp_path).resolve(path)


def test_symlink_escape(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "secret").write_text("private")
    (root / "link").symlink_to(tmp_path)
    workspace = Workspace(root)
    with pytest.raises(ToolError, match="outside"):
        workspace.read_file("link/secret")
    with pytest.raises(ToolError, match="outside"):
        workspace.prepare_write("link/new", "oops")


def test_binary_and_large_reads_rejected(tmp_path):
    workspace = Workspace(tmp_path)
    (tmp_path / "bin").write_bytes(b"a\0b")
    (tmp_path / "large").write_bytes(b"a" * (16 * 1_048_576 + 1))
    with pytest.raises(ToolError, match="Binary"):
        workspace.read_file("bin")
    with pytest.raises(ToolError, match="16 MiB"):
        workspace.read_file("large")


@pytest.mark.parametrize(
    "name,args",
    [
        ("missing", "{}"),
        ("read_file", "{"),
        ("read_file", "[]"),
        ("read_file", '{"path":"a","offset":0}'),
        ("run_shell", '{"command":"hi","timeout_seconds":999}'),
        ("list_dir", '{"unknown":true}'),
    ],
)
def test_registry_validates_model_arguments(tmp_path, name, args):
    with pytest.raises(ToolError):
        ToolRegistry(Workspace(tmp_path)).prepare(ToolCall("c", name, args))


async def test_registry_denies_side_effects_by_default(tmp_path):
    registry = ToolRegistry(Workspace(tmp_path))
    call = ToolCall("c", "write_file", json.dumps({"path": "x", "content": "no"}))
    with pytest.raises(ToolError, match="Permission denied"):
        await registry.execute(registry.prepare(call))
    assert not (tmp_path / "x").exists()


async def test_shell_cwd_and_bounded_output(tmp_path):
    command = (
        shlex.quote(sys.executable)
        + " -c "
        + shlex.quote("import os; print(os.getcwd()); print('x' * 50000)")
    )
    result = await run_shell(command, tmp_path)
    assert str(tmp_path) in result
    assert "Output truncated" in result
    assert len(result) < 25_000


async def test_shell_timeout(tmp_path):
    with pytest.raises(ToolError, match="Timed out"):
        await run_shell("sleep 30", tmp_path, timeout_seconds=0.1)


async def test_shell_failure_retains_exit_status_and_output(tmp_path):
    with pytest.raises(ToolError, match="Exit code: 7") as error:
        await run_shell("printf 'check failed'; exit 7", tmp_path)
    assert "check failed" in str(error.value)


async def test_shell_cancellation_cleans_process_group(tmp_path):
    pid_file = tmp_path / "pid"
    task = asyncio.create_task(run_shell("echo $$ > pid; sleep 30", tmp_path))
    for _ in range(100):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    pid = int(pid_file.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
