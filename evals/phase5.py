"""Live Phase 5 checks in a disposable fixture, using the same core as the CLI."""

import argparse
import asyncio
import json
import shlex
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from smok.checkpoints import Checkpoints
from smok.journal import Journal
from smok.loop import Agent
from smok.models import create_adapter
from smok.models.profiles import resolve_model
from smok.permissions import PermissionPolicy
from smok.team.config import TeamConfig
from smok.team.coordinator import Team
from smok.team.lab import council, replay
from smok.team.worktrees import git
from smok.tools.files import Workspace
from smok.tools.registry import ToolRegistry
from smok.usage import RunBudget


async def run(args):
    if not args.allow_tools:
        raise ValueError(
            "Use --allow-tools to authorize model edits and commands inside this eval fixture."
        )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ-phase5")
    directory = Path(__file__).parent / "results" / stamp
    root = (directory / "workspace").resolve()
    root.mkdir(parents=True)
    git(root, "init", "-q")
    (root / ".gitignore").write_text(".smok/\n__pycache__/\n")
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (root / "notes.txt").write_text("Fixture marker: COPPER-RAVEN-5197\n")
    config = replace(
        resolve_model(args.model),
        max_output_tokens=1536,
        repo_map_tokens=300,
        timeout_seconds=180,
        context_window=32768,
    )
    # Aliases exercise independent route/council/shadow slots on the one installed model.
    alternate = replace(config, name="local/eval-alternate")
    primary_shadow = replace(
        config, name="local/eval-primary", local=False, prices={"input": 0, "output": 0}
    )
    configs = {c.name: c for c in (config, alternate, primary_shadow)}
    registry = ToolRegistry(Workspace(root))
    journal = Journal(root)
    agent = Agent(
        create_adapter(config),
        registry,
        policy=PermissionPolicy(registry.settings, "full-auto"),
        journal=journal,
        checkpoints=Checkpoints(root),
        max_iterations=10,
        budget=RunBudget(tokens=350000, max_turns=8),
    )

    def emit(event):
        journal.write(event)
        if event.type in {"worker_started", "worker_finished", "escalation"}:
            print(json.dumps(event.to_dict()), flush=True)

    team = Team(
        agent,
        TeamConfig(worker_iterations=10, max_requests=70, timeout_seconds=480),
        resolver=lambda n: configs[n],
        emit=emit,
    )
    rows = []
    started = time.monotonic()

    async def consume(events):
        result = []
        try:
            async for event in events:
                emit(event)
                result.append(event)
        finally:
            await events.aclose()
        return result

    check = shlex.join(
        [sys.executable, "-c", "from calc import add; assert add(19,23)==42; assert add(-2,2)==0"]
    )
    task = (
        "Fix add(a,b) in calc.py so it returns the sum. Read the file, make the smallest edit, "
        "and run this check: " + check + ". Do not edit any other source file."
    )
    try:
        workers = json.loads(
            await team.execute(
                "delegate",
                {
                    "tasks": [
                        {
                            "role": "explore",
                            "task": (
                                "Read notes.txt and return the exact fixture marker "
                                "in one sentence."
                            ),
                        },
                        {
                            "role": "review",
                            "task": (
                                "Read calc.py and explain the arithmetic bug briefly. Do not edit."
                            ),
                        },
                    ]
                },
            )
        )
        rows.append(
            {
                "name": "parallel_fresh_workers",
                "passed": all(w["reason"] == "complete" for w in workers["workers"])
                and "COPPER-RAVEN-5197" in workers["workers"][0]["summary"]
                and "return a - b" in (root / "calc.py").read_text(),
                "report": workers["report"],
            }
        )
        print(json.dumps(rows[-1]), flush=True)
        events = await consume(council(team, task, [config.name, alternate.name], check=check))
        report = next(e.data for e in events if e.type == "council_finished")
        rows.append(
            {
                "name": "council_test_selection",
                "passed": report["selected"] is not None
                and all(r["check"] and r["check"]["ok"] for r in report["candidates"])
                and "return a - b" in (root / "calc.py").read_text(),
                "report": report["report"],
            }
        )
        print(json.dumps(rows[-1]), flush=True)
        events = await consume(agent.run(task))
        original = (root / "calc.py").read_text()
        rows.append(
            {
                "name": "routed_primary",
                "passed": events[-1].data.get("reason") == "complete"
                and "return a + b" in original,
            }
        )
        print(json.dumps(rows[-1]), flush=True)
        events = await consume(replay(team, journal.id, check=check))
        report = next(e.data for e in events if e.type == "replay_finished")
        rows.append(
            {
                "name": "real_session_replay",
                "passed": events[-1].data.get("reason") == "complete"
                and (root / "calc.py").read_text() == original,
                "report": report["report"],
            }
        )
        print(json.dumps(rows[-1]), flush=True)
        oracle = json.loads(
            await team.execute(
                "oracle",
                {
                    "question": (
                        "Read calc.py. Does add now handle negative integers? "
                        "Explain in one sentence."
                    )
                },
            )
        )
        rows.append(
            {
                "name": "oracle",
                "passed": oracle["reason"] == "complete" and bool(oracle["summary"]),
                "report": oracle["report"],
            }
        )
        print(json.dumps(rows[-1]), flush=True)
        team.config = replace(team.config, shadow_model=config.name)
        team.primary = primary_shadow
        agent.set_mode("plan")
        events = await consume(agent.run("Read notes.txt and answer with only the fixture marker."))
        report = next(e.data for e in events if e.type == "shadow_finished")
        rows.append(
            {
                "name": "shadow_comparison",
                "passed": report["eligible"] and "COPPER-RAVEN-5197" in report["local"]["summary"],
                "report": report["report"],
                "score": report["score"],
            }
        )
        print(json.dumps(rows[-1]), flush=True)
        agent.set_mode("build")
        job = json.loads(
            await team.action(
                agent, "start_process", {"command": "printf background-ok", "timeout_seconds": 10}
            )
        )
        await registry.jobs.get(job["id"])["task"]
        output = json.loads(registry.jobs.poll(job["id"]))
        rows.append(
            {
                "name": "background_process",
                "passed": output["exit_code"] == 0 and "background-ok" in output["output"],
            }
        )
        print(json.dumps(rows[-1]), flush=True)
    finally:
        await registry.close()
        journal.close()
        report = {
            "model": config.name,
            "note": (
                "Council and shadow use aliases of the same installed local model. "
                "No frontier API, homelab SSH, or live Docker claim."
            ),
            "seconds": round(time.monotonic() - started, 2),
            "checks": rows,
            "passed": len(rows) == 7 and all(r["passed"] for r in rows),
            "usage": agent.budget.usage.export(),
            "session": journal.id,
            "workspace": str(root),
        }
        target = directory / "report.json"
        target.write_text(json.dumps(report, indent=2) + "\n")
        print(str(target.resolve()), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--model", default="ollama/qwen3.6:27b-mlx")
    cli.add_argument("--allow-tools", action="store_true")
    raise SystemExit(asyncio.run(run(cli.parse_args())))
