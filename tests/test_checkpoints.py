import asyncio
import os
import subprocess

import pytest
from test_loop import DONE, STOP, ScriptedModel, call

from smok.checkpoints import Checkpoints
from smok.loop import Agent
from smok.permissions import allow
from smok.tools.files import ToolError, Workspace
from smok.tools.registry import ToolRegistry


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout


def init_repo(root):
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")


def test_undo_preserves_dirty_staged_files_head_and_index(tmp_path):
    init_repo(tmp_path)
    file = tmp_path / "a"
    file.write_text("committed\n")
    git(tmp_path, "add", "a")
    git(tmp_path, "commit", "-qm", "baseline")
    file.write_text("staged\n")
    git(tmp_path, "add", "a")
    file.write_text("user dirty work\n")
    head = git(tmp_path, "rev-parse", "HEAD")
    index = (tmp_path / ".git/index").read_bytes()
    checkpoints = Checkpoints(tmp_path)
    assert checkpoints.begin() == 1
    file.write_text("agent change\n")
    (tmp_path / "new").write_text("created by agent")
    signature, diff, paths = checkpoints.review()
    assert signature and set(paths) == {"a", "new"}
    assert "-user dirty work" in diff and "+agent change" in diff
    record = checkpoints.finish()
    assert set(record["changes"]) == {"a", "new"}
    assert (tmp_path / ".git/index").read_bytes() == index
    assert git(tmp_path, "rev-parse", "HEAD") == head
    (tmp_path / "unrelated").write_text("user added after turn")
    checkpoints.undo()
    assert file.read_text() == "user dirty work\n"
    assert not (tmp_path / "new").exists()
    assert (tmp_path / "unrelated").read_text() == "user added after turn"
    assert (tmp_path / ".git/index").read_bytes() == index
    assert git(tmp_path, "rev-parse", "HEAD") == head
    assert checkpoints.list()[0]["undone"]


def test_non_git_workspace_handles_deleted_files_modes_symlinks_and_multiple_undos(tmp_path):
    file = tmp_path / "script"
    file.write_text("original")
    file.chmod(0o755)
    (tmp_path / "link").symlink_to("script")
    checkpoints = Checkpoints(tmp_path)
    checkpoints.begin()
    file.unlink()
    (tmp_path / "link").unlink()
    (tmp_path / "link").write_text("replaced link")
    checkpoints.finish()
    checkpoints.begin()
    (tmp_path / "second").write_text("second turn")
    checkpoints.finish()
    assert checkpoints.undo()["id"] == 2
    assert not (tmp_path / "second").exists()
    assert checkpoints.undo()["id"] == 1
    assert file.read_text() == "original"
    assert file.stat().st_mode & 0o777 == 0o755
    assert os.readlink(tmp_path / "link") == "script"
    with pytest.raises(ToolError, match="No completed changes"):
        checkpoints.undo()


def test_undo_preflights_all_files_before_restoring_any(tmp_path):
    for name in ["a", "z"]:
        (tmp_path / name).write_text("original")
    checkpoints = Checkpoints(tmp_path)
    checkpoints.begin()
    for name in ["a", "z"]:
        (tmp_path / name).write_text("agent")
    checkpoints.finish()
    (tmp_path / "z").write_text("later user edit")
    with pytest.raises(ToolError, match="files changed since"):
        checkpoints.undo()
    assert (tmp_path / "a").read_text() == "agent"
    assert (tmp_path / "z").read_text() == "later user edit"
    assert not checkpoints.list()[0]["undone"]


def test_shadow_git_respects_ignore_and_excludes_metadata(tmp_path):
    (tmp_path / ".gitignore").write_text("ignored\n")
    (tmp_path / "ignored").write_text("not included")
    checkpoints = Checkpoints(tmp_path)
    checkpoints.begin()
    assert set(checkpoints.pending["before"]["entries"]) == {".gitignore"}
    (tmp_path / "ignored").write_text("still excluded")
    assert checkpoints.finish()["changes"] == []


def test_checkpoint_subdirectory_never_captures_parent_repo_files(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "outside").write_text("outside")
    git(tmp_path, "add", "outside")
    root = tmp_path / "subdir"
    root.mkdir()
    (root / "inside").write_text("inside")
    git(tmp_path, "add", "subdir/inside")
    checkpoints = Checkpoints(root)
    checkpoints.begin()
    assert set(checkpoints.pending["before"]["entries"]) == {"inside"}
    (root / "inside").write_text("changed")
    checkpoints.finish()
    checkpoints.undo()
    assert (root / "inside").read_text() == "inside"


def test_workspace_lock_and_abandoned_checkpoint(tmp_path):
    first, second = Checkpoints(tmp_path), Checkpoints(tmp_path)
    first.begin()
    with pytest.raises(ToolError, match="Another Smok turn"):
        second.begin()
    first._release()  # simulate process exit without a final boundary
    with pytest.raises(ToolError, match="no end snapshot"):
        second.undo()
    second.begin()
    assert second.history[0]["abandoned"]
    second.finish()
    assert second.lock is None


