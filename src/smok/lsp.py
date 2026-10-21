"""A small stdio LSP client: diagnostics, definitions, references; no server edits."""

import asyncio
import contextlib
import json
import os
import shutil
import signal
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote, urlparse

from smok.settings import LanguageServer
from smok.tools.files import ToolError, Workspace

MAX_FRAME = 8 * 1024 * 1024


def server_key(server: LanguageServer) -> str:
    return json.dumps(asdict(server), sort_keys=True)


class LSPClient:
    def __init__(self, workspace: Workspace, server: LanguageServer):
        self.workspace, self.server = workspace, server
        self.process = None
        self.tasks = []
        self.pending = {}
        self.next_id = 0
        self.write_lock = asyncio.Lock()
        self.capabilities = {}
        self.documents = {}
        self.diagnostics = {}
        self.diagnostic_ready = {}
        self.failure = None

    @property
    def running(self):
        return self.process is not None and self.process.returncode is None

    async def start(self):
        command = list(self.server.command)
        if "/" in command[0]:
            candidate = (self.workspace.root / command[0]).resolve()
            executable = str(candidate) if os.access(candidate, os.X_OK) else None
        else:
            sibling = Path(sys.executable).parent / command[0]
            executable = str(sibling) if os.access(sibling, os.X_OK) else shutil.which(command[0])
        if executable is None:
            raise ToolError(
                f"Language server {command[0]!r} is not installed. For Python: uv sync --extra lsp."
            )
        command[0] = executable
        self.process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self.workspace.root,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=MAX_FRAME + 8192,
        )
        self.tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._drain_stderr())]
        try:
            result = await self.request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": self.workspace.root.as_uri(),
                    "workspaceFolders": [
                        {"uri": self.workspace.root.as_uri(), "name": self.workspace.root.name}
                    ],
                    "capabilities": {
                        "general": {"positionEncodings": ["utf-16"]},
                        "workspace": {"configuration": True, "applyEdit": False},
                        "textDocument": {
                            "publishDiagnostics": {"versionSupport": True},
                            "definition": {"linkSupport": True},
                            "diagnostic": {},
                            "synchronization": {"didSave": True},
                        },
                    },
                    "clientInfo": {"name": "smok", "version": "0.2.0"},
                },
            )
            self.capabilities = result.get("capabilities", {})
            if self.capabilities.get("positionEncoding", "utf-16") != "utf-16":
                raise ToolError("This language server did not negotiate UTF-16 positions.")
            await self.notify("initialized", {})
            await self.notify(
                "workspace/didChangeConfiguration", {"settings": self.server.settings}
            )
        except BaseException:
            await self.close()
            raise

    async def _send(self, message):
        if self.failure:
            raise self.failure
        if not self.running or self.process.stdin is None:
            raise ToolError("Language server is not running.")
        raw = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False).encode()
        async with self.write_lock:
            self.process.stdin.write(f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
            try:
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise ToolError("Language server disconnected.") from exc

    async def notify(self, method, params):
        await self._send({"method": method, "params": params})

    async def request(self, method, params, *, seconds=15):
        self.next_id += 1
        identifier = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        try:
            await self._send({"id": identifier, "method": method, "params": params})
            async with asyncio.timeout(seconds):
                return await future
        except TimeoutError as exc:
            with contextlib.suppress(ToolError):
                await self.notify("$/cancelRequest", {"id": identifier})
            raise ToolError(f"Language server timed out on {method}.") from exc
        finally:
            self.pending.pop(identifier, None)

    def _configuration(self, section):
        value = self.server.settings
        for part in (section or "").split("."):
            if part:
                value = value.get(part, {}) if isinstance(value, dict) else {}
        return value

    async def _read(self):
        try:
            assert self.process.stdout is not None
            while True:
                header = await self.process.stdout.readuntil(b"\r\n\r\n")
                fields = dict(
                    line.decode("ascii").split(":", 1) for line in header.strip().split(b"\r\n")
                )
                length = int(next(v for k, v in fields.items() if k.lower() == "content-length"))
                if not 0 <= length <= MAX_FRAME:
                    raise ToolError("Language server sent an oversized frame.")
                message = json.loads(await self.process.stdout.readexactly(length))
                if "method" in message:
                    method, params = message["method"], message.get("params", {})
                    if "id" in message:
                        if method == "workspace/configuration":
                            result = [
                                self._configuration(i.get("section"))
                                for i in params.get("items", [])
                            ]
                        elif method == "workspace/applyEdit":
                            result = {
                                "applied": False,
                                "failureReason": "Smok LSP tools are read-only.",
                            }
                        else:
                            result = None
                        await self._send({"id": message["id"], "result": result})
                    elif method == "textDocument/publishDiagnostics":
                        uri = params["uri"]
                        document = self.documents.get(uri)
                        if (
                            document
                            and params.get("version", document["version"]) == document["version"]
                        ):
                            self.diagnostics[uri] = params
                            self.diagnostic_ready.setdefault(uri, asyncio.Event()).set()
                else:
                    future = self.pending.get(message.get("id"))
                    if future is not None and not future.done():
                        if "error" in message:
                            future.set_exception(
                                ToolError(
                                    "Language server request failed: "
                                    + str(message["error"].get("message", "unknown error"))[:500]
                                )
                            )
                        else:
                            future.set_result(message.get("result"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failure = ToolError(
                "Language server disconnected or sent invalid protocol data "
                f"({type(exc).__name__})."
            )
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(self.failure)
            for event in self.diagnostic_ready.values():
                event.set()

    async def _drain_stderr(self):
        assert self.process.stderr is not None
        while await self.process.stderr.read(8192):
            pass

    async def sync(self, path: Path):
        text = self.workspace._read(path).decode("utf-8")
        uri = path.as_uri()
        old = self.documents.get(uri)
        if old and old["text"] == text:
            return uri, text
        version = old["version"] + 1 if old else 1
        self.documents[uri] = {"text": text, "version": version}
        self.diagnostics.pop(uri, None)
        self.diagnostic_ready[uri] = asyncio.Event()
        if old:
            await self.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": version},
                    "contentChanges": [{"text": text}],
                },
            )
        else:
            await self.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": self.server.language,
                        "version": version,
                        "text": text,
                    }
                },
            )
        sync_options = self.capabilities.get("textDocumentSync", {})
        save = sync_options.get("save") if isinstance(sync_options, dict) else None
        if save is not None and save is not False:
            params = {"textDocument": {"uri": uri}}
            if isinstance(save, dict) and save.get("includeText"):
                params["text"] = text
            await self.notify("textDocument/didSave", params)
        return uri, text

    async def query(self, action: str, path: Path, line: int = 1, column: int = 1):
        uri, text = await self.sync(path)
        if action == "diagnostics":
            if self.capabilities.get("diagnosticProvider"):
                report = await self.request(
                    "textDocument/diagnostic", {"textDocument": {"uri": uri}}
                )
                if report.get("kind") != "full":
                    raise ToolError("Server returned no fresh diagnostic report.")
                items = report.get("items", [])
                version = self.documents[uri]["version"]
            else:
                try:
                    async with asyncio.timeout(10):
                        await self.diagnostic_ready[uri].wait()
                except TimeoutError as exc:
                    raise ToolError("No diagnostics received; this is not a clean result.") from exc
                if self.failure:
                    raise self.failure
                report = self.diagnostics[uri]
                items, version = report.get("diagnostics", []), report.get("version")
            return {
                "path": str(path.relative_to(self.workspace.root)),
                "version": version,
                "document_version": self.documents[uri]["version"],
                "version_verified": version == self.documents[uri]["version"],
                "diagnostics": items[:100],
                "truncated": len(items) > 100,
            }
        lines = text.splitlines()
        if not 1 <= line <= len(lines) or not 1 <= column <= len(lines[line - 1]) + 1:
            raise ToolError("LSP line/column is outside the document (both are 1-based).")
        position = {
            "line": line - 1,
            "character": len(lines[line - 1][: column - 1].encode("utf-16-le")) // 2,
        }
        params = {"textDocument": {"uri": uri}, "position": position}
        if action == "references":
            params["context"] = {"includeDeclaration": True}
        locations = await self.request(f"textDocument/{action}", params)
        if locations is None:
            locations = []
        if isinstance(locations, dict):
            locations = [locations]
        output = []
        for location in locations[:100]:
            target = location.get("uri") or location["targetUri"]
            parsed = urlparse(target)
            target_path = Path(unquote(parsed.path)) if parsed.scheme == "file" else None
            label = (
                str(target_path.relative_to(self.workspace.root))
                if target_path and target_path.is_relative_to(self.workspace.root)
                else target
            )
            start = (
                location.get("range")
                or location.get("targetSelectionRange")
                or location["targetRange"]
            )["start"]
            output.append(
                {"path": label, "line": start["line"] + 1, "column_utf16": start["character"] + 1}
            )
        return {"locations": output, "truncated": len(locations) > 100}

    async def close(self):
        if self.running:
            with contextlib.suppress(ToolError):
                await self.request("shutdown", None, seconds=2)
                await self.notify("exit", None)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
            await self.process.wait()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for future in self.pending.values():
            if not future.done():
                future.cancel()


