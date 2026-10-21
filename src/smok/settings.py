import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from smok.state import state_path, write_json

PERMISSION_MODES = ("ask", "auto-edit", "full-auto")


@dataclass(frozen=True)
class Sandbox:
    backend: str = "host"
    image: str = "python:3.12-slim"
    network: bool = False

    def __post_init__(self):
        if self.backend not in {"host", "docker"}:
            raise ValueError("Sandbox must be host or docker.")
        if not isinstance(self.image, str) or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9._/:@-]*", self.image
        ):
            raise ValueError("Invalid Docker image reference.")
        if not isinstance(self.network, bool):
            raise ValueError("sandbox.network must be true or false.")


@dataclass(frozen=True)
class LanguageServer:
    language: str
    extensions: tuple[str, ...]
    command: tuple[str, ...]
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Each LSP server must be an object.")
        language, extensions, command = (
            value.get(k) for k in ("language", "extensions", "command")
        )
        if not isinstance(language, str) or not language:
            raise ValueError("An LSP server needs a language identifier.")
        if (
            not isinstance(extensions, list)
            or not extensions
            or not all(isinstance(e, str) and e.startswith(".") for e in extensions)
        ):
            raise ValueError("LSP extensions must be a nonempty list such as ['.py'].")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in command)
        ):
            raise ValueError("LSP command must be a nonempty argv list.")
        settings = value.get("settings", {})
        if not isinstance(settings, dict):
            raise ValueError("LSP settings must be an object.")
        return cls(language, tuple(extensions), tuple(command), settings)


DEFAULT_LSP = LanguageServer(
    "python",
    (".py", ".pyi"),
    ("pylsp",),
    {"pylsp": {"plugins": {"pycodestyle": {"enabled": False}, "mccabe": {"enabled": False}}}},
)


class ProjectSettings:
    def __init__(self, root: Path, *, data=None):
        self.root = root.resolve()
        path = state_path(self.root, "settings.json")
        self.data = (
            data if data is not None else (json.loads(path.read_text()) if path.exists() else {})
        )
        if not isinstance(self.data, dict):
            raise ValueError(".smok/settings.json must contain an object.")
        self.permission_mode = self.data.get("permissions", "ask")
        if self.permission_mode not in PERMISSION_MODES:
            raise ValueError("permissions must be ask, auto-edit, or full-auto.")
        self.rules = self.data.get("allow_rules", [])
        if not isinstance(self.rules, list) or not all(isinstance(r, dict) for r in self.rules):
            raise ValueError("allow_rules must be a list of rule objects.")
        for rule in self.rules:
            tool = rule.get("tool")
            if tool == "file_edit" and isinstance(rule.get("path"), str):
                if rule.get("match", "glob") in {"glob", "exact"}:
                    continue
            if tool == "run_shell" and isinstance(rule.get("command"), str):
                if rule.get("match", "argv") in {"argv", "exact"}:
                    continue
            if tool == "lsp" and isinstance(rule.get("command"), list):
                if all(isinstance(p, str) for p in rule["command"]):
                    continue
            if tool == "extension" and isinstance(rule.get("key"), str):
                if re.fullmatch(r"[a-f0-9]{64}", rule["key"]):
                    continue
            raise ValueError(
                "Invalid allow rule: expected file_edit, run_shell, lsp, or extension."
            )
        sandbox = self.data.get("sandbox", {})
        if not isinstance(sandbox, dict) or set(sandbox) - {"backend", "image", "network"}:
            raise ValueError("Invalid sandbox settings.")
        self.sandbox = Sandbox(**sandbox)
        servers = self.data.get("lsp_servers")
        if servers is not None and not isinstance(servers, list):
            raise ValueError("lsp_servers must be a list.")
        self.lsp_servers = (
            [LanguageServer.parse(v) for v in servers] if servers is not None else [DEFAULT_LSP]
        )

    def save(self) -> None:
        # Preserve unrelated configuration edited on disk since this client started.
        path = state_path(self.root, "settings.json")
        latest = json.loads(path.read_text()) if path.exists() else self.data
        if not isinstance(latest, dict):
            raise ValueError(".smok/settings.json must contain an object.")
        self.data = latest
        self.data.update(
            {
                "permissions": self.permission_mode,
                "allow_rules": self.rules,
                "sandbox": asdict(self.sandbox),
            }
        )
        write_json(path, self.data)

    def set_permissions(self, mode: str) -> None:
        if mode not in PERMISSION_MODES:
            raise ValueError("Choose ask, auto-edit, or full-auto.")
        self.permission_mode = mode
        self.save()

    def add_rule(self, rule: dict[str, Any]) -> None:
        if rule not in self.rules:
            self.rules.append(rule)
            self.save()
