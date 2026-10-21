import asyncio
import json
import os
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_gui import ORIGIN, login, setup

from smok.cli import parser, run_cli
from smok.diagnostics import diagnose, probe_model
from smok.models.profiles import resolve_model


def by_id(report, name):
    return next(c for c in report["checks"] if c["id"] == name)


async def test_offline_diagnostics_create_no_state_and_never_contact_a_provider(
    tmp_path, monkeypatch
):
    def unexpected(*args, **kwargs):
        pytest.fail("Offline checks must not contact an endpoint")

    monkeypatch.setattr("httpx.AsyncClient", unexpected)
    monkeypatch.setattr("smok.diagnostics.shutil.which", lambda name: "/bin/" + name)
    report = await diagnose(tmp_path, model="local/setup-test")
    assert report["ok"] and report["generation_requests"] == 0
    assert by_id(report, "connection")["status"] == "skipped"
    assert not list(tmp_path.iterdir())


async def test_saved_keys_used_privately_without_changing_environment(tmp_path, monkeypatch):
    (tmp_path / ".smok").mkdir()
    key_path = tmp_path / ".smok/gui-keys.json"
    key_path.write_text(json.dumps({"SMOK_API_KEY": "saved-secret"}))
    monkeypatch.setenv("SMOK_API_KEY", "environment-secret")
    config_path = tmp_path / "models.yaml"
    config_path.write_text("models:\n  local/setup-test:\n    key_required: true\n")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/v1/models"
        assert request.headers["authorization"] == "Bearer saved-secret"
        return httpx.Response(200, json={"data": [{"id": "setup-test"}]})

    report = await diagnose(
        tmp_path,
        model="local/setup-test",
        config_path=config_path,
        base_url="http://127.0.0.1:1234/v1?secret=query-secret",
        probe=True,
        transport=httpx.MockTransport(handler),
    )
    assert len(requests) == 1 and report["generation_requests"] == 0
    assert by_id(report, "connection")["status"] == "ok"
    assert os.environ["SMOK_API_KEY"] == "environment-secret"
    assert all(
        secret not in json.dumps(report)
        for secret in ["saved-secret", "environment-secret", "query-secret"]
    )
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


async def test_missing_key_and_bad_configuration_do_not_leak_values(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = await diagnose(tmp_path, model="anthropic/setup-test")
    assert not report["ok"] and by_id(report, "credentials")["status"] == "error"
    (tmp_path / ".smok").mkdir()
    (tmp_path / ".smok/gui-keys.json").write_text("SECRET: [raw-secret-value: [")
    report = await diagnose(tmp_path, model="local/test")
    assert not report["ok"]
    assert "raw-secret-value" not in json.dumps(report)


async def test_missing_tools_and_unsafe_metadata_are_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr("smok.diagnostics.shutil.which", lambda name: None)
    root = tmp_path / "project"
    root.mkdir()
    (root / ".smok").symlink_to(tmp_path, target_is_directory=True)
    report = await diagnose(root, model="local/test", probe=True)
    assert not report["ok"] and report["model"] is None
    assert by_id(report, "git")["status"] == by_id(report, "rg")["status"] == "error"
    assert by_id(report, "settings")["status"] == "error"
    assert by_id(report, "connection")["status"] == "skipped"


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, {"secret": "never-reflect-response"}, "error"),
        (404, {}, "warning"),
        (200, {"data": [{"id": "different"}]}, "error"),
        (200, {"data": "wrong-shape"}, "error"),
        (200, {"data": [{"id": "test"}]}, "ok"),
    ],
)
async def test_probe_reports_catalog_and_auth_failures_without_generation(status, body, expected):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    result = await probe_model(
        resolve_model("local/test"), None, transport=httpx.MockTransport(handler)
    )
    assert result["status"] == expected and len(calls) == 1
    assert calls[0].method == "GET" and calls[0].url.path == "/v1/models"
    assert "never-reflect-response" not in json.dumps(result)


async def test_probe_never_follows_redirect_with_credentials():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://other.example/models"})

    result = await probe_model(
        resolve_model("local/test"), "private-key", transport=httpx.MockTransport(handler)
    )
    assert result["status"] == "error" and len(calls) == 1
    assert "private-key" not in json.dumps(result)


async def test_probe_bounds_response_size_and_total_duration(monkeypatch):
    result = await probe_model(
        resolve_model("local/test"),
        None,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 256_001)),
    )
    assert result["status"] == "error"
    monkeypatch.setattr("smok.diagnostics.PROBE_SECONDS", 0.01)

    async def slow(request):
        await asyncio.sleep(2)
        return httpx.Response(200, json={"data": []})

    result = await probe_model(
        resolve_model("local/test"), None, transport=httpx.MockTransport(slow)
    )
    assert result["status"] == "error"


async def test_unsupported_discovery_and_incomplete_hosted_catalog_are_not_verified():
    def unexpected(request):
        pytest.fail("Unsupported adapter must not make a request")

    result = await probe_model(
        resolve_model("anthropic/test"), "key", transport=httpx.MockTransport(unexpected)
    )
    assert result["status"] == "warning"
    config = replace(resolve_model("local/test"), local=False)
    result = await probe_model(
        config,
        None,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []})),
    )
    assert result["status"] == "warning"


async def test_doctor_json_and_failure_exit_without_a_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("smok.diagnostics.shutil.which", lambda name: None)
    args = parser().parse_args(["--doctor", "--json", "-C", str(tmp_path), "--model", "local/test"])
    assert await run_cli(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["ok"] and not (tmp_path / ".smok").exists()


@pytest.mark.parametrize(
    "flags",
    [
        ["--probe-model"],
        ["--doctor", "-p", "do something"],
        ["--doctor", "--continue"],
        ["--doctor", "--gui"],
        ["--doctor", "--sessions"],
    ],
)
async def test_doctor_rejects_conflicting_actions(flags):
    with pytest.raises(ValueError):
        await run_cli(parser().parse_args(flags))


def test_gui_diagnostics_require_auth_and_do_not_create_sessions(tmp_path):
    service, app = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as client:
        assert client.post("/api/diagnostics", json={}).status_code == 401
        login(client)
        before = service.listing()
        result = client.post("/api/diagnostics", json={"model": "local/gui-test"})
        assert result.status_code == 200
        assert result.json()["generation_requests"] == 0
        assert service.listing() == before and not service.sessions
        assert (
            client.post("/api/diagnostics", json={"endpoint": "http://other.example"}).status_code
            == 422
        )
