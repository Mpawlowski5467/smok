"""Observed attempt timing and proof that project checks covered the final files."""

import json

if __package__:
    from .suite import digest, snapshot
else:
    from suite import digest, snapshot


class AttemptEvidence:
    def __init__(self, task, root, start):
        self.root = root
        self.required = task.get("verification_commands", [])
        self.start = start
        self.models = []
        self.tools = []
        self.commands = []
        self.active = None
        self.approval_started = None
        self.approval_seconds = 0.0

    def _close(self, now, outcome):
        if self.active is None:
            return
        kind, row = self.active
        row.update(seconds=round(now - row["started_seconds"], 4), outcome=outcome)
        (self.models if kind == "model" else self.tools).append(row)
        self.active = None

    def observe(self, event, now):
        data = event.data
        if event.type == "model_started":
            self._close(now, "interrupted")
            self.active = (
                "model",
                {
                    "iteration": data["iteration"],
                    "purpose": data["purpose"],
                    "started_seconds": now,
                },
            )
        elif event.type == "usage":
            self._close(now, "returned")
        elif event.type == "tool_call":
            self._close(now, "interrupted")
            row = {"id": data["id"], "name": data["name"], "started_seconds": now}
            if data["name"] == "run_shell":
                try:
                    arguments = json.loads(data["arguments"])
                except (ValueError, TypeError):
                    arguments = {}
                command = arguments.get("command") if isinstance(arguments, dict) else None
                if command in self.required:
                    row["verification"] = {
                        "command": command,
                        "before": digest(snapshot(self.root)),
                    }
            self.active = ("tool", row)
        elif event.type == "permission_requested":
            self.approval_started = now
        elif event.type == "permission_resolved":
            if self.approval_started is not None:
                self.approval_seconds += now - self.approval_started
                self.approval_started = None
        elif event.type == "tool_result":
            if self.active and self.active[0] == "tool":
                verification = self.active[1].pop("verification", None)
                if verification:
                    self.commands.append(
                        {
                            **verification,
                            "after": digest(snapshot(self.root)),
                            "ok": not data["is_error"],
                            "finished_seconds": now,
                        }
                    )
            self._close(now, "error" if data["is_error"] else "returned")

    def finish_work(self, now):
        if self.approval_started is not None:
            self.approval_seconds += now - self.approval_started
            self.approval_started = None
        if self.active:
            # An interrupted command is evidence of an attempt, never of a passing check.
            verification = self.active[1].pop("verification", None)
            if verification:
                self.commands.append(
                    {**verification, "after": None, "ok": False, "finished_seconds": now}
                )
        self._close(now, "interrupted")
        model_seconds = sum(r["seconds"] for r in self.models)
        tool_seconds = sum(r["seconds"] for r in self.tools)
        return {
            "work_seconds": round(now - self.start, 4),
            "model_seconds": round(model_seconds, 4),
            "tool_seconds": round(tool_seconds, 4),
            "approval_seconds": round(self.approval_seconds, 4),
            "other_work_seconds": round(max(0, now - self.start - model_seconds - tool_seconds), 4),
            "model_requests": self.models,
            "tool_calls": self.tools,
        }

    def verification(self):
        final = digest(snapshot(self.root))
        commands = [
            {**row, "matches_final_files": row["before"] == row["after"] == final}
            for row in self.commands
        ]
        latest = {row["command"]: row for row in commands}
        passed = all(
            command in latest and latest[command]["ok"] and latest[command]["matches_final_files"]
            for command in self.required
        )
        return {
            "required": self.required,
            "passed": passed,
            "commands": commands,
            "final_files_fingerprint": final,
        }
