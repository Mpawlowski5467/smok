"""One-shot JSON over SSH. Authentication and host verification stay with OpenSSH."""

import asyncio
import base64
import io
import json
import os
import shlex
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from smok.loop import Agent, checkpoint_operation
from smok.models import create_adapter
from smok.permissions import PermissionPolicy
from smok.process import capture
from smok.settings import Sandbox
from smok.state import state_path
from smok.team.config import EDIT_TOOLS
from smok.team.coordinator import final_text
from smok.team.worktrees import Worktrees, git, snapshot
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.usage import BudgetExceeded, Ledger, RunBudget

MAX_ARCHIVE = 8 * 1024 * 1024


async def read_request():
    limit = 12 * 1024 * 1024
    if stat.S_ISREG(os.fstat(sys.stdin.fileno()).st_mode):
        raw = await asyncio.to_thread(sys.stdin.buffer.readline, limit + 1)
        if len(raw) > limit or not raw.endswith(b"\n"):
            raise ValueError("Runner request exceeds its limit or lacks a terminating newline.")
        return json.loads(raw)
    reader = asyncio.StreamReader(limit=12 * 1024 * 1024)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer
    )
    try:
        async with asyncio.timeout(30):
            raw = await reader.readline()
        if not raw.endswith(b"\n"):
            raise ValueError("Runner request must be one newline-terminated JSON record.")
        return json.loads(raw)
    finally:
        transport.close()


def unpack(encoded, root):
    if not isinstance(encoded, str) or len(encoded) > MAX_ARCHIVE * 4 // 3 + 4:
        raise ValueError("Remote snapshot exceeds 8 MiB.")
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > MAX_ARCHIVE:
        raise ValueError("Remote snapshot exceeds 8 MiB.")
    total, seen = 0, set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            total += member.size
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or not path.parts
                or any(p.casefold() in {".git", ".smok"} for p in path.parts)
                or not (member.isdir() or member.isfile())
                or path.as_posix().casefold() in seen
                or member.size < 0
                or total > MAX_ARCHIVE
                or len(seen) >= 2000
            ):
                raise ValueError("Unsafe or oversized remote archive member.")
            seen.add(path.as_posix().casefold())
            target = root.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source:
                    target.write_bytes(source.read(MAX_ARCHIVE + 1))
                target.chmod(0o700 if member.mode & 0o111 else 0o600)


def ssh_command(config):
    return [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        "--",
        config["host"],
        shlex.join(config["command"]),
    ]


