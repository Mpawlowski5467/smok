"""Exercise the GUI API against a real model in a retained, disposable fixture workspace."""

import argparse
import asyncio
import json
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
import websockets

from smok.gui.server import create_app
from smok.gui.service import Service


async def evaluate(model):
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = Path(__file__).parent / "results" / (stamp + "-phase6")
    root = (directory / "workspace").resolve()
    root.mkdir(parents=True)
    (root / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    (root / "test_calculator.py").write_text(
        "import unittest\nfrom calculator import add\n\n"
        "class Addition(unittest.TestCase):\n"
        "    def test_positive(self): self.assertEqual(add(2, 3), 5)\n"
        "    def test_negative(self): self.assertEqual(add(-2, -4), -6)\n"
    )
    await asyncio.to_thread(subprocess.run, ["git", "init", "-q", str(root)], check=True)
    service = Service(root, model=model)
    listener = socket.create_server(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    app = create_app(root, service=service, token="eval-token", origin=origin)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    stages, errors, approvals, event_types = {}, [], [], {}
    start = time.monotonic()
    report = {"model": model, "workspace": str(root)}
    try:
        while not server.started:  # noqa: ASYNC110
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient(
            base_url=origin, headers={"Origin": origin}, trust_env=False
        ) as client:

            async def request(method, path, **kwargs):
                result = await client.request(method, "/api" + path, **kwargs)
                result.raise_for_status()
                return result.json()

            await request("POST", "/login", json={"token": "eval-token"})
            session = await request("POST", "/sessions", json={})
            identifier = session["id"]
            report["session"] = identifier
            path = "/sessions/" + identifier
            await request("PATCH", path, json={"budget_tokens": 100000, "max_iterations": 10})
            cookie = "smok_session=" + client.cookies.get("smok_session")
            async with websockets.connect(
                origin.replace("http:", "ws:") + "/api" + path + "/events",
                origin=origin,
                additional_headers={"Cookie": cookie},
                max_size=16_000_000,
            ) as ws:
                assert json.loads(await ws.recv())["type"] == "snapshot"
                await request(
                    "POST",
                    path + "/actions",
                    json={
                        "action": "prompt",
                        "data": {
                            "prompt": (
                                "Fix calculator.add so it adds its two arguments. "
                                "Read calculator.py, "
                                "use edit_file to repair it, then run exactly "
                                "python3 -m unittest -q. "
                                "Do not change tests. Briefly summarize the result."
                            )
                        },
                    },
                )
                async with asyncio.timeout(300):
                    async for raw in ws:
                        event = json.loads(raw)
                        kind, data = event["type"], event["data"]
                        event_types[kind] = event_types.get(kind, 0) + 1
                        if kind == "approval_pending":
                            name, arguments = data["name"], data["arguments"]
                            allowed = (
                                name in {"edit_file", "write_file"}
                                and arguments.get("path") == "calculator.py"
                                or name == "run_shell"
                                and arguments.get("command") == "python3 -m unittest -q"
                            )
                            approvals.append(
                                {"name": name, "arguments": arguments, "allowed": allowed}
                            )
                            await request(
                                "POST",
                                path + "/approvals",
                                json={
                                    "request_id": data["request_id"],
                                    "decision": "allow" if allowed else "deny",
                                },
                            )
                        if kind == "error":
                            errors.append(data["message"])
                        if kind == "idle":
                            break
            view = await request("GET", path)
            stages["streamed_chat"] = event_types.get("text_delta", 0) > 0 and not errors
            stages["reviewed_diff"] = any(
                a["name"] == "edit_file" and a["allowed"] for a in approvals
            )
            checked = await asyncio.to_thread(
                subprocess.run,
                ["python3", "-m", "unittest", "-q"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            stages["workspace_checks"] = checked.returncode == 0
            stages["recorded_usage"] = (
                view["state"]["usage"]["requests"] > 0
                and view["state"]["usage"]["estimated_requests"] == 0
            )
            await request(
                "POST", path + "/context", json={"action": "pin", "target": "calculator.py"}
            )
            preview = await request("POST", path + "/share-preview", json={})
            shared = await request("POST", path + "/shares", json={"digest": preview["digest"]})
            async with httpx.AsyncClient(trust_env=False) as stranger:
                response = await stranger.get(shared["url"].replace("/share/", "/api/shares/"))
                stages["readonly_share"] = (
                    response.status_code == 200 and response.json()["read_only"]
                )
            await request("DELETE", "/shares/" + shared["id"])
            checkpoint = view["state"]["last_checkpoint"]
            branch = await request("POST", path + "/branch", json={"checkpoint": checkpoint})
            branch_text = (Path(branch["workspace"]) / "calculator.py").read_text()
            await request("POST", path + "/actions", json={"action": "undo"})
            while (await request("GET", path))["busy"]:  # noqa: ASYNC110
                await asyncio.sleep(0.05)
            stages["branch_and_undo"] = (
                "return a - b" in (root / "calculator.py").read_text()
                and branch_text == (Path(branch["workspace"]) / "calculator.py").read_text()
                and "return a + b" in branch_text
            )
            report.update(
                usage=view["state"]["usage"],
                check=checked.stdout + checked.stderr,
                approvals=approvals,
            )
    except Exception as exc:
        errors.append(str(exc))
    finally:
        server.should_exit = True
        await serving
        listener.close()
        report.update(
            stages=stages,
            errors=errors,
            events=event_types,
            elapsed_seconds=round(time.monotonic() - start, 2),
        )
        output = directory / "report.json"
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "passed": sum(stages.values()),
                    "total": 6,
                    "errors": errors,
                    "report": str(output),
                }
            )
        )
    return 0 if len(stages) == 6 and all(stages.values()) and not errors else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--allow-tools",
        action="store_true",
        help="Allow only fixture edits and its exact check command",
    )
    args = parser.parse_args()
    if not args.allow_tools:
        parser.error("This eval requires --allow-tools for its disposable fixture.")
    raise SystemExit(asyncio.run(evaluate(args.model)))
