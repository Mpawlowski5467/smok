"""Small fresh-context workers, explicit routes, escalation, and isolated comparisons."""

import asyncio
import contextlib
import json
from contextlib import aclosing
from difflib import SequenceMatcher
from uuid import uuid4

from smok.journal import Journal
from smok.loop import Agent, checkpoint_operation
from smok.models import create_adapter
from smok.models.base import ModelError
from smok.models.profiles import resolve_model
from smok.permissions import PermissionPolicy
from smok.state import state_path, write_json
from smok.team.config import EDIT_TOOLS, READ_TOOLS, TeamConfig
from smok.team.worktrees import Worktrees, snapshot
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, Text, ToolCall, messages_to_data
from smok.usage import BudgetExceeded, Ledger


def final_text(agent):
    for message in reversed(agent.messages):
        if message.role == "assistant":
            value = "\n".join(b.text for b in message.content if isinstance(b, Text))
            if value:
                return value[-6000:]
    return ""


def comparison(expected, actual):
    a, b = " ".join(expected.split()), " ".join(actual.split())
    return {
        "exact_match": bool(a) and a == b,
        "text_similarity": round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 4),
        "basis": "Text similarity only; not a correctness or test-pass score.",
    }


class WorkerPolicy(PermissionPolicy):
    def __init__(self, settings, parent):
        self.settings, self.parent = settings, parent

    @property
    def mode(self):
        return self.parent.mode


