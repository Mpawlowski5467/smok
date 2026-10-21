"""Reproducible coding evaluations with profile matrices and independent checks."""

import argparse
import asyncio
import json
import math
import sys
import tempfile
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from smok import __version__
from smok.checkpoints import Checkpoints
from smok.journal import Journal
from smok.loop import Agent
from smok.models import create_adapter
from smok.models.profiles import resolve_model
from smok.process import capture
from smok.state import state_path
from smok.tools.files import Workspace
from smok.tools.registry import SPECS, ToolRegistry
from smok.usage import Ledger, RunBudget

if __package__:
    from .evidence import AttemptEvidence
    from .reporting import compare_reports, save_report
    from .suite import (
        HERE,
        check_task,
        digest,
        load_tasks,
        scope_check,
        snapshot,
        source_fingerprint,
        write_fixture,
    )
else:
    from evidence import AttemptEvidence
    from reporting import compare_reports, save_report
    from suite import (
        HERE,
        check_task,
        digest,
        load_tasks,
        scope_check,
        snapshot,
        source_fingerprint,
        write_fixture,
    )

VARIANTS = {
    "baseline": {},
    "lean": {"prompt_style": "lean"},
    "coding": {"tool_set": "coding"},
    "minimal": {"tool_set": "minimal"},
    "exact": {"edit_format": "exact"},
    "whole-file": {"edit_format": "whole_file"},
    "lean-coding": {"prompt_style": "lean", "tool_set": "coding"},
    "no-thinking": {"reasoning_effort": "none"},
    "focused-repair": {
        "prompt_style": "lean",
        "tool_set": "minimal",
        "reasoning_effort": "none",
    },
}


def profile_data(config):
    value = asdict(config)
    url = urlsplit(config.base_url)
    value["base_url"] = urlunsplit((url.scheme, url.netloc, url.path, "", ""))
    return value


def available_tools(args, task=None):
    """Advertise the same capabilities this runner can authorize, before generation."""
    return {
        spec.name
        for spec in SPECS
        if not spec.requires_approval
        or spec.name in {"write_file", "edit_file"}
        or spec.name == "run_shell"
        and args.allow_shell
        and (task is None or task.get("shell_commands") != [])
        or spec.name.startswith("lsp_")
        and args.allow_lsp
    }


def execution_guidance(task, args):
    lines = ["\nRUN PERMISSIONS: Use only the supplied tools."]
    if not args.allow_shell:
        lines.append("Shell execution is disabled for this run.")
    elif task.get("shell_commands") is not None:
        lines.append(
            "Only these exact shell commands are permitted: "
            + json.dumps(task["shell_commands"])
            + "."
        )
    if task.get("verification_commands"):
        lines.append(
            "Run each of these project checks successfully after your final source changes: "
            + json.dumps(task["verification_commands"])
            + "."
        )
    if not args.allow_lsp:
        lines.append("Language servers are disabled for this run.")
    if not args.allow_shell and not args.allow_lsp:
        lines.append(
            "Review code statically and report runtime checks as not run. "
            "Do not attempt execution through another tool or create test files to bypass this."
        )
    if task.get("allowed_changes") is not None:
        lines.append("Allowed file changes: " + json.dumps(task["allowed_changes"]) + ".")
    return "\n".join(lines) + "\n"


