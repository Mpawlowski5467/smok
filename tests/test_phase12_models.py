import copy
import json
import sys
from dataclasses import asdict, replace

import pytest
import yaml

from evals import qualify, run, suite
from smok.models.profiles import resolve_model
from smok.process import capture

TASKS = suite.load_tasks("phase12")
SOLUTIONS = json.loads((suite.HERE / "phase12_solutions.json").read_text())
CHECK = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"]


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t["id"])
async def test_new_projects_have_failing_seeds_and_verified_references(task, tmp_path):
    suite.write_fixture(tmp_path, task["files"])
    assert (await capture(CHECK, tmp_path)).code != 0
    assert not (await suite.check_task(task, tmp_path))[0]
    suite.write_fixture(tmp_path, SOLUTIONS[task["id"]])
    public = await capture(CHECK, tmp_path)
    assert public.code == 0, public.output
    passed, output = await suite.check_task(task, tmp_path)
    assert passed, output
    assert suite.scope_check(task, tmp_path)["passed"]


def test_new_tasks_do_not_reuse_older_cases_or_expose_graders():
    older = {
        t["id"] for version in ("phase7", "phase10", "phase11") for t in suite.load_tasks(version)
    }
    assert len(TASKS) == 4 and set(SOLUTIONS).isdisjoint(older)
    for task in TASKS:
        assert task["split"] == "holdout"
        assert set(task["allowed_changes"]) == set(SOLUTIONS[task["id"]])
        assert task["verification_commands"] == task["shell_commands"]
        assert "tests/test_project.py" not in task["allowed_changes"]
        assert task["check_file"] not in task["files"]


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t["id"])
async def test_private_checks_reject_repairs_that_pass_public_checks(task, tmp_path):
    suite.write_fixture(tmp_path, task["files"])
    repairs = dict(SOLUTIONS[task["id"]])
    file, before, after = {
        "batch-renames": ("renames/operations.py", "deepcopy(value)", "value"),
        "byte-windows": ("windows/ranges.py", "max(0, size - count)", "size - count"),
        "event-replay": (
            "events/validation.py",
            "deepcopy(event['value'])",
            "event['value']",
        ),
        "command-arguments": (
            "arguments/lexing.py",
            "char in ' \\t\\r\\n'",
            "char.isspace()",
        ),
    }[task["id"]]
    assert before in repairs[file]
    repairs[file] = repairs[file].replace(before, after)
    suite.write_fixture(tmp_path, repairs)
    public = await capture(CHECK, tmp_path)
    assert public.code == 0, public.output
    assert not (await suite.check_task(task, tmp_path))[0]


async def test_event_grader_rejects_extra_value_in_normalized_deletions(tmp_path):
    task = next(t for t in TASKS if t["id"] == "event-replay")
    suite.write_fixture(tmp_path, task["files"])
    repairs = dict(SOLUTIONS[task["id"]])
    file = "events/validation.py"
    assert repairs[file].count("    return result\n") == 1
    repairs[file] = repairs[file].replace(
        "    return result\n",
        "    if action == 'delete':\n        result['value'] = None\n    return result\n",
    )
    suite.write_fixture(tmp_path, repairs)
    assert (await capture(CHECK, tmp_path)).code != 0
    passed, output = await suite.check_task(task, tmp_path)
    assert not passed and "delete normalization must omit value" in output


def matrix():
    profiles = {
        name: asdict(replace(resolve_model(name), **run.VARIANTS["focused-repair"]))
        for name in ("local/first", "local/second")
    }
    plan, rows = [], []
    for repeat in (1, 2):
        for task in TASKS:
            for name, profile in profiles.items():
                case = dict(task=task["id"], model=name, variant="focused-repair", repeat=repeat)
                identity = suite.digest(case)[:20]
                plan.append(dict(case, id=identity))
                rows.append(
                    dict(
                        case,
                        case_id=identity,
                        profile=profile,
                        task_fingerprint=task["fingerprint"],
                        split="holdout",
                        passed=True,
                        check_passed=True,
                        scope={"passed": True},
                        tool_checks_passed=True,
                        verification={"required": task["verification_commands"], "passed": True},
                        stop_reason="complete",
                        seconds=10 if name.endswith("first") else 8,
                        usage=dict(
                            requests=3, input_tokens=100, output_tokens=50, estimated_requests=0
                        ),
                    )
                )
    spec = dict(
        source="source-sha",
        suite="phase12",
        plan=plan,
        limits={"task_timeout": 300, "max_iterations": 16},
        tasks={t["id"]: t["fingerprint"] for t in TASKS},
        task_splits={t["id"]: t["split"] for t in TASKS},
        profiles=list(profiles.values()),
        profile_matrix=[
            dict(model=k, variant="focused-repair", profile=v) for k, v in profiles.items()
        ],
    )
    return dict(
        schema_version=2,
        spec=spec,
        source_fingerprint=spec["source"],
        fingerprint=suite.digest(spec),
        plan=plan,
        status="complete",
        results=rows,
        smok_version="0.12.0",
        attempts=[],
    )


def compare(report):
    return qualify.qualify(
        report,
        model="local/first",
        candidate_model="local/second",
        baseline_variant="focused-repair",
        candidate="focused-repair",
    )


def reseal(report):
    report["fingerprint"] = suite.digest(report["spec"])


