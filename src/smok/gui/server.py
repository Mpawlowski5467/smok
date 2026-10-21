"""Loopback-only HTTP/WebSocket API with a per-launch browser capability."""

import asyncio
import hashlib
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from smok.gui.history import share_projection
from smok.gui.service import Service
from smok.permissions import PermissionPolicy
from smok.settings import ProjectSettings
from smok.state import state_path, write_json
from smok.tools.files import ToolError


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Body):
    token: str = Field(max_length=100)


class OpenSession(Body):
    resume: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=200)


class Action(Body):
    action: Literal[
        "prompt",
        "reload",
        "compact",
        "review",
        "handoff",
        "skill",
        "recipe",
        "command",
        "mcp",
        "council",
        "replay",
        "accept",
        "oracle",
        "delegate",
        "remote_run",
        "remote_batch",
        "start_process",
        "stop_process",
        "undo",
        "restore",
    ]
    data: dict = Field(default_factory=dict)


class Decision(Body):
    request_id: str = Field(max_length=40)
    decision: Literal["allow", "always", "deny"]


class Controls(Body):
    mode: Literal["plan", "build"] | None = None
    model: str | None = Field(default=None, max_length=200)
    permissions: Literal["ask", "auto-edit", "full-auto"] | None = None
    budget_tokens: int | None = Field(default=None, ge=1, le=100_000_000)
    budget_usd: float | None = Field(default=None, gt=0, le=10000, allow_inf_nan=False)
    max_iterations: int | None = Field(default=None, ge=1, le=40)
    turn_timeout: float | None = Field(default=None, ge=1, le=86400, allow_inf_nan=False)


class ContextChange(Body):
    action: Literal["pin", "drop"]
    target: str = Field(min_length=1, max_length=1000)


class Branch(Body):
    checkpoint: int = Field(ge=1)


class Share(Body):
    include_tools: bool = False
    digest: str | None = Field(default=None, max_length=64)


class SetupCheck(Body):
    model: str | None = Field(default=None, max_length=200)
    probe: bool = False


