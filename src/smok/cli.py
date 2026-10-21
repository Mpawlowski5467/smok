import argparse
import asyncio
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

import yaml
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from smok import __version__
from smok.checkpoints import Checkpoints
from smok.extensions.runtime import Extensions
from smok.extensions.workflows import connect_mcp, invocation, parameters, run_extension, run_review
from smok.journal import Journal
from smok.loop import Agent
from smok.models import create_adapter
from smok.models.base import ModelError
from smok.models.profiles import REASONING_EFFORTS, resolve_model
from smok.permissions import PermissionPolicy, command_matches, deny
from smok.settings import PERMISSION_MODES, ProjectSettings
from smok.team.config import TeamConfig
from smok.team.coordinator import Team
from smok.team.lab import accept, council, replay
from smok.tools.files import ToolError, Workspace, bounded
from smok.tools.registry import PreparedTool, ToolRegistry
from smok.types import Event, Message
from smok.types import Text as MessageText
from smok.usage import BudgetExceeded, RunBudget

EMBER = "#E8562A"
BONE = "#D8BFA3"
SMOKE = "#F3ECE6"
HELP = """/model provider/model       Switch model and keep history
/mode plan|build            Switch mode (Tab also toggles)
/permissions MODE           Save ask, auto-edit, or full-auto for this project
/allow git status          Save a shell argv pattern (one * matches one argument)
/rules [clear]             Show or clear saved approvals
/undo                      Restore the latest changed checkpoint, if files still match
/checkpoints               List checkpoint history
/sessions                  List saved sessions (restart with --resume ID or --continue)
/compact                   Summarize older history, retaining recent exchanges
/handoff                   Export an editable summary; start fresh with --handoff FILE
/context [pin|drop TARGET]  Inspect token shares, pin a file, or drop a pin/group:N
/map [QUERY]               Inspect the repository outline
/todos                     Show the session task list
/usage                     Show session and current-run usage
/cost [provider/model]     Preview the next request at configured prices
/extensions                List skills, commands, hooks, plugins, recipes, and servers
/reload                    Reload extensions; disconnect MCP servers without starting code
/skill NAME [key=value]    Load a skill and run its guidance
/recipe NAME [key=value]   Run a parameterized workflow, stopping on failure or denial
/review [BASE]             Review working changes, or a branch against BASE, in plan mode
/mcp [SERVER]              List servers or approve and connect one
/team                      Show routes, shared budget, and retained team runs
/delegate ROLE TASK        Start a fresh worker; edit workers keep a separate worktree
/oracle QUESTION           Ask the configured second-opinion model
/jobs                      List session-owned background processes
/poll ID [OFFSET]          Read background output from a byte offset
/background COMMAND        Start an approved shell job (stops when Smok exits)
/stop ID                   Stop a background process
/accept RUN:INDEX          Apply a retained council candidate if the workspace is unchanged
/clear                     Clear conversation and remembered reads
/help                      Show these commands
/exit                      Leave Smok

Approval: y = once, a = always for this file/command/server, n or Enter = deny.
Plan mode disables file mutations and ALL shell commands; hooks are suspended.
MCP tools in plan mode require a user-configured read_only list; startup still needs approval.
Tab toggles mode; Ctrl-Space completes commands. Ctrl-D exits; Ctrl-C clears input or stops a run.
"""


def terminal_text(value: str) -> str:
    value = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", value)
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    return "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and not 127 <= ord(c) < 160))


