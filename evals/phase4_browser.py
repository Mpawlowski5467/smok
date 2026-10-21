"""Exercise a user-installed Playwright MCP server against an isolated local counter page."""

import argparse
import asyncio
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from smok.tools.files import Workspace
from smok.tools.registry import ToolRegistry
from smok.types import ToolCall

HTML = b"""<!doctype html><html><head><title>Smok browser fixture</title></head>
<body><h1>Smok browser fixture</h1><p role="status" id="count">Count: 0</p>
<button onclick="document.getElementById('count').textContent='Count: 1'">Add one</button>
</body></html>"""


async def evaluate(args, destination):
    root = destination / "workspace"
    root.mkdir(parents=True)
    requests = []

    async def handle(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        requests.append(request.split(b"\r\n", 1)[0].decode())
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
            + str(len(HTML)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + HTML
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    config = {
        "mcp_servers": {
            "browser": {
                "command": str(args.server.resolve()),
                "args": [
                    "--headless",
                    "--isolated",
                    "--block-service-workers",
                    "--no-webmcp",
                    "--executable-path",
                    str(args.browser.resolve()),
                    "--output-dir",
                    str(root / ".smok/browser-output"),
                    "--timeout-navigation",
                    "15000",
                ],
                "timeout_seconds": 60,
            }
        }
    }
    (root / ".smok").mkdir()
    (root / ".smok/settings.json").write_text(json.dumps(config))
    tools = ToolRegistry(Workspace(root))
    results = []
    report = {
        "passed": False,
        "server": str(args.server),
        "browser": str(args.browser),
        "url": url,
        "stages": results,
    }
    started = time.monotonic()

    async def call(name, arguments):
        if name != "mcp_connect":
            name = next(key for key, item in tools.extensions.mcp.tools.items() if item[1] == name)
        prepared = tools.prepare(ToolCall(f"call-{len(results)}", name, json.dumps(arguments)))
        output = await tools.execute(prepared, approved=True)
        results.append({"tool": name, "arguments": arguments, "result": output})
        return output

    try:
        async with server, asyncio.timeout(150):
            await call("mcp_connect", {"server": "browser"})
            await call("browser_navigate", {"url": url})
            # Current Playwright versions link navigation snapshots on disk. Explicit
            # browser_snapshot returns inline accessibility text through MCP.
            snapshot = await call("browser_snapshot", {})
            text = "\n".join(c.get("text", "") for c in json.loads(snapshot)["content"])
            ref = re.search(r'button "Add one" \[ref=([^\]]+)\]', text)
            if not ref or "Count: 0" not in text:
                raise ValueError("Initial browser snapshot did not expose the counter and button.")
            click_schema = next(
                item[2].parameters
                for item in tools.extensions.mcp.tools.values()
                if item[1] == "browser_click"
            )
            target_key = "target" if "target" in click_schema["properties"] else "ref"
            await call("browser_click", {"element": "Add one", target_key: ref[1]})
            after = await call("browser_snapshot", {})
            shot = json.loads(
                await call("browser_take_screenshot", {"type": "png", "scale": "css"})
            )
            saved = [c["saved_path"] for c in shot["content"] if "saved_path" in c]
            report["screenshot_paths"] = saved
            report["counter_changed"] = "Count: 1" in after
            report["screenshot_saved"] = bool(saved) and await asyncio.to_thread(
                lambda: all(Path(p).is_file() for p in saved)
            )
            report["passed"] = (
                report["counter_changed"] and report["screenshot_saved"] and bool(requests)
            )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await tools.close()
        server.close()
        await server.wait_closed()
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["requests"] = requests
        (destination / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server", type=Path, required=True, help="Installed playwright-mcp executable"
    )
    parser.add_argument(
        "--browser", type=Path, required=True, help="Installed Chrome/Chromium executable"
    )
    parser.add_argument(
        "--allow-browser",
        action="store_true",
        required=True,
        help="Authorize this isolated local browser integration test",
    )
    args = parser.parse_args()
    destination = (
        Path(__file__).resolve().parent
        / "results"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-phase4-browser")
    )
    report = asyncio.run(evaluate(args, destination))
    print(
        json.dumps({k: v for k, v in report.items() if k not in {"stages", "requests"}}, indent=2)
    )
    print(f"Report: {destination / 'report.json'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
