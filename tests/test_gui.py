import asyncio
import base64
import io
import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from starlette.websockets import WebSocketDisconnect

from smok.checkpoints import Checkpoints
from smok.context import message_tokens
from smok.gui.history import journal_view
from smok.gui.server import create_app
from smok.gui.service import Service
from smok.images import Image
from smok.journal import Journal
from smok.models.anthropic import serialize_messages as anthropic_messages
from smok.models.openai_compat import serialize_messages as openai_messages
from smok.state import state_path
from smok.tools.files import ToolError
from smok.types import Event, Message, Text, messages_from_data, messages_to_data

ORIGIN = "http://127.0.0.1:8765"


class Model:
    def __init__(self, config):
        self.config = replace(config, repo_map_tokens=0, max_output_tokens=128)
        self.name = config.name
        self.calls = 0

    async def stream(self, system, messages, tools):
        prompt = next(
            (b.text for m in reversed(messages) for b in m.content if isinstance(b, Text)), ""
        )
        if self.calls == 0 and "edit" in prompt:
            yield Event(
                "tool_call", {"id": "read", "name": "read_file", "arguments": '{"path":"hello.py"}'}
            )
            reason = "tool_calls"
        elif self.calls == 1:
            yield Event(
                "tool_call",
                {
                    "id": "edit",
                    "name": "edit_file",
                    "arguments": json.dumps(
                        {"path": "hello.py", "old_text": "before", "new_text": "after"}
                    ),
                },
            )
            reason = "tool_calls"
        else:
            for text in ["The workspace ", "is ready."]:
                yield Event("text_delta", {"text": text})
                await asyncio.sleep(0)
            reason = "stop"
        self.calls += 1
        yield Event("usage", {"input_tokens": 40, "output_tokens": 8})
        yield Event("stop", {"reason": reason})


def setup(root, factory=Model):
    service = Service(root, model="local/gui-test", factory=factory)
    return service, create_app(root, token="launch-secret", origin=ORIGIN, service=service)