async def remote_run(team, runner, task):
    config = team.config.remote_runners[runner]
    baseline, _ = await checkpoint_operation(lambda: snapshot(team.root))
    archive = await checkpoint_operation(
        lambda: git(team.root, "archive", "--format=tar", baseline, limit=MAX_ARCHIVE)
    )
    budget = team.agent.budget
    if budget.tokens is None:
        raise ToolError(
            "Remote runs require --budget-tokens to allocate a bounded remote allowance."
        )
    pending_tokens = sum(row[0] for row in budget.reservations.values())
    allowance = min(
        50000,
        budget.tokens - budget.usage.input_tokens - budget.usage.output_tokens - pending_tokens,
    )
    calls = min(team.config.worker_iterations, (budget.max_requests or 48) - budget.requests)
    dollars = None
    if budget.dollars is not None:
        if budget.usage.unpriced_requests or any(
            r[1] is None for r in budget.reservations.values()
        ):
            raise ToolError("Cannot allocate remote dollars with unpriced requests outstanding.")
        dollars = (
            budget.dollars
            - budget.usage.known_cost_usd
            - sum(r[1] for r in budget.reservations.values())
        )
    if allowance <= 0 or calls <= 0 or dollars is not None and dollars <= 0:
        raise BudgetExceeded("No shared budget remains for a remote worker.")
    payload = {
        "version": 1,
        "task": task,
        "archive": base64.b64encode(archive).decode(),
        "tokens": allowance,
        "dollars": dollars,
        "requests": calls,
        "timeout_seconds": team.config.timeout_seconds,
    }
    # Book the entire allocation before awaiting transport. Interrupted transports stay charged.
    budget.requests += calls
    reservation = "remote-" + uuid4().hex
    budget.reservations[reservation] = (allowance, dollars)
    charged = Ledger(
        requests=calls,
        input_tokens=allowance,
        estimated_requests=calls,
        known_cost_usd=dollars or 0,
        unpriced_requests=0 if dollars is not None else calls,
    )
    try:
        result = await capture(
            ssh_command(config),
            team.root,
            seconds=team.config.timeout_seconds + 30,
            limit=4 * 1024 * 1024,
            input_data=(json.dumps(payload) + "\n").encode(),
        )
        if result.code or result.timed_out or result.truncated:
            raise ToolError(
                "SSH runner did not return a complete result. The allocation remains charged; "
                "the remote deadline bounds any work still running."
            )
        response = json.loads(result.output)
        if (
            not isinstance(response, dict)
            or response.get("version") != 1
            or not isinstance(response.get("patch"), str)
            or len(response["patch"]) > 2 * 1024 * 1024
        ):
            raise ToolError("Invalid remote result.")
        usage = Ledger.restore(response.get("usage"))
        if (
            usage.requests > calls
            or usage.input_tokens + usage.output_tokens > allowance
            or dollars is not None
            and (usage.unpriced_requests or usage.known_cost_usd > dollars)
        ):
            raise ToolError("Remote usage exceeded its allocation; full allowance charged.")
        charged = usage
        id = uuid4().hex[:12]
        patch = state_path(team.root, "team", "runs", id, "remote.patch")
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text(response.pop("patch"))
        return team.report(
            "remote",
            {"runner": runner, "baseline": baseline, "patch": str(patch), "result": response},
            id,
        )
    finally:
        budget.reservations.pop(reservation)
        budget.usage.merge(charged)
        team.agent.usage.merge(charged)
        team.agent.save()


async def run_request(
    payload, *, config, root, sandbox, factory=create_adapter, deadline_seconds=600
):
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "task",
        "archive",
        "tokens",
        "dollars",
        "requests",
        "timeout_seconds",
    }:
        raise ValueError("Invalid runner request.")
    if (
        payload["version"] != 1
        or not isinstance(payload["task"], str)
        or not 1 <= len(payload["task"]) <= 12000
    ):
        raise ValueError("Invalid remote task.")
    for key, cap in (("tokens", 50000), ("requests", 40), ("timeout_seconds", 1800)):
        if type(payload[key]) is not int or not 1 <= payload[key] <= cap:
            raise ValueError("Invalid remote budget or deadline.")
    if sandbox.backend != "docker":
        raise ValueError("Remote runners require the Docker shell backend; no host fallback.")
    budget = RunBudget(
        tokens=payload["tokens"], dollars=payload["dollars"], max_requests=payload["requests"]
    )
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smok-runner-", dir=root) as directory:
        workspace = Path(directory)
        unpack(payload["archive"], workspace)
        git(workspace, "init", "-q")
        baseline, _ = snapshot(workspace)
        registry = ToolRegistry(Workspace(workspace))
        registry.sandbox = Sandbox("docker", sandbox.image, sandbox.network)
        registry.allowed_tools, registry.enable_hooks = EDIT_TOOLS, False
        agent = Agent(
            factory(config),
            registry,
            policy=PermissionPolicy(registry.settings, "full-auto"),
            budget=budget,
            max_iterations=payload["requests"],
        )
        reason, errors = "error", []
        try:
            async with asyncio.timeout(min(deadline_seconds, payload["timeout_seconds"])):
                async for event in agent.run(payload["task"]):
                    if event.type == "turn_finished":
                        reason = event.data["reason"]
                    elif event.type in {"error", "budget_exhausted"}:
                        errors.append(event.data["message"][:2000])
        except TimeoutError:
            reason = "timeout"
        finally:
            await registry.close()
        patch = Worktrees(workspace).patch(workspace, baseline)
        return {
            "version": 1,
            "reason": reason,
            "summary": final_text(agent),
            "errors": errors,
            "usage": agent.usage.export(),
            "patch": patch,
            "sandbox": "docker",
            "commands": registry.shell_evidence[-20:],
        }
