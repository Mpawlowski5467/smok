import json
from dataclasses import replace

import httpx
import pytest
from test_adapters import FIXTURES
from test_loop import DONE, ScriptedModel

from evals.run import VARIANTS, profile_data
from evals.suite import digest
from smok.cli import parser, run_cli
from smok.gui.config import Configuration
from smok.models.base import ModelError
from smok.models.openai_compat import OpenAICompatibleAdapter
from smok.models.profiles import resolve_model
from smok.tools.registry import SPECS


@pytest.mark.parametrize("effort", [None, "none", "low"])
async def test_reasoning_is_explicit_on_wire_without_changing_tools_or_output_limit(effort):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text=(FIXTURES / "openai_tool.sse").read_text())

    config = replace(resolve_model("local/fixture"), reasoning_effort=effort)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [e async for e in OpenAICompatibleAdapter(config, client).stream("s", [], SPECS)]
    assert events[-1].type == "stop"
    payload = requests[0]
    if effort is None:
        assert "reasoning_effort" not in payload
    else:
        assert payload["reasoning_effort"] == effort
    assert payload["max_tokens"] == config.max_output_tokens
    assert len(payload["tools"]) == len(SPECS)


@pytest.mark.parametrize("effort", [False, 0, [], {}, "", "turbo"])
def test_invalid_reasoning_effort_is_rejected(effort):
    with pytest.raises(ValueError, match="reasoning_effort"):
        replace(resolve_model("local/fixture"), reasoning_effort=effort)


def test_anthropic_does_not_silently_ignore_a_compatibility_option():
    with pytest.raises(ValueError, match="OpenAI-compatible"):
        replace(resolve_model("anthropic/fixture"), reasoning_effort="none")


def test_reasoning_profile_roundtrips_through_yaml_and_gui_without_changing_defaults(tmp_path):
    selector = "ollama/qwen3.6:27b-mlx"
    assert resolve_model(selector).reasoning_effort is None
    path = tmp_path / "models.yaml"
    path.write_text(f'models:\n  {selector}:\n    reasoning_effort: "none"\n')
    assert resolve_model(selector, config_path=path).reasoning_effort == "none"
    config = Configuration(tmp_path, model=selector)
    config.update({"profiles": {selector: {"reasoning_effort": "none"}}})
    assert Configuration(tmp_path, model=selector).resolve().reasoning_effort == "none"
    config.update({"profiles": {selector: {"reasoning_effort": None}}})
    assert Configuration(tmp_path, model=selector).resolve().reasoning_effort is None


async def test_cli_reasoning_override_persists_on_resume_and_can_be_cleared(
    tmp_path, monkeypatch, capsys
):
    configs = []

    def create(config):
        configs.append(config)
        model = ScriptedModel([DONE])
        model.config = config
        model.name = config.name
        return model

    monkeypatch.setattr("smok.cli.create_adapter", create)
    flags = ["-C", str(tmp_path), "--json", "-p", "Hello"]
    for extra in (
        ["--model", "local/fixture", "--reasoning-effort", "none"],
        ["--continue"],
        ["--continue", "--reasoning-effort", "default"],
    ):
        assert await run_cli(parser().parse_args(flags + extra)) == 0
        capsys.readouterr()
    assert [c.reasoning_effort for c in configs] == ["none", "none", None]


async def test_unsupported_provider_setting_fails_without_retry_or_silent_fallback():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(400, text="private request details")

    config = replace(resolve_model("local/fixture"), reasoning_effort="none")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelError, match="HTTP 400") as failure:
            _ = [e async for e in OpenAICompatibleAdapter(config, client).stream("s", [], [])]
    assert len(requests) == 1 and "private" not in str(failure.value)


def test_eval_variant_records_reasoning_control_in_run_identity():
    config = resolve_model("local/fixture")
    tuned = replace(config, **VARIANTS["no-thinking"])
    assert tuned.reasoning_effort == "none" and config.reasoning_effort is None
    assert digest(profile_data(config)) != digest(profile_data(tuned))
