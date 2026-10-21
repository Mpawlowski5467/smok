import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import pytest
from test_phase4_extensions import prepare

from smok.extensions.mcp import configurations, external_references
from smok.permissions import PermissionPolicy
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import ToolCall, ToolSpec

SERVER = Path(__file__).parent / "fixtures/mcp_server.py"


def registry(root, config=None, mode="build"):
    path = root / ".smok"
    path.mkdir(exist_ok=True)
    config = config or {"command": sys.executable, "args": [str(SERVER)], "timeout_seconds": 5}
    (path / "settings.json").write_text(json.dumps({"mcp_servers": {"fixture": config}}))
    return ToolRegistry(Workspace(root), mode=mode)


def tool_name(tools, original):
    return next(key for key, value in tools.extensions.mcp.tools.items() if value[1] == original)


async def test_real_stdio_discovery_calls_errors_and_cleanup(tmp_path):
    tools = registry(tmp_path)
    connection = prepare(tools, "mcp_connect", server="fixture")
    try:
        assert not tools.extensions.mcp.connections
        with pytest.raises(ToolError, match="Permission denied"):
            await tools.execute(connection)
        await tools.execute(connection, approved=True)
        echo = tool_name(tools, "echo")
        assert echo.startswith("mcp__fixture__") and len(echo) <= 64
        request = prepare(tools, echo, text="hello")
        with pytest.raises(ToolError, match="Permission denied"):
            await tools.execute(request)
        result = json.loads(await tools.execute(request, approved=True))
        assert result["structured_content"]["echo"] == "hello"
        pid = result["structured_content"]["pid"]
        with pytest.raises(ToolError, match="Invalid arguments"):
            prepare(tools, echo, text=42)
        with pytest.raises(ToolError, match="Error executing tool fail"):
            await tools.execute(prepare(tools, tool_name(tools, "fail")), approved=True)
        await tools.execute(prepare(tools, "mcp_disconnect", server="fixture"))
        assert not any(spec.name == echo for spec in tools.specs)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        await tools.close()


async def test_mcp_plan_uses_local_allowlist_not_server_hints(tmp_path):
    tools = registry(
        tmp_path, {"command": sys.executable, "args": [str(SERVER)], "read_only": ["echo"]}, "plan"
    )
    try:
        await tools.execute(prepare(tools, "mcp_connect", server="fixture"), approved=True)
        echo = tool_name(tools, "echo")
        write = tool_name(tools, "write_marker")
        assert echo in {s.name for s in tools.specs} and write not in {s.name for s in tools.specs}
        with pytest.raises(ToolError, match="Plan mode"):
            prepare(tools, write, content="unsafe")
        await tools.execute(prepare(tools, echo, text="safe"), approved=True)
        tools.set_mode("build")
        prepared = prepare(tools, write, content="unsafe")
        tools.set_mode("plan")
        with pytest.raises(ToolError, match="Plan mode"):
            await tools.execute(prepared, approved=True)
        assert not (tmp_path / "marker.txt").exists()
    finally:
        await tools.close()


async def test_plan_blocks_unconfigured_mcp_startup(tmp_path):
    tools = registry(tmp_path, mode="plan")
    with pytest.raises(ToolError, match="Plan mode"):
        prepare(tools, "mcp_connect", server="fixture")
    assert not tools.extensions.mcp.connections


async def test_remembered_mcp_grant_cannot_cover_changed_config_or_arguments(tmp_path):
    tools = registry(tmp_path)
    policy = PermissionPolicy(tools.settings)
    prepared = prepare(tools, "mcp_connect", server="fixture")
    policy.remember(prepared)
    assert policy.allowed(prepared)
    tools.extensions.mcp.configs["fixture"]["args"].append("9000")
    assert not policy.allowed(prepare(tools, "mcp_connect", server="fixture"))
    # Remote credentials are referenced by environment-variable names, never serialized values.
    assert "headers_env" not in json.dumps(prepared.permission_data())


async def test_timeout_disconnects_and_does_not_retry(tmp_path):
    tools = registry(
        tmp_path, {"command": sys.executable, "args": [str(SERVER)], "timeout_seconds": 1}
    )
    try:
        await tools.execute(prepare(tools, "mcp_connect", server="fixture"), approved=True)
        echo = json.loads(
            await tools.execute(prepare(tools, tool_name(tools, "echo"), text="pid"), approved=True)
        )
        pid = echo["structured_content"]["pid"]
        with pytest.raises(ToolError, match="may have completed"):
            await tools.execute(prepare(tools, tool_name(tools, "wait"), seconds=20), approved=True)
        assert not tools.extensions.mcp.specs("build")
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        await tools.close()


async def test_cancelling_mcp_call_cleans_up_process(tmp_path):
    tools = registry(tmp_path)
    try:
        await tools.execute(prepare(tools, "mcp_connect", server="fixture"), approved=True)
        connection = tools.extensions.mcp.connections["fixture"]
        task = asyncio.create_task(
            tools.execute(prepare(tools, tool_name(tools, "wait"), seconds=20), approved=True)
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert connection.task.done()
    finally:
        await tools.close()


async def test_real_streamable_http_transport(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(SERVER),
        str(port),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    tools = registry(tmp_path, {"url": f"http://127.0.0.1:{port}/mcp"})
    try:
        for _ in range(100):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            pytest.fail("HTTP MCP fixture did not start")
        await tools.execute(prepare(tools, "mcp_connect", server="fixture"), approved=True)
        result = await tools.execute(
            prepare(tools, tool_name(tools, "echo"), text="http works"), approved=True
        )
        assert "http works" in result
    finally:
        await tools.close()
        process.terminate()
        await process.wait()


@pytest.mark.parametrize(
    "config",
    [
        {"url": "http://remote.example/mcp"},
        {"url": "https://token:secret@example.org/mcp"},
        {"url": "https://example.org/mcp?key=secret"},
        {"command": "python", "args": "bad"},
        {"command": "python", "url": "https://example.org/mcp"},
        {"command": "python", "timeout_seconds": 0},
        {"command": "python", "env": {"secret": "value"}},
    ],
)
def test_invalid_mcp_settings_rejected(config):
    with pytest.raises(ToolError):
        configurations({"mcp_servers": {"test": config}})


def test_external_json_schema_references_cannot_trigger_network():
    assert external_references(
        {"type": "object", "properties": {"data": {"$ref": "http://localhost/secret"}}}
    )
    assert external_references({"$dynamicRef": "file:///etc/passwd"})
    assert not external_references(
        {"$defs": {"t": {"type": "string"}}, "properties": {"v": {"$ref": "#/$defs/t"}}}
    )


def test_recursive_server_schema_and_deep_json_return_recoverable_errors(tmp_path, monkeypatch):
    tools = registry(tmp_path)
    spec = ToolSpec(
        "recursive",
        "A malformed recursive server schema",
        {
            "type": "object",
            "$defs": {"loop": {"$ref": "#/$defs/loop"}},
            "properties": {"x": {"$ref": "#/$defs/loop"}},
        },
    )
    monkeypatch.setattr(tools.extensions, "specs", lambda mode: [spec])
    with pytest.raises(ToolError, match="recursion limit"):
        prepare(tools, "recursive", x="value")
    with pytest.raises(ToolError, match="JSON nesting limit"):
        tools.prepare(ToolCall("deep", "recursive", "[" * 10000 + "0" + "]" * 10000))
