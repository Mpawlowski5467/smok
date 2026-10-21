"""Session ownership, background turns, reconnectable event delivery, and approvals."""

import asyncio
import contextlib
import json
from collections import deque
from contextlib import aclosing
from pathlib import Path
from uuid import uuid4

from smok.checkpoints import Checkpoints
from smok.extensions.workflows import connect_mcp, run_extension, run_review
from smok.gui.config import Configuration
from smok.gui.history import append_event, journal_view
from smok.images import Image, validate_images
from smok.journal import Journal
from smok.loop import Agent, checkpoint_operation
from smok.models import create_adapter
from smok.permissions import PermissionPolicy
from smok.settings import ProjectSettings
from smok.state import state_path, write_json
from smok.team.coordinator import Team
from smok.team.lab import accept, council, replay
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import Event, Message, Text, messages_to_data
from smok.usage import RunBudget


class Session:
    def __init__(self, service, root, *, resume=None, state=None, model=None):
        self.service, self.root = service, root
        self.journal = Journal(root, resume=resume)
        self.id = self.journal.id
        self.events = deque(maxlen=400)
        self.listeners = set()
        self.pending = {}
        self.task = None
        self.title = "New session"
        try:
            saved = state or self.journal.loaded
            config = service.config.resolve(model or (saved or {}).get("model"))
            settings = ProjectSettings(root)
            registry = ToolRegistry(Workspace(root), settings=settings)
            self.agent = Agent(
                service.factory(config),
                registry,
                approver=self.approve,
                policy=PermissionPolicy(settings),
                checkpoints=Checkpoints(root),
                journal=self.journal,
                budget=RunBudget(),
                max_iterations=12,
            )
            if saved:
                self.agent.restore(saved)
                self.agent.context.refresh_pins()
            if resume:
                history = journal_view(root, resume)
                self.title = history["title"]
                for event in history["events"]:
                    append_event(self.events, event)
            self.team = Team(
                self.agent, resolver=service.config.resolve, factory=service.factory, emit=self.emit
            )
            if state:
                self.emit(
                    Event(
                        "history_restored",
                        {"messages": messages_to_data(self.agent.messages, images=False)},
                    )
                )
            self.agent.save()
        except BaseException:
            self.journal.close()
            raise

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def emit(self, event):
        self.journal.write(event)
        append_event(self.events, event)
        if event.type == "turn_started" and self.title == "New session":
            self.title = event.data.get("prompt", "New session")[:90]
        packet = event.to_dict()
        for queue in tuple(self.listeners):
            if queue.full():
                # A slow client receives a fresh snapshot instead of silently missing grants.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "resync", "data": {}})
            else:
                queue.put_nowait(packet)

    async def approve(self, prepared):
        key = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        data = {
            **prepared.permission_data(),
            "request_id": key,
            "backend": self.agent.tools.sandbox.backend,
            "image": self.agent.tools.sandbox.image,
        }
        if prepared.write:
            data.update(diff=prepared.write.diff[:100_000], path=prepared.write.path)
        self.pending[key] = (future, data)
        self.emit(Event("approval_pending", data))
        try:
            # Survives browser disconnects/reconnects; never grants on timeout or disconnect.
            async with asyncio.timeout(600):
                return await future
        except TimeoutError:
            return False
        finally:
            self.pending.pop(key, None)
            self.emit(Event("approval_closed", {"request_id": key}))

    def decide(self, key, decision):
        entry = self.pending.get(key)
        if not entry or entry[0].done():
            raise ValueError("This approval is no longer pending.")
        entry[0].set_result({"allow": True, "always": "always", "deny": False}[decision])

    def view(self):
        agent = self.agent
        workers = {}
        for event in self.events:
            if event["type"] in {"worker_started", "worker_finished"}:
                data = event["data"]
                workers[data["id"]] = {
                    **workers.get(data["id"], {}),
                    **data,
                    "status": data.get("reason", "running"),
                }
        return {
            "id": self.id,
            "title": self.title,
            "workspace": str(self.root),
            "owned": True,
            "busy": self.busy,
            "state": agent.state(),
            "events": list(self.events),
            "pending": [p[1] for p in self.pending.values()],
            "context": agent.last_context
            if self.busy and agent.last_context
            else agent.context_report(),
            "checkpoints": Checkpoints(self.root).list(),
            "team": self.team.listing(),
            "workers": list(workers.values()),
            "jobs": json.loads(agent.tools.jobs.poll()),
            "extensions": agent.tools.extensions.listing(),
            "permissions": agent.policy.mode,
            "limits": {
                "budget_tokens": agent.budget.tokens,
                "budget_usd": agent.budget.dollars,
                "max_iterations": agent.max_iterations,
                "turn_timeout": agent.turn_timeout,
            },
            "vision": agent.config.vision,
            "estimates": [agent.cost_preview(m) for m in self.service.config.profiles()],
        }

    async def consume(self, stream):
        async with aclosing(stream) as events:
            async for event in events:
                self.emit(event)

    async def perform(self, action, data):
        agent, tools = self.agent, self.agent.tools
        if action == "prompt":
            images = [Image(**image) for image in data.get("images", [])]
            validate_images(agent.messages, images)
            role = "plan" if tools.mode == "plan" else "edit"
            config = (
                self.team.resolve(self.team.config.ladder[0])
                if self.team.config.ladder and role == "edit"
                else self.team.routed(role)
            )
            if images and not config.vision:
                raise ValueError(
                    "Enable vision on a compatible model profile before attaching images."
                )
            await self.consume(agent.run(data["prompt"], images=images))
        elif action == "reload":
            self.emit(Event("extension_report", json.loads(await tools.extensions.reload())))
        elif action == "compact":
            await self.consume(agent.compact())
        elif action == "review":
            await self.consume(run_review(agent, data.get("base") or None))
        elif action == "handoff":
            await self.consume(agent.handoff())
        elif action in {"skill", "recipe", "command"}:
            await self.consume(
                run_extension(
                    agent,
                    {"skill": "skills", "recipe": "recipes", "command": "commands"}[action],
                    data["name"],
                    data.get("values", {}),
                    data.get("arguments", ""),
                )
            )
        elif action == "mcp":
            await self.consume(connect_mcp(agent, data["name"]))
        elif action == "council":
            await self.consume(
                council(
                    self.team,
                    data["task"],
                    data["models"],
                    check=data.get("check") or None,
                    judge=data.get("judge") or None,
                )
            )
        elif action == "replay":
            await self.consume(
                replay(
                    self.team,
                    data["session"],
                    base=data.get("base") or None,
                    check=data.get("check") or None,
                    system=data.get("system", ""),
                )
            )
        elif action == "accept":
            self.emit(await accept(self.team, data["run"], data["candidate"]))
        elif action in {
            "oracle",
            "delegate",
            "remote_run",
            "remote_batch",
            "start_process",
            "stop_process",
        }:
            result = await self.team.action(agent, action, data)
            agent.messages.append(
                Message(
                    "user",
                    [Text("User-requested action result (reference data):\n" + result[:12000])],
                )
            )
            self.emit(Event("action_result", {"action": action, "content": result}))
        elif action in {"undo", "restore"}:
            if tools.mode == "plan":
                raise ToolError("Switch to build mode to restore files.")
            if any(
                job.get("status") == "running"
                for session in self.service.sessions.values()
                if session.root == self.root
                for job in json.loads(session.agent.tools.jobs.poll()).get("jobs", [])
            ):
                raise ToolError("Stop background processes before restoring files.")
            if action == "undo":
                self.emit(await agent.undo())
            else:
                record = await checkpoint_operation(
                    lambda: agent.checkpoints.restore_to(data["checkpoint"])
                )
                tools.workspace.read_hashes.clear()
                await tools.languages.close()
                agent.messages.append(
                    Message(
                        "user",
                        [
                            Text(
                                f"The user restored checkpoint {data['checkpoint']}. "
                                "Re-read files before continuing."
                            )
                        ],
                    )
                )
                self.emit(
                    Event("checkpoint_restored", {"id": record["id"], "paths": record["changes"]})
                )
        else:
            raise ValueError("Unsupported action.")
        agent.save()

    def start(self, action, data):
        self.service.require_idle(self.root)

        async def run():
            try:
                await self.perform(action, data)
            except asyncio.CancelledError:
                self.emit(Event("turn_finished", {"reason": "cancelled"}))
            except (ValueError, OSError, ToolError, KeyError, TypeError) as exc:
                self.emit(Event("error", {"message": str(exc)}))
            except Exception:
                self.emit(
                    Event(
                        "error", {"message": "The action failed. Check the server log for details."}
                    )
                )
                import logging

                logging.getLogger(__name__).exception("GUI action failed")
            finally:
                for future, _ in list(self.pending.values()):
                    if not future.done():
                        future.cancel()
                self.agent.save()
                self.task = None
                self.emit(Event("idle"))

        self.task = asyncio.create_task(run())

    async def stop(self):
        if self.busy:
            self.task.cancel()
            await self.task

    async def close(self):
        await self.stop()
        try:
            await self.agent.tools.close()
        finally:
            self.journal.close()