def test_restore_rejects_replaced_parent_symlink(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/a").write_text("original")
    checkpoints = Checkpoints(root)
    checkpoints.begin()
    (root / "src/a").write_text("agent")
    checkpoints.finish()
    (root / "src").rename(tmp_path / "moved")
    (root / "src").symlink_to(tmp_path / "moved")
    with pytest.raises(ToolError, match="escapes|symlink"):
        checkpoints.undo()
    assert (tmp_path / "moved/a").read_text() == "agent"


async def test_cancelled_turn_finishes_checkpoint_and_is_undoable(tmp_path):
    started = asyncio.Event()

    class Model:
        name = "fixture/cancel"

        async def stream(self, system, messages, tools):
            if len(messages) == 1:
                yield call("write_file", {"path": "a", "content": "new"})
                yield STOP
            else:
                started.set()
                await asyncio.Event().wait()

    checkpoints = Checkpoints(tmp_path)
    agent = Agent(
        Model(), ToolRegistry(Workspace(tmp_path)), checkpoints=checkpoints, approver=allow
    )

    async def consume():
        return [e async for e in agent.run("write and wait")]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not agent.running and checkpoints.lock is None
    assert checkpoints.list()[0]["changes"] == ["a"]
    event = await agent.undo()
    assert event.type == "checkpoint_restored" and not (tmp_path / "a").exists()


async def test_self_check_uses_actual_changes_and_repeats_after_further_edits(tmp_path):
    model = ScriptedModel(
        [
            [call("write_file", {"path": "a", "content": "first"}), STOP],
            [call("read_file", {"path": "a"}), STOP],
            [call("run_shell", {"command": "cat a"}), STOP],
            [call("edit_file", {"path": "a", "old_text": "first", "new_text": "fixed"}), STOP],
            [call("run_shell", {"command": "cat a"}), STOP],
            DONE,
        ]
    )
    agent = Agent(
        model, ToolRegistry(Workspace(tmp_path)), checkpoints=Checkpoints(tmp_path), approver=allow
    )
    events = [e async for e in agent.run("Implement")]
    assert sum(e.type == "self_check_started" for e in events) == 2
    reviews = [
        m.content[0].text
        for m in agent.messages
        if m.role == "user"
        and hasattr(m.content[0], "text")
        and "recorded command results" in m.content[0].text
    ]
    assert len(reviews) == 1 and "+fixed" in reviews[0] and "+first" not in reviews[0]
    first_reviews = [
        b.text
        for m in model.histories[3]
        for b in m.content
        if getattr(b, "text", "").startswith("Review this diff")
    ]
    assert len(first_reviews) == 1 and "+first" in first_reviews[0]
    assert events[-1].data["reason"] == "complete"
    assert events[-2].type == "checkpoint_finished"
    assert (tmp_path / "a").read_text() == "fixed"


async def test_self_check_includes_shell_changes_and_failed_checks(tmp_path):
    model = ScriptedModel(
        [
            [call("run_shell", {"command": "printf new > a; exit 7"}), STOP],
            DONE,
            DONE,
        ]
    )
    agent = Agent(
        model, ToolRegistry(Workspace(tmp_path)), checkpoints=Checkpoints(tmp_path), approver=allow
    )
    events = [e async for e in agent.run("Implement")]
    review = next(e for e in events if e.type == "self_check_started")
    assert review.data["paths"] == ["a"]
    assert not review.data["checks"][0]["ok"]
    assert "Exit code: 7" in review.data["checks"][0]["output"]


async def test_self_check_skips_unchanged_turns_and_respects_iteration_limit(tmp_path):
    agent = Agent(
        ScriptedModel([DONE]), ToolRegistry(Workspace(tmp_path)), checkpoints=Checkpoints(tmp_path)
    )
    events = [e async for e in agent.run("Explain")]
    assert not any(e.type == "self_check_started" for e in events)
    agent.model = ScriptedModel([[call("write_file", {"path": "a", "content": "new"}), STOP], DONE])
    agent.approver = allow
    agent.max_iterations = 2
    events = [e async for e in agent.run("Implement")]
    assert events[-1].data["reason"] == "iteration_limit"
    assert any(e.type == "self_check_started" for e in events)
    assert agent.checkpoints.lock is None
    agent.model = ScriptedModel([[call("write_file", {"path": "b", "content": "new"}), STOP]])
    agent.max_iterations = 1
    events = [e async for e in agent.run("Another edit")]
    assert events[-1].data["reason"] == "iteration_limit"
    assert agent.checkpoints.lock is None


def test_changed_ignore_rule_does_not_hide_previously_snapshotted_file(tmp_path):
    (tmp_path / "a").write_text("before")
    checkpoints = Checkpoints(tmp_path)
    checkpoints.begin()
    (tmp_path / ".gitignore").write_text("a\n")
    (tmp_path / "a").write_text("after")
    record = checkpoints.finish()
    assert set(record["changes"]) == {".gitignore", "a"}
    checkpoints.undo()
    assert (tmp_path / "a").read_text() == "before"
    assert not (tmp_path / ".gitignore").exists()
