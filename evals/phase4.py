"""Live model exercise of commands, skills, hooks, MCP, web, self-authoring, recipes, and review."""

import argparse
import asyncio
import json
import re
import shlex
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import yaml

from smok.checkpoints import Checkpoints
from smok.extensions.review import git
from smok.extensions.workflows import run_extension, run_review
from smok.journal import Journal
from smok.loop import Agent
from smok.models import create_adapter
from smok.models.profiles import resolve_model
from smok.tools.files import Workspace
from smok.tools.registry import ToolRegistry
from smok.usage import RunBudget

HERE = Path(__file__).resolve().parent
SENTINEL = "EMBER-QUARTZ-6284"
BROKEN = '"""Keep this public API."""\n\ndef add(a, b):\n    return a - b\n'


def markdown(path, name, description, body, parameters=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump({"name": name, "description": description, "parameters": parameters or {}})
        + "---\n"
        + body
    )


async def evaluate(args, destination):
    root = destination / "workspace"
    root.mkdir(parents=True)
    plugin = root / ".smok-extensions/plugins/team"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: team\ndescription: Phase 4 fixture workflows\n")
    markdown(
        plugin / "skills/repair/SKILL.md",
        "repair",
        "Repair the addition fixture",
        "Read calc.py, preserve its docstring and public function name, then use edit_file "
        "to make add return arithmetic addition. Only change calc.py in this repair. "
        "The after-edit hook formats the file; read it again after the hook.",
    )
    markdown(
        plugin / "commands/repair.md",
        "repair",
        "Apply the fixture repair skill",
        "Load skill team/repair. Repair {{target}} following that skill. Verify by running "
        "python3 -c 'from calc import add; assert add(4, 5) == 9; assert add(-2, 2) == 0'. "
        "Keep the final response brief.",
        {"target": None},
    )
    recipes = plugin / "recipes"
    recipes.mkdir()
    (recipes / "verify.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "verify",
                "description": "Check proof and arithmetic",
                "parameters": {"file": None},
                "steps": [
                    "Read {{file}} and report its marker in one sentence.",
                    "Run python3 -c 'from calc import add; assert add(2, 3) == 5'. "
                    "Report the result briefly.",
                ],
            }
        )
    )
    (root / "formatter.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "event = json.load(sys.stdin)\npath = Path(event['arguments']['path'])\n"
        "if path.name == 'calc.py':\n"
        "    lines = [s.rstrip() for s in path.read_text().splitlines()]\n"
        "    path.write_text('\\n'.join(lines) + '\\n')\n"
        "    Path('formatter-ran.txt').write_text('formatted calc.py')\n"
    )
    (plugin / "hooks.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "name": "format",
                    "event": "after_tool",
                    "tools": ["write_file", "edit_file"],
                    "command": shlex.join([sys.executable, "formatter.py"]),
                }
            ]
        )
    )
    (root / "calc.py").write_text(BROKEN)
    requests = []
    url = ""

    async def handle(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        target = request.split(b" ")[1].decode()
        requests.append(target)
        if target.startswith("/search?"):
            body = json.dumps(
                {
                    "results": [
                        {
                            "title": "Local fixture source",
                            "url": url + "/source",
                            "content": "Fetch the source for its verification marker.",
                        }
                    ]
                }
            ).encode()
            mime = b"application/json"
        else:
            body = f"<h1>Fixture source</h1><p>Verification marker: {SENTINEL}</p>".encode()
            mime = b"text/html"
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: "
            + mime
            + b"\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    (root / ".smok").mkdir()
    (root / ".smok/settings.json").write_text(
        json.dumps(
            {
                "mcp_servers": {
                    "fixture": {
                        "command": sys.executable,
                        "args": [str(HERE.parent / "tests/fixtures/mcp_server.py")],
                    }
                },
                "web": {
                    "search_provider": "searxng",
                    "search_url": url + "/search",
                    "allow_hosts": ["127.0.0.1"],
                },
            }
        )
    )
    await git(root, "init", "-q")
    await git(root, "config", "user.name", "Smok fixture")
    await git(root, "config", "user.email", "fixture@example.invalid")
    (root / ".gitignore").write_text(".smok/\n__pycache__/\n")
    await git(root, "add", ".")
    await git(root, "commit", "-qm", "fixture baseline")
    config = replace(
        resolve_model(args.model, config_path=args.config),
        max_output_tokens=2048,
        context_window=32768,
        repo_map_tokens=300,
    )
    journal = Journal(root)

    async def approve(_request):
        return True  # Explicit --allow-tools flag, only this disposable fixture.

    tools = ToolRegistry(Workspace(root))
    agent = Agent(
        create_adapter(config),
        tools,
        approver=approve,
        journal=journal,
        checkpoints=Checkpoints(root),
        max_iterations=16,
        budget=RunBudget(max_turns=8, tokens=250000),
    )
    stages, events = [], []
    report = {"model": config.name, "passed": False, "stages": stages, "session_id": journal.id}
    started = time.monotonic()

    async def consume(name, stream):
        print(f"Running {name}…", flush=True)
        stage = {"name": name, "passed": False}
        stages.append(stage)
        local = []
        try:
            async for event in stream:
                item = event.to_dict()
                local.append(item)
                events.append(item)
                journal.write(event)
                with (destination / "events.jsonl").open("a") as log:
                    log.write(json.dumps({"stage": name, **item}) + "\n")
                if event.type in {"tool_call", "error", "budget_exhausted"}:
                    print(
                        f"  {event.type}: {event.data.get('name', event.data.get('message', ''))}",
                        flush=True,
                    )
                if event.type == "turn_finished":
                    stage["stop_reason"] = event.data["reason"]
        finally:
            await stream.aclose()
        if stage.get("stop_reason") != "complete":
            raise ValueError(f"{name} stopped: {stage.get('stop_reason')}")
        return stage, local

    def successful(local, name):
        return any(
            e["type"] == "tool_result" and not e["data"]["is_error"] and e["data"]["name"] == name
            for e in local
        )

    try:
        async with server, asyncio.timeout(args.timeout):
            stage, local = await consume(
                "command-skill-hook-repair",
                run_extension(agent, "commands", "team/repair", {"target": "calc.py"}),
            )
            check = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "from calc import add; assert add(10,-3)==7; assert add(0,0)==0; "
                "assert add(2.5,1.5)==4",
                cwd=root,
            )
            await check.wait()
            stage["passed"] = (
                check.returncode == 0
                and (root / "formatter-ran.txt").exists()
                and successful(local, "load_skill")
                and successful(local, "edit_file")
            )
            if not stage["passed"]:
                raise ValueError("Repair, skill, or hook oracle failed.")
            stage, local = await consume(
                "mcp-and-web",
                agent.run(
                    "Connect to MCP server fixture, then call its echo tool with text "
                    "'phase4 transport'. Use web_search for 'Smok fixture marker', then "
                    "web_fetch the returned source URL. Write the exact verification "
                    "marker from that page to proof.txt. Keep your reply brief."
                ),
            )
            stage["passed"] = (
                all(successful(local, n) for n in ("mcp_connect", "web_search", "web_fetch"))
                and any(
                    e["type"] == "tool_result"
                    and e["data"]["name"].startswith("mcp__fixture__echo")
                    and not e["data"]["is_error"]
                    for e in local
                )
                and (root / "proof.txt").read_text().strip() == SENTINEL
            )
            if not stage["passed"]:
                raise ValueError("MCP/web evidence oracle failed.")
            stage, local = await consume(
                "author-and-reload",
                agent.run(
                    "Create .smok-extensions/skills/greeting/SKILL.md with YAML front matter "
                    "name: greeting and description: A short Polish greeting, followed by "
                    "a Markdown body saying to reply with Cześć. Then use reload_extensions "
                    "and load_skill(greeting). "
                    "Do not change other files. Reply briefly."
                ),
            )
            stage["passed"] = (
                "greeting" in tools.extensions.catalog.skills
                and successful(local, "reload_extensions")
                and successful(local, "load_skill")
            )
            if not stage["passed"]:
                raise ValueError("Self-authored extension oracle failed.")
            stage, local = await consume(
                "recipe", run_extension(agent, "recipes", "team/verify", {"file": "proof.txt"})
            )
            stage["passed"] = (
                sum(e["type"] == "recipe_step_finished" and e["data"]["ok"] for e in local) == 2
            )
            # Make the repaired state the baseline, then introduce a known new defect for review.
            await git(root, "add", ".")
            await git(root, "commit", "-qm", "repaired baseline")
            (root / "calc.py").write_text(BROKEN)
            before = (root / "calc.py").read_bytes()
            stage, local = await consume("review", run_review(agent))
            answer = "".join(e["data"]["text"] for e in local if e["type"] == "text_delta")
            stage["answer"] = answer
            stage["passed"] = (
                successful(local, "review_diff")
                and "calc.py" in answer
                and bool(re.search(r"subtract|subtraction|a\s*-\s*b|addition", answer, re.I))
                and (root / "calc.py").read_bytes() == before
                and tools.mode == "build"
            )
            report["passed"] = all(s["passed"] for s in stages)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await tools.close()
        journal.close()
        server.close()
        await server.wait_closed()
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["usage"] = agent.usage.export()
        report["web_requests"] = requests
        (destination / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument(
        "--allow-tools",
        action="store_true",
        required=True,
        help="Authorize writes, shell hooks, local MCP and local web fixtures",
    )
    args = parser.parse_args()
    destination = HERE / "results" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-phase4")
    report = asyncio.run(evaluate(args, destination))
    print(json.dumps(report, indent=2))
    print(f"Report: {destination / 'report.json'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
