import json
from dataclasses import replace

import pytest
from test_loop import ScriptedModel

from smok.gui.config import Configuration
from smok.loop import Agent
from smok.models.profiles import resolve_model
from smok.permissions import allow
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry
from smok.types import ToolCall


def agent(root, **tuning):
    model = ScriptedModel([])
    model.config = replace(resolve_model("local/test"), repo_map_tokens=0, **tuning)
    model.name = model.config.name
    return Agent(model, ToolRegistry(Workspace(root)), approver=allow)


def call(name, **arguments):
    return ToolCall("test", name, json.dumps(arguments))


@pytest.mark.parametrize("field", ["prompt_style", "tool_set", "edit_format"])
@pytest.mark.parametrize("value", ["invalid", None, [], 1])
def test_profile_values_are_validated(field, value):
    with pytest.raises(ValueError, match=field):
        replace(resolve_model("local/test"), **{field: value})


def test_profile_cost_preview_and_worker_restrictions_intersect(tmp_path):
    active = agent(tmp_path)
    full = {s.name for s in active.tools.specs}
    target = replace(active.config, prompt_style="lean", tool_set="minimal")
    assert active.context_report(target)["input_tokens"] < active.context_report()["input_tokens"]
    assert {s.name for s in active.tools.specs} == full
    active.model.config = target
    assert "grep" not in {s.name for s in active.tools.specs}
    with pytest.raises(ToolError, match="tool set"):
        active.tools.prepare(call("grep", pattern="x"))
    active.tools.allowed_tools = {"read_file"}
    assert {s.name for s in active.tools.specs} == {"read_file"}
    with pytest.raises(ToolError, match="restricted tool set"):
        active.tools.prepare(call("write_file", path="new.py", content=""))
    active.tools.allowed_tools = None
    active.set_mode("plan")
    with pytest.raises(ToolError, match="Plan mode"):
        active.tools.prepare(call("run_shell", command="true"))


async def test_edit_formats_and_model_switch_revalidate_pending_changes(tmp_path):
    (tmp_path / "file.py").write_text("before\n")
    active = agent(tmp_path, edit_format="exact")
    active.tools.workspace.read_file("file.py")
    with pytest.raises(ToolError, match="exact edits"):
        active.tools.prepare(call("write_file", path="file.py", content="after\n"))
    create = active.tools.prepare(call("write_file", path="new.py", content="new\n"))
    await active.tools.execute(create, approved=True)
    edit = active.tools.prepare(
        call("edit_file", path="file.py", old_text="before", new_text="after")
    )
    active.model.config = replace(active.config, edit_format="whole_file")
    assert "edit_file" not in {s.name for s in active.tools.specs}
    assert "Prefer edit_file" not in active.base_system()
    with pytest.raises(ToolError, match="whole-file"):
        await active.tools.execute(edit, approved=True)
    write = active.tools.prepare(call("write_file", path="file.py", content="after\n"))
    active.model.config = replace(active.config, edit_format="exact")
    with pytest.raises(ToolError, match="exact edits"):
        await active.tools.execute(write, approved=True)
    assert (tmp_path / "file.py").read_text() == "before\n"
    active.model.config = replace(active.config, edit_format="both")
    await active.tools.execute(write, approved=True)
    assert (tmp_path / "file.py").read_text() == "after\n"
    await active.tools.close()


def test_gui_profiles_and_session_state_retain_tuning(tmp_path):
    config = Configuration(tmp_path)
    settings = config.update(
        {
            "profiles": {
                "local/test": {"prompt_style": "lean", "tool_set": "coding", "edit_format": "exact"}
            },
            "default_model": "local/test",
        }
    )
    selected = next(p for p in settings["models"] if p["name"] == "local/test")
    assert selected["prompt_style"] == "lean" and selected["tool_set"] == "coding"
    restored = Configuration(tmp_path).resolve()
    active = agent(tmp_path)
    active.model.config = restored
    saved = active.state()["context_settings"]
    assert (saved["prompt_style"], saved["tool_set"], saved["edit_format"]) == (
        "lean",
        "coding",
        "exact",
    )
    assert "edit_file" in {t.name for t in active.tools.specs}
    assert "web_fetch" not in {t.name for t in active.tools.specs}
