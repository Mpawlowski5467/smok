"""Real SDK server used by transport and model evaluations; never contacts an external service."""

import asyncio
import os
import sys
from pathlib import Path

from mcp.server import MCPServer
from pydantic import BaseModel

server = MCPServer("Smok fixture", log_level="ERROR")


class EchoResult(BaseModel):
    echo: str
    pid: int


@server.tool()
def echo(text: str) -> EchoResult:
    """Echo text and report the subprocess PID."""
    return EchoResult(echo=text, pid=os.getpid())


@server.tool()
def write_marker(content: str) -> str:
    """Write marker.txt in the fixture workspace."""
    Path("marker.txt").write_text(content)
    return "Wrote marker.txt"


@server.tool()
def fail() -> str:
    """Return an intentional tool failure."""
    raise ValueError("Intentional fixture failure")


@server.tool()
async def wait(seconds: float) -> str:
    """Wait so cancellation and timeout cleanup can be verified."""
    await asyncio.sleep(seconds)
    return "Finished waiting"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[1]))
    else:
        server.run()