class LanguageServers:
    def __init__(self, workspace: Workspace, servers: list[LanguageServer]):
        self.workspace, self.servers = workspace, servers
        self.clients = {}

    def select(self, path: str):
        suffix = self.workspace.resolve(path).suffix
        server = next((s for s in self.servers if suffix in s.extensions), None)
        if server is None:
            raise ToolError(
                f"No LSP server configured for {suffix or 'this file'}. "
                "Set lsp_servers in project settings."
            )
        return server

    def started(self, server):
        client = self.clients.get(server_key(server))
        return client is not None and client.running and client.failure is None

    async def execute(self, server, action, **arguments):
        key = server_key(server)
        try:
            if not self.started(server):
                if key in self.clients:
                    await self.clients[key].close()
                client = LSPClient(self.workspace, server)
                self.clients[key] = client
                await client.start()
            result = await self.clients[key].query(
                action, self.workspace.resolve(arguments.pop("path")), **arguments
            )
            return json.dumps(result, ensure_ascii=False)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ToolError("Language server returned an unsupported result shape.") from exc

    async def changed(self, path: str):
        resolved = self.workspace.resolve(path)
        for client in self.clients.values():
            if client.running and resolved.as_uri() in client.documents:
                await client.sync(resolved)

    async def close(self):
        await asyncio.gather(*(client.close() for client in self.clients.values()))
        self.clients.clear()
