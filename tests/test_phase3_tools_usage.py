import json
import re
from dataclasses import replace

import httpx
import pytest
from test_adapters import FIXTURES
from test_loop import DONE, STOP, call
from test_phase2_tools import prepare
from test_phase3_sessions import configured

from smok.loop import Agent
from smok.models.anthropic import AnthropicAdapter
from smok.models.base import ModelError
from smok.models.openai_compat import OpenAICompatibleAdapter
from smok.models.profiles import resolve_model
from smok.outputs import CAPTURE_BYTES, OutputStore
from smok.repo_map import RepoMap
from smok.todos import validate_todos
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import SPECS, ToolRegistry
from smok.types import Event, Message, Text, messages_to_data
from smok.usage import BudgetExceeded, Ledger, RunBudget, cost


async def test_large_tool_result_is_retrievable_without_recursive_archiving(tmp_path):
    (tmp_path / "large.txt").write_text("prefix " * 4000 + "TAIL_SENTINEL")
    tools = ToolRegistry(Workspace(tmp_path))
    preview = await tools.execute(prepare(tools, "read_file", path="large.txt"))
    assert "TAIL_SENTINEL" not in preview
    identifier = re.search(r"saved: ([a-f0-9]{32})", preview)[1]
    page = await tools.execute(
        prepare(tools, "read_output", id=identifier, offset=18000, limit=12000)
    )
    assert "TAIL_SENTINEL" in page
    assert len(list((tmp_path / ".smok/outputs").glob("*.txt"))) == 1
    reopened = ToolRegistry(Workspace(tmp_path))
    assert "TAIL_SENTINEL" in await reopened.execute(
        prepare(reopened, "read_output", id=identifier, offset=28000, limit=1000)
    )
    with pytest.raises(ToolError):
        prepare(tools, "read_output", id=identifier, offset=-1)


async def test_large_failed_command_output_retains_tail(tmp_path):
    tools = ToolRegistry(Workspace(tmp_path))
    command = 'python3 -c \'print("x" * 20000 + "ERROR_TAIL"); raise SystemExit(3)\''
    with pytest.raises(ToolError) as error:
        await tools.execute(prepare(tools, "run_shell", command=command), approved=True)
    identifier = re.search(r"saved: ([a-f0-9]{32})", str(error.value))[1]
    assert "ERROR_TAIL" in tools.outputs.read(identifier, 19500, 1000)


def test_large_schema_error_is_archived_before_a_tool_can_execute(tmp_path):
    tools = ToolRegistry(Workspace(tmp_path))
    with pytest.raises(ToolError) as error:
        prepare(tools, "read_file", path=["x" * 16000, "BAD_ARGUMENT_TAIL"])
    identifier = re.search(r"saved: ([a-f0-9]{32})", str(error.value))[1]
    assert len(str(error.value)) < 12500
    assert "BAD_ARGUMENT_TAIL" in tools.outputs.read(identifier, 15800, 1000)
    assert not tools.workspace.read_hashes


def test_output_archive_caps_and_path_boundaries_are_explicit(tmp_path):
    store = OutputStore(tmp_path)
    identifier, capped = store.save("x" * (CAPTURE_BYTES + 50))
    assert capped and "remaining output is unavailable" in store.read(
        identifier, CAPTURE_BYTES, 200
    )
    with pytest.raises(ToolError, match="Invalid output ID"):
        store.read("../../private")
    path = tmp_path / ".smok/outputs" / (identifier + ".txt")
    assert path.stat().st_mode & 0o777 == 0o600
    path.unlink()
    path.symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="symlink"):
        store.read(identifier)


