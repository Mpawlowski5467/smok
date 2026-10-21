"""Private snapshot commits and detached candidates; never change the user's index or HEAD."""

import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from smok.checkpoints import git_environment
from smok.state import state_path
from smok.tools.files import ToolError

EXCLUDE = [".", ":(exclude).smok", ":(exclude).smok/**"]


def git(root, *args, env=None, input=None, limit=4 * 1024 * 1024, check=True):
    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "commit.gpgSign=false",
                *args,
            ],
            cwd=root,
            env=env or git_environment(),
            input=input,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError("Git workspace operation could not finish within 60 seconds.") from exc
    if check and result.returncode:
        raise ToolError(
            "Git workspace operation failed: " + result.stderr.decode(errors="replace")[:2000]
        )
    if len(result.stdout) > limit:
        raise ToolError("Git workspace output exceeds the capture limit.")
    return result.stdout


def no_filters(root):
    names = git(
        root,
        "config",
        "--null",
        "--name-only",
        "--get-regexp",
        r"^filter\..*\.(clean|smudge|process|required)$",
        check=False,
    ).split(b"\0")
    overrides = []
    for raw in names:
        if raw:
            name = raw.decode("utf-8")
            overrides += ["-c", name + ("=false" if name.endswith(".required") else "=")]
    return overrides


def root_check(root):
    top = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip()).resolve()
    if top != root.resolve():
        raise ToolError("Team worktrees require the workspace to be the Git repository root.")


def snapshot(root):
    root_check(root)
    paths = set(
        git(root, "ls-files", "-co", "--exclude-standard", "-z", "--", *EXCLUDE).split(b"\0")
    )
    head = None
    try:
        head = git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    except ToolError:
        pass
    if head:
        paths.update(git(root, "ls-tree", "-rz", "--name-only", head).split(b"\0"))
    paths = sorted(p for p in paths if p and p != b".smok" and not p.startswith(b".smok/"))
    if any(
        row.startswith(b"160000 ") for row in git(root, "ls-files", "--stage", "-z").split(b"\0")
    ):
        raise ToolError(
            "Team snapshots do not support submodules; use a repository without gitlinks."
        )
    total = 0
    for raw in paths:
        path = root / os.fsdecode(raw)
        if path.is_symlink():
            continue
        if path.is_file():
            total += path.stat().st_size
    if total > 50 * 1024 * 1024 or len(paths) > 20000:
        raise ToolError(
            "Team snapshot exceeds 50 MiB or 20,000 files. Narrow the repository first."
        )
    index = state_path(root, "team", "index-" + uuid4().hex)
    index.parent.mkdir(parents=True, exist_ok=True)
    env = {
        **git_environment(),
        "GIT_INDEX_FILE": str(index),
        "GIT_AUTHOR_NAME": "Smok",
        "GIT_AUTHOR_EMAIL": "smok@localhost",
        "GIT_COMMITTER_NAME": "Smok",
        "GIT_COMMITTER_EMAIL": "smok@localhost",
    }
    filters = no_filters(root)
    try:
        git(root, *filters, "read-tree", head or "--empty", env=env)
        git(root, *filters, "rm", "--cached", "-r", "--ignore-unmatch", "--", ".smok", env=env)
        if paths:
            git(
                root,
                *filters,
                "--literal-pathspecs",
                "add",
                "-A",
                "-f",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
                env=env,
                input=b"\0".join(paths) + b"\0",
            )
        tree = git(root, *filters, "write-tree", env=env).decode().strip()
        commit = (
            git(root, *filters, "commit-tree", tree, env=env, input=b"Smok isolated run snapshot\n")
            .decode()
            .strip()
        )
        git(root, "update-ref", "refs/smok/snapshots/" + commit, commit)
        return commit, tree
    finally:
        index.unlink(missing_ok=True)
        Path(str(index) + ".lock").unlink(missing_ok=True)


class Worktrees:
    def __init__(self, root, id=None):
        self.root = root
        self.id = id or uuid4().hex[:12]
        if not re.fullmatch(r"[a-f0-9]{12}", self.id):
            raise ToolError("Invalid team run ID.")
        self.directory = state_path(root, "team", "runs", self.id)
        self.directory.mkdir(parents=True, exist_ok=True)

    def create(self, name, commit):
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", name):
            raise ToolError("Invalid candidate name.")
        path = self.directory / name
        if path.exists() or path.is_symlink():
            raise ToolError("Candidate directory already exists.")
        commit = (
            git(self.root, "rev-parse", "--verify", "--end-of-options", commit + "^{commit}")
            .decode()
            .strip()
        )
        git(self.root, *no_filters(self.root), "worktree", "add", "--detach", str(path), commit)
        return path

    def remove(self, path):
        if path.parent != self.directory:
            raise ToolError("Not a managed candidate.")
        git(self.root, "worktree", "remove", "--force", str(path))

    def patch(self, path, baseline):
        final, _ = snapshot(path)
        return git(
            path,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            baseline,
            final,
            "--",
            *EXCLUDE,
            limit=2 * 1024 * 1024,
        ).decode("utf-8", errors="strict")
