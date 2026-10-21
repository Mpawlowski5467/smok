"""Live, multi-turn Phase 3 smoke eval with inspectable sessions and deterministic checks."""

import argparse
import asyncio
import json
import re
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from run import check_task

from smok.checkpoints import Checkpoints
from smok.journal import Journal
from smok.loop import Agent
from smok.models import create_adapter
from smok.models.base import ModelError
from smok.models.profiles import resolve_model
from smok.tools.files import Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Message, Text
from smok.usage import BudgetExceeded, RunBudget

HERE = Path(__file__).resolve().parent
SENTINEL = "BRONZE-PINE-4721"
ORIGINAL = '"""Compatibility matters."""\n\n\ndef add(a, b):\n    return a - b\n'


async def evaluate(args, destination):
    root = destination / "workspace"
    root.mkdir(mode=0o700)
    # The results folder is ignored by the harness repository. Give this fixture its
    # own repository so parent ignore rules cannot exclude its checkpoint contents.
    init = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "init.templateDir=",
        "init",
        "--quiet",
        str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, error = await init.communicate()
    if init.returncode:
        raise ValueError("Could not initialize the evaluation fixture: " + error.decode())
    (root / "calc.py").write_text(ORIGINAL)
    # One long line forces output archiving, with a marker beyond the 12000-character preview.
    (root / "notes.txt").write_text(
        "Reference observations. " * 1300 + f"\nTAIL MARKER: {SENTINEL}\n"
    )
    config = replace(
        resolve_model(args.model, config_path=args.config),
        keep_recent=2,
        max_output_tokens=2048,
        context_window=32768,
        repo_map_tokens=500,
    )
    config.api_key()
    journal = Journal(root)
    agents, events, stages = [], [], []

    async def approve(request):
        return request.call.name in {"write_file", "edit_file"} or (
            request.call.name == "run_shell" and args.allow_shell
        )

    def create(journal, config, mode="build"):
        agent = Agent(
            create_adapter(config),
            ToolRegistry(Workspace(root), mode=mode),
            journal=journal,
            approver=approve,
            max_iterations=16,
            checkpoints=Checkpoints(root),
            budget=RunBudget(tokens=200000, max_turns=3),
        )
        agents.append(agent)
        return agent

    def consume_event(event):
        events.append(event.to_dict())
        journal.write(event)
        with (destination / "events.jsonl").open("a") as log:
            log.write(json.dumps(event.to_dict()) + "\n")
        if event.type in {"error", "budget_exhausted", "compaction_finished", "handoff_created"}:
            print(f"  {event.type}: {event.data}", flush=True)

    async def turn(agent, name, prompt):
        print(f"Running {name}…", flush=True)
        reason = None
        async for event in agent.run(prompt):
            consume_event(event)
            if event.type == "turn_finished":
                reason = event.data["reason"]
        stages.append({"name": name, "stop_reason": reason})
        if reason != "complete":
            raise ValueError(f"{name} stopped: {reason}")

    result = {"model": config.name, "passed": False, "stages": stages}
    started = time.monotonic()
    try:
        async with asyncio.timeout(args.timeout):
            first = create(journal, config, mode="plan")
            await turn(
                first,
                "plan",
                "Plan a repair of calc.py so add(a, b) returns arithmetic "
                "addition for numbers. Preserve the public name and the module docstring "
                "exactly. Only calc.py may change. Use repo_map, read calc.py, and use "
                "write_todos to track inspecting the archive and repairing and verifying "
                "the function. Do not edit yet; reply when ready.",
            )
            await turn(
                first,
                "archive",
                "Read notes.txt using read_file. Its final marker is "
                "beyond the preview: use read_output with the returned archive ID, "
                "offset 29500, limit 1200 to retrieve it. Report the actual tail marker "
                "and update the inspection todo. Keep the repair pending and do not edit.",
            )
            archive_events = [
                e
                for e in events
                if e["type"] == "tool_result"
                and e["data"]["name"] == "read_output"
                and not e["data"]["is_error"]
            ]
            result["archive_readback"] = any(
                SENTINEL in e["data"]["content"] for e in archive_events
            )
            result["todos_persisted"] = bool(first.tools.todos)
            result["plan_unchanged"] = (root / "calc.py").read_text() == ORIGINAL
            # Lower the working limit to force a real automatic compaction after resumption.
            # No synthetic messages are added: all retained history came from the live model.
            used = first.context_report()["input_tokens"] + config.max_output_tokens
            config = replace(config, context_window=max(8192, int(used * 1.05)), compact_at=0.7)
            first.model.config = config
            first.save()
            session_id = journal.id
            await first.tools.close()
            journal.close()
            journal = Journal(root, resume=session_id)
            second = create(journal, config)
            second.restore(journal.loaded)
            second.set_mode("build")
            result["resumed_without_read_grants"] = not second.tools.workspace.read_hashes
            await turn(
                second,
                "resume-and-compact",
                "Continue the planned repair, preserving "
                "the original constraints. Re-read current files, fix the function, "
                "verify representative cases, and update the todos accurately.",
            )
            result["automatic_compaction"] = any(
                e["type"] == "compaction_started" and e["data"]["automatic"] for e in events
            )
            result["compaction_completed"] = any(e["type"] == "compaction_finished" for e in events)
            passed, detail = await check_task(
                {
                    "check": """import runpy
module = runpy.run_path("calc.py")
assert module["__doc__"] == "Compatibility matters."
for a, b in [(2, 3), (-4, 1), (0, 0), (0.5, 1.25)]:
    assert module["add"](a, b) == a + b
print("Addition and preserved public API/docstring verified.")
"""
                },
                root,
            )
            result["file_check"], result["check_output"] = passed, detail
            source_files = {
                str(p.relative_to(root))
                for p in root.rglob("*")
                if p.is_file() and not {".git", ".smok", "__pycache__"}.intersection(p.parts)
            }
            result["scope_preserved"] = source_files == {"calc.py", "notes.txt"} and (
                (root / "notes.txt").read_text()
                == "Reference observations. " * 1300 + f"\nTAIL MARKER: {SENTINEL}\n"
            )
            handoff_path = None
            async for event in second.handoff():
                consume_event(event)
                if event.type == "handoff_created":
                    handoff_path = Path(event.data["path"])
            result["handoff_created"] = handoff_path is not None
            result["original_session"] = journal.id
            result["original_usage"] = second.usage.export()
            journal.close()
            journal = Journal(root)
            fresh = create(journal, replace(config, context_window=32768))
            fresh.messages = [
                Message(
                    "user",
                    [
                        Text(
                            "User-provided handoff context; re-read files before editing.\n"
                            + handoff_path.read_text()
                        )
                    ],
                )
            ]
            fresh.save()
            before = (root / "calc.py").read_bytes()
            await turn(
                fresh,
                "fresh-handoff",
                "State the preserved function name and exact "
                "module docstring from this handoff. Do not edit any files.",
            )
            answer = " ".join(b.text for b in fresh.messages[-1].content if isinstance(b, Text))
            result["handoff_recall"] = (
                bool(re.search(r"\badd\b", answer)) and "Compatibility matters." in answer
            )
            result["fresh_session"] = journal.id
            result["fresh_usage"] = fresh.usage.export()
            result["fresh_session_isolated"] = (
                fresh.turns == 1 and journal.id != result["original_session"]
            )
            result["handoff_unchanged"] = (root / "calc.py").read_bytes() == before
            result["passed"] = all(
                result[key]
                for key in (
                    "archive_readback",
                    "todos_persisted",
                    "plan_unchanged",
                    "resumed_without_read_grants",
                    "automatic_compaction",
                    "compaction_completed",
                    "file_check",
                    "scope_preserved",
                    "handoff_created",
                    "handoff_recall",
                    "fresh_session_isolated",
                    "handoff_unchanged",
                )
            )
    except (ValueError, OSError, TimeoutError, ModelError, BudgetExceeded) as exc:
        result["error"] = str(exc) or "Evaluation timed out."
    finally:
        for agent in agents:
            await agent.tools.close()
        journal.close()
    result["seconds"] = round(time.monotonic() - started, 2)
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--allow-tools", action="store_true")
    parser.add_argument("--allow-shell", action="store_true")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument(
        "--finish-handoff",
        type=Path,
        help="Finish handoff/recall from a prior Phase 3 results directory",
    )
    args = parser.parse_args()
    if not args.allow_tools:
        parser.error("Live evals require --allow-tools for writes in a disposable fixture.")
    destination = HERE / "results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ-phase3")
    destination.mkdir(parents=True, mode=0o700)
    result = (
        await finish_handoff(args, destination)
        if args.finish_handoff
        else await evaluate(args, destination)
    )
    (destination / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"{'PASS' if result['passed'] else 'FAIL'} · {result['seconds']}s")
    print(f"Report: {destination / 'report.json'}")
    return 0 if result["passed"] else 1


