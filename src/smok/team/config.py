"""Opt-in model routes and bounded teamwork configuration."""

import re
from dataclasses import dataclass, field

ROLES = {"explore", "plan", "edit", "review", "oracle"}
READ_TOOLS = frozenset({"read_file", "list_dir", "grep", "glob", "repo_map", "read_output"})
EDIT_TOOLS = READ_TOOLS | {"write_file", "edit_file", "run_shell", "write_todos"}


@dataclass(frozen=True)
class TeamConfig:
    routes: dict = field(default_factory=dict)
    ladder: tuple = ()
    shadow_model: str | None = None
    max_workers: int = 3
    worker_iterations: int = 8
    max_requests: int = 48
    timeout_seconds: int = 600
    stall_threshold: int = 3
    remote_runners: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or set(data) - cls.__dataclass_fields__.keys():
            raise ValueError("Invalid team settings.")
        values = dict(data)
        routes = values.get("routes", {})
        if (
            not isinstance(routes, dict)
            or set(routes) - ROLES
            or any(not isinstance(v, str) or not v for v in routes.values())
        ):
            raise ValueError("Team routes map explore, plan, edit, review, or oracle to models.")
        ladder = values.get("ladder", [])
        if (
            not isinstance(ladder, (list, tuple))
            or len(ladder) > 3
            or any(not isinstance(v, str) or not v for v in ladder)
            or len(set(ladder)) != len(ladder)
        ):
            raise ValueError("The ladder needs up to three distinct model selectors.")
        values["ladder"] = tuple(ladder)
        for key, maximum in {
            "max_workers": 3,
            "worker_iterations": 40,
            "max_requests": 500,
            "timeout_seconds": 1800,
            "stall_threshold": 10,
        }.items():
            value = values.get(key, getattr(cls(), key))
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
                raise ValueError(f"team.{key} must be an integer from 1 to {maximum}.")
        shadow = values.get("shadow_model")
        if shadow is not None and (not isinstance(shadow, str) or not shadow):
            raise ValueError("shadow_model must be a model selector.")
        runners = values.get("remote_runners", {})
        if not isinstance(runners, dict) or len(runners) > 10:
            raise ValueError("remote_runners must be an object with up to ten runners.")
        for name, runner in runners.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", name) or not isinstance(runner, dict):
                raise ValueError("Invalid runner name or configuration.")
            if set(runner) != {"host", "command"}:
                raise ValueError("A runner needs an SSH host and fixed command argv.")
            if not isinstance(runner["host"], str) or not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,200}", runner["host"]
            ):
                raise ValueError("Invalid SSH host; use an SSH config alias or user@host.")
            command = runner["command"]
            if (
                not isinstance(command, list)
                or not command
                or len(command) > 30
                or any(not isinstance(v, str) or not v or "\0" in v or "\n" in v for v in command)
            ):
                raise ValueError("Runner command must be a fixed argv list.")
        return cls(**values)