def login(client):
    response = client.post("/api/login", json={"token": "launch-secret"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]


def wait_for(client, identifier, condition):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        view = client.get(f"/api/sessions/{identifier}").json()
        if condition(view):
            return view
        time.sleep(0.01)
    pytest.fail("Session did not reach expected state")


def test_http_auth_origin_host_and_websocket_guards(tmp_path):
    service, app = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        assert client.get("/api/bootstrap").status_code == 401
        assert client.post("/api/login", json={"token": "wrong"}).status_code == 401
        assert (
            client.post(
                "/api/login",
                json={"token": "launch-secret"},
                headers={"origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
        login(client)
        assert client.get("/api/bootstrap").status_code == 200
        assert client.post("/api/sessions", json={}, headers={"origin": "null"}).status_code == 403
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/sessions/missing/events", headers={"origin": "https://evil.example"}
            ):
                pass
        response = client.get("/")
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["referrer-policy"] == "no-referrer"
    assert not service.sessions


@pytest.mark.parametrize(
    "decision,expected", [("allow", "after"), ("deny", "before"), ("always", "after")]
)
def test_stream_reconnect_exact_approval_and_restore(tmp_path, decision, expected):
    (tmp_path / "hello.py").write_text("before\n")
    _, app = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        login(client)
        identifier = client.post("/api/sessions", json={}).json()["id"]
        path = f"/api/sessions/{identifier}"
        assert (
            client.post(
                path + "/actions", json={"action": "prompt", "data": {"prompt": "edit hello"}}
            ).status_code
            == 202
        )
        view = wait_for(client, identifier, lambda v: v["pending"])
        pending = view["pending"][0]
        assert "+after" in pending["diff"] and (tmp_path / "hello.py").read_text() == "before\n"
        assert client.patch(path, json={"mode": "plan"}).status_code == 409
        # A new browser connection sees the still-live request, with its unique decision ID.
        with client.websocket_connect(ORIGIN.replace("http:", "ws:") + path + "/events") as ws:
            snapshot = ws.receive_json()
            assert snapshot["type"] == "snapshot"
            assert snapshot["data"]["pending"][0]["request_id"] == pending["request_id"]
        assert (
            client.post(
                path + "/approvals",
                json={"request_id": pending["request_id"], "decision": decision},
            ).status_code
            == 200
        )
        view = wait_for(client, identifier, lambda v: not v["busy"])
        assert (tmp_path / "hello.py").read_text() == expected + "\n"
        assert view["state"]["usage"]["requests"] >= 2
        assert any(e["type"] == "text_delta" for e in view["events"])
        assert (
            client.post(
                path + "/approvals", json={"request_id": pending["request_id"], "decision": "allow"}
            ).status_code
            == 409
        )
        if decision == "always":
            assert client.get("/api/settings").json()["allow_rules"] == [
                {"tool": "file_edit", "path": "hello.py", "match": "exact"}
            ]
        if decision != "deny":
            branch = client.post(path + "/branch", json={"checkpoint": 1})
            assert branch.status_code == 200, branch.text
            branch_root = branch.json()["workspace"]
            assert branch_root != str(tmp_path)
            assert (
                state_path(tmp_path, "branches") / branch_root.split("/")[-1] / "hello.py"
            ).read_text() == "after\n"
            client.post(path + "/actions", json={"action": "undo"})
            wait_for(client, identifier, lambda v: not v["busy"])
            assert (tmp_path / "hello.py").read_text() == "before\n"
            client.delete(f"/api/sessions/{branch.json()['id']}")
        client.delete(path)
        assert client.post("/api/sessions", json={"resume": identifier}).status_code == 200


def test_cancel_pending_does_not_grant_or_leave_session_locked(tmp_path):
    (tmp_path / "hello.py").write_text("before\n")
    _, app = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        login(client)
        identifier = client.post("/api/sessions", json={}).json()["id"]
        path = f"/api/sessions/{identifier}"
        client.post(path + "/actions", json={"action": "prompt", "data": {"prompt": "edit hello"}})
        wait_for(client, identifier, lambda v: bool(v["pending"]))
        client.post(path + "/stop", json={})
        view = client.get(path).json()
        assert not view["pending"] and not view["busy"]
        assert (tmp_path / "hello.py").read_text() == "before\n"
        client.delete(path)
        resumed = Journal(tmp_path, resume=identifier)
        resumed.close()


def test_cli_session_watch_cannot_steal_writer(tmp_path):
    service, app = setup(tmp_path)
    journal = Journal(tmp_path)
    journal.write(Event("turn_started", {"prompt": "hello from CLI"}))
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        login(client)
        view = client.get(f"/api/sessions/{journal.id}").json()
        assert view["owned"] is False and view["title"] == "hello from CLI"
        response = client.post("/api/sessions", json={"resume": journal.id})
        assert response.status_code == 409 and "already open" in response.text
        journal.write(Event("text_delta", {"text": "Live CLI output"}))
        with client.websocket_connect(
            ORIGIN.replace("http:", "ws:") + f"/api/sessions/{journal.id}/events"
        ) as ws:
            assert ws.receive_json()["data"]["events"][-1]["data"]["text"] == "Live CLI output"
        assert (
            client.post(
                f"/api/sessions/{journal.id}/actions", json={"action": "compact"}
            ).status_code
            == 409
        )
    journal.close()
    assert not service.sessions


def test_settings_keys_validation_and_readonly_share(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service, app = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        login(client)
        response = client.put(
            "/api/settings",
            json={
                "secrets": {"OPENAI_API_KEY": "fixture-secret-8c31"},
                "mcp_servers": {"browser": {"command": "npx", "args": ["@playwright/mcp"]}},
            },
        )
        assert response.status_code == 200, response.text
        assert "fixture-secret-8c31" not in response.text
        assert service.config.key_path.stat().st_mode & 0o777 == 0o600
        previous = service.config.key_path.read_bytes()
        assert client.put("/api/settings", json={"secrets": {"PATH": "bad"}}).status_code == 409
        assert service.config.key_path.read_bytes() == previous
        assert (
            client.put(
                "/api/settings", json={"mcp_servers": {"bad": {"url": "http://example.org"}}}
            ).status_code
            == 409
        )
        identifier = client.post("/api/sessions", json={}).json()["id"]
        session = service.sessions[identifier]
        session.agent.messages = [Message("user", [Text("Review fixture-secret-8c31")])]
        session.agent.save()
        path = f"/api/sessions/{identifier}"
        preview = client.post(path + "/share-preview", json={}).json()
        assert "fixture-secret" not in json.dumps(preview)
        assert "[REDACTED]" in json.dumps(preview)
        assert client.post(path + "/shares", json={"digest": "stale"}).status_code == 409
        created = client.post(path + "/shares", json={"digest": preview["digest"]}).json()
        stranger = TestClient(app, base_url=ORIGIN)
        if True:
            shared = stranger.get("/api/shares/" + created["id"])
            assert shared.status_code == 200 and shared.json()["read_only"] is True
            assert "workspace" not in shared.json()
            assert stranger.get("/api/sessions").status_code == 401
            assert (
                stranger.delete(
                    "/api/shares/" + created["id"], headers={"origin": ORIGIN}
                ).status_code
                == 401
            )
        assert client.delete("/api/shares/" + created["id"]).status_code == 200
        assert client.get("/api/shares/" + created["id"]).status_code == 404
        client.put("/api/settings", json={"secrets": {"OPENAI_API_KEY": None}})


def image():
    stream = io.BytesIO()
    PillowImage.new("RGB", (20, 16), (220, 80, 20)).save(stream, format="PNG")
    return Image("image/png", base64.b64encode(stream.getvalue()).decode())


def test_vision_round_trip_formats_and_estimates():
    picture = image()
    messages = [Message("user", [Text("Explain this"), picture])]
    assert messages_from_data(messages_to_data(messages)) == messages
    assert openai_messages("system", messages)[1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert anthropic_messages(messages)[0]["content"][1]["source"]["data"] == picture.data
    assert 1024 < message_tokens(messages) < 2000
    with pytest.raises(ValueError, match="declared media"):
        Image("image/jpeg", picture.data)
    with pytest.raises(ValueError):
        Image("image/svg+xml", "<svg/>")
    with pytest.raises(ValueError):
        Image("image/png", "https://example.org/picture.png")


def test_image_capability_blocks_before_model_call(tmp_path):
    service, app = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        login(client)
        identifier = client.post("/api/sessions", json={}).json()["id"]
        picture = image()
        client.post(
            f"/api/sessions/{identifier}/actions",
            json={
                "action": "prompt",
                "data": {
                    "prompt": "Look",
                    "images": [{"media_type": picture.media_type, "data": picture.data}],
                },
            },
        )
        view = wait_for(client, identifier, lambda v: not v["busy"])
        assert view["state"]["usage"]["requests"] == 0
        assert "vision" in view["events"][-2]["data"]["message"]
        client.put("/api/settings", json={"profiles": {"local/gui-test": {"vision": True}}})
        client.post(
            f"/api/sessions/{identifier}/actions",
            json={
                "action": "prompt",
                "data": {
                    "prompt": "Look",
                    "images": [{"media_type": picture.media_type, "data": picture.data}],
                },
            },
        )
        view = wait_for(client, identifier, lambda v: not v["busy"])
        assert view["state"]["usage"]["requests"] == 1
        client.delete(f"/api/sessions/{identifier}")
        assert (
            client.post("/api/sessions", json={"resume": identifier}).json()["state"]["messages"][
                0
            ]["content"][1]["type"]
            == "image"
        )


def test_checkpoint_restore_is_undoable_and_refuses_later_manual_change(tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("zero")
    checkpoints = Checkpoints(tmp_path)
    checkpoints.begin()
    path.write_text("one")
    checkpoints.finish()
    checkpoints.begin()
    path.write_text("two")
    checkpoints.finish()
    path.write_text("manual")
    with pytest.raises(Exception, match="outside Smok"):
        checkpoints.restore_to(1)
    assert path.read_text() == "manual"
    path.write_text("two")
    assert checkpoints.restore_to(1)["restored_from"] == 1
    assert path.read_text() == "one"
    checkpoints.undo()
    assert path.read_text() == "two"


async def test_restore_refuses_background_jobs_in_another_workspace_session(tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("zero")
    service, _ = setup(tmp_path)
    try:
        current, other = service.open(), service.open()
        checkpoints = current.agent.checkpoints
        checkpoints.begin()
        path.write_text("one")
        checkpoints.finish()
        checkpoints.begin()
        path.write_text("two")
        checkpoints.finish()
        job = json.loads(await other.agent.tools.jobs.start("sleep 30"))
        for action in ("restore", "undo"):
            with pytest.raises(ToolError, match="Stop background processes"):
                await current.perform(action, {"checkpoint": 1})
            assert path.read_text() == "two"
        await other.agent.tools.jobs.stop(job["id"])
        await current.perform("restore", {"checkpoint": 1})
        assert path.read_text() == "one"
        await current.perform("undo", {})
        assert path.read_text() == "two"
    finally:
        await service.close()


def test_history_coalesces_stream_and_ignores_partial_record(tmp_path):
    journal = Journal(tmp_path)
    journal.write(Event("turn_started", {"prompt": "hello"}))
    for _ in range(500):
        journal.write(Event("text_delta", {"text": "x"}))
    identifier = journal.id
    journal.close()
    with state_path(tmp_path, "sessions", identifier + ".jsonl").open("ab") as stream:
        stream.write(b'{"incomplete":')
    view = journal_view(tmp_path, identifier)
    assert view["title"] == "hello"
    assert view["events"][-1]["data"]["text"] == "x" * 500


def test_settings_revision_rejects_stale_forms_and_cli_sees_profiles(tmp_path):
    from smok.gui.config import Configuration
    from smok.settings import ProjectSettings

    config = Configuration(tmp_path)
    old = config.view()["revision"]
    settings = ProjectSettings(tmp_path)
    settings.add_rule({"tool": "file_edit", "path": "new.py", "match": "exact"})
    with pytest.raises(ValueError, match="another client"):
        config.update({"revision": old, "allow_rules": []})
    config.update(
        {
            "profiles": {"local/shared": {"vision": True, "base_url": "http://127.0.0.1:9999/v1"}},
            "default_model": "local/shared",
        }
    )
    shared = Configuration(tmp_path).resolve()
    assert shared.name == "local/shared" and shared.vision
    assert shared.base_url == "http://127.0.0.1:9999/v1"
    assert Configuration(tmp_path, model="local/explicit").resolve().name == "local/explicit"
    assert ProjectSettings(tmp_path).rules[0]["path"] == "new.py"


async def test_cli_uses_gui_model_and_key_settings(tmp_path, monkeypatch, capsys):
    import smok.cli as cli
    from smok.gui.config import Configuration

    monkeypatch.delenv("SMOK_API_KEY", raising=False)
    config = Configuration(tmp_path)
    config.update(
        {
            "profiles": {"local/shared": {"base_url": "http://127.0.0.1:9999/v1"}},
            "default_model": "local/shared",
            "secrets": {"SMOK_API_KEY": "fixture-shared-key"},
        }
    )
    seen = []

    def factory(model):
        seen.append(model)
        return Model(model)

    monkeypatch.setattr(cli, "create_adapter", factory)
    code = await cli.run_cli(
        cli.parser().parse_args(
            [
                "-C",
                str(tmp_path),
                "-p",
                "hello",
                "--no-input",
                "--no-self-check",
                "--no-checkpoints",
            ]
        )
    )
    output = capsys.readouterr().out
    assert code == 0
    assert seen[0].name == "local/shared"
    assert seen[0].base_url == "http://127.0.0.1:9999/v1"
    assert seen[0].api_key() == "fixture-shared-key"
    assert "fixture-shared-key" not in output
    config.update({"secrets": {"SMOK_API_KEY": None}})


def test_short_environment_key_redaction_keeps_share_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    service, app = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        login(client)
        identifier = client.post("/api/sessions", json={}).json()["id"]
        service.sessions[identifier].agent.messages = [Message("user", [Text("x")])]
        snapshot = client.post(f"/api/sessions/{identifier}/share-preview", json={}).json()[
            "snapshot"
        ]
        assert snapshot["messages"][0] == {
            "role": "user",
            "content": [{"type": "text", "text": "[REDACTED]"}],
        }
