"""Shadow Git snapshots, independent of the user's repository and index."""

import contextlib
import difflib
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from smok.state import state_path, write_json
from smok.tools.files import ToolError, bounded

EXCLUDED = {".git", ".smok", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
MAX_FILES = 5000
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024


def git_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Smok checkpoint",
            "GIT_AUTHOR_EMAIL": "smok@localhost",
            "GIT_COMMITTER_NAME": "Smok checkpoint",
            "GIT_COMMITTER_EMAIL": "smok@localhost",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return env


class Checkpoints:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.directory = state_path(root, "checkpoints")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.repo = state_path(root, "checkpoints", "objects.git")
        self.path = state_path(root, "checkpoints", "history.json")
        self.lock = None
        self.pending = None
        self.history = []

    def _acquire(self):
        if self.lock is not None:
            raise ToolError("A checkpoint operation is already running.")
        descriptor = os.open(
            state_path(self.root, "checkpoints", "lock"),
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(descriptor)
            raise ToolError(
                "Another Smok turn is using this workspace. Wait for it to finish."
            ) from exc
        self.lock = descriptor
        try:
            self._load()
            if not self.repo.exists():
                self._command(
                    ["git", "init", "--bare", "--quiet", "--object-format=sha1", str(self.repo)]
                )
        except BaseException:
            self._release()
            raise

    def _release(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    def _load(self):
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.history = data.get("history", [])
        self.pending = data.get("pending")

    def _save(self):
        write_json(self.path, {"version": 1, "history": self.history, "pending": self.pending})

    def _command(self, argv, data=None, *, check=True):
        try:
            result = subprocess.run(
                argv,
                input=data,
                capture_output=True,
                cwd=self.root,
                env=git_environment(),
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError(
                "Checkpoint Git operation failed. Check Git installation and disk access."
            ) from exc
        if check and result.returncode:
            raise ToolError(
                "Checkpoint Git operation failed: " + result.stderr.decode(errors="replace")[:500]
            )
        return result

    def _git(self, args, data=None, *, check=True):
        return self._command(
            [
                "git",
                "--git-dir=" + str(self.repo),
                "--work-tree=" + str(self.root),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=" + os.devnull,
                *args,
            ],
            data,
            check=check,
        )

    def _files(self):
        result = self._command(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                ".",
            ],
            check=False,
        )
        if result.returncode:
            result = self._git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
        paths = set(os.fsdecode(p) for p in result.stdout.split(b"\0") if p)
        selected = sorted(p for p in paths if not set(PurePosixPath(p).parts) & EXCLUDED)
        if len(selected) > MAX_FILES:
            raise ToolError(
                "Checkpoint exceeds 5000 files. Narrow the workspace or update .gitignore."
            )
        return selected

    def _path(self, name):
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or set(relative.parts) & EXCLUDED:
            raise ToolError("Unsafe checkpoint path.")
        path = self.root / name
        if not path.parent.resolve().is_relative_to(self.root):
            raise ToolError(f"Checkpoint path escapes the workspace: {name}")
        # A parent symlink can redirect an otherwise relative restore to unrelated data.
        for parent in path.parents:
            if parent == self.root:
                break
            if parent.is_symlink():
                raise ToolError(f"Checkpoint path has a symlink parent: {name}")
        return path

    def _entry(self, name, *, store=False):
        path = self._path(name)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raw = os.fsencode(os.readlink(path))
            kind, mode = "symlink", 0o777
        elif stat.S_ISREG(info.st_mode):
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE + 1)
            if len(raw) > MAX_FILE:
                raise ToolError(f"Checkpoint file exceeds 16 MiB: {name}")
            kind, mode = "file", stat.S_IMODE(info.st_mode)
        elif stat.S_ISDIR(info.st_mode):
            return {"kind": "directory"}
        else:
            raise ToolError(f"Checkpoint cannot capture a special file: {name}")
        oid = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        if store:
            self._git(["hash-object", "-w", "--stdin"], raw)
        return {"oid": oid, "kind": kind, "mode": mode, "size": len(raw)}

    def _snapshot(self):
        entries = {}
        total = 0
        names = set(self._files())
        if self.pending:
            # A changed ignore rule must not hide a file present in the before snapshot.
            names.update(self.pending["before"]["entries"])
        if len(names) > MAX_FILES:
            raise ToolError("Checkpoint exceeds 5000 files.")
        for name in sorted(names):
            entry = self._entry(name, store=True)
            if entry is None or entry["kind"] == "directory":
                continue
            entries[name] = entry
            total += entry["size"]
            if total > MAX_TOTAL:
                raise ToolError(
                    "Checkpoint exceeds 128 MiB. Narrow the workspace or update .gitignore."
                )
        self._git(["read-tree", "--empty"])
        records = bytearray()
        for name, entry in entries.items():
            mode = (
                "120000"
                if entry["kind"] == "symlink"
                else "100755"
                if entry["mode"] & 0o111
                else "100644"
            )
            records.extend(f"{mode} {entry['oid']}\t".encode() + os.fsencode(name) + b"\0")
        self._git(["update-index", "-z", "--index-info"], bytes(records))
        tree = self._git(["write-tree"]).stdout.decode().strip()
        parent = self._git(["rev-parse", "--verify", "refs/heads/checkpoints"], check=False)
        args = ["commit-tree", tree]
        if parent.returncode == 0:
            args += ["-p", parent.stdout.decode().strip()]
        commit = self._git(args, b"Smok workspace checkpoint\n").stdout.decode().strip()
        self._git(["update-ref", "refs/heads/checkpoints", commit])
        return {"commit": commit, "entries": entries}

    @staticmethod
    def changed(before, after):
        return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))

    def begin(self):
        self._acquire()
        try:
            if self.pending:
                # A hard-crashed turn has no reliable end boundary. Preserve its backup, never
                # silently attribute subsequent user changes to that interrupted turn.
                self.history.append({**self.pending, "abandoned": True, "changes": []})
                self.pending = None
            self.pending = {"id": len(self.history) + 1, "before": self._snapshot()}
            self._save()
            return self.pending["id"]
        except BaseException:
            self._release()
            raise

    def finish(self):
        if not self.pending or self.lock is None:
            return None
        try:
            after = self._snapshot()
            record = {
                **self.pending,
                "after": after,
                "undone": False,
                "changes": self.changed(self.pending["before"]["entries"], after["entries"]),
            }
            self.history.append(record)
            self.pending = None
            self._save()
            return record
        finally:
            self._release()

    def _blob(self, entry):
        oid = entry["oid"]
        if not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}", oid):
            raise ToolError("Invalid checkpoint object ID.")
        return self._git(["cat-file", "blob", oid]).stdout

    def review(self):
        if not self.pending:
            return "", "", []
        current = self._snapshot()
        before, after = self.pending["before"]["entries"], current["entries"]
        changes = self.changed(before, after)
        signature = (
            hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest()
            if changes
            else ""
        )
        pieces = ["Changed files: " + bounded(", ".join(changes), 2000) + "\n"] if changes else []
        for name in changes[:20]:
            old = self._blob(before[name]) if name in before else b""
            new = self._blob(after[name]) if name in after else b""
            if name in before and name in after and before[name]["mode"] != after[name]["mode"]:
                pieces.append(
                    f"Mode changed: {name}: {before[name]['mode']:o} -> {after[name]['mode']:o}\n"
                )
            if b"\0" in old or b"\0" in new:
                pieces.append(f"Binary file changed: {name}\n")
            else:
                pieces.extend(
                    difflib.unified_diff(
                        old.decode(errors="replace").splitlines(True),
                        new.decode(errors="replace").splitlines(True),
                        fromfile=f"before/{name}",
                        tofile=f"after/{name}",
                    )
                )
            if sum(map(len, pieces)) > 12000:
                break
        return signature, bounded("".join(pieces), 12000), changes

    def _restore(self, name, entry):
        path = self._path(name)
        if entry is None:
            path.unlink(missing_ok=True)
            return
        raw = self._blob(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".smok-restore-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                if entry["kind"] == "file":
                    stream.write(raw)
            if entry["kind"] == "symlink":
                os.unlink(temporary)
                os.symlink(os.fsdecode(raw), temporary)
            else:
                os.chmod(temporary, entry["mode"])
            os.replace(temporary, path)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)

    def undo(self):
        self._acquire()
        try:
            if self.pending:
                raise ToolError(
                    "An interrupted checkpoint has no end snapshot; review its backup manually."
                )
            record = next(
                (r for r in reversed(self.history) if r.get("changes") and not r.get("undone")),
                None,
            )
            if record is None:
                raise ToolError("No completed changes to undo.")
            before, after = record["before"]["entries"], record["after"]["entries"]
            conflicts = [p for p in record["changes"] if self._entry(p) != after.get(p)]
            if conflicts:
                raise ToolError(
                    "Undo refused: files changed since Smok's turn: " + ", ".join(conflicts)
                )
            restored = []
            try:
                for name in record["changes"]:
                    self._restore(name, before.get(name))
                    restored.append(name)
            except BaseException:
                for name in reversed(restored):
                    with contextlib.suppress(OSError, ToolError):
                        self._restore(name, after.get(name))
                raise
            record["undone"] = True
            self._save()
            return record
        finally:
            self._release()

    def list(self):
        self._load()
        return [
            {
                "id": r["id"],
                "changes": r.get("changes", []),
                "undone": r.get("undone", False),
                "abandoned": r.get("abandoned", False),
            }
            for r in self.history
        ]

    def restore_to(self, identifier):
        """Restore a completed boundary as a new, undoable checkpoint."""
        self._acquire()
        try:
            if self.pending:
                raise ToolError("Finish or stop the active turn before restoring.")
            target = next((r for r in self.history if r["id"] == identifier), None)
            if not target or "after" not in target or target.get("undone"):
                raise ToolError("Choose a completed checkpoint that has not been undone.")
            later = [r for r in self.history if r["id"] > identifier and not r.get("undone")]
            if any("after" not in r for r in later):
                raise ToolError("An interrupted checkpoint prevents an automatic restore.")
            expected = (later[-1] if later else target)["after"]["entries"]
            desired = target["after"]["entries"]
            paths = self.changed(expected, desired)
            conflicts = [p for p in paths if self._entry(p) != expected.get(p)]
            if conflicts:
                raise ToolError(
                    "Restore refused: files changed outside Smok: " + ", ".join(conflicts)
                )
            before = self._snapshot()
            restored = []
            try:
                for name in paths:
                    self._restore(name, desired.get(name))
                    restored.append(name)
                after = self._snapshot()
            except BaseException:
                for name in reversed(restored):
                    with contextlib.suppress(OSError, ToolError):
                        self._restore(name, before["entries"].get(name))
                raise
            record = {
                "id": len(self.history) + 1,
                "before": before,
                "after": after,
                "changes": paths,
                "undone": False,
                "restored_from": identifier,
            }
            self.history.append(record)
            self._save()
            return record
        finally:
            self._release()

    def branch_to(self, identifier, destination):
        """Export a checkpoint into a new directory without changing the source workspace."""
        self._acquire()
        try:
            target = next((r for r in self.history if r["id"] == identifier), None)
            if self.pending or not target or "after" not in target:
                raise ToolError("Choose a completed checkpoint after the active turn ends.")
            if destination.exists():
                raise ToolError("Branch destination already exists.")
            destination.mkdir(parents=True, mode=0o700)
            # Restore regular files first: a saved symlink must never redirect a later write.
            entries = target["after"]["entries"]
            branch = Checkpoints(destination)
            for name, entry in sorted(
                entries.items(), key=lambda item: item[1]["kind"] == "symlink"
            ):
                path = branch._path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = self._blob(entry)
                if entry["kind"] == "symlink":
                    os.symlink(os.fsdecode(raw), path)
                else:
                    path.write_bytes(raw)
                    path.chmod(entry["mode"])
            return destination
        finally:
            self._release()