class Service:
    def __init__(self, root, *, factory=create_adapter, **config):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Workspace must be a directory.")
        self.factory = factory
        self.config = Configuration(self.root, **config)
        self.sessions = {}
        self.branch_path = state_path(self.root, "gui-branches.json")
        self.branches = Configuration.read(self.branch_path)

    def root_for(self, identifier):
        branch = self.branches.get(identifier)
        if branch:
            if (
                not isinstance(branch, str)
                or len(branch) != 32
                or any(c not in "0123456789abcdef" for c in branch)
            ):
                raise ValueError("Invalid branch mapping.")
            return state_path(self.root, "branches", branch)
        return self.root

    def require_idle(self, root=None):
        if any(s.busy and (root is None or s.root == root) for s in self.sessions.values()):
            raise ValueError("Wait for the active action or stop it first.")

    def open(self, *, resume=None, state=None, root=None, model=None):
        if resume in self.sessions:
            return self.sessions[resume]
        if len(self.sessions) >= 12:
            raise ValueError("Close a session before opening more than 12.")
        session = Session(
            self,
            root or (self.root_for(resume) if resume else self.root),
            resume=resume,
            state=state,
            model=model,
        )
        self.sessions[session.id] = session
        return session

    def owned(self, identifier):
        if identifier not in self.sessions:
            raise ValueError("This session is watch-only. Resume it to make changes.")
        return self.sessions[identifier]

    def view(self, identifier):
        if identifier in self.sessions:
            return self.sessions[identifier].view()
        root = self.root_for(identifier)
        history = journal_view(root, identifier)
        context = next(
            (e["data"] for e in reversed(history["events"]) if e["type"] == "context_usage"), {}
        )
        return {
            **history,
            "workspace": str(root),
            "owned": False,
            "busy": False,
            "pending": [],
            "checkpoints": Checkpoints(root).list(),
            "context": context,
            "team": {},
            "jobs": {},
        }

    def listing(self):
        rows = Journal.list(self.root)
        for identifier in self.branches:
            rows.extend(r for r in Journal.list(self.root_for(identifier)) if r["id"] == identifier)
        for row in rows:
            session = self.sessions.get(row["id"])
            row.update(
                owned=session is not None,
                busy=bool(session and session.busy),
                branch=row["id"] in self.branches,
                title=session.title
                if session
                else journal_view(self.root_for(row["id"]), row["id"])["title"],
            )
        return sorted(rows, key=lambda r: r["updated"], reverse=True)[:100]

    async def branch(self, identifier, checkpoint):
        source = self.owned(identifier)
        self.require_idle(source.root)
        view = await asyncio.to_thread(journal_view, source.root, identifier, checkpoint=checkpoint)
        if not view["state"]:
            raise ValueError("This session has no saved state at that checkpoint.")
        key = uuid4().hex
        root = state_path(self.root, "branches", key)
        await checkpoint_operation(lambda: source.agent.checkpoints.branch_to(checkpoint, root))
        write_json(state_path(root, "settings.json"), ProjectSettings(source.root).data)
        state = {**view["state"], "last_checkpoint": None}
        session = self.open(root=root, state=state)
        session.title = f"Branch · {source.title}"
        session.emit(
            Event(
                "branch_created",
                {"source": identifier, "checkpoint": checkpoint, "title": session.title},
            )
        )
        self.branches[session.id] = key
        write_json(self.branch_path, self.branches)
        return session

    async def close(self):
        for session in self.sessions.values():
            with contextlib.suppress(OSError, ValueError):
                await session.close()
