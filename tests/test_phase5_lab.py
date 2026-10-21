import asyncio
import json
import shlex
import sys
from pathlib import Path

import pytest
from test_loop import DONE, STOP, call
from test_phase5_team import model, setup

from smok.checkpoints import Checkpoints
from smok.journal import Journal
from smok.team.lab import accept, council, replay, replay_source
from smok.team.worktrees import Worktrees, git, snapshot
from smok.tools.files import ToolError
from smok.types import Event


def repository(root):
    git(root, "init", "-q")
    (root / ".gitignore").write_text(".smok/\n*.secret\n")
    (root / "calc.py").write_text("answer = 0\n")
    commit, _ = snapshot(root)
    git(root, "update-ref", "HEAD", commit)
    git(root, "reset", "--mixed", "HEAD")
    return commit


def editing(name, number):
    return model(
        name,
        [
            [call("read_file", {"path": "calc.py"}), STOP],
            [call("write_file", {"path": "calc.py", "content": f"answer = {number}\n"}), STOP],
            DONE,
            DONE,
        ],
    )


async def test_snapshot_preserves_index_head_dirty_and_untracked_files(tmp_path):
    baseline = repository(tmp_path)
    (tmp_path / "calc.py").write_text("answer = 1\n")
    git(tmp_path, "add", "calc.py")
    (tmp_path / "calc.py").write_text("answer = 2\n")
    (tmp_path / "new.txt").write_text("untracked")
    (tmp_path / "hidden.secret").write_text("do not copy")
    index = (tmp_path / ".git/index").read_bytes()
    snap, _ = snapshot(tmp_path)
    worktrees = Worktrees(tmp_path)
    path = worktrees.create("candidate", snap)
    assert (path / "calc.py").read_text() == "answer = 2\n"
    assert (path / "new.txt").read_text() == "untracked"
    assert not (path / "hidden.secret").exists()
    assert not (path / ".smok").exists()
    assert (tmp_path / ".git/index").read_bytes() == index
    assert git(tmp_path, "rev-parse", "HEAD").decode().strip() == baseline
    worktrees.remove(path)


async def test_council_selects_passing_candidate_and_accept_guards_changes(tmp_path):
    repository(tmp_path)
    index = (tmp_path / ".git/index").read_bytes()
    agent, team = setup(
        tmp_path,
        full_auto=True,
        factory=lambda c: editing(c.name, 42 if c.name == "local/good" else 7),
    )
    agent.checkpoints = Checkpoints(tmp_path)
    check = shlex.join([sys.executable, "-c", "from calc import answer; assert answer == 42"])
    events = [
        e async for e in council(team, "Set the answer", ["local/good", "local/bad"], check=check)
    ]
    report = next(e.data for e in events if e.type == "council_finished")
    assert report["selected"] == 0
    assert report["candidates"][0]["check"]["ok"]
    assert not report["candidates"][1]["check"]["ok"]
    assert (tmp_path / "calc.py").read_text() == "answer = 0\n"
    assert (tmp_path / ".git/index").read_bytes() == index
    (tmp_path / "new.txt").write_text("new work")
    with pytest.raises(ToolError, match="changed since"):
        await accept(team, report["id"], 0)
    (tmp_path / "new.txt").unlink()
    await accept(team, report["id"], 0)
    assert (tmp_path / "calc.py").read_text() == "answer = 42\n"
    assert (tmp_path / ".git/index").read_bytes() == index
    await agent.undo()
    assert (tmp_path / "calc.py").read_text() == "answer = 0\n"
    await agent.tools.close()


async def test_judge_cannot_choose_a_failed_candidate(tmp_path):
    repository(tmp_path)

    def factory(c):
        if c.name == "local/judge":
            return model(
                c.name,
                [
                    [
                        Event("text_delta", {"text": '{"candidate":1}'}),
                        Event("stop", {"reason": "stop"}),
                    ]
                ],
            )
        return editing(c.name, 42 if c.name == "local/good" else 0)

    agent, team = setup(tmp_path, full_auto=True, factory=factory)
    check = shlex.join([sys.executable, "-c", "from calc import answer; assert answer == 42"])
    report = [
        e.data
        async for e in council(
            team, "Fix", ["local/good", "local/bad"], check=check, judge="local/judge"
        )
        if e.type == "council_finished"
    ][0]
    assert report["selected"] == 0 and report["judge"]["selection_error"]
    await agent.tools.close()


async def test_edit_delegation_returns_patch_in_isolated_worktree(tmp_path):
    repository(tmp_path)
    agent, team = setup(tmp_path, full_auto=True, factory=lambda c: editing(c.name, 17))
    report = json.loads(
        await team.execute("delegate", {"tasks": [{"role": "edit", "task": "Make 17"}]})
    )
    worker = report["workers"][0]
    assert worker["reason"] == "complete"
    assert (
        await asyncio.to_thread((Path(worker["workspace"]) / "calc.py").read_text)
        == "answer = 17\n"
    )
    patch = Path(worker["patch"])
    assert "+answer = 17" in await asyncio.to_thread(patch.read_text)
    assert (tmp_path / "calc.py").read_text() == "answer = 0\n"
    await agent.tools.close()


async def test_shadow_reads_snapshot_and_reports_heuristic_without_main_edits(tmp_path):
    repository(tmp_path)
    primary = model("frontier/main", local=False)
    agent, team = setup(tmp_path, primary=primary, settings={"shadow_model": "local/shadow"})
    events = [e async for e in agent.run("Explain calc")]
    report = next(e.data for e in events if e.type == "shadow_finished")
    assert report["eligible"] and report["score"]["exact_match"]
    assert "not a correctness" in report["score"]["basis"]
    shadow_path = Path(report["local"]["workspace"])
    assert not await asyncio.to_thread(shadow_path.exists)
    assert (tmp_path / "calc.py").read_text() == "answer = 0\n"
    assert agent.budget.usage.requests == 2
    await agent.tools.close()


