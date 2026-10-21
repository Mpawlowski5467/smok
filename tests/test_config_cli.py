import json

import pytest

from smok.cli import parser, run_cli, terminal_text
from smok.journal import Journal
from smok.models.profiles import resolve_model
from smok.types import Event


def test_provider_slash_preserves_namespaced_model():
    config = resolve_model("openrouter/team/coder")
    assert config.model == "team/coder"


def test_config_environment_and_custom_profile(tmp_path, monkeypatch):
    file = tmp_path / "models.yaml"
    file.write_text("models:\n  ollama/custom:\n    max_output_tokens: 8192\n")
    monkeypatch.setenv("SMOK_MODEL", "ollama/custom")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:9000/v1/")
    config = resolve_model(config_path=file)
    assert config.model == "custom" and config.max_output_tokens == 8192
    assert config.base_url == "http://localhost:9000/v1"


def test_missing_key_and_invalid_selector(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        resolve_model("anthropic/coder").api_key()
    with pytest.raises(ValueError, match="provider/model"):
        resolve_model("unknown")


@pytest.mark.parametrize(
    "content",
    [
        "providers: []",
        "models: {bad: 3}",
        "default_model: 4",
        "providers: {custom: {adapter: openai_compat}}\ndefault_model: custom/test",
    ],
)
def test_invalid_config_has_actionable_error(tmp_path, monkeypatch, content):
    monkeypatch.delenv("SMOK_MODEL", raising=False)
    file = tmp_path / "invalid.yaml"
    file.write_text(content)
    with pytest.raises(ValueError):
        resolve_model(config_path=file)


def test_journal_jsonl_and_permissions(tmp_path):
    journal = Journal(tmp_path)
    journal.write(Event("text_delta", {"text": "hello\nworld"}))
    journal.close()
    lines = journal.path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["data"]["text"] == "hello\nworld"
    assert journal.path.stat().st_mode & 0o777 == 0o600


def test_terminal_control_sequences_are_not_executed():
    assert terminal_text("hi\x1b[31m red\x1b[0m\x1b]52;c;bad\x07\n") == "hi red\n"


async def test_cli_json_events_and_default_denial(tmp_path, monkeypatch, capsys):
    from test_loop import DONE, STOP, ScriptedModel, call

    model = ScriptedModel([[call("write_file", {"path": "a", "content": "x"}), STOP], DONE])
    monkeypatch.setattr("smok.cli.create_adapter", lambda _: model)
    args = parser().parse_args(["-C", str(tmp_path), "--json", "-p", "Do it"])
    assert await run_cli(args) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]["type"] == "turn_started"
    assert any(e["type"] == "permission_resolved" and not e["data"]["approved"] for e in events)
    assert not (tmp_path / "a").exists()


async def test_cli_explicit_approval(tmp_path, monkeypatch, capsys):
    from test_loop import DONE, STOP, ScriptedModel, call

    model = ScriptedModel([[call("write_file", {"path": "a", "content": "x"}), STOP], DONE, DONE])
    monkeypatch.setattr("smok.cli.create_adapter", lambda _: model)
    args = parser().parse_args(["-C", str(tmp_path), "--yes", "--json", "-p", "Do it"])
    assert await run_cli(args) == 0
    assert (tmp_path / "a").read_text() == "x"


async def test_cli_iteration_limit_is_nonzero(tmp_path, monkeypatch, capsys):
    from test_loop import STOP, ScriptedModel, call

    monkeypatch.setattr(
        "smok.cli.create_adapter",
        lambda _: ScriptedModel(
            [
                [call("list_dir", {}), STOP],
            ]
        ),
    )
    args = parser().parse_args(["-C", str(tmp_path), "--json", "--max-iterations", "1", "-p", "Go"])
    assert await run_cli(args) == 2


@pytest.mark.parametrize(
    "arguments", [["--json"], ["--yes", "--no-input"], ["--max-iterations", "0"]]
)
async def test_invalid_cli_modes_fail_early(arguments):
    with pytest.raises(ValueError):
        await run_cli(parser().parse_args(arguments))


async def test_switching_provider_does_not_reuse_endpoint_override(tmp_path, monkeypatch, capsys):
    from test_loop import ScriptedModel

    commands = iter(["/model openai/test-model", "/exit"])
    configs = []

    class Input:
        def __init__(self, **kwargs):
            pass

        async def prompt_async(self, *args, **kwargs):
            return next(commands)

    def create(config):
        configs.append(config)
        return ScriptedModel([])

    monkeypatch.setattr("smok.cli.PromptSession", Input)
    monkeypatch.setattr("smok.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("smok.cli.create_adapter", create)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    args = parser().parse_args(
        [
            "-C",
            str(tmp_path),
            "--model",
            "ollama/test-model",
            "--base-url",
            "http://127.0.0.1:9000/v1",
        ]
    )
    assert await run_cli(args) == 0
    assert configs[0].base_url == "http://127.0.0.1:9000/v1"
    assert configs[1].base_url == "https://api.openai.com/v1"
