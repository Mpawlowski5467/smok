import copy
import json
from dataclasses import replace

import httpx
import pytest
import yaml
from test_adapters import FIXTURES
from test_loop import DONE, ScriptedModel
from test_phase11_qualification import report_fixture

from evals import qualify
from evals.run import profile_data
from evals.suite import digest
from smok.cli import parser, run_cli
from smok.gui.config import Configuration
from smok.models.openai_compat import OpenAICompatibleAdapter
from smok.models.profiles import resolve_model
from smok.tools.registry import SPECS


@pytest.mark.parametrize(
    "values", [{}, {"temperature": 0, "top_p": 0}, {"temperature": 1, "top_p": 0.95}]
)
async def test_sampling_controls_reach_wire_without_changing_other_controls(values):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text=(FIXTURES / "openai_tool.sse").read_text())

    config = replace(resolve_model("local/fixture"), **values)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        _ = [e async for e in OpenAICompatibleAdapter(config, client).stream("s", [], SPECS)]
    payload = requests[0]
    assert {k: payload[k] for k in ("temperature", "top_p") if k in payload} == values
    assert payload["max_tokens"] == 4096 and len(payload["tools"]) == len(SPECS)
    assert "reasoning_effort" not in payload


@pytest.mark.parametrize("name,upper", [("temperature", 2), ("top_p", 1)])
@pytest.mark.parametrize(
    "value", [False, [], {}, "0.5", float("nan"), float("inf"), -0.1, 2.1, 10**400]
)
def test_invalid_sampling_controls_fail_before_requests(name, upper, value):
    with pytest.raises(ValueError, match=name):
        replace(resolve_model("local/fixture"), **{name: value})
    with pytest.raises(ValueError, match=name):
        replace(resolve_model("local/fixture"), **{name: upper + 0.01})


@pytest.mark.parametrize("name", ["temperature", "top_p"])
def test_unsupported_adapter_rejects_sampling_override(name):
    with pytest.raises(ValueError, match="OpenAI-compatible"):
        replace(resolve_model("anthropic/fixture"), **{name: 0.5})


async def test_yaml_gui_and_cli_resume_retain_or_clear_sampling(tmp_path, monkeypatch, capsys):
    selector = "local/fixture"
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"models": {selector: {"temperature": 0, "top_p": 0.95}}}))
    configs = []

    def create(config):
        configs.append(config)
        model = ScriptedModel([DONE])
        model.config, model.name = config, config.name
        return model

    monkeypatch.setattr("smok.cli.create_adapter", create)
    flags = ["-C", str(tmp_path), "--json", "-p", "Hello"]
    for extra in (["--model", selector, "--config", str(path)], ["--continue"]):
        assert await run_cli(parser().parse_args(flags + extra)) == 0
        capsys.readouterr()
    assert [(c.temperature, c.top_p) for c in configs] == [(0, 0.95), (0, 0.95)]
    settings = Configuration(tmp_path, model=selector)
    settings.update({"profiles": {selector: {"temperature": 0, "top_p": 0.95}}})
    assert settings.resolve().temperature == 0 and settings.resolve().top_p == 0.95
    settings.update({"profiles": {selector: {"temperature": None, "top_p": None}}})
    assert settings.resolve().temperature is settings.resolve().top_p is None
    assert resolve_model(selector).temperature is resolve_model(selector).top_p is None


def test_qualification_preserves_legacy_reports_and_exports_tested_sampling(tmp_path):
    report = report_fixture()
    for profile in report["spec"]["profiles"]:
        profile.pop("temperature")
        profile.pop("top_p")
    report["fingerprint"] = digest(report["spec"])
    before = copy.deepcopy(report)
    result = qualify.qualify(report, model="local/fixture", candidate="no-thinking")
    assert report == before and result["profiles"]["no-thinking"]["top_p"] is None
    # Profile objects in this fixture are shared by the spec, matrix, and rows.
    candidate = report["spec"]["profiles"][1]
    candidate["temperature"], candidate["top_p"] = 1, 0.95
    report["fingerprint"] = digest(report["spec"])
    result = qualify.qualify(report, model="local/fixture", candidate="no-thinking")
    assert result["changed_controls"]["top_p"] == {"baseline": None, "candidate": 0.95}
    path = tmp_path / "selected.yaml"
    path.write_text(qualify.profile_yaml(result, "no-thinking"))
    selected = resolve_model("local/fixture", config_path=path)
    assert (selected.temperature, selected.top_p) == (1, 0.95)
    assert digest(profile_data(selected)) != digest(profile_data(resolve_model("local/fixture")))