class Terminal:
    def __init__(self, *, json_mode: bool = False):
        self.json_mode = json_mode
        self.console = Console(stderr=json_mode, highlight=False)
        self.streaming = False
        self.input_tokens = 0
        self.output_tokens = 0

    def end_text(self):
        if self.streaming:
            self.console.print()
            self.streaming = False

    def render(self, event: Event):
        data = event.data
        if event.type == "usage":
            self.input_tokens += data.get("input_tokens", 0)
            self.output_tokens += data.get("output_tokens", 0)
        if self.json_mode:
            print(json.dumps(event.to_dict(), ensure_ascii=False), flush=True)
            return
        match event.type:
            case "text_delta":
                self.console.print(
                    terminal_text(data["text"]), end="", markup=False, soft_wrap=True
                )
                self.streaming = True
            case "tool_call":
                self.end_text()
                self.console.print(Text(f"  › {terminal_text(data['name'])}", style=EMBER))
            case "tool_result":
                style = "red" if data["is_error"] else "dim"
                self.console.print(Text(terminal_text(bounded(data["content"], 2000)), style=style))
            case "diff":
                self.end_text()
                path = (
                    str(Path(data["workspace"]) / data["path"])
                    if data.get("workspace")
                    else data["path"]
                )
                self.console.print(Text(f"Change {terminal_text(path)}", style=BONE))
                self.console.print(
                    Syntax(
                        terminal_text(bounded(data["diff"], 12000)),
                        "diff",
                        theme="ansi_dark",
                        word_wrap=True,
                    )
                )
            case "permission_requested":
                self.end_text()
                if data["name"] == "run_shell":
                    self.console.print(
                        Panel(
                            Text(terminal_text(data["arguments"]["command"])),
                            title=f"Shell · {data.get('backend', 'host')}",
                            border_style=EMBER,
                        )
                    )
                elif data.get("server_command"):
                    self.console.print(
                        Panel(
                            Text(terminal_text(json.dumps(data["server_command"]))),
                            title="Start language server (host)",
                            border_style=EMBER,
                        )
                    )
                if data.get("hooks") or data.get("extension"):
                    self.console.print(
                        Panel(
                            Text(
                                terminal_text(
                                    json.dumps(
                                        {
                                            "action": data["name"],
                                            "arguments": data["arguments"],
                                            "hooks": data.get("hooks"),
                                            "extension": data.get("extension"),
                                            "always_scope": data.get("approval_scope"),
                                        },
                                        indent=2,
                                    )
                                )
                            ),
                            title="Extension action",
                            border_style=EMBER,
                        )
                    )
            case "self_check_started":
                self.end_text()
                self.console.print("Reviewing changes and verification results…", style=BONE)
            case "compaction_started":
                self.end_text()
                self.console.print("Summarizing older context…", style=BONE)
            case "compaction_finished":
                self.console.print(
                    f"History estimate: {data['before_estimated_tokens']:,} → "
                    f"{data['after_estimated_tokens']:,} tokens.",
                    style=BONE,
                )
            case "compaction_skipped":
                self.console.print(Text(data["reason"], style=BONE))
            case "handoff_created":
                self.console.print(
                    Text("Edit this handoff, then use --handoff FILE:\n" + data["path"], style=BONE)
                )
            case "todos_updated":
                self.console.print(
                    Text(
                        terminal_text(
                            "\n".join(f"[{t['status']}] {t['text']}" for t in data["items"])
                            or "No todos yet."
                        ),
                        style=BONE,
                    )
                )
            case (
                "context_report"
                | "cost_preview"
                | "session_list"
                | "usage_report"
                | "extension_report"
                | "team_report"
                | "council_finished"
                | "replay_finished"
                | "shadow_finished"
                | "candidate_accepted"
            ):
                self.console.print(
                    Text(terminal_text(json.dumps(data, indent=2, ensure_ascii=False)))
                )
            case "repo_map":
                self.console.print(Text(terminal_text(data["text"])))
            case "recipe_step_started":
                self.end_text()
                self.console.print(
                    Text(f"Recipe {data['name']} · step {data['step']}/{data['total']}", style=BONE)
                )
            case (
                "worker_started"
                | "worker_finished"
                | "model_routed"
                | "escalation"
                | "shadow_started"
                | "council_started"
                | "replay_started"
            ):
                self.end_text()
                self.console.print(
                    Text(terminal_text(event.type + ": " + json.dumps(data)), style=BONE)
                )
            case "recipe_stopped":
                self.end_text()
                self.console.print(Text(data["reason"], style="red"))
            case "budget_exhausted" | "model_retry":
                self.end_text()
                self.console.print(Text(data["message"], style=BONE))
            case "checkpoint_restored":
                self.console.print(
                    Text(
                        f"Restored checkpoint {data['id']}: "
                        + terminal_text(", ".join(data["paths"])),
                        style=BONE,
                    )
                )
            case "error" | "turn_time_limit":
                self.end_text()
                self.console.print(Text(terminal_text(data["message"]), style="red"))
            case "turn_finished":
                self.end_text()
                if data["reason"] == "iteration_limit":
                    self.console.print(
                        "Iteration limit reached. Continue with another prompt.", style=BONE
                    )

    async def approve(self, prepared: PreparedTool):
        if not sys.stdin.isatty():
            return False
        # Persistent grants are limited to the displayed file, exact command, or server argv.
        session: PromptSession[str] = PromptSession()
        try:
            answer = await session.prompt_async(
                f"Allow {prepared.call.name}? [y]es / [a]lways / [N]o: "
            )
        except (KeyboardInterrupt, EOFError):
            return False
        answer = answer.strip().lower()
        return "always" if answer in {"a", "always"} else answer in {"y", "yes"}


