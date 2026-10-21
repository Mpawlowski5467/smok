"""Private, addressable tool transcripts; previews never grant general metadata access."""

import os
import re
from uuid import uuid4

from smok.state import state_path
from smok.tools.files import ToolError

CAPTURE_BYTES = 16 * 1024 * 1024
PREVIEW_CHARS = 12000


class OutputStore:
    def __init__(self, root):
        self.root = root

    def save(self, text):
        identifier = uuid4().hex
        path = state_path(self.root, "outputs", identifier + ".txt")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = text.encode("utf-8")
        truncated = len(raw) > CAPTURE_BYTES
        if truncated:
            raw = raw[:CAPTURE_BYTES].decode("utf-8", errors="ignore").encode("utf-8")
            raw += b"\n[Archive reached the 16 MiB storage limit; remaining output is unavailable.]"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return identifier, truncated

    def preview(self, text):
        if len(text) <= PREVIEW_CHARS:
            return text
        identifier, truncated = self.save(text)
        label = "Output archive capped" if truncated else "Full tool output saved"
        return (
            text[:PREVIEW_CHARS] + f"\n[Preview truncated. {label}: {identifier}. "
            f'Use read_output with id="{identifier}" and character offset/limit.]'
        )

    def read(self, id: str, offset: int = 0, limit: int = 12000):
        if not re.fullmatch(r"[a-f0-9]{32}", id):
            raise ToolError("Invalid output ID. Use the ID returned with a truncated preview.")
        path = state_path(self.root, "outputs", id + ".txt")
        try:
            with path.open("rb") as stream:
                raw = stream.read(CAPTURE_BYTES + 1024)
        except FileNotFoundError as exc:
            raise ToolError("This output archive is missing in the current workspace.") from exc
        if len(raw) > CAPTURE_BYTES + 512:
            raise ToolError("Output archive exceeds its storage limit.")
        text = raw.decode("utf-8")
        end = min(len(text), offset + limit)
        return f"Output {id}: characters {offset}:{end} of {len(text)}\n" + text[offset:end]
