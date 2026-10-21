import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_phase2_tools import prepare

from smok.lsp import LSPClient
from smok.settings import DEFAULT_LSP, LanguageServer
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry


async def test_real_python_server_diagnostics_definition_references_and_refresh(tmp_path):
    executable = Path(sys.executable).parent / "pylsp"
    if not executable.is_file():
        pytest.skip("Install the lsp extra for the real Python language-server check.")
    file = tmp_path / "app.py"
    file.write_text('def greet(name):\n    return missing\n\nmessage = greet("dragon")\n')
    tools = ToolRegistry(Workspace(tmp_path))
    try:
        request = prepare(tools, "lsp_diagnostics", path="app.py")
        assert request.requires_approval
        with pytest.raises(ToolError, match="Permission denied"):
            await tools.execute(request)
        report = json.loads(await tools.execute(request, approved=True))
        assert any(
            "undefined name" in d["message"] and "missing" in d["message"]
            for d in report["diagnostics"]
        )
        definition = prepare(tools, "lsp_definition", path="app.py", line=4, column=11)
        assert not definition.requires_approval
        result = json.loads(await tools.execute(definition))
        assert {"path": "app.py", "line": 1, "column_utf16": 5} in result["locations"]
        references = prepare(tools, "lsp_references", path="app.py", line=1, column=5)
        result = json.loads(await tools.execute(references))
        assert {p["line"] for p in result["locations"]} == {1, 4}
        tools.workspace.read_file("app.py")
        edit = prepare(
            tools, "edit_file", path="app.py", old_text="return missing", new_text="return name"
        )
        await tools.execute(edit, approved=True)
        report = json.loads(await tools.execute(prepare(tools, "lsp_diagnostics", path="app.py")))
        assert report["diagnostics"] == []
        # A user edit outside the agent's edit tool must refresh the open document too.
        file.write_text(file.read_text().replace("return name", "return other_missing"))
        report = json.loads(await tools.execute(prepare(tools, "lsp_diagnostics", path="app.py")))
        assert any("other_missing" in d["message"] for d in report["diagnostics"])
        process = next(iter(tools.languages.clients.values())).process
    finally:
        await tools.close()
    assert process.returncode is not None


async def test_protocol_ignores_old_diagnostics_and_rejects_server_edits(tmp_path):
    file = tmp_path / "app.py"
    file.write_text("x = 1\n")
    client = LSPClient(Workspace(tmp_path), DEFAULT_LSP)
    reader = asyncio.StreamReader()
    client.process = SimpleNamespace(stdout=reader)
    uri = file.as_uri()
    client.documents[uri] = {"text": "x = 1\n", "version": 2}
    client.diagnostic_ready[uri] = asyncio.Event()
    sent = []

    async def send(message):
        sent.append(message)

    client._send = send
    task = asyncio.create_task(client._read())

    def publish(message):
        raw = json.dumps(message).encode()
        frame = f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw
        for i in range(0, len(frame), 7):
            reader.feed_data(frame[i : i + 7])

    publish(
        {
            "method": "textDocument/publishDiagnostics",
            "params": {"uri": uri, "version": 1, "diagnostics": [{"message": "stale"}]},
        }
    )
    publish({"id": 10, "method": "workspace/applyEdit", "params": {"edit": {}}})
    for _ in range(20):
        await asyncio.sleep(0)
        if sent:
            break
    assert uri not in client.diagnostics
    assert not client.diagnostic_ready[uri].is_set()
    assert sent[0]["result"]["applied"] is False
    publish(
        {
            "method": "textDocument/publishDiagnostics",
            "params": {"uri": uri, "version": 2, "diagnostics": []},
        }
    )
    await asyncio.wait_for(client.diagnostic_ready[uri].wait(), 1)
    assert client.diagnostics[uri]["diagnostics"] == []
    reader.feed_eof()
    await task
    assert isinstance(client.failure, ToolError)
    assert file.read_text() == "x = 1\n"


async def test_position_conversion_uses_utf16_and_validates_bounds(tmp_path):
    file = tmp_path / "app.py"
    file.write_text('"🐉"; value\n')
    client = LSPClient(Workspace(tmp_path), DEFAULT_LSP)
    calls = []

    async def notify(*args):
        pass

    async def request(method, params):
        calls.append((method, params))
        return [{"uri": file.as_uri(), "range": {"start": {"line": 0, "character": 6}}}]

    client.notify, client.request = notify, request
    result = await client.query("definition", file, line=1, column=6)
    assert calls[0][1]["position"] == {"line": 0, "character": 6}
    assert result["locations"] == [{"path": "app.py", "line": 1, "column_utf16": 7}]
    with pytest.raises(ToolError, match="outside the document"):
        await client.query("definition", file, line=4, column=1)


async def test_missing_and_disconnected_language_servers_are_recoverable(tmp_path):
    client = LSPClient(
        Workspace(tmp_path), LanguageServer("none", (".x",), ("smok-missing-server",))
    )
    with pytest.raises(ToolError, match="not installed"):
        await client.start()
    reader = asyncio.StreamReader()
    client.process = SimpleNamespace(stdout=reader)
    waiting = asyncio.get_running_loop().create_future()
    client.pending[1] = waiting
    reader.feed_data(b"Content-Length: 999999999\r\n\r\n")
    await client._read()
    with pytest.raises(ToolError, match="invalid protocol"):
        await waiting


async def test_saved_document_notifications_and_unversioned_reports_are_explicit(tmp_path):
    file = tmp_path / "app.py"
    file.write_text("value = 1\n")
    client = LSPClient(Workspace(tmp_path), DEFAULT_LSP)
    client.capabilities = {"textDocumentSync": {"save": {"includeText": True}}}
    sent = []

    async def notify(method, params):
        sent.append((method, params))
        if method == "textDocument/didSave":
            uri = params["textDocument"]["uri"]
            client.diagnostics[uri] = {"diagnostics": []}
            client.diagnostic_ready[uri].set()

    client.notify = notify
    result = await client.query("diagnostics", file)
    assert [method for method, _ in sent] == ["textDocument/didOpen", "textDocument/didSave"]
    assert sent[-1][1]["text"] == file.read_text()
    assert not result["version_verified"] and result["version"] is None
    assert result["document_version"] == 1


async def test_silent_language_server_never_reports_clean_diagnostics(tmp_path, monkeypatch):
    file = tmp_path / "app.py"
    file.write_text("bad\n")
    client = LSPClient(Workspace(tmp_path), DEFAULT_LSP)

    async def notify(*args):
        pass

    client.notify = notify
    real_timeout = asyncio.timeout
    monkeypatch.setattr("smok.lsp.asyncio.timeout", lambda _: real_timeout(0.01))
    with pytest.raises(ToolError, match="not a clean result"):
        await client.query("diagnostics", file)