def parser():
    cli = argparse.ArgumentParser(description="Smok — a local-first coding harness.")
    cli.add_argument("--gui", action="store_true", help="Launch the local web app")
    cli.add_argument("--port", type=int, default=8765, help="GUI port; 0 chooses a free port")
    cli.add_argument(
        "--no-browser", action="store_true", help="Print the GUI launch link without opening it"
    )
    cli.add_argument("--version", action="version", version=f"smok {__version__}")
    cli.add_argument("--model", "-m", help="provider/model (default: SMOK_MODEL or profile)")
    cli.add_argument("--workspace", "-C", type=Path, default=Path.cwd())
    cli.add_argument("--config", type=Path, help="YAML model/provider overrides")
    cli.add_argument("--base-url", help="Override the initially selected provider's endpoint")
    cli.add_argument("--doctor", action="store_true", help="Check setup without creating a session")
    cli.add_argument(
        "--probe-model",
        action="store_true",
        help="With --doctor, request the configured endpoint's model list; no generation",
    )
    cli.add_argument("--max-iterations", type=int, default=12)
    cli.add_argument(
        "--turn-timeout",
        type=float,
        help="Seconds per turn, including approvals and routing; 0 clears a saved limit",
    )
    cli.add_argument("--mode", choices=["plan", "build"], default=None)
    resume = cli.add_mutually_exclusive_group()
    resume.add_argument("--resume", metavar="ID", help="Resume a session in this workspace")
    resume.add_argument(
        "--continue", dest="continue_session", action="store_true", help="Resume the latest session"
    )
    resume.add_argument("--handoff", type=Path, help="Start a fresh session from an edited summary")
    cli.add_argument("--sessions", action="store_true", help="List saved sessions and exit")
    cli.add_argument("--compact", action="store_true", help="Compact a resumed session and exit")
    cli.add_argument(
        "--export-handoff", action="store_true", help="Export a resumed session summary and exit"
    )
    cli.add_argument(
        "--context-window", type=int, help="Working token limit; configure for your endpoint"
    )
    cli.add_argument(
        "--max-output-tokens", type=int, help="Override the per-request output allowance"
    )
    cli.add_argument(
        "--reasoning-effort",
        choices=("default", *REASONING_EFFORTS),
        help="Model-specific thinking control for compatible endpoints; default clears an override",
    )
    cli.add_argument("--max-turns", type=int, help="Maximum user tasks in this CLI invocation")
    cli.add_argument(
        "--budget-tokens", type=int, help="Total input/output token allowance for this run"
    )
    cli.add_argument(
        "--budget-usd", type=float, help="Estimated API cost cap; requires explicit prices"
    )
    cli.add_argument(
        "--permissions", choices=PERMISSION_MODES, help="Override saved permissions for this run"
    )
    cli.add_argument(
        "--sandbox", choices=["host", "docker"], help="Shell backend; default from project settings"
    )
    cli.add_argument("--sandbox-image", help="Already installed Docker image")
    cli.add_argument(
        "--sandbox-network",
        action="store_true",
        default=None,
        help="Explicitly enable container networking",
    )
    cli.add_argument("--prompt", "-p", help="Run one task and exit")
    cli.add_argument(
        "--extensions", action="store_true", help="List extensions without a model call"
    )
    cli.add_argument("--command", help="Run a Markdown prompt command by name")
    cli.add_argument("--skill", help="Load a skill and run its guidance")
    cli.add_argument("--recipe", help="Run a parameterized recipe")
    cli.add_argument(
        "--param", action="append", default=[], metavar="KEY=VALUE", help="Extension parameter"
    )
    cli.add_argument(
        "--arguments", default="", help="Text substituted for {{args}} in an extension"
    )
    cli.add_argument(
        "--review",
        nargs="?",
        const="",
        metavar="BASE",
        help="Review uncommitted changes, or committed branch changes against BASE",
    )
    cli.add_argument(
        "--json",
        action="store_true",
        help="JSONL events for a prompt or one-shot action; no prompts",
    )
    cli.add_argument(
        "--yes", "-y", action="store_true", help="Alias for --permissions full-auto for this run"
    )
    cli.add_argument(
        "--no-input", action="store_true", help="Deny new approval requests without prompting"
    )
    cli.add_argument("--no-log", action="store_true", help="Disable local session logs")
    cli.add_argument("--team", action="store_true", help="Show routes and retained team runs")
    cli.add_argument("--delegate", metavar="TASK", help="Run one fresh-context worker")
    cli.add_argument("--role", choices=["explore", "plan", "edit", "review"], default="explore")
    cli.add_argument("--oracle", metavar="QUESTION", help="Ask a second-opinion model")
    cli.add_argument(
        "--council", metavar="TASK", help="Compare two or three isolated implementations"
    )
    cli.add_argument("--council-model", action="append", default=[], metavar="MODEL")
    cli.add_argument("--check", help="Explicit validation command for council or replay")
    cli.add_argument("--judge", help="Model that selects among eligible council candidates")
    cli.add_argument("--shadow-model", help="Local model to answer alongside a frontier model")
    cli.add_argument("--accept", metavar="RUN:INDEX", help="Accept a retained council candidate")
    cli.add_argument(
        "--replay", metavar="SESSION", help="Replay logged user tasks in an isolated worktree"
    )
    cli.add_argument("--replay-base", help="Starting Git revision for logs without a snapshot")
    cli.add_argument(
        "--replay-system", type=Path, help="Additional system instructions for a replay experiment"
    )
    cli.add_argument(
        "--remote-runner", metavar="NAME", help="Run --remote-task on a configured SSH runner"
    )
    cli.add_argument("--remote-task", metavar="TASK")
    cli.add_argument(
        "--remote-batch", type=Path, metavar="JSON_FILE", help="Dispatch 1-3 SSH tasks concurrently"
    )
    cli.add_argument(
        "--runner", action="store_true", help="Serve one bounded JSON request on stdin (SSH)"
    )
    cli.add_argument(
        "--runner-root", type=Path, help="Server-owned directory for disposable runner workspaces"
    )
    cli.add_argument(
        "--no-checkpoints", action="store_true", help="Explicitly disable turn snapshots and undo"
    )
    cli.add_argument(
        "--no-self-check", action="store_true", help="Skip automatic review of changed files"
    )
    cli.add_argument(
        "--undo", action="store_true", help="Undo the latest changed checkpoint and exit"
    )
    return cli


