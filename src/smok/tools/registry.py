import json
from dataclasses import asdict, dataclass, replace
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from smok.extensions.catalog import Hook, fingerprint
from smok.extensions.runtime import Extensions
from smok.instructions import Instructions
from smok.lsp import LanguageServers
from smok.outputs import CAPTURE_BYTES, OutputStore
from smok.repo_map import RepoMap
from smok.settings import LanguageServer, ProjectSettings
from smok.team.jobs import Jobs
from smok.team.specs import MUTATING as TEAM_MUTATING
from smok.team.specs import SPECS as TEAM_SPECS
from smok.todos import validate_todos
from smok.tools.files import PendingWrite, ToolError, Workspace
from smok.tools.search import Search
from smok.tools.shell import run_shell
from smok.tuning import TOOL_SETS
from smok.types import ToolCall, ToolSpec


def schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


PATH = {"type": "string", "minLength": 1, "description": "Path relative to the workspace."}
POSITION = {
    "path": PATH,
    "line": {"type": "integer", "minimum": 1, "description": "1-based line number."},
    "column": {"type": "integer", "minimum": 1, "description": "1-based Unicode character column."},
}
MUTATING = {"write_file", "edit_file", "run_shell"} | TEAM_MUTATING
SPECS = [
    ToolSpec(
        "read_output",
        "Read a saved tool output by its ID. Offsets are zero-based characters.",
        schema(
            {
                "id": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 12000},
            },
            ["id"],
        ),
    ),
    ToolSpec(
        "write_todos",
        "Replace the session todo list for substantial ongoing work. Optional for small "
        "repairs. Update at meaningful milestones; mark checks done only after their results.",
        schema(
            {
                "items": {
                    "type": "array",
                    "maxItems": 30,
                    "items": schema(
                        {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "status": {"enum": ["pending", "in_progress", "done", "blocked"]},
                        },
                        ["id", "text", "status"],
                    ),
                }
            },
            ["items"],
        ),
    ),
    ToolSpec(
        "repo_map",
        "Get a Tree-sitter outline of Python/JS/TS symbols, ranked by query relevance.",
        schema(
            {
                "query": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 500, "maximum": 12000},
            },
            [],
        ),
    ),
    ToolSpec(
        "read_file",
        "Read a UTF-8 file with line numbers. Read before editing.",
        schema(
            {
                "path": PATH,
                "offset": {"type": "integer", "minimum": 1, "default": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
            },
            ["path"],
        ),
    ),
    ToolSpec(
        "list_dir",
        "List up to 200 entries. / marks folders; @ marks links.",
        schema({"path": PATH}, []),
    ),
    ToolSpec(
        "write_file",
        "Create or replace a UTF-8 file. Read existing files first.",
        schema(
            {
                "path": PATH,
                "content": {"type": "string"},
            },
            ["path", "content"],
        ),
        True,
    ),
    ToolSpec(
        "edit_file",
        "Replace one exact, unique string in a previously read file. "
        "Include enough context to match once.",
        schema(
            {
                "path": PATH,
                "old_text": {"type": "string", "minLength": 1},
                "new_text": {"type": "string"},
            },
            ["path", "old_text", "new_text"],
        ),
        True,
    ),
    ToolSpec(
        "grep",
        "Search text with ripgrep regex; returns file paths and line numbers. "
        "Respects ignore files.",
        schema(
            {
                "pattern": {"type": "string", "minLength": 1},
                "path": PATH,
                "glob": {"type": "string"},
                "ignore_case": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
            },
            ["pattern"],
        ),
    ),
    ToolSpec(
        "glob",
        "Find files by glob, e.g. **/*.py. Respects ignore files.",
        schema(
            {
                "pattern": {"type": "string", "minLength": 1},
                "path": PATH,
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
            },
            ["pattern"],
        ),
    ),
    ToolSpec(
        "run_shell",
        "Run a shell command in the workspace using the configured host or Docker backend.",
        schema(
            {
                "command": {"type": "string", "minLength": 1},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
            },
            ["command"],
        ),
        True,
    ),
    ToolSpec(
        "lsp_diagnostics",
        "Get current language-server diagnostics for a file. First server start needs approval.",
        schema({"path": PATH}, ["path"]),
        True,
    ),
    ToolSpec(
        "lsp_definition",
        "Find a symbol's definition. Line and column are 1-based. "
        "First server start needs approval.",
        schema(POSITION, ["path", "line", "column"]),
        True,
    ),
    ToolSpec(
        "lsp_references",
        "Find symbol references. Line and column are 1-based. First server start needs approval.",
        schema(POSITION, ["path", "line", "column"]),
        True,
    ),
]


