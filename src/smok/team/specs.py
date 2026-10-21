from smok.types import ToolSpec


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


TASK = {"type": "string", "minLength": 1, "maxLength": 12000}
SPECS = [
    ToolSpec(
        "delegate",
        "Run 1-3 independent workers with fresh contexts; returns summaries only. "
        "Explore/plan/review are read-only; edits use an isolated worktree. No nested delegation.",
        obj(
            {
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": obj(
                        {"task": TASK, "role": {"enum": ["explore", "plan", "edit", "review"]}},
                        ["task", "role"],
                    ),
                }
            },
            ["tasks"],
        ),
        True,
    ),
    ToolSpec(
        "oracle",
        "Ask the configured second-opinion model. Read-only; returns bounded advice.",
        obj({"question": TASK}, ["question"]),
        True,
    ),
    ToolSpec(
        "remote_run",
        "Send a repository snapshot and task to a configured SSH sandbox runner. "
        "Returns a summary and patch artifact; never applies remote changes automatically.",
        obj({"runner": {"type": "string"}, "task": TASK}, ["runner", "task"]),
        True,
    ),
    ToolSpec(
        "remote_batch",
        "Run 1-3 independent tasks concurrently on configured SSH sandbox runners. "
        "Each job reserves its own part of the shared budget and returns a patch artifact.",
        obj(
            {
                "jobs": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": obj({"runner": {"type": "string"}, "task": TASK}, ["runner", "task"]),
                }
            },
            ["jobs"],
        ),
        True,
    ),
    ToolSpec(
        "start_process",
        "Start a session-owned background shell on the selected backend. "
        "Poll output by ID; all jobs stop when Smok exits. Effects can outlive a checkpoint.",
        obj(
            {
                "command": TASK,
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
            },
            ["command"],
        ),
        True,
    ),
    ToolSpec(
        "poll_process",
        "List jobs or read their bounded output ring. Offsets are bytes.",
        obj({"id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}}),
    ),
    ToolSpec(
        "stop_process",
        "Stop a background process and its process group.",
        obj({"id": {"type": "string"}}, ["id"]),
        True,
    ),
]
MUTATING = {"start_process", "stop_process", "remote_run", "remote_batch"}