async def finish_handoff(args, destination):
    """Retain the original report and run only the unfinished export/recall stages."""
    previous = args.finish_handoff.resolve()
    prior = json.loads((previous / "report.json").read_text())
    required = (
        "archive_readback",
        "todos_persisted",
        "plan_unchanged",
        "resumed_without_read_grants",
        "automatic_compaction",
        "compaction_completed",
        "file_check",
    )
    if not all(prior.get(key) for key in required):
        raise ValueError("The previous evaluation must have passed the resume/repair stages.")
    root = previous / "workspace"
    original_id = prior.get("original_session")
    if original_id is None:
        prior_events = [
            json.loads(line) for line in (previous / "events.jsonl").read_text().splitlines()
        ]
        original_id = next(
            event["data"]["session_id"] for event in prior_events if event["type"] == "turn_started"
        )
    journal = Journal(root, resume=original_id)
    config = replace(
        resolve_model(args.model, config_path=args.config),
        **journal.loaded.get("context_settings", {}),
    )
    agents = []
    started = time.monotonic()
    result = {
        "model": config.name,
        "passed": False,
        "previous_report": str(previous / "report.json"),
        "original_session": original_id,
        "checks": {k: prior[k] for k in required},
    }

    def create():
        agent = Agent(
            create_adapter(config),
            ToolRegistry(Workspace(root)),
            journal=journal,
            budget=RunBudget(tokens=100000),
            self_check=False,
        )
        agents.append(agent)
        return agent

    def emit(event):
        journal.write(event)
        with (destination / "events.jsonl").open("a") as log:
            log.write(json.dumps(event.to_dict()) + "\n")

    try:
        async with asyncio.timeout(args.timeout):
            resumed = create()
            resumed.restore(journal.loaded)
            print("Resuming saved session to export handoff…", flush=True)
            handoff_path = None
            async for event in resumed.handoff():
                emit(event)
                if event.type == "handoff_created":
                    handoff_path = Path(event.data["path"])
            result["checks"]["handoff_created"] = handoff_path is not None
            result["handoff_path"] = str(handoff_path)
            result["original_usage"] = resumed.usage.export()
            journal.close()
            journal = Journal(root)
            fresh = create()
            fresh.set_mode("plan")
            raw = handoff_path.read_text()
            fresh.messages = [Message("user", [Text("User-provided handoff reference:\n" + raw)])]
            fresh.save()
            print("Checking handoff recall in a fresh session…", flush=True)
            async for event in fresh.run(
                "State the preserved function name and exact module "
                "docstring from the handoff. Do not edit any files."
            ):
                emit(event)
                if event.type == "turn_finished":
                    result["stop_reason"] = event.data["reason"]
            answer = " ".join(b.text for b in fresh.messages[-1].content if isinstance(b, Text))
            result["answer"] = answer
            result["checks"]["handoff_recall"] = (
                bool(re.search(r"\badd\b", answer)) and "Compatibility matters." in answer
            )
            result["checks"]["fresh_session_isolated"] = (
                fresh.turns == 1 and journal.id != original_id
            )
            result["fresh_session"] = journal.id
            result["fresh_usage"] = fresh.usage.export()
            result["passed"] = (
                all(result["checks"].values()) and result["stop_reason"] == "complete"
            )
    except (ValueError, OSError, TimeoutError, ModelError, BudgetExceeded) as exc:
        result["error"] = str(exc) or "Evaluation timed out."
    finally:
        for agent in agents:
            await agent.tools.close()
        journal.close()
    result["seconds"] = round(time.monotonic() - started, 2)
    return result


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