@dataclass(frozen=True)
class PreparedTool:
    call: ToolCall
    spec: ToolSpec
    arguments: dict[str, Any]
    write: PendingWrite | None = None
    requires_approval: bool = False
    server: LanguageServer | None = None
    hooks: tuple[Hook, ...] = ()
    approval_key: str | None = None
    extension_context: dict | None = None
    generation: int = 0
    workspace: str = ""

    def permission_data(self) -> dict[str, Any]:
        return {
            "id": self.call.id,
            "name": self.call.name,
            "arguments": self.arguments,
            "workspace": self.workspace,
            "diff": self.write.diff if self.write else None,
            "server_command": list(self.server.command) if self.server else None,
            "hooks": [asdict(hook) for hook in self.hooks],
            "extension": self.extension_context,
            "approval_scope": "exact action, arguments, hook commands, and configuration"
            if self.approval_key
            else None,
        }


class ToolRegistry:
    def __init__(
        self, workspace: Workspace, *, settings: ProjectSettings | None = None, mode="build"
    ):
        self.workspace = workspace
        self.workspace.output_limit = None
        self.outputs = OutputStore(workspace.root)
        self.repo_map = RepoMap(workspace)
        self.todos = []
        self.settings = settings or ProjectSettings(workspace.root)
        self.instructions = Instructions(workspace)
        self.search = Search(workspace)
        self.search.output_limit = CAPTURE_BYTES
        self.languages = LanguageServers(workspace, self.settings.lsp_servers)
        self.sandbox = self.settings.sandbox
        self.extensions = Extensions(workspace, self.settings)
        self.set_mode(mode)
        self.revision = 0
        self.diffs = []
        self.shell_evidence = []
        self.team = None
        self.jobs = Jobs(self)
        self.allowed_tools = None
        self.mode_ceiling = None
        self.enable_hooks = True
        self.model_config = lambda: None

    def set_mode(self, mode):
        if mode not in {"plan", "build"}:
            raise ValueError("Mode must be plan or build.")
        self.mode = mode

    @property
    def read_only(self):
        return (
            self.mode == "plan" or self.mode_ceiling is not None and self.mode_ceiling() == "plan"
        )

    @property
    def specs(self):
        return self.specs_for(self.model_config())

    def specs_for(self, config):
        specs = (
            [s for s in SPECS if not self.read_only or s.name not in MUTATING]
            + self.extensions.specs(self.mode)
            + [
                s
                for s in TEAM_SPECS
                if (self.team or s.name.endswith("_process"))
                and (not self.read_only or s.name not in MUTATING)
            ]
        )
        selected = TOOL_SETS[config.tool_set] if config else None
        specs = [
            s
            for s in specs
            if (self.allowed_tools is None or s.name in self.allowed_tools)
            and (selected is None or s.name in selected)
            and not (config and config.edit_format == "whole_file" and s.name == "edit_file")
        ]
        if config and config.edit_format == "exact":
            specs = [
                replace(s, description="Create a new UTF-8 file. Use edit_file for existing files.")
                if s.name == "write_file"
                else s
                for s in specs
            ]
        return specs

    def check_profile(self, name, args=None):
        config = self.model_config()
        if not config:
            return
        selected = TOOL_SETS[config.tool_set]
        if selected is not None and name not in selected:
            raise ToolError(f"The model's {config.tool_set} tool set excludes {name}.")
        if config.edit_format == "whole_file" and name == "edit_file":
            raise ToolError(
                "This model uses whole-file writes. Read the file, then use write_file."
            )
        if (
            config.edit_format == "exact"
            and name == "write_file"
            and args
            and self.workspace.resolve(args["path"]).exists()
        ):
            raise ToolError("This model uses exact edits for existing files. Use edit_file.")

    def prepare(self, call: ToolCall) -> PreparedTool:
        try:
            return self._prepare(call)
        except ToolError as exc:
            raise ToolError(self.outputs.preview(str(exc))) from exc

    def _prepare(self, call: ToolCall) -> PreparedTool:
        self.check_profile(call.name)
        if self.allowed_tools is not None and call.name not in self.allowed_tools:
            raise ToolError("This run's restricted tool set blocks the action.")
        if self.read_only and call.name in MUTATING:
            raise ToolError(
                "Plan mode is read-only: file changes and all shell commands are disabled. "
                "Ask the user to switch to build mode."
            )
        spec = next(
            (
                s
                for s in SPECS
                + self.extensions.specs("build")
                + [s for s in TEAM_SPECS if self.team or s.name.endswith("_process")]
                if s.name == call.name
            ),
            None,
        )
        if spec is None:
            raise ToolError(
                f"Unknown tool {call.name!r}. Available: " + ", ".join(s.name for s in self.specs)
            )
        try:
            args = json.loads(call.arguments)
        except RecursionError as exc:
            raise ToolError("Tool arguments exceed the JSON nesting limit.") from exc
        except json.JSONDecodeError as exc:
            raise ToolError(f"Invalid tool JSON: {exc.msg}. Send a complete JSON object.") from exc
        try:
            Draft202012Validator(spec.parameters).validate(args)
        except RecursionError as exc:
            raise ToolError(
                "Tool schema or arguments exceed the validation recursion limit."
            ) from exc
        except ValidationError as exc:
            raise ToolError(f"Invalid arguments for {call.name}: {exc.message}") from exc
        self.check_profile(call.name, args)
        self.extensions.check_mode(call.name, args, self.mode)
        if self.team:
            self.team.check_mode(call.name, args)
        if "path" in args and spec in SPECS:
            self.instructions.observe(args["path"])
        write = None
        server = None
        required = spec.requires_approval
        if call.name in {"write_file", "edit_file"}:
            self.instructions.require_before_edit(args["path"])
            prepare = (
                self.workspace.prepare_write
                if call.name == "write_file"
                else self.workspace.prepare_edit
            )
            write = prepare(**args)
        elif call.name.startswith("lsp_"):
            server = self.languages.select(args["path"])
            required = not self.languages.started(server)
        hooks = (
            tuple(h for h in self.extensions.catalog.hooks if h.matches(call.name))
            if self.mode == "build" and self.enable_hooks
            else ()
        )
        extension_context = self.extensions.approval(call.name, args)
        if spec in TEAM_SPECS:
            extension_context = extension_context | self.team_context(call.name, args)
        if hooks:
            extension_context = extension_context | {"hooks_backend": asdict(self.sandbox)}
            if server:
                extension_context["language_server_command"] = list(server.command)
        key = (
            self.approval_key(call.name, args, hooks, extension_context)
            if hooks or extension_context
            else None
        )
        return PreparedTool(
            call,
            spec,
            args,
            write,
            required or bool(hooks),
            server,
            hooks,
            key,
            extension_context,
            self.extensions.generation,
            str(self.workspace.root),
        )

    def team_context(self, name, args):
        if name.endswith("_process"):
            return {
                "background_backend": asdict(self.sandbox),
                "workspace": str(self.workspace.root),
            }
        return self.team.approval(name, args) if self.team else {}

    def approval_key(self, name, args, hooks, extension_context):
        return fingerprint(
            {
                "name": name,
                "arguments": args,
                "hooks": [asdict(h) for h in hooks],
                "extension": extension_context,
                "sandbox": asdict(self.sandbox),
            }
        )

    async def execute(self, prepared: PreparedTool, *, approved: bool = False) -> str:
        try:
            self.check_prepared(prepared, approved)
            before = await self.run_hooks(prepared, "before_tool")
            try:
                output = await self._execute(prepared, approved=approved)
            except (ToolError, OSError, ValueError) as exc:
                after = await self.run_hooks(prepared, "after_tool", str(exc), is_error=True)
                raise ToolError(str(exc) + before + after) from exc
            after = await self.run_hooks(prepared, "after_tool", output)
            output += before + after
            return output if prepared.call.name == "read_output" else self.outputs.preview(output)
        except ToolError as exc:
            raise ToolError(self.outputs.preview(str(exc))) from exc

    def check_prepared(self, prepared, approved):
        self.check_profile(prepared.call.name, prepared.arguments)
        if self.allowed_tools is not None and prepared.call.name not in self.allowed_tools:
            raise ToolError("This run's restricted tool set blocks the action.")
        if self.read_only and prepared.call.name in MUTATING:
            raise ToolError("Plan mode blocks this action even when it was previously approved.")
        if self.mode == "plan" and prepared.hooks:
            raise ToolError("Plan mode blocks previously prepared hook commands.")
        self.extensions.check_mode(prepared.call.name, prepared.arguments, self.mode)
        if self.team:
            self.team.check_mode(prepared.call.name, prepared.arguments)
        if prepared.spec in TEAM_SPECS:
            current = self.team_context(prepared.call.name, prepared.arguments)
            if any(prepared.extension_context.get(k) != v for k, v in current.items()):
                raise ToolError("Team action configuration changed; prepare it again.")
        if prepared.generation != self.extensions.generation:
            raise ToolError(
                "Extensions were reloaded while waiting for approval. Prepare the action again."
            )
        if prepared.approval_key and prepared.approval_key != self.approval_key(
            prepared.call.name, prepared.arguments, prepared.hooks, prepared.extension_context
        ):
            raise ToolError("Action configuration changed while waiting for approval.")
        if prepared.requires_approval and not approved:
            raise ToolError("Permission denied. Do not retry this action without user direction.")

    async def run_hooks(self, prepared, event, output=None, is_error=False):
        evidence = ""
        for hook in prepared.hooks:
            if hook.event != event:
                continue
            args = {
                k: v[:12000] if isinstance(v, str) else v for k, v in prepared.arguments.items()
            }
            payload = {
                "event": event,
                "tool": prepared.call.name,
                "arguments": args,
                "truncated_arguments": [
                    k
                    for k, v in prepared.arguments.items()
                    if isinstance(v, str) and len(v) > 12000
                ],
                "result": output[:12000] if output is not None else None,
                "is_error": is_error,
            }
            try:
                result = await run_shell(
                    hook.command,
                    self.workspace.root,
                    hook.timeout_seconds,
                    sandbox=self.sandbox,
                    output_limit=24000,
                    input_data=json.dumps(payload).encode(),
                )
            except (ToolError, OSError) as exc:
                self.shell_evidence.append(
                    {"hook": hook.name, "event": event, "ok": False, "output": str(exc)[-2000:]}
                )
                stage = (
                    "Tool action was blocked before execution."
                    if event == "before_tool"
                    else "Tool action already finished; do not repeat it automatically."
                )
                raise ToolError(
                    f"{stage}\nHook {hook.name} failed:\n{exc}\n"
                    + ("Original tool result:\n" + (output or "") if event == "after_tool" else "")
                ) from exc
            finally:
                # Hooks can change arbitrary workspace files, like approved shell commands.
                self.workspace.read_hashes.clear()
                self.revision += 1
            self.shell_evidence.append(
                {"hook": hook.name, "event": event, "ok": True, "output": result[-2000:]}
            )
            evidence += f"\nHook {hook.name} ({event}):\n{result}"
        return evidence

    async def _execute(self, prepared: PreparedTool, *, approved: bool = False) -> str:
        self.check_prepared(prepared, approved)
        args = prepared.arguments
        match prepared.call.name:
            case "start_process":
                return await self.jobs.start(**args)
            case "poll_process":
                return self.jobs.poll(**args)
            case "stop_process":
                return await self.jobs.stop(**args)
            case "delegate" | "oracle" | "remote_run" | "remote_batch" if self.team:
                return await self.team.execute(prepared.call.name, args)
            case "read_output":
                return self.outputs.read(**args)
            case "write_todos":
                self.todos = validate_todos(args["items"])
                return json.dumps(self.todos, ensure_ascii=False)
            case "repo_map":
                return await self.repo_map.build(**args)
            case "read_file":
                return self.workspace.read_file(**args)
            case "list_dir":
                return self.workspace.list_dir(**args)
            case "write_file" | "edit_file":
                assert prepared.write is not None
                # Instructions can change while the approval prompt is open, too.
                self.instructions.require_before_edit(args["path"])
                result = self.workspace.apply_write(prepared.write)
                self.revision += 1
                self.diffs.append(prepared.write.diff)
                try:
                    await self.languages.changed(args["path"])
                except ToolError:
                    result += (
                        " Language server refresh failed; "
                        "re-query diagnostics before relying on them."
                    )
                return result + "\n" + prepared.write.diff
            case "grep":
                return await self.search.grep(**args)
            case "glob":
                return await self.search.glob(**args)
            case "run_shell":
                try:
                    result = await run_shell(
                        root=self.workspace.root,
                        sandbox=self.sandbox,
                        output_limit=CAPTURE_BYTES,
                        **args,
                    )
                except ToolError as exc:
                    self.shell_evidence.append(
                        {"command": args["command"], "ok": False, "output": str(exc)[-2000:]}
                    )
                    raise
                self.shell_evidence.append(
                    {"command": args["command"], "ok": True, "output": result[-2000:]}
                )
                return result
            case "lsp_diagnostics" | "lsp_definition" | "lsp_references":
                assert prepared.server is not None
                return await self.languages.execute(
                    prepared.server, prepared.call.name[4:], **dict(args)
                )
        return await self.extensions.execute(prepared.call.name, args)

    async def close(self):
        try:
            await self.jobs.close()
        finally:
            try:
                await self.extensions.close()
            finally:
                await self.languages.close()