async def test_replay_uses_only_tasks_not_saved_tool_calls_or_grants(tmp_path):
    baseline = repository(tmp_path)
    journal = Journal(tmp_path)
    journal.write(Event("replay_snapshot", {"commit": baseline}))
    journal.write(Event("task_started", {"prompt": "Set answer to 23", "mode": "build"}))
    journal.write(
        Event("tool_call", {"name": "run_shell", "arguments": '{"command":"touch forbidden"}'})
    )
    journal.write(Event("permission_resolved", {"approved": True}))
    journal.close()
    seen = []

    def factory(c):
        result = editing(c.name, 23)
        seen.append(result)
        return result

    agent, team = setup(tmp_path, full_auto=True, factory=factory)
    events = [e async for e in replay(team, journal.id, system="Additional replay experiment.")]
    result = next(e.data for e in events if e.type == "replay_finished")
    assert result["tasks"] == 1 and result["result"]["reason"] == "complete"
    assert seen[0].histories[0][0].content[0].text == "Set answer to 23"
    assert not (tmp_path / "forbidden").exists()
    assert not (Path(result["result"]["workspace"]) / "forbidden").exists()
    assert (tmp_path / "calc.py").read_text() == "answer = 0\n"
    await agent.tools.close()


async def test_legacy_replay_requires_explicit_starting_revision(tmp_path):
    repository(tmp_path)
    journal = Journal(tmp_path)
    journal.write(Event("turn_started", {"prompt": "Task"}))
    journal.close()
    assert replay_source(tmp_path, journal.id)[0] == ["Task"]
    agent, team = setup(tmp_path)
    with pytest.raises(ValueError, match="no initial snapshot"):
        _ = [e async for e in replay(team, journal.id)]
    await agent.tools.close()


async def test_council_cancellation_cleans_inflight_budget_and_keeps_candidate(tmp_path):
    repository(tmp_path)
    started = asyncio.Event()

    class Waiting:
        def __init__(self, cfg):
            self.name, self.config = cfg.name, cfg

        async def stream(self, system, messages, tools):
            started.set()
            await asyncio.Event().wait()
            yield

    agent, team = setup(tmp_path, factory=Waiting)

    async def run():
        return [e async for e in council(team, "Wait", ["local/a", "local/b"], check="true")]

    pending = asyncio.create_task(run())
    await asyncio.wait_for(started.wait(), 5)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not agent.budget.reservations
    assert agent.budget.usage.requests >= 1
    await agent.tools.close()


def test_snapshot_and_checkout_never_execute_git_filters(tmp_path):
    repository(tmp_path)
    (tmp_path / ".gitattributes").write_text("*.py filter=surprise\n")
    git(tmp_path, "config", "filter.surprise.clean", "touch filter-ran; cat")
    git(tmp_path, "config", "filter.surprise.smudge", "touch filter-ran; cat")
    git(tmp_path, "config", "filter.surprise.required", "true")
    commit, _ = snapshot(tmp_path)
    trees = Worktrees(tmp_path)
    path = trees.create("candidate", commit)
    assert not (tmp_path / "filter-ran").exists()
    assert not (path / "filter-ran").exists()
    assert (path / "calc.py").read_text() == "answer = 0\n"
    trees.remove(path)


def test_snapshot_includes_staged_deletion_and_tracked_ignored_files(tmp_path):
    repository(tmp_path)
    (tmp_path / "important.secret").write_text("tracked")
    git(tmp_path, "add", "-f", "important.secret")
    commit, _ = snapshot(tmp_path)
    git(tmp_path, "update-ref", "HEAD", commit)
    git(tmp_path, "reset", "--mixed", "HEAD")
    git(tmp_path, "rm", "calc.py")
    commit, _ = snapshot(tmp_path)
    trees = Worktrees(tmp_path)
    path = trees.create("candidate", commit)
    assert not (path / "calc.py").exists()
    assert (path / "important.secret").read_text() == "tracked"
    trees.remove(path)


def test_mixed_legacy_log_keeps_all_prompts_and_needs_explicit_base(tmp_path):
    base = repository(tmp_path)
    journal = Journal(tmp_path)
    journal.write(Event("turn_started", {"prompt": "Older task"}))
    journal.write(Event("turn_started", {"prompt": "New task", "internal": False}))
    journal.write(Event("replay_snapshot", {"commit": base}))
    journal.write(Event("task_started", {"prompt": "New task"}))
    journal.close()
    tasks, saved_base, _ = replay_source(tmp_path, journal.id)
    assert tasks == ["Older task", "New task"] and saved_base is None


async def test_worker_diff_is_visible_before_permission_request(tmp_path):
    repository(tmp_path)
    events = []
    agent, team = setup(tmp_path, factory=lambda c: editing(c.name, 17))
    team.emit = events.append
    report = json.loads(
        await team.execute("delegate", {"tasks": [{"role": "edit", "task": "Fix"}]})
    )
    assert report["workers"][0]["denied"]
    diff = next(e for e in events if e.type == "diff")
    permission = next(e for e in events if e.type == "permission_requested")
    assert events.index(diff) < events.index(permission)
    assert diff.data["workspace"] != str(tmp_path)
    assert permission.data["workspace"] == diff.data["workspace"]
    assert "+answer = 17" in permission.data["diff"]
    assert (tmp_path / "calc.py").read_text() == "answer = 0\n"
    await agent.tools.close()
