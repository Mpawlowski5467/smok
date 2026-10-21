"""Check a locally built macOS app in a disposable workspace, with no model generation."""

import argparse
import hashlib
import json
import plistlib
import re
import selectors
import socket
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from smok import __version__
from smok.journal import Journal

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(app):
    server = app / "Contents/MacOS/smok-server"
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    require(
        info["CFBundleShortVersionString"] == __version__, "Bundle version does not match Smok."
    )
    version = subprocess.run(
        [str(server), "--version"], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    require(version == f"smok-gui {__version__}", "Bundled server version differs.")
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    checks = ["bundle version", "bundled server version", "complete bundle signature"]
    with tempfile.TemporaryDirectory(prefix="smok-native-check-") as temporary:
        workspace = Path(temporary).resolve()
        with (workspace / "server-stderr.log").open("w+") as stderr:
            process = subprocess.Popen(
                [
                    str(server),
                    "--workspace",
                    str(workspace),
                    "--model",
                    "local/setup-smoke",
                    "--native",
                    "--port",
                    "0",
                ],
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
            )
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    require(selector.select(timeout=30), "Bundled server did not become ready.")
                launch = json.loads(process.stdout.readline(8192))
                url = urlsplit(launch["url"])
                require(
                    url.scheme == "http" and url.hostname == "127.0.0.1", "Invalid launch origin."
                )
                origin = f"{url.scheme}://{url.netloc}"
                token = parse_qs(url.fragment)["token"][0]
                with httpx.Client(
                    base_url=origin, headers={"origin": origin}, timeout=10, trust_env=False
                ) as client:
                    require(
                        client.get("/api/health").json() == {"ready": True}, "Health check failed."
                    )
                    require(client.get("/api/bootstrap").status_code == 401, "Missing auth guard.")
                    require(
                        client.post("/api/login", json={"token": token}).status_code == 200,
                        "Login failed.",
                    )
                    require(
                        client.get("/api/bootstrap").json()["workspace"] == str(workspace),
                        "Wrong workspace.",
                    )
                    checks.extend(["loopback readiness", "authentication", "workspace bootstrap"])
                    response = client.post("/api/diagnostics", json={})
                    require(response.status_code == 200, "Setup diagnostics failed.")
                    report = response.json()
                    require(
                        report["smok_version"] == __version__ and report["ok"],
                        "Bundled local setup failed.",
                    )
                    require(
                        report["generation_requests"] == 0 and not report["probe_requested"],
                        "Unexpected model request.",
                    )
                    require(
                        client.get("/api/sessions").json() == [], "Setup checks created a session."
                    )
                    checks.append("offline setup diagnostics without a session")
                    html = client.get("/").text
                    assets = re.findall(r'(?:src|href)="(/assets/[^"?#]+)"', html)
                    require(any(a.endswith(".js") for a in assets), "Missing compiled interface.")
                    for asset in assets:
                        require(".." not in Path(asset).parts, "Unsafe asset path.")
                        response = client.get(asset)
                        require(
                            response.status_code == 200
                            and response.content
                            == (ROOT / "src/smok/gui/static" / asset.lstrip("/")).read_bytes(),
                            "Compiled asset bytes differ.",
                        )
                    checks.append("compiled asset byte parity")
                    view = client.post("/api/sessions", json={}).json()
                    session = view["id"]
                    path = f"/api/sessions/{session}"
                    require(
                        client.patch(path, json={"turn_timeout": 0}).status_code == 422,
                        "Invalid deadline accepted.",
                    )
                    require(
                        client.patch(path, json={"turn_timeout": 90}).json()["limits"][
                            "turn_timeout"
                        ]
                        == 90,
                        "Deadline not saved.",
                    )
                    require(client.delete(path).status_code == 200, "Session release failed.")
                    view = client.post("/api/sessions", json={"resume": session}).json()
                    require(view["state"]["turn_timeout"] == 90, "Deadline not resumed.")
                    require(
                        client.patch(path, json={"turn_timeout": None}).json()["limits"][
                            "turn_timeout"
                        ]
                        is None,
                        "Deadline not cleared.",
                    )
                    require(view["state"]["turns"] == 0, "Unexpected generation.")
                    checks.append("deadline validation, save, resume, and clear")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    raise
                process.stdout.close()
            require(process.returncode in {0, -15}, "Bundled server shutdown failed.")
            stderr.seek(0)
            errors = stderr.read()
            require(
                "Traceback" not in errors and "ERROR" not in errors,
                "Bundled server logged an error.",
            )
        with socket.socket() as connection:
            require(
                connection.connect_ex(("127.0.0.1", url.port)) != 0, "Listener survived shutdown."
            )
        journal = Journal(workspace, resume=session)
        try:
            require(
                journal.loaded["turn_timeout"] is None and journal.loaded["turns"] == 0,
                "Saved state differs after shutdown.",
            )
        finally:
            journal.close()
        checks.extend(["graceful shutdown", "listener closed", "session writer lock released"])
    return {
        "smok_version": __version__,
        "passed": True,
        "generation_requests": 0,
        "checks": checks,
        "executables": {
            name: hashlib.sha256((app / "Contents/MacOS" / name).read_bytes()).hexdigest()
            for name in ("smok-server", "smok-desktop")
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app", type=Path, default=ROOT / "desktop/src-tauri/target/release/bundle/macos/Smok.app"
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        output = json.dumps(check(args.app.resolve()), indent=2) + "\n"
        if args.report:
            args.report.write_text(output)
        print(output, end="")
        return 0
    except (OSError, ValueError, KeyError, httpx.HTTPError, subprocess.SubprocessError) as exc:
        # Do not expose launch tokens, configured values, or captured server output.
        print(
            f"Desktop check failed ({type(exc).__name__}). Check the local build and prerequisites."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
