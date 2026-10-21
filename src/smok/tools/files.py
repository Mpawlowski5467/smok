import difflib
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 16 * 1_048_576
MAX_OUTPUT_CHARS = 24_000


class ToolError(Exception):
    """A recoverable tool error that should be returned to the model."""


def bounded(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[Output truncated; use a smaller range.]"


@dataclass(frozen=True)
class PendingWrite:
    path: str
    content: str
    expected_hash: str | None
    diff: str
    resolved_path: Path


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Workspace must be a directory.")
        self.read_hashes: dict[Path, str] = {}
        self.output_limit = MAX_OUTPUT_CHARS

    def output(self, text):
        return bounded(text, self.output_limit) if self.output_limit is not None else text

    def resolve(self, raw: str) -> Path:
        candidate = (self.root / raw).resolve()
        if not candidate.is_relative_to(self.root):
            raise ToolError("Path is outside the workspace.")
        if any(p in {".git", ".smok"} for p in candidate.relative_to(self.root).parts):
            raise ToolError("Smok and Git metadata are protected from file tools.")
        return candidate

    def _read(self, path: Path) -> bytes:
        if not path.is_file():
            raise ToolError("Path is not a regular file.")
        # Bound the read itself, not just the returned text.
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ToolError("File exceeds the 16 MiB limit. Use a targeted shell command.")
        if b"\0" in raw:
            raise ToolError("Binary files are not supported by text tools.")
        return raw

    def read_file(self, path: str, offset: int = 1, limit: int = 200) -> str:
        resolved = self.resolve(path)
        raw = self._read(resolved)
        text = raw.decode("utf-8")
        self.read_hashes[resolved] = hashlib.sha256(raw).hexdigest()
        lines = text.splitlines()
        selected = lines[offset - 1 : offset - 1 + limit]
        output = "\n".join(f"{i} | {line}" for i, line in enumerate(selected, start=offset))
        end = min(offset - 1 + limit, len(lines))
        return self.output(f"{path}: {len(lines)} lines; showing {offset}-{end}\n{output}")

    def list_dir(self, path: str = ".") -> str:
        resolved = self.resolve(path)
        if not resolved.is_dir():
            raise ToolError("Path is not a directory.")
        # Stop enumeration too: very large directories should not allocate unbounded memory.
        entries: list[str] = []
        with os.scandir(resolved) as scan:
            for entry in scan:
                if entry.name in {".git", ".smok"}:
                    continue
                suffix = "@" if entry.is_symlink() else "/" if entry.is_dir() else ""
                entries.append(entry.name + suffix)
                if len(entries) == 201:
                    break
        truncated = len(entries) > 200
        output = "\n".join(sorted(entries[:200])) or "(empty directory)"
        if truncated:
            output += "\n[Listing truncated at 200 entries.]"
        return bounded(output)

    def prepare_write(self, path: str, content: str) -> PendingWrite:
        resolved = self.resolve(path)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ToolError("Write exceeds the 16 MiB limit.")
        old = ""
        expected = None
        if resolved.exists():
            raw = self._read(resolved)
            expected = hashlib.sha256(raw).hexdigest()
            if self.read_hashes.get(resolved) != expected:
                raise ToolError(
                    "Read the file with read_file before overwriting it; it may have changed."
                )
            old = raw.decode("utf-8")
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{path}" if expected else "/dev/null",
                tofile=f"b/{path}",
            )
        )
        return PendingWrite(path, content, expected, diff, resolved)

    def apply_write(self, pending: PendingWrite) -> str:
        resolved = self.resolve(pending.path)
        if resolved != pending.resolved_path:
            raise ToolError("File path changed while waiting for approval. Read it again.")
        actual = hashlib.sha256(self._read(resolved)).hexdigest() if resolved.exists() else None
        if actual != pending.expected_hash:
            raise ToolError(
                "File changed while waiting for approval. Read it again before writing."
            )
        mode = (resolved.stat().st_mode & 0o777) if resolved.exists() else 0o644
        resolved.parent.mkdir(parents=True, exist_ok=True)
        # Replace atomically so a failed write cannot leave a half-written file.
        fd, temporary = tempfile.mkstemp(prefix=".smok-write-", dir=resolved.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(pending.content.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, resolved)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        # The model knows the exact bytes it just supplied. Keep that version as
        # observed so a follow-up edit does not require an otherwise redundant
        # read. prepare_write/apply_write still reject any intervening change;
        # hooks and context resets continue to invalidate this knowledge.
        self.read_hashes[resolved] = hashlib.sha256(pending.content.encode("utf-8")).hexdigest()
        return f"Wrote {len(pending.content.encode('utf-8'))} bytes to {pending.path}."

    def prepare_edit(self, path: str, old_text: str, new_text: str) -> PendingWrite:
        if not old_text:
            raise ToolError("old_text must not be empty. Use write_file to create a file.")
        resolved = self.resolve(path)
        content = self._read(resolved).decode("utf-8")
        first = content.find(old_text)
        repeated = first != -1 and content.find(old_text, first + 1) != -1
        if first == -1 or repeated:
            count = "multiple" if repeated else "no"
            raise ToolError(
                f"old_text must match exactly once; found {count} matches. Include more context."
            )
        if old_text == new_text:
            raise ToolError("old_text and new_text are identical; no edit is needed.")
        return self.prepare_write(path, content.replace(old_text, new_text, 1))