async def evaluate(task, config, args, destination, *, budget=None, factory=create_adapter):
    started = time.monotonic()
    result = {
        "task": task["id"],
        "task_fingerprint": task["fingerprint"],
        "model": config.name,
        "split": task["split"],
        "category": task["category"],
        "passed": False,
        "stop_reason": "error",
        "tools": {},
        "tool_errors": 0,
        "denials": 0,
        "self_checks": 0,
        "context_samples": [],
    }
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"smok-eval-{task['id']}-") as temporary:
        root = await asyncio.to_thread(Path(temporary).resolve)
        write_fixture(root, task["files"])
        initialized = await capture(["git", "init", "-q"], root)
        if initialized.code:
            raise ValueError("Could not initialize isolated eval fixture.")
        original = snapshot(root)

        async def approve(request):
            name = request.call.name
            if name in {"write_file", "edit_file"}:
                allowed = task.get("allowed_changes")
                path = str((root / request.arguments["path"]).resolve().relative_to(root))
                return allowed is None or path in allowed
            if name == "run_shell":
                return args.allow_shell and (
                    task.get("shell_commands") is None
                    or request.arguments["command"] in task["shell_commands"]
                )
            return name.startswith("lsp_") and args.allow_lsp

        journal = Journal(root)
        registry = ToolRegistry(Workspace(root))
        registry.allowed_tools = available_tools(args, task)
        registry.enable_hooks = False
        agent = Agent(
            factory(config),
            registry,
            approver=approve,
            max_iterations=args.max_iterations,
            checkpoints=Checkpoints(root),
            journal=journal,
            budget=budget,
            turn_timeout=args.task_timeout,
            extra_system=execution_guidance(task, args),
        )
        result["profile"] = profile_data(agent.config)
        result["available_tools"] = sorted(spec.name for spec in agent.tools.specs)
        evidence = AttemptEvidence(task, root, time.monotonic() - started)
        try:
            with (destination / "events.jsonl").open("w") as log:
                try:
                    # The core owns the work deadline; allow bounded cleanup/reporting time.
                    async with asyncio.timeout(args.task_timeout + 10):
                        async for event in agent.run(task["prompt"]):
                            elapsed = time.monotonic() - started
                            evidence.observe(event, elapsed)
                            log.write(
                                json.dumps(
                                    {**event.to_dict(), "elapsed_seconds": round(elapsed, 4)}
                                )
                                + "\n"
                            )
                            log.flush()
                            journal.write(event)
                            if event.type == "tool_result":
                                if event.data["is_error"]:
                                    result["tool_errors"] += 1
                                else:
                                    name = event.data["name"]
                                    result["tools"][name] = result["tools"].get(name, 0) + 1
                            elif event.type == "permission_resolved" and not event.data["approved"]:
                                result["denials"] += 1
                            elif event.type == "self_check_started":
                                result["self_checks"] += 1
                            elif event.type == "context_usage":
                                result["context_samples"].append(event.data)
                            elif event.type == "turn_finished":
                                result["stop_reason"] = event.data["reason"]
                            elif event.type == "error":
                                result["error"] = event.data.get("message", "")[:2000]
                except TimeoutError:
                    result["stop_reason"] = "timeout"
                except (ValueError, OSError) as exc:
                    result["error"] = str(exc)[:2000]
                finally:
                    await agent.tools.close()
                    result["timing"] = evidence.finish_work(time.monotonic() - started)
            scope = scope_check(task, root)
            result["scope"] = scope
            if scope["passed"]:
                passed, output = await check_task(task, root)
                scope = scope_check(task, root)
                result["scope"] = scope
            else:
                passed, output = False, "Changes exceeded task scope or created unsafe files."
            result.update(check_passed=passed, check_output=output)
            result["verification"] = evidence.verification()
            result["tool_checks_passed"] = all(
                result["tools"].get(k, 0) >= v for k, v in task.get("expected_tools", {}).items()
            )
            result["passed"] = (
                passed
                and scope["passed"]
                and result["stop_reason"] == "complete"
                and result["tool_checks_passed"]
                and result["verification"]["passed"]
            )
            artifacts = destination / "files"
            artifacts.mkdir()
            for name, data in snapshot(root).items():
                path = root / name
                if data["kind"] == "file" and not any(
                    p.is_symlink() for p in [path, *path.parents]
                ):
                    output = artifacts / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(path.read_bytes())
            if task.get("verify_undo"):
                try:
                    await agent.undo()
                    result["undo_passed"] = snapshot(root) == original
                except Exception as exc:
                    result.update(undo_passed=False, undo_error=str(exc)[:2000])
                result["passed"] &= result["undo_passed"] and result["self_checks"] > 0
        finally:
            await agent.tools.close()
            journal.close()
            (destination / "session.jsonl").write_bytes(
                state_path(root, "sessions", journal.id + ".jsonl").read_bytes()
            )
            result["usage"] = agent.usage.export()
            result["turns"] = agent.turns
            result["iterations"] = agent.usage.requests
            result["input_tokens"] = agent.usage.input_tokens
            result["output_tokens"] = agent.usage.output_tokens
            result["seconds"] = round(time.monotonic() - started, 2)
            if "timing" in result:
                result["timing"].update(
                    setup_seconds=round(evidence.start, 4),
                    grading_and_cleanup_seconds=round(
                        max(
                            0,
                            time.monotonic()
                            - started
                            - evidence.start
                            - result["timing"]["work_seconds"],
                        ),
                        4,
                    ),
                )
            (destination / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--list", action="store_true")
    p.add_argument("--model", action="append", help="Repeat for a model matrix")
    p.add_argument("--config", type=Path)
    p.add_argument("--task", action="append")
    p.add_argument(
        "--suite",
        choices=["phase1", "phase2", "phase7", "phase10", "phase11", "phase12"],
        default="phase7",
    )
    p.add_argument("--split", choices=["tune", "holdout", "all"], default="tune")
    p.add_argument("--variant", action="append", choices=VARIANTS)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--allow-tools", action="store_true")
    p.add_argument("--allow-shell", action="store_true")
    p.add_argument("--allow-lsp", action="store_true")
    p.add_argument("--max-iterations", type=int, default=12)
    p.add_argument("--task-timeout", type=float, default=180)
    p.add_argument("--max-requests", type=int, default=400, help="Shared cap across all cases")
    p.add_argument("--budget-tokens", type=int)
    p.add_argument("--budget-usd", type=float)
    p.add_argument(
        "--resume", type=Path, help="Resume the same plan/config/limits; repeat its flags"
    )
    p.add_argument(
        "--compare", type=Path, nargs="+", help="Compare saved reports without a provider"
    )
    return p


async def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.compare:
        print(compare_reports(args.compare))
        return 0
    tasks = load_tasks(args.suite)
    if args.task:
        unknown = set(args.task) - {t["id"] for t in tasks}
        if unknown:
            p.error("Unknown tasks: " + ", ".join(sorted(unknown)))
        tasks = [t for t in tasks if t["id"] in args.task]
    tasks = [t for t in tasks if args.split == "all" or t["split"] == args.split]
    if not tasks:
        p.error("No tasks selected; use --split holdout or --split all for held-out tasks.")
    if args.list:
        for task in tasks:
            print(f"{task['id']}\t{task['split']}\t{task['category']}")
        return 0
    if not args.allow_tools:
        p.error("Live evals require --allow-tools for fixture writes and generated-code checks.")
    if not args.allow_shell and any(t.get("verification_commands") for t in tasks):
        p.error("Selected tasks require project test execution; supply --allow-shell.")
    if not 1 <= args.repeats <= 10 or not 1 <= args.max_iterations <= 40:
        p.error("Use 1-10 repeats and 1-40 model calls per task.")
    if not math.isfinite(args.task_timeout) or not 0 < args.task_timeout <= 3600:
        p.error("Task timeout must be positive and at most 3600 seconds.")
    budget = RunBudget(
        tokens=args.budget_tokens, dollars=args.budget_usd, max_requests=args.max_requests
    )
    configs = [resolve_model(name, config_path=args.config) for name in (args.model or [None])]
    if len({c.name for c in configs}) != len(configs):
        p.error("Model selectors must be unique.")
    variants = list(dict.fromkeys(args.variant or ["baseline"]))
    profiles = {(c.name, v): replace(c, **VARIANTS[v]) for c in configs for v in variants}
    for config in profiles.values():
        config.api_key()
    plan = []
    for repeat in range(1, args.repeats + 1):
        for task_index, task in enumerate(tasks):
            order = list(profiles)
            if not (task_index + repeat) % 2:
                order.reverse()
            for model, variant in order:
                case = {
                    "task": task["id"],
                    "model": model,
                    "variant": variant,
                    "repeat": repeat,
                }
                plan.append({**case, "id": digest(case)[:20]})
    if len(plan) > 1000:
        p.error("Select at most 1,000 model/task/repeat cases.")
    spec = {
        "suite": args.suite,
        "tasks": {t["id"]: t["fingerprint"] for t in tasks},
        "task_splits": {t["id"]: t["split"] for t in tasks},
        "profiles": [profile_data(c) for c in profiles.values()],
        "profile_matrix": [
            {"model": model, "variant": variant, "profile": profile_data(config)}
            for (model, variant), config in profiles.items()
        ],
        "profile_fingerprints": [digest(asdict(c)) for c in profiles.values()],
        "plan": plan,
        "limits": {
            k: getattr(args, k)
            for k in (
                "max_iterations",
                "task_timeout",
                "max_requests",
                "budget_tokens",
                "budget_usd",
                "allow_shell",
                "allow_lsp",
            )
        },
        "source": source_fingerprint(),
        "available_tools": sorted(available_tools(args)),
    }
    fingerprint = digest(spec)
    if args.resume:
        destination = args.resume.resolve()
        if (destination / "report.json").is_symlink():
            raise ValueError("Resume report cannot be a symlink.")
        report = json.loads((destination / "report.json").read_text())
        if report.get("schema_version") != 2 or report.get("fingerprint") != fingerprint:
            raise ValueError(
                "Resume requires unchanged source, tasks, profiles, limits, and flags."
            )
        budget.usage = Ledger.restore(report["budget"]["usage"])
        budget.requests = report["budget"]["requests"]
        budget.turns = report["budget"]["turns"]
    else:
        destination = (
            HERE / "results" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + args.suite)
        )
        destination.mkdir(parents=True, mode=0o700)
        report = {
            "schema_version": 2,
            "smok_version": __version__,
            "fingerprint": fingerprint,
            "source_fingerprint": spec["source"],
            "spec": spec,
            "plan": plan,
            "results": [],
            "attempts": [],
            "status": "running",
        }

    def save():
        report["budget"] = {
            "usage": budget.usage.export(),
            "requests": budget.requests,
            "turns": budget.turns,
        }
        save_report(destination, report)

    report["status"] = "running"
    save()
    print(f"Report: {destination / 'report.json'}", flush=True)
    completed = {r["case_id"] for r in report["results"]}
    try:
        for case in plan:
            if case["id"] in completed:
                continue
            if budget.requests >= args.max_requests:
                report["status"] = "budget_limit"
                break
            task = next(t for t in tasks if t["id"] == case["task"])
            config = profiles[(case["model"], case["variant"])]
            relative = "attempts/" + case["id"] + "-" + uuid4().hex[:8]
            attempt = {**case, "evidence": relative, "status": "running"}
            report["attempts"].append(attempt)
            save()
            print(
                f"Running {case['task']} · {config.name} · {case['variant']} · "
                f"repeat {case['repeat']}…",
                flush=True,
            )
            result = await evaluate(task, config, args, destination / relative, budget=budget)
            result.update(
                case_id=case["id"],
                variant=case["variant"],
                repeat=case["repeat"],
                evidence=relative,
            )
            report["results"].append(result)
            attempt["status"] = "finished"
            save()
            print(
                f"  {'PASS' if result['passed'] else 'FAIL'} · {result['iterations']} calls · "
                f"{result['seconds']}s · {result['stop_reason']}",
                flush=True,
            )
            if result["stop_reason"] == "budget_limit":
                report["status"] = "budget_limit"
                break
        else:
            report["status"] = "complete"
    except BaseException:
        report["status"] = "interrupted"
        if report["attempts"] and report["attempts"][-1]["status"] == "running":
            report["attempts"][-1]["status"] = "interrupted"
        raise
    finally:
        save()
    return (
        0 if report["status"] == "complete" and all(r["passed"] for r in report["results"]) else 1
    )


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (ValueError, OSError) as exc:
        print(f"smok eval: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
