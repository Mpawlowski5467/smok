import asyncio

import pytest

from smok.process import ProcessResult
from smok.settings import Sandbox
from smok.tools.files import ToolError
from smok.tools.shell import docker_command, run_shell


def test_docker_is_confined_to_workspace_without_network_or_image_pull(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".smok").mkdir()
    command = "python -m pytest && echo done"
    args = docker_command(command, tmp_path, Sandbox(backend="docker"), "smok-test")
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--pull") + 1] == "never"
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges"
    assert "--read-only" in args and "--privileged" not in args
    assert args[-2:] == ["-c", command]
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "--mount"]
    assert mounts == [
        f"type=bind,src={tmp_path},dst=/workspace",
        f"type=bind,src={tmp_path}/.git,dst=/workspace/.git,readonly",
        f"type=bind,src={tmp_path}/.smok,dst=/workspace/.smok,readonly",
    ]
    assert "/var/run/docker.sock" not in " ".join(args)
    enabled = docker_command("true", tmp_path, Sandbox(backend="docker", network=True), "smok-test")
    assert enabled[enabled.index("--network") + 1] == "bridge"


@pytest.mark.parametrize("failure", ["daemon", "timeout", "cancel"])
async def test_failed_docker_commands_cleanup_without_host_fallback(tmp_path, monkeypatch, failure):
    calls = []
    monkeypatch.setattr("smok.tools.shell.shutil.which", lambda _: "/docker")

    async def capture(args, *positional, **kwargs):
        calls.append(args)
        if args[1] == "rm":
            return ProcessResult(0, b"", False, False)
        if failure == "cancel":
            raise asyncio.CancelledError()
        return ProcessResult(125, b"Docker daemon is unavailable", False, failure == "timeout")

    monkeypatch.setattr("smok.tools.shell.capture", capture)
    expected = asyncio.CancelledError if failure == "cancel" else ToolError
    with pytest.raises(expected):
        await run_shell("touch file", tmp_path, sandbox=Sandbox(backend="docker"))
    assert len(calls) == 2 and calls[0][:2] == ["docker", "run"]
    assert calls[1][:3] == ["docker", "rm", "-f"]
    assert calls[1][-1] == calls[0][calls[0].index("--name") + 1]
    assert not (tmp_path / "file").exists()


async def test_missing_docker_never_uses_host_shell(tmp_path, monkeypatch):
    monkeypatch.setattr("smok.tools.shell.shutil.which", lambda _: None)
    with pytest.raises(ToolError, match="Docker is not installed"):
        await run_shell("touch file", tmp_path, sandbox=Sandbox(backend="docker"))
    assert not (tmp_path / "file").exists()