def create_app(root, *, token=None, origin="http://127.0.0.1:8765", service=None):
    token = token or secrets.token_urlsafe(32)
    cookie = secrets.token_urlsafe(32)
    host = origin.removeprefix("http://")
    if not host.startswith("127.0.0.1:") or not host.split(":")[-1].isdigit():
        raise ValueError("The GUI must use a loopback HTTP origin.")
    service = service or Service(root)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await service.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service, app.state.token = service, token

    def authenticated(connection):
        value = connection.cookies.get("smok_session", "")
        return bool(value and secrets.compare_digest(value, cookie))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if request.headers.get("host") != host:
            return JSONResponse({"detail": "Unrecognized host."}, status_code=403)
        request_origin = request.headers.get("origin")
        if (
            request_origin
            and request_origin != origin
            or request.method not in {"GET", "HEAD"}
            and request_origin != origin
        ):
            return JSONResponse({"detail": "Use this app's own browser origin."}, status_code=403)
        public = path in {"/api/login", "/api/health"} or (
            path.startswith("/api/shares/") and request.method == "GET"
        )
        if path.startswith("/api/") and not public and not authenticated(request):
            return JSONResponse(
                {"detail": "Open the launch link to connect to Smok."}, status_code=401
            )
        # Limit chunked bodies as well as Content-Length; never buffer an unbounded upload.
        if request.method not in {"GET", "HEAD"}:
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 9_000_000:
                    return JSONResponse({"detail": "Request exceeds 9 MB."}, status_code=413)
            request._body = bytes(raw)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                "connect-src 'self' ws://"
                + host
                + "; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

    @app.exception_handler(ValueError)
    @app.exception_handler(ToolError)
    async def invalid(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(FileNotFoundError)
    async def missing(_request, _exc):
        return JSONResponse({"detail": "This session or file is unavailable."}, status_code=404)

    @app.get("/api/health")
    async def health():
        return {"ready": True}

    @app.post("/api/login")
    async def login(body: Login):
        if not secrets.compare_digest(body.token, token):
            raise HTTPException(401, "Invalid launch token.")
        response = JSONResponse({"connected": True})
        response.set_cookie("smok_session", cookie, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/bootstrap")
    async def bootstrap():
        return {
            "workspace": str(service.root),
            "settings": service.config.view(),
            "sessions": await asyncio.to_thread(service.listing),
        }

    @app.get("/api/sessions")
    async def sessions():
        return await asyncio.to_thread(service.listing)

    @app.post("/api/diagnostics")
    async def diagnostics(body: SetupCheck):
        from smok.diagnostics import diagnose

        return await diagnose(
            service.root,
            model=body.model or service.config.initial_model,
            config_path=service.config.config_path,
            base_url=service.config.base_url,
            probe=body.probe,
        )

    @app.post("/api/sessions")
    async def open_session(body: OpenSession):
        return service.open(resume=body.resume, model=body.model).view()

    @app.get("/api/sessions/{identifier}")
    async def session_view(identifier: str):
        return service.view(identifier)

    @app.delete("/api/sessions/{identifier}")
    async def release(identifier: str):
        session = service.owned(identifier)
        await session.close()
        del service.sessions[identifier]
        return {"closed": True}

    @app.post("/api/sessions/{identifier}/actions", status_code=202)
    async def action(identifier: str, body: Action):
        if body.action == "prompt":
            prompt = body.data.get("prompt")
            if not isinstance(prompt, str) or not 0 < len(prompt.strip()) <= 100_000:
                raise ValueError("Enter a prompt of at most 100,000 characters.")
            if set(body.data) - {"prompt", "images"}:
                raise ValueError("Unknown prompt field.")
        elif len(json.dumps(body.data)) > 64_000:
            raise ValueError("Action input exceeds 64 KB.")
        service.owned(identifier).start(body.action, body.data)
        return {"started": True}

    @app.post("/api/sessions/{identifier}/stop")
    async def stop(identifier: str):
        await service.owned(identifier).stop()
        return {"stopped": True}

    @app.post("/api/sessions/{identifier}/approvals")
    async def approve(identifier: str, body: Decision):
        service.owned(identifier).decide(body.request_id, body.decision)
        return {"decided": True}

    @app.get("/api/sessions/{identifier}/jobs/{job}")
    async def job_output(identifier: str, job: str, offset: int = 0):
        if offset < 0:
            raise ValueError("Offset must be nonnegative.")
        return json.loads(service.owned(identifier).agent.tools.jobs.poll(job, offset))

    @app.patch("/api/sessions/{identifier}")
    async def controls(identifier: str, body: Controls):
        session = service.owned(identifier)
        service.require_idle(session.root)
        agent = session.agent
        if body.model:
            config = service.config.resolve(body.model)
            agent.model = service.factory(config)
            session.team.primary = session.team.active_config = config
        if body.mode:
            agent.set_mode(body.mode)
        if body.permissions:
            agent.policy.mode = body.permissions
        if "budget_tokens" in body.model_fields_set or "budget_usd" in body.model_fields_set:
            # Keep consumed usage and pending reservations; changing limits never resets spend.
            budget = agent.budget
            if "budget_tokens" in body.model_fields_set:
                budget.tokens = body.budget_tokens
            if "budget_usd" in body.model_fields_set:
                budget.dollars = body.budget_usd
        if body.max_iterations:
            agent.max_iterations = body.max_iterations
        if "turn_timeout" in body.model_fields_set:
            agent.turn_timeout = body.turn_timeout
        agent.save()
        return session.view()

    @app.post("/api/sessions/{identifier}/context")
    async def context(identifier: str, body: ContextChange):
        session = service.owned(identifier)
        service.require_idle(session.root)
        if body.action == "pin":
            session.agent.context.pin(body.target)
        else:
            session.agent.context.drop(body.target, session.agent.messages)
        session.agent.save()
        return session.view()

    @app.post("/api/sessions/{identifier}/branch")
    async def branch(identifier: str, body: Branch):
        return (await service.branch(identifier, body.checkpoint)).view()

    @app.get("/api/settings")
    async def settings():
        return service.config.view()

    @app.put("/api/settings")
    async def update_settings(body: dict):
        service.require_idle()
        if len(json.dumps(body)) > 128_000:
            raise ValueError("Settings exceed 128 KB.")
        result = service.config.update(body)
        for session in service.sessions.values():
            if session.root != service.root:
                continue
            agent = session.agent
            new = ProjectSettings(session.root)
            agent.tools.settings = new
            agent.tools.sandbox = new.sandbox
            agent.policy = PermissionPolicy(new)
            await agent.tools.extensions.reload()
            config = service.config.resolve(agent.config.name)
            agent.model = service.factory(config)
            session.team.primary = session.team.active_config = config
        return result

    def projection(identifier, include_tools):
        result = share_projection(service.view(identifier), include_tools=include_tools)
        # Redact configured key values too; the human preview still covers arbitrary secrets.
        secret_names = {item["name"] for item in service.config.view()["secrets"]}
        values = {os.getenv(name) for name in secret_names} - {None, ""}

        def redact(text):
            for secret in sorted(values, key=len, reverse=True):
                text = text.replace(secret, "[REDACTED]")
            return text

        result["title"] = redact(result["title"])
        for message in result["messages"]:
            for block in message["content"]:
                for key in ("text", "content", "arguments", "name"):
                    if key in block:
                        block[key] = redact(block[key])
        serialized = json.dumps(result, ensure_ascii=False)
        return result, hashlib.sha256(serialized.encode()).hexdigest()

    @app.post("/api/sessions/{identifier}/share-preview")
    async def preview_share(identifier: str, body: Share):
        snapshot, digest = projection(identifier, body.include_tools)
        return {"snapshot": snapshot, "digest": digest}

    @app.post("/api/sessions/{identifier}/shares")
    async def create_share(identifier: str, body: Share):
        snapshot, digest = projection(identifier, body.include_tools)
        if body.digest != digest:
            raise ValueError("The transcript changed. Preview it again before sharing.")
        key = secrets.token_urlsafe(24)
        snapshot.update(expires=time.time() + 7 * 86400)
        write_json(state_path(service.root, "shares", key + ".json"), snapshot)
        return {"id": key, "url": origin + "/share/" + key, "expires": snapshot["expires"]}

    def share_path(key):
        if len(key) != 32 or not all(c.isalnum() or c in "_-" for c in key):
            raise HTTPException(404, "Share unavailable.")
        return state_path(service.root, "shares", key + ".json")

    @app.get("/api/shares/{key}")
    async def read_share(key: str):
        data = json.loads(share_path(key).read_text())
        if data["expires"] < time.time():
            raise HTTPException(410, "This share has expired.")
        return data

    @app.delete("/api/shares/{key}")
    async def revoke_share(key: str):
        share_path(key).unlink(missing_ok=True)
        return {"revoked": True}

    @app.get("/api/shares")
    async def list_shares():
        directory = state_path(service.root, "shares")
        rows = []
        if directory.exists():
            for path in sorted(directory.glob("*.json"))[:100]:
                value = json.loads(share_path(path.stem).read_text())
                rows.append(
                    {
                        "id": path.stem,
                        "title": value["title"],
                        "expires": value["expires"],
                        "url": origin + "/share/" + path.stem,
                    }
                )
        return rows

    @app.websocket("/api/sessions/{identifier}/events")
    async def events(socket: WebSocket, identifier: str):
        if (
            socket.headers.get("host") != host
            or socket.headers.get("origin") != origin
            or not authenticated(socket)
        ):
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = asyncio.Queue(maxsize=256)
        owned = service.sessions.get(identifier)
        if owned:
            owned.listeners.add(queue)
        last_metadata = 0
        try:
            view = service.view(identifier)
            await socket.send_json({"type": "snapshot", "data": view})
            previous = view.get("record_count")
            while True:
                if owned and owned is not service.sessions.get(identifier):
                    await socket.close(code=1012)
                    break
                if owned:
                    try:
                        packet = await asyncio.wait_for(queue.get(), 2)
                        if packet["type"] == "resync":
                            packet = {"type": "snapshot", "data": owned.view()}
                        await socket.send_json(packet)
                    except TimeoutError:
                        pass
                    if time.monotonic() - last_metadata > 0.3:
                        data = owned.view()
                        data.pop("events", None)
                        data["state"].pop("messages", None)
                        await socket.send_json({"type": "metadata", "data": data})
                        last_metadata = time.monotonic()
                else:
                    await asyncio.sleep(1)
                    view = await asyncio.to_thread(service.view, identifier)
                    if view.get("record_count") != previous:
                        previous = view.get("record_count")
                        await socket.send_json({"type": "snapshot", "data": view})
                    else:
                        await socket.send_json({"type": "heartbeat", "data": {}})
        except (WebSocketDisconnect, OSError, RuntimeError):
            pass
        except (ValueError, FileNotFoundError):
            await socket.close(code=1008)
        finally:
            if owned:
                owned.listeners.discard(queue)

    assets = Path(__file__).parent / "static"

    @app.get("/{path:path}")
    async def frontend(path: str):
        target = (assets / path).resolve()
        if not target.is_relative_to(assets.resolve()) or Path(path).name.startswith("."):
            raise HTTPException(404)
        if path.startswith("api/"):
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target)
        index = assets / "index.html"
        if not index.exists():
            return JSONResponse(
                {"detail": "Build the GUI with npm --prefix web run build."}, status_code=503
            )
        return FileResponse(index)

    return app
