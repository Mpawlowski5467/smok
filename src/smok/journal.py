"""Append-only JSONL sessions with durable state boundaries and exclusive resume locks."""

import fcntl
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from smok.state import state_path
from smok.types import Event

MAX_RECORD = 16 * 1024 * 1024
MAX_SESSION = 256 * 1024 * 1024
ID_PATTERN = r"\d{8}T\d{6}Z-[a-f0-9]{8}"


class Journal:
    def __init__(self, workspace: Path, *, resume: str | None = None):
        self.root = workspace.resolve()
        directory = state_path(self.root, "sessions")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.id = resume.removesuffix(".jsonl") if resume else f"{stamp}-{uuid4().hex[:8]}"
        if not re.fullmatch(ID_PATTERN, self.id):
            raise ValueError("Use a session ID from --sessions or /sessions.")
        self.path = state_path(self.root, "sessions", self.id + ".jsonl")
        flags = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW
        if not resume:
            flags |= os.O_CREAT | os.O_EXCL
        descriptor = os.open(self.path, flags, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.stream = os.fdopen(descriptor, "r+b", buffering=0)
        except OSError as exc:
            os.close(descriptor)
            raise ValueError("This session is already open in another Smok process.") from exc
        self.loaded = None
        try:
            if resume:
                header, state, valid_bytes = self.read(self.path)
                if header.get("workspace") != str(self.root):
                    raise ValueError("The saved session belongs to a different workspace.")
                if header.get("schema_version") != 2 or state is None:
                    raise ValueError("This older event-only log cannot be resumed.")
                self.loaded = state
                # A process crash may leave an incomplete last record. Discard only that suffix.
                self.stream.truncate(valid_bytes)
                self.write(Event("session_resumed", {"id": self.id}))
            else:
                self.write(
                    Event(
                        "session_started",
                        {
                            "id": self.id,
                            "workspace": str(self.root),
                            "schema_version": 2,
                        },
                    )
                )
        except BaseException:
            self.close()
            raise

    @staticmethod
    def read(path):
        if path.is_symlink() or path.stat().st_size > MAX_SESSION:
            raise ValueError("Session path is redirected or exceeds the 256 MiB read limit.")
        header, state, valid_bytes = {}, None, 0
        with path.open("rb") as stream:
            while raw := stream.readline(MAX_RECORD + 1):
                if len(raw) > MAX_RECORD:
                    raise ValueError("Session record exceeds the 16 MiB limit.")
                if not raw.endswith(b"\n"):
                    break
                try:
                    record = json.loads(raw)
                except (ValueError, UnicodeError) as exc:
                    raise ValueError("Session contains a damaged complete JSONL record.") from exc
                if not isinstance(record, dict) or not isinstance(record.get("data"), dict):
                    raise ValueError("Invalid session record.")
                if not valid_bytes:
                    if record.get("type") != "session_started":
                        raise ValueError("Missing session header.")
                    header = record["data"]
                if record.get("type") == "session_state":
                    state = record["data"]
                valid_bytes += len(raw)
        return header, state, valid_bytes

    def write(self, event: Event) -> None:
        entry = {"timestamp": datetime.now(UTC).isoformat(), **event.to_dict()}
        raw = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
        if len(raw) > MAX_RECORD:
            raise ValueError("Session record exceeds 16 MiB; compact before continuing.")
        if self.stream.seek(0, os.SEEK_END) + len(raw) > MAX_SESSION:
            raise ValueError("Session exceeds 256 MiB; start a handoff session.")
        self.stream.write(raw)
        if event.type in {"session_state", "session_started"}:
            os.fsync(self.stream.fileno())

    def save(self, state):
        self.write(Event("session_state", state))

    def close(self):
        self.stream.close()

    @classmethod
    def list(cls, root):
        directory = state_path(root, "sessions")
        if not directory.exists():
            return []
        rows = []
        for path in sorted(
            directory.glob("*.jsonl"), key=lambda p: p.lstat().st_mtime, reverse=True
        ):
            if path.is_symlink():
                continue
            try:
                header, state, _ = cls.read(path)
                if header.get("workspace") != str(root.resolve()):
                    continue
                rows.append(
                    {
                        "id": path.stem,
                        "model": state.get("model") if state else None,
                        "resumable": header.get("schema_version") == 2 and state is not None,
                        "turns": state.get("turns", 0) if state else 0,
                        "updated": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                    }
                )
            except (ValueError, OSError):
                continue
        return rows[:100]

    @classmethod
    def latest(cls, root):
        row = next((r for r in cls.list(root) if r["resumable"]), None)
        if row is None:
            raise ValueError("No resumable sessions in this workspace.")
        return row["id"]
