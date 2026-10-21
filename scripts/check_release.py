"""Verify local release versions, archive contents, and source parity. Never publishes."""

import argparse
import ast
import hashlib
import json
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git",
    ".smok",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "target",
    "build",
    "dist",
    "test-results",
    "playwright-report",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def allowed_path(name):
    path = PurePosixPath(name)
    return bool(name) and not (
        path.is_absolute()
        or "\\" in name
        or ".." in path.parts
        or ":" in name
        or set(path.parts) & EXCLUDED
        or any(p.startswith(".env") and p != ".env.example" for p in path.parts)
        or name.startswith(("evals/results/", "desktop/src-tauri/binaries/"))
        or name.endswith((".pyc", ".pyo", ".tsbuildinfo", ".DS_Store"))
    )


def versions(root):
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = project["version"]
    module = ast.parse((root / "src/smok/__init__.py").read_text())
    declared = [
        node.value.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    ]
    require(declared == [version], "Python runtime version differs from project metadata.")
    for name in ("web", "desktop"):
        package = json.loads((root / name / "package.json").read_text())
        lock = json.loads((root / name / "package-lock.json").read_text())
        require(
            package["version"] == lock["version"] == lock["packages"][""]["version"] == version,
            f"{name} package versions disagree.",
        )
    cargo = tomllib.loads((root / "desktop/src-tauri/Cargo.toml").read_text())
    cargo_lock = tomllib.loads((root / "desktop/src-tauri/Cargo.lock").read_text())
    native = next(p for p in cargo_lock["package"] if p["name"] == "smok-desktop")
    tauri = json.loads((root / "desktop/src-tauri/tauri.conf.json").read_text())
    uv = tomllib.loads((root / "uv.lock").read_text())
    python = next(p for p in uv["package"] if p["name"] == project["name"])
    require(
        cargo["package"]["version"]
        == native["version"]
        == tauri["version"]
        == python["version"]
        == version,
        "Native/Python lock or bundle versions disagree.",
    )
    return version


def verify(root, wheel, sdist, version):
    package_files = {
        str(p.relative_to(root / "src"))
        for p in (root / "src/smok").rglob("*")
        if p.is_file() and allowed_path(str(p.relative_to(root / "src")))
    }
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel entries.")
        require(all(allowed_path(n) for n in names), "Wheel contains excluded or unsafe files.")
        included = {n for n in names if n.startswith("smok/") and not n.endswith("/")}
        require(included == package_files, "Wheel source/asset file set differs from the checkout.")
        for name in included:
            require(
                archive.read(name) == (root / "src" / name).read_bytes(),
                f"Wheel bytes differ: {name}",
            )
        info = f"smok_harness-{version}.dist-info/"
        require(
            all(n.startswith(("smok/", info)) for n in names),
            "Unexpected wheel package or metadata.",
        )
        metadata = BytesParser().parsebytes(archive.read(info + "METADATA"))
        require(
            metadata["Version"] == version and metadata["Name"] == "smok-harness",
            "Wheel metadata differs.",
        )
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        require(len(names) == len(set(names)), "Duplicate source archive entries.")
        prefix = f"smok_harness-{version}/"
        included = set()
        for member in members:
            require(
                member.name.startswith(prefix) and (member.isfile() or member.isdir()),
                "Unsafe source archive entry.",
            )
            name = member.name[len(prefix) :]
            require(allowed_path(name), "Source archive contains excluded or unsafe files.")
            if not member.isfile():
                continue
            included.add(name)
            data = archive.extractfile(member).read()
            if name == "PKG-INFO":
                metadata = BytesParser().parsebytes(data)
                require(metadata["Version"] == version, "Source archive version differs.")
            else:
                require(
                    (root / name).is_file() and data == (root / name).read_bytes(),
                    f"Source archive bytes differ: {name}",
                )
        required = {
            "README.md",
            "pyproject.toml",
            "uv.lock",
            "docs/setup.md",
            "docs/validation.md",
            "scripts/check_release.py",
            "scripts/check_desktop.py",
            ".github/workflows/checks.yml",
            "tests/test_phase9_setup.py",
            "evals/phase7_tasks.json",
            "evals/solutions.json",
            "PKG-INFO",
        } | {"src/" + name for name in package_files}
        required |= {
            str(path.relative_to(root))
            for folder in ("tests", "scripts", "docs", "evals")
            for path in (root / folder).rglob("*")
            if path.is_file() and allowed_path(str(path.relative_to(root)))
        }
        require(
            required <= included,
            "Source archive is missing required source, tests, or release guides.",
        )
        graders = {}
        for task_file, solution_file in (
            ("phase7_tasks.json", "solutions.json"),
            ("phase10_tasks.json", "phase10_solutions.json"),
            ("phase11_tasks.json", "phase11_solutions.json"),
            ("phase12_tasks.json", "phase12_solutions.json"),
        ):
            tasks = json.loads(archive.extractfile(prefix + "evals/" + task_file).read())
            solutions = json.loads(archive.extractfile(prefix + "evals/" + solution_file).read())
            require(
                set(solutions) == {t["id"] for t in tasks},
                "Reference solutions do not match tasks.",
            )
            require(all("evals/" + t["check_file"] in included for t in tasks), "Missing graders.")
            graders[task_file] = len(tasks)
    return {
        "version": version,
        "passed": True,
        "wheel_files_matched": len(package_files),
        "source_files_matched": len(included) - 1,
        "graders": sum(graders.values()),
        "suites": graders,
        "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel, sdist)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        version = versions(ROOT)
        report = verify(
            ROOT,
            args.dist / f"smok_harness-{version}-py3-none-any.whl",
            args.dist / f"smok_harness-{version}.tar.gz",
            version,
        )
        output = json.dumps(report, indent=2) + "\n"
        if args.report:
            args.report.write_text(output)
        print(output, end="")
        return 0
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Release check failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
