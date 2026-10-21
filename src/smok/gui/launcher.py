"""Start a private local server, optionally launching a browser or native host."""

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
import webbrowser
from pathlib import Path

import uvicorn

from smok import __version__
from smok.gui.server import create_app
from smok.gui.service import Service


def run(
    *,
    workspace,
    model=None,
    config=None,
    base_url=None,
    port=8765,
    browser=True,
    native=False,
    parent_pid=None,
):
    if parent_pid is not None and parent_pid < 2:
        raise ValueError("Parent PID must be a positive process ID greater than 1.")
    token = secrets.token_urlsafe(32)
    service = Service(workspace, model=model, config_path=config, base_url=base_url)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        app = create_app(workspace, token=token, origin=origin, service=service)
        url = origin + "/#token=" + token
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_level="warning",
                access_log=False,
                ws_max_size=16384,
                timeout_graceful_shutdown=15,
            )
        )

        async def serve():
            async def ready():
                while not server.started:  # noqa: ASYNC110
                    await asyncio.sleep(0.05)
                if native:
                    print(json.dumps({"url": url}), flush=True)
                else:
                    print(
                        f"Smok is running locally: {url}\n"
                        f"Workspace: {service.root}\nCtrl+C to stop.",
                        flush=True,
                    )
                if browser:
                    await asyncio.to_thread(webbrowser.open, url)

            async def watch_parent():
                while not server.should_exit:
                    await asyncio.sleep(1)
                    if parent_pid is not None:
                        try:
                            os.kill(parent_pid, 0)
                        except ProcessLookupError:
                            server.should_exit = True
                            return

            parent = asyncio.create_task(watch_parent()) if parent_pid is not None else None
            task = asyncio.create_task(ready())
            try:
                await server.serve(sockets=[listener])
            finally:
                task.cancel()
                if parent:
                    parent.cancel()
                await service.close()

        asyncio.run(serve())


def main():
    parser = argparse.ArgumentParser(description="Smok local app server")
    parser.add_argument("--version", action="version", version=f"smok-gui {__version__}")
    parser.add_argument("--workspace", "-C", type=Path, default=Path.cwd())
    parser.add_argument("--model")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        run(
            workspace=args.workspace,
            model=args.model,
            config=args.config,
            base_url=args.base_url,
            port=args.port,
            browser=not (args.no_browser or args.native),
            native=args.native,
            parent_pid=args.parent_pid,
        )
    except (ValueError, OSError) as exc:
        print(f"smok gui: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
