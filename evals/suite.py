"""Validated fixtures and independent, bounded correctness checks."""

import hashlib
import json
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from smok.process import capture

HERE = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def safe_name(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or PurePosixPath(name).is_absolute()
        or ".." in name.split("/")
        or any(p in {"", ".", ".git", ".smok", "__pycache__"} for p in name.split("/"))
    ):
        raise ValueError(f"Invalid fixture path: {name!r}")
    return name


def load_tasks(suite="phase7"):
    filename = {
        "phase1": "tasks.json",
        "phase2": "phase2_tasks.json",
        "phase7": "phase7_tasks.json",
        "phase10": "phase10_tasks.json",
        "phase11": "phase11_tasks.json",
        "phase12": "phase12_tasks.json",
    }[suite]
    rows = json.loads((HERE / filename).read_text())
    seen = set()
    for task in rows:
        name = safe_name(task["id"])
        if "/" in name or name in seen:
            raise ValueError("Task IDs must be unique directory names.")
        seen.add(name)
        if not isinstance(task["prompt"], str) or not task["prompt"].strip():
            raise ValueError("Task needs a prompt.")
        if not isinstance(task["files"], dict) or not all(
            isinstance(v, str) and len(v.encode()) < 1_048_576 for v in task["files"].values()
        ):
            raise ValueError("Fixture files must be bounded text.")
        for path in [*task["files"], *task.get("allowed_changes", [])]:
            safe_name(path)
        for key in ("shell_commands", "verification_commands"):
            if key in task and (
                not isinstance(task[key], list)
                or len(task[key]) > 20
                or any(not isinstance(c, str) or not c.strip() or len(c) > 4096 for c in task[key])
                or len(set(task[key])) != len(task[key])
            ):
                raise ValueError(f"Invalid {key} list.")
        if task.get("verification_commands") and not set(task["verification_commands"]) <= set(
            task.get("shell_commands", [])
        ):
            raise ValueError("Verification commands must be explicitly allowed shell commands.")
        if "check_file" in task:
            path = HERE / safe_name(task["check_file"])
            if not path.resolve().is_relative_to(HERE) or path.is_symlink():
                raise ValueError("Check script must stay in evals.")
            task["check"] = path.read_text()
        compile(task["check"], task.get("check_file", name), "exec")
        task.setdefault("split", "tune")
        task.setdefault("category", suite)
        if task["split"] not in {"tune", "holdout"}:
            raise ValueError("Invalid task split.")
        task["fingerprint"] = digest(task)
    return rows


def write_fixture(root, files):
    for name, content in files.items():
        path = root / safe_name(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def snapshot(root):
    """Never dereference generated symlinks or read unlimited output."""
    result = {}
    total = 0
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if {".smok", ".git", "__pycache__"}.intersection(rel.parts):
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            result[str(rel)] = {"kind": "symlink"}
        elif stat.S_ISREG(mode):
            total += path.stat().st_size
            if total > 16 * 1_048_576:
                raise ValueError("Fixture output exceeds 16 MiB.")
            if path.stat().st_size > 1_048_576:
                result[str(rel)] = {"kind": "oversized"}
            else:
                result[str(rel)] = {
                    "kind": "file",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
        elif not stat.S_ISDIR(mode):
            result[str(rel)] = {"kind": "special"}
        if len(result) > 2000:
            raise ValueError("Fixture produced more than 2,000 files.")
    return result


def scope_check(task, root):
    current = snapshot(root)
    expected = {
        name: {"kind": "file", "sha256": hashlib.sha256(text.encode()).hexdigest()}
        for name, text in task["files"].items()
    }
    changed = sorted(
        k for k in current.keys() | expected.keys() if current.get(k) != expected.get(k)
    )
    allowed = task.get("allowed_changes")
    outside = [p for p in changed if allowed is not None and p not in allowed]
    unsafe = [p for p, data in current.items() if data["kind"] != "file"]
    return {
        "passed": not outside and not unsafe,
        "changed": changed,
        "outside_scope": outside,
        "unsafe_files": unsafe,
    }


async def check_task(task, root):
    # Check code is outside model history/workspace. The marker rejects exit(0),
    # but does not make generated Python an adversarial security sandbox.
    marker = "SMOK_CHECK_COMPLETE_" + uuid4().hex
    code = (
        "import sys\nsys.path.insert(0, sys.argv[1])\n"
        + task["check"]
        + f"\nprint({marker!r}, flush=True)\n"
    )
    # A same-size repair within one second must not reuse the broken fixture's .pyc.
    with tempfile.TemporaryDirectory(prefix="smok-grader-cache-") as cache:
        result = await capture(
            [sys.executable, "-I", "-B", "-X", f"pycache_prefix={cache}", "-c", code, str(root)],
            root,
            seconds=10,
            limit=16000,
        )
    output = result.output.decode(errors="replace")
    passed = result.code == 0 and not result.timed_out and marker in output.splitlines()
    return passed, output.replace(marker, "[independent check completed]")[-4000:]


def source_fingerprint():
    root = HERE.parent
    paths = sorted((root / "src/smok").rglob("*.py")) + sorted(HERE.glob("*.py"))
    return digest(
        {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    )
