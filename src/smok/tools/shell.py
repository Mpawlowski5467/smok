import asyncio
import contextlib
import os
import shutil
from pathlib import Path
from uuid import uuid4

from smok.process import capture
from smok.settings import Sandbox
from smok.tools.files import ToolError


def docker_command(command: str, root: Path, sandbox: Sandbox, name: str) -> list[str]:
    if "," in str(root):
        raise ToolError("Docker bind mounts do not support this workspace path (contains a comma).")
    argv = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--pull",
        "never",
        "--init",
        "--network",
        "bridge" if sandbox.network else "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--memory",
        "1g",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=128m",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--env",
        "HOME=/tmp",
        "--env",
        "GIT_OPTIONAL_LOCKS=0",
        "--mount",
        f"type=bind,src={root},dst=/workspace",
        "--workdir",
        "/workspace",
    ]
    for protected in (".git", ".smok"):
        path = root / protected
        if path.exists():
            argv += ["--mount", f"type=bind,src={path},dst=/workspace/{protected},readonly"]
    return argv + ["--entrypoint", "/bin/sh", sandbox.image, "-c", command]


async def run_shell(
    command: str,
    root: Path,
    timeout_seconds: float = 30,
    *,
    sandbox: Sandbox | None = None,
    output_limit: int = 24000,
    input_data: bytes | None = None,
) -> str:
    sandbox = sandbox or Sandbox()
    name = f"smok-{uuid4().hex}"
    if sandbox.backend == "docker" and not shutil.which("docker"):
        raise ToolError(
            "Docker is not installed. Install it or explicitly choose the host backend."
        )
    argv = (
        docker_command(command, root, sandbox, name)
        if sandbox.backend == "docker"
        else [
            "/bin/sh",
            "-c",
            command,
        ]
    )
    if input_data is not None and sandbox.backend == "docker":
        argv.insert(2, "--interactive")
    try:
        options = {"input_data": input_data} if input_data is not None else {}
        result = await capture(argv, root, seconds=timeout_seconds, limit=output_limit, **options)
    finally:
        if sandbox.backend == "docker":
            # Killing the client alone does not stop its container.
            task = asyncio.create_task(capture(["docker", "rm", "-f", name], root, seconds=10))
            with contextlib.suppress(OSError):
                await asyncio.shield(task)
    status = (
        f"Timed out after {timeout_seconds:g}s" if result.timed_out else f"Exit code: {result.code}"
    )
    output = result.output.decode("utf-8", errors="replace")
    if result.truncated:
        output += f"\n[Output truncated at {output_limit} bytes; remaining output is unavailable.]"
    text = f"{status}\n{output}"
    if result.timed_out or result.code:
        if sandbox.backend == "docker":
            text += "\nDocker mode never falls back to the host. Check the daemon and local image."
        raise ToolError(text)
    return text