async def test_repo_map_parses_languages_ranks_terms_and_refreshes(tmp_path):
    (tmp_path / "a.py").write_text("class Example:\n    def compute(self):\n        return 2\n")
    (tmp_path / "b.ts").write_text("interface Account { id: number }\nfunction lookup() {}\n")
    (tmp_path / "c.js").write_text("export function render() { return 1; }\n")
    (tmp_path / "d.tsx").write_text("export const App = () => <div />;\n")
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "ignored.py").write_text("def hidden(): pass")
    (tmp_path / ".smok").mkdir()
    (tmp_path / ".smok/private.py").write_text("def private(): pass")
    (tmp_path / "link.py").symlink_to(tmp_path / "a.py")
    workspace = Workspace(tmp_path)
    repo_map = RepoMap(workspace)
    text = await repo_map.build("Account lookup")
    assert text.index("b.ts") < text.index("a.py")
    assert "1: interface Account" in text and "2: function compute" in text
    assert "function render" in text and "variable_declarator App" in text
    assert not any(name in text for name in ("hidden", "private.py", "link.py"))
    assert not workspace.read_hashes
    (tmp_path / "a.py").write_text("def renamed(): pass\n")
    text = await repo_map.build("renamed")
    assert "renamed" in text and "compute" not in text
    assert len(await repo_map.build(max_chars=150)) < 250


async def test_todos_update_in_plan_mode_without_file_permission(tmp_path):
    tools = ToolRegistry(Workspace(tmp_path), mode="plan")
    items = [{"id": "inspect", "text": "Inspect current API", "status": "in_progress"}]
    result = await tools.execute(prepare(tools, "write_todos", items=items))
    assert "Inspect current API" in result and tools.todos == items
    assert tools.revision == 0


@pytest.mark.parametrize(
    "items",
    [
        [{"id": "x", "text": "x", "status": "invalid"}],
        [{"id": "x", "text": "x", "status": "done"}] * 2,
        [{"id": str(i), "text": "x", "status": "in_progress"} for i in range(2)],
        [{"id": "x", "text": "", "status": "pending"}],
    ],
)
def test_invalid_todos_are_rejected(items):
    with pytest.raises(ValueError):
        validate_todos(items)


@pytest.mark.parametrize("budget", [RunBudget(tokens=10), RunBudget(dollars=0.000001)])
async def test_budget_stops_before_model_or_tool_execution(tmp_path, budget):
    model = configured([[call("write_file", {"path": "bad", "content": "x"}), STOP]])
    model.config = replace(model.config, local=False, prices={"input": 1, "output": 2})
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)), budget=budget)
    events = [e async for e in agent.run("Build")]
    assert events[-1].data["reason"] == "budget_limit"
    assert not model.histories and not (tmp_path / "bad").exists()


def test_explicit_prices_cache_accounting_and_local_zero_cost():
    config = replace(
        resolve_model("anthropic/fixture"),
        prices={"input": 2, "output": 8, "cache_read": 0.2, "cache_write": 2.5},
    )
    usage = {
        "input_tokens": 1000,
        "output_tokens": 100,
        "cache_read_input_tokens": 600,
        "cache_creation_input_tokens": 300,
        "source": "provider",
    }
    ledger = Ledger()
    ledger.record(config, usage)
    assert ledger.input_tokens == 1000 and ledger.known_cost_usd == pytest.approx(0.00187)
    assert cost(config, {"input_tokens": 1000, "output_tokens": 100}, reserve=True) == 0.0033
    assert cost(resolve_model("ollama/fixture"), usage) == 0
    assert cost(resolve_model("openai/fixture"), usage) is None
    with pytest.raises(BudgetExceeded, match="explicit prices"):
        RunBudget(dollars=1).check(resolve_model("openai/fixture"), 10)
    assert Ledger.restore(ledger.export()).export() == ledger.export()


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": -1, "output_tokens": 1},
        {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 20},
    ],
)
async def test_invalid_usage_reserves_allowance_and_blocks_pending_tools(tmp_path, usage):
    model = configured(
        [[call("write_file", {"path": "bad", "content": "x"}), Event("usage", usage), STOP]]
    )
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    events = [e async for e in agent.run("Build")]
    assert events[-1].data["reason"] == "error" and not (tmp_path / "bad").exists()
    assert agent.usage.requests == 1 and agent.usage.estimated_requests == 1
    assert agent.usage.output_tokens == model.config.max_output_tokens


async def test_disconnect_still_charges_reserved_tokens(tmp_path):
    model = configured([[ModelError("connection lost")]])
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    events = [e async for e in agent.run("Try")]
    assert events[-1].data["reason"] == "error"
    assert agent.usage.input_tokens > 0 and agent.usage.output_tokens == 4096
    assert agent.budget.usage.requests == 1


