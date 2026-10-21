from __future__ import annotations

import fnmatch
import re
import shlex
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

from smok.settings import ProjectSettings

if TYPE_CHECKING:
    from smok.tools.registry import PreparedTool

Approver = Callable[["PreparedTool"], Awaitable[bool | Literal["always"]]]


def command_matches(command: str, pattern: str) -> bool:
    # Match argv, never a shell-program prefix. Even quoted operators use the approval path.
    if re.search(r"[;&|<>()$`\n\r]", command + pattern):
        return False
    try:
        args, patterns = shlex.split(command), shlex.split(pattern)
    except ValueError:
        return False
    return (
        bool(args)
        and len(args) == len(patterns)
        and all(fnmatch.fnmatchcase(arg, pat) for arg, pat in zip(args, patterns, strict=True))
    )


class PermissionPolicy:
    def __init__(self, settings: ProjectSettings, mode: str | None = None):
        self.settings = settings
        self.mode = mode or settings.permission_mode

    def allowed(self, request: PreparedTool) -> bool:
        if self.mode == "full-auto":
            return True
        if request.approval_key:
            return any(
                rule["tool"] == "extension" and rule.get("key") == request.approval_key
                for rule in self.settings.rules
            )
        name = request.call.name
        if self.mode == "auto-edit" and name in {"write_file", "edit_file"}:
            return True
        for rule in self.settings.rules:
            if name in {"write_file", "edit_file"} and rule["tool"] == "file_edit":
                assert request.write is not None
                path = str(request.write.resolved_path.relative_to(self.settings.root))
                matches = (
                    path == rule["path"]
                    if rule.get("match", "glob") == "exact"
                    else fnmatch.fnmatchcase(path, rule["path"])
                )
                if matches:
                    return True
            elif name == "run_shell" and rule["tool"] == "run_shell":
                command = request.arguments["command"]
                if rule.get("match", "argv") == "exact":
                    if command == rule["command"]:
                        return True
                elif command_matches(command, rule["command"]):
                    return True
            elif request.server and rule["tool"] == "lsp":
                if list(request.server.command) == rule["command"]:
                    return True
        return False

    def remember(self, request: PreparedTool):
        if request.approval_key:
            rule = {"tool": "extension", "key": request.approval_key, "name": request.call.name}
        elif request.call.name in {"write_file", "edit_file"}:
            assert request.write is not None
            path = str(request.write.resolved_path.relative_to(self.settings.root))
            rule = {"tool": "file_edit", "path": path, "match": "exact"}
        elif request.call.name == "run_shell":
            rule = {"tool": "run_shell", "command": request.arguments["command"], "match": "exact"}
        elif request.server:
            rule = {"tool": "lsp", "command": list(request.server.command)}
        else:
            raise ValueError("This action does not support a saved approval.")
        self.settings.add_rule(rule)


async def deny(_request: PreparedTool) -> bool:
    return False


async def allow(_request: PreparedTool) -> bool:
    """Install only after explicit authorization by a client."""
    return True
