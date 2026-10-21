import hashlib
from pathlib import Path

from smok.tools.files import ToolError, Workspace


class Instructions:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.seen: dict[Path, str] = {}
        self.directories = {workspace.root}

    @staticmethod
    def read(path):
        with path.open("rb") as stream:
            raw = stream.read(32769)
        if len(raw) > 32768:
            raise ToolError("An AGENTS.md file exceeds the 32 KiB instruction limit.")
        return raw

    def paths_for(self, raw: str):
        path = self.workspace.resolve(raw)
        directory = path if path.is_dir() else path.parent
        chain = []
        while directory.is_relative_to(self.workspace.root):
            candidate = directory / "AGENTS.md"
            if candidate.is_file():
                resolved = self.workspace.resolve(str(candidate))
                chain.append(resolved)
            if directory == self.workspace.root:
                break
            directory = directory.parent
        return list(reversed(chain))

    def observe(self, path: str):
        resolved = self.workspace.resolve(path)
        self.directories.add(resolved if resolved.is_dir() else resolved.parent)

    def build(self):
        paths = set()
        for directory in self.directories:
            paths.update(self.paths_for(str(directory) + "/"))
        text = []
        total = 0
        for path in sorted(paths, key=lambda p: (len(p.parts), str(p))):
            raw = self.read(path)
            total += len(raw)
            if total > 65536:
                raise ToolError("Project AGENTS.md instructions exceed the 64 KiB prompt budget.")
            content = raw.decode("utf-8")
            digest = hashlib.sha256(raw).hexdigest()
            self.seen[path] = digest
            self.workspace.read_hashes[path] = digest
            name = path.relative_to(self.workspace.root)
            text.append(
                f"\nProject instructions from {name} (apply within {name.parent}):\n{content}\n"
            )
        return "".join(text)

    def require_before_edit(self, path: str):
        for instruction in self.paths_for(path):
            digest = hashlib.sha256(self.read(instruction)).hexdigest()
            if (
                self.seen.get(instruction) != digest
                and self.workspace.read_hashes.get(instruction) != digest
            ):
                name = instruction.relative_to(self.workspace.root)
                raise ToolError(
                    f"Read {name} before editing this scope. Its instructions are new or changed."
                )