@pytest.mark.parametrize("count,expected", [(1234, "complete"), (40000, "error")])
async def test_provider_preflight_count_controls_context_gate(tmp_path, count, expected):
    model = configured([DONE])
    model.config = replace(model.config, count_tokens=True)
    counts = []

    async def count_input(system, messages, tools):
        counts.append((system, messages, tools))
        return count

    model.count_input = count_input
    agent = Agent(model, ToolRegistry(Workspace(tmp_path)))
    events = [e async for e in agent.run("Inspect")]
    assert len(counts) == 1 and events[-1].data["reason"] == expected
    if expected == "complete":
        data = next(e.data for e in events if e.type == "context_usage")
        assert data["source"] == "provider_count" and data["input_tokens"] == 1234
    else:
        assert not model.histories and not agent.usage.requests


async def test_anthropic_count_and_cache_breakpoints_preserve_history():
    requests = []
    config = resolve_model("anthropic/fixture")
    messages = [Message("user", [Text("Task")])]
    before = messages_to_data(messages)

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"input_tokens": 1234})

    config = replace(config, key_required=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AnthropicAdapter(config, client)
        assert await adapter.count_input("base\n\nRuntime context:\nmap", messages, SPECS) == 1234
    payload = requests[0]
    assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert payload["system"][0]["text"] == "base"
    assert "cache_control" not in payload["system"][1]
    assert payload["messages"][-1]["content"][-1]["cache_control"]["type"] == "ephemeral"
    assert messages_to_data(messages) == before and "stream" not in payload


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="private error"),
        httpx.Response(200, json={"input_tokens": -1}),
        httpx.Response(200, json={"input_tokens": True}),
        httpx.Response(200, json=[]),
    ],
)
async def test_invalid_token_counter_fails_without_exposing_body(response):
    config = replace(resolve_model("anthropic/fixture"), key_required=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(ModelError) as error:
            await AnthropicAdapter(config, client).count_input("s", [], [])
    assert "private error" not in str(error.value)


async def test_anthropic_stream_cache_totals_include_read_and_creation():
    raw = (
        (FIXTURES / "anthropic_tool.sse")
        .read_text()
        .replace(
            '"input_tokens":21',
            '"input_tokens":21,"cache_read_input_tokens":60,"cache_creation_input_tokens":30',
        )
    )
    config = replace(resolve_model("anthropic/fixture"), key_required=False)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=raw))
    ) as client:
        events = [e async for e in AnthropicAdapter(config, client).stream("s", [], [])]
    usage = next(e.data for e in events if e.type == "usage")
    assert usage["input_tokens"] == 111 and usage["output_tokens"] == 9


@pytest.mark.parametrize("details,expected", [(None, 0), ({"cached_tokens": 12}, 12)])
async def test_openai_cache_usage_and_nullable_details(details, expected):
    raw = (
        (FIXTURES / "openai_tool.sse")
        .read_text()
        .replace(
            '"prompt_tokens":21',
            '"prompt_tokens":21,"prompt_tokens_details":' + json.dumps(details),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=raw))
    ) as client:
        events = [
            e
            async for e in OpenAICompatibleAdapter(resolve_model("ollama/fixture"), client).stream(
                "s", [], []
            )
        ]
    usage = next(e.data for e in events if e.type == "usage")
    assert usage["input_tokens"] == 21 and usage["cache_read_input_tokens"] == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"context_window": 4000},
        {"max_output_tokens": True},
        {"compact_at": float("nan")},
        {"chars_per_token": 0},
        {"prices": {"input": -1}},
        {"local": "yes"},
    ],
)
def test_model_limits_are_validated(overrides):
    with pytest.raises(ValueError):
        replace(resolve_model("ollama/fixture"), **overrides)


@pytest.mark.parametrize(
    "overrides", [{"tokens": 0}, {"max_turns": 1.5}, {"dollars": float("nan")}, {"dollars": -1}]
)
def test_run_limits_are_validated(overrides):
    with pytest.raises(ValueError):
        RunBudget(**overrides)