def test_cross_model_same_variant_is_paired_and_exported_to_correct_model(tmp_path):
    result = compare(matrix())
    assert result["schema_version"] == 2 and result["comparison"] == "models"
    assert result["counts"] == {"both_pass": 8} and result["verdict"] == "candidate_supported"
    assert result["changed_controls"] == {}
    assert "local/second" in qualify.markdown(result)
    for selected, name in (("baseline", "local/first"), ("candidate", "local/second")):
        exported = qualify.profile_yaml(result, selected)
        data = yaml.safe_load(exported)
        assert set(data) == {"models"} and list(data["models"]) == [name]
        assert set(data["models"][name]) == set(qualify.PROFILE_FIELDS)
        path = tmp_path / (selected + ".yaml")
        path.write_text(exported)
        config = resolve_model(name, config_path=path)
        assert config.reasoning_effort == "none" and config.tool_set == "minimal"
        assert resolve_model(name).reasoning_effort is None
    with pytest.raises(ValueError):
        qualify.profile_yaml(result, "focused-repair")


@pytest.mark.parametrize("failure", ["correctness", "verification", "scope", "completion"])
def test_cross_model_failures_cannot_be_speed_wins(failure):
    report = matrix()
    row = report["results"][1]
    row["passed"] = False
    row["seconds"] = 0.001
    if failure == "correctness":
        row["check_passed"] = False
    elif failure == "verification":
        row["verification"]["passed"] = False
    elif failure == "scope":
        row["scope"]["passed"] = False
    else:
        row["stop_reason"] = "time_limit"
    result = compare(report)
    assert result["verdict"] == "tradeoff" and result["shared_pass_latency"]["pairs"] == 7
    assert result["counts"]["regression"] == 1


def test_cross_model_missing_and_unbalanced_coverage():
    report = matrix()
    report["results"].pop()
    report["status"] = "interrupted"
    result = compare(report)
    assert result["verdict"] == "incomplete" and len(result["missing_pairs"]) == 1
    report["plan"].pop()
    reseal(report)
    with pytest.raises(ValueError, match="same tasks and repeats"):
        compare(report)


def test_cross_model_differing_connections_disclosed_without_exporting_them():
    report = matrix()
    report["spec"]["profiles"][1]["base_url"] = "https://different.example/v1?secret=value"
    report["spec"]["profiles"][1]["api_key_env"] = "DIFFERENT_KEY"
    reseal(report)
    result = compare(report)
    assert result["connection_differences"] == ["api_key_env", "base_url"]
    rendered = qualify.markdown(result)
    assert "Other differing settings" in rendered and "secret=value" not in rendered
    assert "DIFFERENT_KEY" not in qualify.profile_yaml(result, "candidate")


def test_export_cannot_substitute_a_different_provider_model():
    report = matrix()
    report["spec"]["profiles"][1]["model"] = "first"
    reseal(report)
    with pytest.raises(ValueError, match="Provider model differs"):
        compare(report)


def test_cross_model_cli_explicit_selection_and_no_network(tmp_path, monkeypatch, capsys):
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network access"))
    report = tmp_path / "report.json"
    report.write_text(json.dumps(matrix()))
    flags = [
        str(report),
        "--model",
        "local/first",
        "--candidate-model",
        "local/second",
        "--baseline-variant",
        "focused-repair",
        "--candidate",
        "focused-repair",
        "--export-profile",
        str(tmp_path / "selected.yaml"),
        "--select",
        "candidate",
    ]
    assert qualify.main(flags) == 0
    capsys.readouterr()
    assert list(yaml.safe_load((tmp_path / "selected.yaml").read_text())["models"]) == [
        "local/second"
    ]
    assert qualify.main(flags) == 2
    with pytest.raises(SystemExit):
        qualify.main([str(report), "--candidate-model", "local/second"])


async def test_runner_alternates_models_and_requires_same_plan_on_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "HERE", tmp_path)
    rows = {(r["task"], r["model"], r["repeat"]): r for r in matrix()["results"]}
    calls = []

    async def fake(task, config, args, destination, *, budget):
        repeat = 1 + sum(t == task["id"] and m == config.name for t, m in calls)
        calls.append((task["id"], config.name))
        row = copy.deepcopy(rows[(task["id"], config.name, repeat)])
        row["profile"] = run.profile_data(config)
        row["iterations"] = 3
        row["usage"] = {**run.Ledger().export(), **row["usage"]}
        return row

    monkeypatch.setattr(run, "evaluate", fake)
    flags = [
        "--suite",
        "phase12",
        "--split",
        "holdout",
        "--model",
        "local/first",
        "--model",
        "local/second",
        "--variant",
        "focused-repair",
        "--repeats",
        "2",
        "--allow-tools",
        "--allow-shell",
    ]
    assert await run.main(flags) == 0
    path = next((tmp_path / "results").glob("*/report.json"))
    report = json.loads(path.read_text())
    assert compare(report)["planned_pairs"] == 8
    for index in range(0, 8, 2):
        pair = [c["model"] for c in report["plan"][index : index + 2]]
        repeated = [c["model"] for c in report["plan"][index + 8 : index + 10]]
        assert pair == list(reversed(repeated))
    assert [c["model"] for c in report["plan"][:4]] == [
        "local/first",
        "local/second",
        "local/second",
        "local/first",
    ]
    assert await run.main(flags + ["--resume", str(path.parent)]) == 0
    assert len(calls) == 16
    with pytest.raises(ValueError, match="unchanged"):
        await run.main(flags + ["--resume", str(path.parent), "--task-timeout", "301"])