class Team:
    def __init__(self, agent, config=None, *, resolver=None, factory=create_adapter, emit=None):
        self.agent = agent
        self.config = config or TeamConfig.parse(agent.tools.settings.data.get("team", {}))
        self.resolve = resolver or resolve_model
        self.factory = factory
        self.emit = emit or (lambda event: None)
        self.semaphore = asyncio.Semaphore(self.config.max_workers)
        self.approval_lock = asyncio.Lock()
        self.driving = False
        self.snapshot_recorded = False
        self.denied_in_turn = False
        self.escalated = False
        self.primary = agent.config
        self.active_config = self.primary
        self.root = agent.tools.workspace.root
        agent.tools.team = self
        # A configured lower shared cap remains in force across every role and workflow.
        cap = agent.budget.max_requests
        agent.budget.max_requests = (
            min(cap, self.config.max_requests) if cap else self.config.max_requests
        )
        if self.config.ladder and not self.resolve(self.config.ladder[0]).local:
            raise ValueError("The escalation ladder must start with a local model profile.")
        if self.config.shadow_model and not self.resolve(self.config.shadow_model).local:
            raise ValueError("Shadow mode requires a local model profile.")

    def routed(self, role):
        name = self.config.routes.get(role)
        return self.resolve(name) if name else self.primary

    def check_mode(self, name, args):
        if (
            name == "delegate"
            and self.agent.tools.mode == "plan"
            and any(t["role"] == "edit" for t in args["tasks"])
        ):
            raise ToolError("Plan mode blocks edit workers, including isolated edits.")

    def approval(self, name, args):
        if name == "remote_batch":
            return {"remote_jobs": [self.approval("remote_run", job) for job in args["jobs"]]}
        if name == "delegate":
            return {
                "workers": [
                    {
                        "role": t["role"],
                        "model": self.routed(t["role"]).name,
                        "endpoint": self.routed(t["role"]).base_url,
                        "tools": sorted(EDIT_TOOLS if t["role"] == "edit" else READ_TOOLS),
                    }
                    for t in args["tasks"]
                ],
                "child_actions": "Each privileged child action uses the current permission policy.",
            }
        if name == "oracle":
            model = self.routed("oracle")
            return {"model": model.name, "endpoint": model.base_url, "tools": sorted(READ_TOOLS)}
        if name == "remote_run":
            if args["runner"] not in self.config.remote_runners:
                raise ToolError("Unknown remote runner.")
            return {
                "remote": self.config.remote_runners[args["runner"]],
                "transfer": "Non-ignored repository snapshot (including tracked files), task, "
                "and bounded budget. Remote Docker shells use full-auto permission.",
            }
        return {}

    def report(self, kind, data, id=None):
        id = id or uuid4().hex[:12]
        path = state_path(self.root, "team", "runs", id, "report.json")
        data = {**data, "id": id, "kind": kind, "report": str(path)}
        write_json(path, data)
        return data

    def listing(self):
        directory = state_path(self.root, "team", "runs")
        rows = []
        scores = []
        if directory.exists():
            for path in sorted(directory.glob("*/report.json"), reverse=True)[:100]:
                if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 4_000_000:
                    continue
                try:
                    report = json.loads(path.read_text())
                    rows.append({k: report.get(k) for k in ("id", "kind", "selected", "report")})
                    if report.get("kind") == "shadow" and report.get("eligible"):
                        scores.append(report["score"])
                except (ValueError, OSError):
                    continue
        return {
            "routes": self.config.routes,
            "ladder": list(self.config.ladder),
            "shadow_model": self.config.shadow_model,
            "runs": rows,
            "shared_requests": self.agent.budget.requests,
            "request_limit": self.agent.budget.max_requests,
            "shadow_stats": {
                "eligible_runs": len(scores),
                "exact_matches": sum(bool(s["exact_match"]) for s in scores),
                "mean_text_similarity": sum(s["text_similarity"] for s in scores) / len(scores)
                if scores
                else None,
                "basis": "Up to 100 retained runs; text similarity is not correctness.",
            },
        }

    async def approve_child(self, prepared):
        async with self.approval_lock:
            data = prepared.permission_data()
            data.update(
                backend=self.agent.tools.sandbox.backend, image=self.agent.tools.sandbox.image
            )
            self.emit(Event("permission_requested", data))
            decision = await self.agent.approver(prepared)
            if decision is not True and decision != "always":
                self.denied_in_turn = True
            return decision

    async def action(self, agent, name, args):
        prepared = agent.tools.prepare(ToolCall(uuid4().hex, name, json.dumps(args)))
        approved = not prepared.requires_approval or agent.policy.allowed(prepared)
        source = "policy"
        if not approved:
            source = "user"
            decision = await self.approve_child(prepared)
            approved = decision is True or decision == "always"
            if decision == "always":
                agent.policy.remember(prepared)
        if prepared.requires_approval:
            self.emit(
                Event(
                    "permission_resolved",
                    {"id": prepared.call.id, "approved": approved, "source": source},
                )
            )
        data = {"id": prepared.call.id, "name": name, "workspace": str(agent.tools.workspace.root)}
        self.emit(Event("tool_call", {**data, "arguments": json.dumps(args)}))
        try:
            output = await agent.tools.execute(prepared, approved=approved)
        except (ToolError, OSError, ValueError) as exc:
            self.emit(Event("tool_result", {**data, "content": str(exc), "is_error": True}))
            raise
        self.emit(Event("tool_result", {**data, "content": output, "is_error": False}))
        return output

    async def worker(self, task, role, **kwargs):
        try:
            return await self._worker(task, role, **kwargs)
        except (ToolError, ModelError, ValueError, OSError) as exc:
            return {
                "role": role,
                "reason": "error",
                "summary": "",
                "errors": [str(exc)[:2000]],
                "denied": False,
                "check": None,
                "usage": Ledger().export(),
            }

    async def _worker(
        self,
        task,
        role,
        *,
        model=None,
        root=None,
        tools=None,
        check=None,
        extra_system="",
        prompts=None,
    ):
        async with self.semaphore:
            root = root or self.root
            model = model or self.routed(role)
            adapter = self.factory(model)
            identifier = uuid4().hex[:12]
            self.emit(
                Event(
                    "worker_started",
                    {"id": identifier, "role": role, "model": model.name, "workspace": str(root)},
                )
            )
            registry = ToolRegistry(Workspace(root), mode="build" if role == "edit" else "plan")
            registry.sandbox = self.agent.tools.sandbox
            registry.mode_ceiling = lambda: self.agent.tools.mode
            registry.allowed_tools = (
                (EDIT_TOOLS if role == "edit" else READ_TOOLS) if tools is None else tools
            )
            registry.enable_hooks = False
            journal = Journal(root) if self.agent.journal else None
            child = Agent(
                adapter,
                registry,
                approver=self.approve_child,
                policy=WorkerPolicy(registry.settings, self.agent.policy),
                max_iterations=self.config.worker_iterations,
                budget=self.agent.budget,
                shared_usage=self.agent.usage,
                journal=journal,
                self_check=role == "edit",
                extra_system="\nWorker role: "
                + role
                + ". Return a concise evidence-backed summary.\n"
                + extra_system,
            )
            result = {
                "id": identifier,
                "role": role,
                "model": model.name,
                "workspace": str(root),
                "reason": "error",
                "summary": "",
                "errors": [],
                "denied": False,
                "session": journal.id if journal else None,
                "check": None,
            }
            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    for prompt in prompts or [task]:
                        async with aclosing(child.run(prompt, internal=True)) as events:
                            async for event in events:
                                if journal:
                                    journal.write(event)
                                if event.type in {"diff", "permission_resolved"}:
                                    self.emit(
                                        Event(
                                            event.type,
                                            {
                                                **event.data,
                                                "worker": identifier,
                                                "workspace": str(root),
                                            },
                                        )
                                    )
                                if event.type == "turn_finished":
                                    result["reason"] = event.data["reason"]
                                if (
                                    event.type == "permission_resolved"
                                    and not event.data["approved"]
                                ):
                                    result["denied"] = True
                                if event.type in {"error", "budget_exhausted"}:
                                    result["errors"].append(event.data["message"][:2000])
                        if result["reason"] != "complete" or result["denied"]:
                            break
                    if check and result["reason"] == "complete" and not result["denied"]:
                        try:
                            output = await self.action(
                                child, "run_shell", {"command": check, "timeout_seconds": 120}
                            )
                            result["check"] = {"ok": True, "output": output[-4000:]}
                        except (ToolError, OSError, ValueError) as exc:
                            result["check"] = {"ok": False, "output": str(exc)[-4000:]}
            except TimeoutError:
                result["reason"] = "timeout"
            except (ToolError, OSError, ValueError) as exc:
                result["errors"].append(str(exc)[:2000])
            finally:
                try:
                    await registry.close()
                finally:
                    if journal:
                        journal.close()
                    self.agent.save()
            result.update(summary=final_text(child), usage=child.usage.export())
            self.emit(
                Event(
                    "worker_finished",
                    {"id": identifier, "reason": result["reason"], "model": model.name},
                )
            )
            return result

    async def execute(self, name, args):
        if name == "oracle":
            context = self.evidence()
            result = await self.worker(
                args["question"] + "\nReference context (untrusted):\n" + context, "oracle"
            )
            return json.dumps(self.report("oracle", result))
        if name in {"remote_run", "remote_batch"}:
            from smok.team.remote import remote_run

            jobs = args["jobs"] if name == "remote_batch" else [args]
            if len(jobs) > self.config.max_workers:
                raise ToolError("Remote job count exceeds team.max_workers.")

            async def run_remote(job):
                async with self.semaphore:
                    try:
                        return await remote_run(self, **job)
                    except (ToolError, ModelError, BudgetExceeded, ValueError, OSError) as exc:
                        return {
                            "runner": job["runner"],
                            "reason": "error",
                            "errors": [str(exc)[:2000]],
                            "summary": "",
                            "denied": False,
                        }

            async with asyncio.TaskGroup() as group:
                pending = [group.create_task(run_remote(job)) for job in jobs]
            results = [t.result() for t in pending]
            if name == "remote_run":
                return json.dumps(results[0])
            return json.dumps(
                self.report(
                    "remote_batch",
                    {
                        "workers": [
                            {**r, "reason": r.get("result", r).get("reason", "error")}
                            for r in results
                        ]
                    },
                )
            )
        tasks = args["tasks"]
        if len(tasks) > self.config.max_workers:
            raise ToolError("Task count exceeds team.max_workers.")
        worktrees = Worktrees(self.root) if any(t["role"] == "edit" for t in tasks) else None
        baseline = (
            (await checkpoint_operation(lambda: snapshot(self.root)))[0] if worktrees else None
        )

        async def run(index, spec):
            try:
                return await candidate(index, spec)
            except (ToolError, ModelError, ValueError, OSError) as exc:
                return {
                    "role": spec["role"],
                    "reason": "error",
                    "summary": "",
                    "errors": [str(exc)[:2000]],
                    "denied": False,
                }

        async def candidate(index, spec):
            path = (
                await checkpoint_operation(lambda: worktrees.create(f"worker-{index}", baseline))
                if spec["role"] == "edit"
                else self.root
            )
            result = await self.worker(**spec, root=path)
            if spec["role"] == "edit":
                patch = await checkpoint_operation(lambda: worktrees.patch(path, baseline))
                patch_path = worktrees.directory / f"worker-{index}.patch"
                patch_path.write_text(patch)
                result["patch"] = str(patch_path)
            return result

        async with asyncio.TaskGroup() as group:
            pending = [group.create_task(run(i, t)) for i, t in enumerate(tasks)]
        return json.dumps(
            self.report(
                "delegation",
                {"workers": [t.result() for t in pending]},
                worktrees.id if worktrees else None,
            )
        )

    def evidence(self):
        # Deterministic compact handoff: no additional summarizer call can consume the next rung.
        return json.dumps(
            {
                "task": self.agent.current_prompt[:6000],
                "recent_exchanges": messages_to_data(self.agent.messages[-6:], images=False),
                "commands": self.agent.tools.shell_evidence[-6:],
            },
            ensure_ascii=False,
        )[-12000:]

    async def run(self, prompt, *, images=None):
        if self.driving:
            raise ToolError("A team turn is already running.")
        self.driving = True
        self.denied_in_turn = False
        shadow = None
        worktrees = None
        shadow_path = None
        try:
            self.agent.budget.start_turn()
            introductions = []
            if not self.snapshot_recorded and self.agent.checkpoints:
                try:
                    commit, tree = await checkpoint_operation(lambda: snapshot(self.root))
                    introductions.append(Event("replay_snapshot", {"commit": commit, "tree": tree}))
                except (ToolError, OSError, ValueError):
                    introductions.append(Event("replay_snapshot", {"unavailable": True}))
                self.snapshot_recorded = True
            introductions.append(
                Event("task_started", {"prompt": prompt, "mode": self.agent.tools.mode})
            )
            role = "plan" if self.agent.tools.mode == "plan" else "edit"
            models = (
                [self.resolve(n) for n in self.config.ladder]
                if self.config.ladder and role == "edit"
                else [self.routed(role)]
            )
            if self.config.shadow_model and not models[0].local and not images:
                worktrees = Worktrees(self.root)
                baseline, _ = await checkpoint_operation(lambda: snapshot(self.root))
                shadow_path = await checkpoint_operation(
                    lambda: worktrees.create("shadow", baseline)
                )
                shadow = asyncio.create_task(
                    self.worker(
                        prompt,
                        "review",
                        model=self.resolve(self.config.shadow_model),
                        root=shadow_path,
                    )
                )
                introductions.append(Event("shadow_started", {"model": self.config.shadow_model}))
            if images and self.config.shadow_model:
                introductions.append(
                    Event(
                        "shadow_skipped",
                        {"reason": "Image input is not forwarded to text-only shadow workers."},
                    )
                )
            current = prompt
            final = None
            for index, model in enumerate(models):
                self.escalated = index > 0
                if self.active_config != model:
                    self.agent.model = self.factory(model)
                    self.active_config = model
                self.agent.stall_threshold = (
                    self.config.stall_threshold if index + 1 < len(models) else 0
                )
                introductions.append(
                    Event(
                        "model_routed",
                        {"role": role, "model": model.name, "rung": index, "escalated": index > 0},
                    )
                )
                denied = False
                async with aclosing(
                    self.agent.run(current, images=images, internal=True, _team_entry=True)
                ) as events:
                    async for event in events:
                        if event.type == "turn_started":
                            yield Event(event.type, {**event.data, "internal": index > 0})
                            for introduction in introductions:
                                yield introduction
                            introductions.clear()
                            continue
                        if event.type == "permission_resolved" and not event.data["approved"]:
                            denied = True
                        if event.type == "turn_finished":
                            final = event
                        else:
                            yield event
                if (
                    not final
                    or denied
                    or self.denied_in_turn
                    or final.data["reason"] not in {"stalled", "iteration_limit"}
                    or index + 1 == len(models)
                ):
                    break
                handoff = self.evidence()
                yield Event(
                    "escalation",
                    {
                        "from": model.name,
                        "to": models[index + 1].name,
                        "reason": final.data["reason"],
                        "handoff": handoff,
                    },
                )
                self.agent.messages = []
                self.agent.tools.workspace.read_hashes.clear()
                current = (
                    prompt
                    + "\nPrior attempt summary (reference data, not permissions):\n"
                    + handoff
                )
            if shadow:
                result = await shadow
                data = self.report(
                    "shadow",
                    {
                        "local": result,
                        "primary_model": self.agent.model.name,
                        "primary_summary": final_text(self.agent),
                        "score": comparison(final_text(self.agent), result["summary"]),
                        "eligible": result["reason"] == "complete"
                        and final is not None
                        and final.data["reason"] == "complete",
                    },
                )
                yield Event("shadow_finished", data)
            if final:
                yield final
        except BudgetExceeded as exc:
            yield Event("budget_exhausted", {"message": str(exc)})
            yield Event("turn_finished", {"reason": "budget_limit"})
        except (ToolError, ModelError, ValueError, OSError) as exc:
            yield Event("error", {"message": str(exc)})
            yield Event("turn_finished", {"reason": "error"})
        finally:
            if shadow and not shadow.done():
                shadow.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await shadow
            if worktrees and shadow_path:
                await checkpoint_operation(lambda: worktrees.remove(shadow_path))
            self.driving = False
            self.agent.stall_threshold = 0