def mode_bindings(agent, emit):
    bindings = KeyBindings()

    @bindings.add("tab")
    def toggle(event):
        agent.set_mode("build" if agent.tools.mode == "plan" else "plan")
        agent.save()
        emit(Event("mode_changed", {"mode": agent.tools.mode}))
        event.app.invalidate()

    @bindings.add("c-space")
    def complete(event):
        event.current_buffer.start_completion(select_first=False)

    return bindings


async def run_cli(args):
    if args.probe_model and not args.doctor:
        raise ValueError("--probe-model requires --doctor.")
    if args.doctor and (
        args.runner or args.gui or args.resume or args.continue_session or args.handoff
    ):
        raise ValueError("--doctor cannot start or resume a GUI, runner, or session.")
    if args.runner:
        from smok.settings import Sandbox
        from smok.team.remote import read_request, run_request

        if not args.runner_root or args.sandbox == "host":
            raise ValueError("--runner needs --runner-root and uses Docker only.")
        result = await run_request(
            await read_request(),
            config=resolve_model(args.model, config_path=args.config, base_url=args.base_url),
            root=args.runner_root.resolve(),
            sandbox=Sandbox(
                "docker", args.sandbox_image or "python:3.12-slim", bool(args.sandbox_network)
            ),
        )
        print(json.dumps(result), flush=True)
        return 0
    actions = sum(
        [
            args.undo,
            args.sessions,
            args.compact,
            args.export_handoff,
            args.extensions,
            args.doctor,
            bool(args.command),
            bool(args.skill),
            bool(args.recipe),
            args.review is not None,
            args.team,
            bool(args.delegate),
            bool(args.oracle),
            bool(args.council),
            bool(args.accept),
            bool(args.replay),
            bool(args.remote_runner),
            bool(args.remote_batch),
        ]
    )
    if actions > 1 or actions and args.prompt is not None:
        raise ValueError("Choose one prompt or one one-shot action.")
    if bool(args.remote_runner) != bool(args.remote_task):
        raise ValueError("Use --remote-runner and --remote-task together.")
    if (
        args.check
        and not (args.council or args.replay)
        or (args.judge or args.council_model)
        and not args.council
        or (args.replay_base or args.replay_system)
        and not args.replay
    ):
        raise ValueError("Council/replay options require their matching action.")
    if args.json and args.prompt is None and not actions:
        raise ValueError("--json requires a prompt or one-shot action.")
    if (args.param or args.arguments) and not (args.command or args.skill or args.recipe):
        raise ValueError("--param and --arguments require --command, --skill, or --recipe.")
    if args.yes and (args.no_input or args.permissions):
        raise ValueError("Do not combine --yes with --no-input or --permissions.")
    if args.max_iterations < 1 or args.undo and args.no_checkpoints:
        raise ValueError("Invalid iteration limit or undo with checkpoints disabled.")
    resuming = args.resume or args.continue_session
    if args.no_log and resuming:
        raise ValueError("Resume requires session persistence; omit --no-log.")
    if (args.compact or args.export_handoff) and not resuming:
        raise ValueError("Use --resume ID or --continue with this session action.")
    if args.prompt is None and not actions and not sys.stdin.isatty():
        raise ValueError("Use --prompt for non-interactive input.")
    if args.doctor:
        from smok.diagnostics import diagnose

        result = await diagnose(
            args.workspace,
            model=args.model,
            config_path=args.config,
            base_url=args.base_url,
            probe=args.probe_model,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            console = Console(highlight=False)
            console.print(Text(f"Smok {__version__} · setup checks", style=f"bold {EMBER}"))
            for check in result["checks"]:
                console.print(
                    Text(
                        terminal_text(
                            f"[{check['status'].upper()}] {check['label']}: {check['detail']}"
                        )
                    )
                )
                if check["remedy"]:
                    console.print(Text(terminal_text("  " + check["remedy"]), style="dim"))
            console.print("No session created. No model generation requested.")
        return 0 if result["ok"] else 2
    budget = RunBudget(args.max_turns, args.budget_tokens, args.budget_usd)
    workspace = Workspace(args.workspace)
    terminal = Terminal(json_mode=args.json or args.prompt is not None)
    if args.sessions:
        terminal.render(Event("session_list", {"sessions": Journal.list(workspace.root)}))
        return 0
    if args.extensions:
        extensions = Extensions(workspace, ProjectSettings(workspace.root))
        terminal.render(Event("extension_report", extensions.listing()))
        return 0
    identifier = Journal.latest(workspace.root) if args.continue_session else args.resume
    journal = (
        None
        if args.no_log or args.undo and not identifier
        else Journal(workspace.root, resume=identifier)
    )
    tools = None
    try:
        saved = journal.loaded if journal and journal.loaded else {}
        selector = args.model or saved.get("model")
        from smok.gui.config import Configuration

        gui_config = Configuration(workspace.root, model=args.model, config_path=args.config)
        config = gui_config.resolve(selector, base_url=args.base_url)
        if saved and not args.model and not args.config:
            allowed = {
                "context_window",
                "max_output_tokens",
                "compact_at",
                "keep_recent",
                "chars_per_token",
                "repo_map_tokens",
                "vision",
                "prompt_style",
                "tool_set",
                "edit_format",
                "reasoning_effort",
                "temperature",
                "top_p",
            }
            saved_context = saved.get("context_settings", {})
            if not isinstance(saved_context, dict) or set(saved_context) - allowed:
                raise ValueError("Invalid saved context settings.")
            config = replace(config, **saved_context)
        overrides = {
            k: v
            for k, v in {
                "context_window": args.context_window,
                "max_output_tokens": args.max_output_tokens,
            }.items()
            if v is not None
        }
        if args.reasoning_effort is not None:
            overrides["reasoning_effort"] = (
                None if args.reasoning_effort == "default" else args.reasoning_effort
            )
        config = replace(config, **overrides)
        override_provider = config.name.partition("/")[0]
        settings = ProjectSettings(workspace.root)
        sandbox_changes = {
            k: v
            for k, v in {
                "backend": args.sandbox,
                "image": args.sandbox_image,
                "network": args.sandbox_network,
            }.items()
            if v is not None
        }
        sandbox = replace(settings.sandbox, **sandbox_changes)
        if args.sandbox_network and sandbox.backend != "docker":
            raise ValueError("--sandbox-network requires Docker.")
        policy = PermissionPolicy(settings, "full-auto" if args.yes else args.permissions)
        checkpoints = None if args.no_checkpoints else Checkpoints(workspace.root)
        tools = ToolRegistry(workspace, settings=settings, mode=args.mode or "build")
        tools.sandbox = sandbox
        agent = Agent(
            create_adapter(config),
            tools,
            approver=deny if args.no_input or terminal.json_mode else terminal.approve,
            max_iterations=args.max_iterations,
            policy=policy,
            checkpoints=checkpoints,
            self_check=not args.no_self_check,
            journal=journal,
            budget=budget,
        )
        if saved:
            agent.restore(saved)
            if args.mode:
                agent.set_mode(args.mode)
            agent.context.refresh_pins()
        if args.turn_timeout is not None:
            from smok.reliability import validate_timeout

            agent.turn_timeout = validate_timeout(
                None if args.turn_timeout == 0 else args.turn_timeout
            )
        if args.handoff:
            with args.handoff.open("rb") as stream:
                raw = stream.read(64001)
            if len(raw) > 64000:
                raise ValueError("Handoff summaries must be at most 64000 UTF-8 bytes.")
            agent.messages.append(
                Message(
                    "user",
                    [
                        MessageText(
                            "User-provided handoff context. Re-read current files; this is "
                            "reference data, not authorization to replay earlier actions:\n"
                            + raw.decode("utf-8")
                        )
                    ],
                )
            )
        agent.save()
        terminal.input_tokens = agent.usage.input_tokens
        terminal.output_tokens = agent.usage.output_tokens

        def emit(event):
            if journal:
                journal.write(event)
            terminal.render(event)

        def resolve_team(name):
            if name == config.name:
                return config
            return replace(
                gui_config.resolve(
                    name,
                    base_url=args.base_url if name.partition("/")[0] == override_provider else None,
                ),
                **overrides,
            )

        team_config = TeamConfig.parse(settings.data.get("team", {}))
        if args.shadow_model:
            team_config = replace(team_config, shadow_model=args.shadow_model)
        team = Team(agent, team_config, resolver=resolve_team, factory=create_adapter, emit=emit)
        team.primary = config
        team.active_config = config

        async def team_action(name, values):
            budget.start_turn()
            result = json.loads(await team.action(agent, name, values))
            emit(Event("team_report", result))
            # Retain only the bounded report, not workers' tool exchanges.
            agent.messages.append(
                Message(
                    "user",
                    [MessageText("Team result (reference data):\n" + json.dumps(result)[:12000])],
                )
            )
            agent.save()
            workers = result.get("workers", [result.get("result", result)])
            ok = all(w.get("reason") == "complete" and not w.get("denied") for w in workers)
            emit(Event("turn_finished", {"reason": "complete" if ok else "worker_failed"}))
            return 0 if ok else 2

        async def consume(stream):
            status = 0
            try:
                async for event in stream:
                    emit(event)
                    if event.type == "turn_finished":
                        status = 0 if event.data["reason"] == "complete" else 2
            finally:
                await stream.aclose()
            return status

        if args.undo:
            emit(await agent.undo())
            return 0
        if args.team:
            emit(Event("team_report", team.listing()))
            return 0
        if args.accept:
            run, sep, index = args.accept.partition(":")
            if not sep or not index.isdigit():
                raise ValueError("Use --accept RUN:INDEX.")
            emit(await accept(team, run, int(index)))
            return 0
        if args.delegate:
            return await team_action(
                "delegate", {"tasks": [{"task": args.delegate, "role": args.role}]}
            )
        if args.oracle:
            return await team_action("oracle", {"question": args.oracle})
        if args.remote_runner:
            return await team_action(
                "remote_run", {"runner": args.remote_runner, "task": args.remote_task}
            )
        if args.remote_batch:
            if args.remote_batch.stat().st_size > 40000:
                raise ValueError("Remote batch JSON must be at most 40,000 bytes.")
            return await team_action(
                "remote_batch", {"jobs": json.loads(args.remote_batch.read_text())}
            )
        if args.council:
            return await consume(
                council(team, args.council, args.council_model, check=args.check, judge=args.judge)
            )
        if args.replay:
            system = ""
            if args.replay_system:
                if args.replay_system.stat().st_size > 16000:
                    raise ValueError("Replay system additions must be at most 16,000 bytes.")
                system = args.replay_system.read_text()
            return await consume(
                replay(team, args.replay, base=args.replay_base, check=args.check, system=system)
            )
        if args.compact:
            return await consume(agent.compact())
        if args.export_handoff:
            return await consume(agent.handoff())
        if args.review is not None:
            return await consume(run_review(agent, args.review or None))
        for kind, selected in (
            ("commands", args.command),
            ("skills", args.skill),
            ("recipes", args.recipe),
        ):
            if selected:
                return await consume(
                    run_extension(agent, kind, selected, parameters(args.param), args.arguments)
                )
        if args.prompt is not None:
            return await consume(agent.run(args.prompt))
        title = Text("❯_  smok", style=f"bold {EMBER}")
        title.append("\nA small dragon for your code.", style=SMOKE)
        title.append(f"\n\n{config.name}\n{workspace.root}", style=BONE)
        title.append(f"\nSession {journal.id if journal else '(not saved)'}", style=BONE)
        title.append("\n\nTab plan/build · /context · /compact · /handoff · /help", style="dim")
        terminal.console.print(Panel(title, border_style=EMBER, padding=(1, 2)))
        commands = [
            "/model",
            "/mode",
            "/permissions",
            "/allow",
            "/rules",
            "/undo",
            "/checkpoints",
            "/sessions",
            "/compact",
            "/handoff",
            "/context",
            "/map",
            "/todos",
            "/usage",
            "/cost",
            "/clear",
            "/help",
            "/exit",
            "/extensions",
            "/reload",
            "/skill",
            "/recipe",
            "/review",
            "/mcp",
            "/team",
            "/delegate",
            "/oracle",
            "/jobs",
            "/poll",
            "/background",
            "/stop",
            "/accept",
        ]
        commands.extend("/" + key for key in tools.extensions.catalog.commands)
        completer = WordCompleter(commands)
        session: PromptSession[str] = PromptSession(
            completer=completer,
            key_bindings=mode_bindings(agent, emit),
            style=Style.from_dict({"prompt": EMBER, "bottom-toolbar": "bg:#1A1A1F #D8BFA3"}),
        )

        def toolbar():
            ctx = agent.last_context or {}
            used = ctx.get("input_tokens", 0)
            return (
                f" {tools.mode.upper()} · {agent.model.name}"
                f"{' (escalated)' if team.escalated else ''} · {policy.mode} · "
                f"{tools.sandbox.backend}\n"
                f" context ~{used:,}/{agent.config.context_window:,} · "
                f"{agent.usage.input_tokens:,} in / {agent.usage.output_tokens:,} out · /usage"
            )

        while True:
            try:
                line = (
                    await session.prompt_async(
                        FormattedText([("class:prompt", "smok ❯ ")]),
                        bottom_toolbar=toolbar,
                    )
                ).strip()
            except KeyboardInterrupt:
                continue
            except EOFError:
                return 0
            if not line:
                continue
            command, _, value = line.partition(" ")
            value = value.strip()
            try:
                match command:
                    case "/exit":
                        return 0
                    case "/help":
                        terminal.console.print(HELP, markup=False)
                    case "/clear":
                        agent.clear()
                        emit(Event("conversation_cleared"))
                        terminal.console.print(
                            "Conversation cleared; usage totals retained.", style="dim"
                        )
                    case "/model":
                        if not value:
                            terminal.console.print(agent.model.name, markup=False)
                            continue
                        config = gui_config.resolve(
                            value,
                            base_url=args.base_url
                            if value.partition("/")[0] == override_provider
                            else None,
                        )
                        config = replace(config, **overrides)
                        config.api_key()
                        agent.model = create_adapter(config)
                        team.primary = config
                        team.active_config = config
                        agent.last_context = None
                        agent.save()
                        emit(Event("model_changed", {"model": config.name}))
                        terminal.console.print(Text(f"Now using {config.name}.", style=BONE))
                    case "/mode":
                        if value:
                            agent.set_mode(value)
                            agent.save()
                            emit(Event("mode_changed", {"mode": tools.mode}))
                        terminal.console.print(f"Mode: {tools.mode}", style=BONE)
                    case "/permissions":
                        if value:
                            settings.set_permissions(value)
                            policy.mode = value
                            emit(Event("permissions_changed", {"mode": value}))
                        terminal.console.print(f"Permissions: {policy.mode}", style=BONE)
                    case "/allow":
                        if not value or not command_matches(value, value):
                            raise ValueError("Use a command argv pattern without shell operators.")
                        settings.add_rule({"tool": "run_shell", "command": value, "match": "argv"})
                        terminal.console.print("Saved command rule.", style=BONE)
                    case "/rules":
                        if value == "clear":
                            settings.rules.clear()
                            settings.save()
                        elif value:
                            raise ValueError("Use /rules or /rules clear.")
                        terminal.console.print(Text(json.dumps(settings.rules, indent=2)))
                    case "/undo":
                        emit(await agent.undo())
                    case "/checkpoints":
                        terminal.console.print(
                            Text(json.dumps(checkpoints.list() if checkpoints else [], indent=2))
                        )
                    case "/sessions":
                        emit(Event("session_list", {"sessions": Journal.list(workspace.root)}))
                    case "/compact":
                        await consume(agent.compact())
                    case "/handoff":
                        await consume(agent.handoff())
                    case "/context":
                        action, _, target = value.partition(" ")
                        if action == "pin" and target:
                            agent.context.pin(target)
                        elif action == "drop" and target:
                            agent.context.drop(target, agent.messages)
                        elif value:
                            raise ValueError(
                                "Use /context, /context pin PATH, or /context drop PATH|group:N."
                            )
                        agent.save()
                        emit(Event("context_report", agent.context_report()))
                    case "/map":
                        agent.context.map_text = await tools.repo_map.build(
                            value or agent.current_prompt
                        )
                        emit(Event("repo_map", {"text": agent.context.map_text}))
                    case "/todos":
                        emit(Event("todos_updated", {"items": tools.todos}))
                    case "/usage":
                        emit(
                            Event(
                                "usage_report",
                                {
                                    "session": agent.usage.export(),
                                    "run": budget.usage.export(),
                                    "limits": {
                                        "tokens": budget.tokens,
                                        "usd": budget.dollars,
                                        "turns": budget.max_turns,
                                    },
                                    "turns_used": budget.turns,
                                },
                            )
                        )
                    case "/cost":
                        names = {value or agent.model.name}
                        if not value and args.config:
                            data = yaml.safe_load(args.config.read_text()) or {}
                            names.update(data.get("models", {}))
                        previews = []
                        for name in sorted(names):
                            selected = (
                                agent.config
                                if name == agent.model.name
                                else gui_config.resolve(name)
                            )
                            previews.append(agent.cost_preview(selected))
                        emit(Event("cost_preview", {"models": previews}))
                    case "/extensions":
                        emit(Event("extension_report", tools.extensions.listing()))
                    case "/reload":
                        result = await tools.extensions.reload()
                        completer.words = commands + [
                            "/" + k for k in tools.extensions.catalog.commands
                        ]
                        emit(Event("extension_report", json.loads(result)))
                    case "/skill" | "/recipe":
                        key, values, arguments = invocation(value)
                        await consume(
                            run_extension(
                                agent,
                                "skills" if command == "/skill" else "recipes",
                                key,
                                values,
                                arguments,
                            )
                        )
                    case "/review":
                        await consume(run_review(agent, value or None))
                    case "/mcp":
                        if value:
                            await consume(connect_mcp(agent, value))
                        else:
                            emit(
                                Event(
                                    "extension_report",
                                    {"mcp_servers": tools.extensions.mcp.listing()},
                                )
                            )
                    case "/team":
                        emit(Event("team_report", team.listing()))
                    case "/oracle":
                        await team_action("oracle", {"question": value})
                    case "/delegate":
                        role, _, task = value.partition(" ")
                        await team_action("delegate", {"tasks": [{"role": role, "task": task}]})
                    case "/jobs":
                        emit(Event("team_report", json.loads(tools.jobs.poll())))
                    case "/poll":
                        parts = value.split()
                        if not 1 <= len(parts) <= 2 or len(parts) == 2 and not parts[1].isdigit():
                            raise ValueError("Use /poll ID [BYTE_OFFSET].")
                        emit(
                            Event(
                                "team_report",
                                json.loads(
                                    tools.jobs.poll(
                                        parts[0], int(parts[1]) if len(parts) == 2 else 0
                                    )
                                ),
                            )
                        )
                    case "/background" | "/stop":
                        name = "start_process" if command == "/background" else "stop_process"
                        values = {"command": value} if command == "/background" else {"id": value}
                        emit(
                            Event("team_report", json.loads(await team.action(agent, name, values)))
                        )
                    case "/accept":
                        run, sep, index = value.partition(":")
                        if not sep or not index.isdigit():
                            raise ValueError("Use /accept RUN:INDEX.")
                        emit(await accept(team, run, int(index)))
                    case _:
                        if command[1:] in tools.extensions.catalog.commands and command.startswith(
                            "/"
                        ):
                            key, values, arguments = invocation(line[1:])
                            await consume(run_extension(agent, "commands", key, values, arguments))
                        elif line.startswith("/"):
                            terminal.console.print("Unknown command. Use /help.", style=BONE)
                        else:
                            await consume(agent.run(line))
            except (ValueError, ToolError, ModelError, BudgetExceeded, OSError) as exc:
                terminal.console.print(Text(terminal_text(str(exc)), style="red"))
    finally:
        try:
            if tools:
                await tools.close()
        finally:
            if journal:
                journal.close()


def main():
    args = parser().parse_args()
    try:
        if args.gui:
            defaults = vars(parser().parse_args([]))
            allowed = {"gui", "workspace", "model", "config", "base_url", "port", "no_browser"}
            if any(k not in allowed and v != defaults[k] for k, v in vars(args).items()):
                raise ValueError(
                    "With --gui, use workspace, model, config, base-url, port, or no-browser; "
                    "configure turns in the app."
                )
            from smok.gui.launcher import run

            run(
                workspace=args.workspace,
                model=args.model,
                config=args.config,
                base_url=args.base_url,
                port=args.port,
                browser=not args.no_browser,
            )
            return 0
        return asyncio.run(run_cli(args))
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
    except (ValueError, ToolError, ModelError, BudgetExceeded, OSError, yaml.YAMLError) as exc:
        print(f"smok: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
