"""Build the web assets and a self-contained Tauri desktop application on this host."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(argv, cwd=ROOT):
    subprocess.run(argv, cwd=cwd, check=True)


def main():
    run(["npm", "--prefix", "web", "run", "build"])
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "smok-server",
            "--specpath",
            "build",
            "--distpath",
            "build/sidecar",
            "--workpath",
            "build/pyinstaller",
            "--paths",
            "src",
            "--collect-all",
            "smok",
            "--collect-submodules",
            "uvicorn",
            "--collect-submodules",
            "mcp.client",
            "scripts/gui_sidecar.py",
        ]
    )
    rust = subprocess.check_output(["rustc", "-vV"], text=True)
    target = next(line.split(": ", 1)[1] for line in rust.splitlines() if line.startswith("host:"))
    destination = ROOT / "desktop/src-tauri/binaries"
    destination.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    shutil.copy2(
        ROOT / f"build/sidecar/smok-server{suffix}", destination / f"smok-server-{target}{suffix}"
    )
    run(["npm", "run", "build"], ROOT / "desktop")
    if sys.platform == "darwin":
        run(
            [
                "codesign",
                "--verify",
                "--deep",
                "--strict",
                "desktop/src-tauri/target/release/bundle/macos/Smok.app",
            ]
        )


if __name__ == "__main__":
    main()
