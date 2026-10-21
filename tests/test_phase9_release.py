import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.check_release import allowed_path, verify, versions
from smok import __version__


@pytest.mark.parametrize(
    "name",
    [
        ".smok/gui-keys.json",
        ".env",
        "web/node_modules/a.js",
        "evals/results/private.json",
        "desktop/src-tauri/binaries/server",
        "../secret",
        "/tmp/secret",
        "a\\b",
        "C:/secret",
    ],
)
def test_release_policy_excludes_private_build_and_unsafe_paths(name):
    assert not allowed_path(name)
    assert allowed_path(".env.example")


def archives(root, *, wheel_extra=None, changed_source=False, link=False):
    content = {
        "src/smok/__init__.py": b'__version__ = "0.9.0"\n',
        "README.md": b"Smok",
        "pyproject.toml": b"",
        "uv.lock": b"",
        "docs/setup.md": b"Setup",
        "docs/validation.md": b"Checks",
        "scripts/check_release.py": b"",
        "scripts/check_desktop.py": b"",
        ".github/workflows/checks.yml": b"",
        "tests/test_phase9_setup.py": b"",
        "evals/phase7_tasks.json": json.dumps(
            [{"id": "one", "check_file": "checks/one.py"}]
        ).encode(),
        "evals/solutions.json": b'{"one": {}}',
        "evals/phase10_tasks.json": json.dumps(
            [{"id": "one", "check_file": "checks/one.py"}]
        ).encode(),
        "evals/phase10_solutions.json": b'{"one": {}}',
        "evals/phase11_tasks.json": json.dumps(
            [{"id": "one", "check_file": "checks/one.py"}]
        ).encode(),
        "evals/phase11_solutions.json": b'{"one": {}}',
        "evals/phase12_tasks.json": json.dumps(
            [{"id": "one", "check_file": "checks/one.py"}]
        ).encode(),
        "evals/phase12_solutions.json": b'{"one": {}}',
        "evals/checks/one.py": b"assert True",
    }
    for name, data in content.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    wheel, sdist = root / "build.whl", root / "build.tar.gz"
    metadata = b"Name: smok-harness\nVersion: 0.9.0\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("smok/__init__.py", content["src/smok/__init__.py"])
        archive.writestr("smok_harness-0.9.0.dist-info/METADATA", metadata)
        if wheel_extra:
            archive.writestr(wheel_extra, b"unexpected")
    with tarfile.open(sdist, "w:gz") as archive:
        for name, data in {**content, "PKG-INFO": metadata}.items():
            member = tarfile.TarInfo("smok_harness-0.9.0/" + name)
            if changed_source and name == "README.md":
                data = b"stale bytes"
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        if link:
            member = tarfile.TarInfo("smok_harness-0.9.0/external")
            member.type = tarfile.SYMTYPE
            member.linkname = "/tmp/other"
            archive.addfile(member)
    return wheel, sdist


@pytest.mark.parametrize("mutation", ["clean", "private", "stale", "symlink", "missing-module"])
def test_release_checks_detect_packaging_regressions(tmp_path, mutation):
    wheel, sdist = archives(
        tmp_path,
        wheel_extra=".smok/keys.json" if mutation == "private" else None,
        changed_source=mutation == "stale",
        link=mutation == "symlink",
    )
    if mutation == "missing-module":
        (tmp_path / "src/smok/new_module.py").write_text("new = True\n")
    if mutation == "clean":
        result = verify(tmp_path, wheel, sdist, "0.9.0")
        assert result["passed"] and result["wheel_files_matched"] == 1
    else:
        with pytest.raises(ValueError):
            verify(tmp_path, wheel, sdist, "0.9.0")


def test_release_versions_reject_a_stale_frontend_lock(tmp_path):
    root = Path(__file__).resolve().parents[1]
    assert versions(root) == __version__
    for name in [
        "pyproject.toml",
        "src/smok/__init__.py",
        "web/package.json",
        "web/package-lock.json",
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / name).read_bytes())
    path = tmp_path / "web/package-lock.json"
    lock = json.loads(path.read_text())
    lock["packages"][""]["version"] = "0.0.1"
    path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="web package versions disagree"):
        versions(tmp_path)
