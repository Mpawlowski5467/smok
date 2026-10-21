import copy
import json
import sys
from dataclasses import asdict, replace

import pytest
import yaml

from evals import qualify, run, suite
from smok.models.profiles import resolve_model
from smok.process import capture

TASKS = suite.load_tasks("phase11")
SOLUTIONS = json.loads((suite.HERE / "phase11_solutions.json").read_text())


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t["id"])
async def test_fresh_seeds_fail_and_references_pass_public_and_independent_checks(task, tmp_path):
    suite.write_fixture(tmp_path, task["files"])
    command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"]
    assert (await capture(command, tmp_path)).code != 0
    assert not (await suite.check_task(task, tmp_path))[0]
    suite.write_fixture(tmp_path, SOLUTIONS[task["id"]])
    result = await capture(command, tmp_path)
    assert result.code == 0, result.output
    passed, output = await suite.check_task(task, tmp_path)
    assert passed, output
    assert suite.scope_check(task, tmp_path)["passed"]


def test_fresh_suite_contract_and_separation():
    existing = {t["id"] for version in ("phase7", "phase10") for t in suite.load_tasks(version)}
    assert len(TASKS) == 4 and {t["id"] for t in TASKS} == set(SOLUTIONS)
    assert not existing & set(SOLUTIONS)
    for task in TASKS:
        assert task["split"] == "holdout"
        assert task["verification_commands"] == task["shell_commands"]
        assert set(task["allowed_changes"]) == set(SOLUTIONS[task["id"]])
        assert "tests/test_project.py" not in task["allowed_changes"]
        assert task["check_file"] not in task["files"]
        assert not any("reference" in name or "grader" in name for name in task["files"])


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task["id"])
async def test_independent_checks_reject_plausible_repairs_passing_public_tests(task, tmp_path):
    suite.write_fixture(tmp_path, task["files"])
    repairs = dict(SOLUTIONS[task["id"]])
    if task["id"] == "stock-reservations":
        repairs["stock/orders.py"] = repairs["stock/orders.py"].replace(
            "type(count) is not int", "not isinstance(count, int)"
        )
    elif task["id"] == "document-splices":
        repairs["splices/core.py"] = repairs["splices/core.py"].replace("    spans.sort()\n", "")
    elif task["id"] == "release-selection":
        repairs["releases/catalog.py"] = repairs["releases/catalog.py"].replace(
            "rc if rc is not None else 0", "0"
        )
    else:
        repairs["tables/indexing.py"] = repairs["tables/indexing.py"].replace(
            " or isinstance(value, bool)", ""
        )
    assert repairs != SOLUTIONS[task["id"]]
    suite.write_fixture(tmp_path, repairs)
    public = await capture(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"], tmp_path
    )
    assert public.code == 0, public.output
    assert not (await suite.check_task(task, tmp_path))[0]


def report_fixture(tasks=3, repeats=2):
    model = resolve_model("local/fixture")
    configs = {
        "baseline": asdict(model),
        "no-thinking": asdict(replace(model, reasoning_effort="none")),
    }
    plan, results = [], []
    for repeat in range(1, repeats + 1):
        for task in range(tasks):
            for variant, profile in configs.items():
                case = {
                    "task": f"project-{task}",
                    "model": model.name,
                    "variant": variant,
                    "repeat": repeat,
                }
                identity = suite.digest(case)[:20]
                plan.append({**case, "id": identity})
                results.append(
                    {
                        **case,
                        "case_id": identity,
                        "profile": profile,
                        "task_fingerprint": suite.digest(task),
                        "split": "holdout",
                        "passed": True,
                        "check_passed": True,
                        "scope": {"passed": True},
                        "tool_checks_passed": True,
                        "verification": {"required": ["python3 checks.py"], "passed": True},
                        "stop_reason": "complete",
                        "seconds": 10 if variant == "baseline" else 8,
                        "usage": {
                            "requests": 4,
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "estimated_requests": 0,
                        },
                    }
                )
    spec = {
        "source": "source-sha",
        "suite": "phase11",
        "tasks": {f"project-{i}": suite.digest(i) for i in range(tasks)},
        "task_splits": {f"project-{i}": "holdout" for i in range(tasks)},
        "plan": plan,
        "limits": {"task_timeout": 300, "max_iterations": 16},
        "profiles": list(configs.values()),
        "profile_matrix": [
            {"model": model.name, "variant": v, "profile": p} for v, p in configs.items()
        ],
    }
    return {
        "schema_version": 2,
        "spec": spec,
        "source_fingerprint": spec["source"],
        "fingerprint": suite.digest(spec),
        "plan": plan,
        "status": "complete",
        "results": results,
        "smok_version": "0.11.0",
        "attempts": [],
    }


def reseal(report):
    report["fingerprint"] = suite.digest(report["spec"])


def fail(row, *, code=True, verify=True, stop="time_limit"):
    row.update(passed=False, check_passed=code, stop_reason=stop)
    row["verification"]["passed"] = verify


def test_repeated_comparison_and_runtime_only_profile_export(tmp_path):
    report = report_fixture()
    result = qualify.qualify(report)
    assert result["verdict"] == "candidate_supported" and result["paired_cases"] == 6
    assert result["shared_pass_latency"]["median_candidate_time_reduction_percent"] == 20
    assert result["changed_controls"] == {
        "reasoning_effort": {"baseline": None, "candidate": "none"}
    }
    assert "6/6" in qualify.markdown(result)
    profile = yaml.safe_load(qualify.profile_yaml(result, "no-thinking"))
    assert set(profile) == {"models"} and set(profile["models"]) == {"local/fixture"}
    assert not {"base_url", "api_key_env", "prices", "default_model"} & set(
        profile["models"]["local/fixture"]
    )
    path = tmp_path / "profile.yaml"
    path.write_text(qualify.profile_yaml(result, "no-thinking"))
    config = resolve_model("local/fixture", config_path=path)
    assert config.reasoning_effort == "none" and config.max_output_tokens == 4096
    assert resolve_model("local/fixture").reasoning_effort is None
    assert (
        yaml.safe_load(qualify.profile_yaml(result, "baseline"))["models"]["local/fixture"][
            "reasoning_effort"
        ]
        is None
    )


@pytest.mark.parametrize("failure", ["code", "verification", "completion", "scope"])
def test_candidate_regressions_are_never_hidden_by_timing(failure):
    report = report_fixture()
    row = report["results"][1]
    fail(
        row,
        code=failure != "code",
        verify=failure != "verification",
        stop="complete" if failure != "completion" else "time_limit",
    )
    if failure == "scope":
        row["scope"]["passed"] = False
    row["seconds"] = 0.5
    result = qualify.qualify(report)
    assert result["verdict"] == "tradeoff"
    assert result["counts"]["regression"] == 1
    assert result["shared_pass_latency"]["pairs"] == 5


def test_code_regression_is_visible_even_if_baseline_also_timed_out():
    report = report_fixture()
    fail(report["results"][0])
    fail(report["results"][1], code=False, stop="complete")
    result = qualify.qualify(report)
    assert result["counts"]["both_fail"] == 1 and result["verdict"] == "tradeoff"
    assert result["pairs"][0]["code_regression"]
    assert "code regression" in qualify.markdown(result)


def test_timeout_to_pass_is_a_quality_win_not_a_successful_speedup():
    report = report_fixture()
    fail(report["results"][0])
    report["results"][0]["seconds"] = 300.1
    result = qualify.qualify(report)
    assert result["counts"]["win"] == 1 and result["verdict"] == "candidate_supported"
    assert result["shared_pass_latency"]["pairs"] == 5
    assert result["summary"]["baseline"]["stops"]["time_limit"] == 1


@pytest.mark.parametrize("status", ["running", "interrupted", "budget_limit"])
def test_incomplete_plans_do_not_recommend_or_count_missing_as_failures(status):
    report = report_fixture()
    report["status"] = status
    report["results"].pop()
    result = qualify.qualify(report)
    assert result["verdict"] == "incomplete" and result["planned_pairs"] == 6
    assert result["paired_cases"] == 5 and len(result["missing_pairs"]) == 1
    assert result["summary"]["no-thinking"]["recorded"] == 5
    assert result["summary"]["no-thinking"]["passed"] == 5


@pytest.mark.parametrize("tasks,repeats", [(1, 3), (2, 2), (3, 1)])
def test_small_samples_remain_exploratory(tasks, repeats):
    assert qualify.qualify(report_fixture(tasks, repeats))["verdict"] == "exploratory"


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "spec",
        "task",
        "profile",
        "split",
        "duplicate",
        "unknown",
        "pass",
        "nan",
        "negative",
        "missing",
        "unbalanced",
        "connection",
        "unlabeled",
    ],
)
def test_inconsistent_or_noncomparable_reports_are_rejected(mutation):
    report = report_fixture()
    row = report["results"][0]
    if mutation == "source":
        report["source_fingerprint"] = "different"
    elif mutation == "spec":
        report["spec"]["limits"]["task_timeout"] = 600
    elif mutation == "task":
        row["task_fingerprint"] = "different"
    elif mutation == "profile":
        row["profile"] = dict(row["profile"], reasoning_effort="low")
    elif mutation == "split":
        row["split"] = "tune"
    elif mutation == "duplicate":
        report["results"].append(copy.deepcopy(row))
    elif mutation == "unknown":
        row["case_id"] = "unknown"
    elif mutation == "pass":
        row["check_passed"] = False
    elif mutation == "nan":
        row["seconds"] = float("nan")
    elif mutation == "negative":
        row["usage"]["input_tokens"] = -1
    elif mutation == "missing":
        report["results"].pop()
    elif mutation == "unbalanced":
        report["plan"].pop()
        report["results"].pop()
        reseal(report)
    elif mutation == "connection":
        report["spec"]["profiles"][1]["base_url"] = "http://different.example/v1"
        reseal(report)
    elif mutation == "unlabeled":
        del report["spec"]["profile_matrix"]
        reseal(report)
    with pytest.raises(ValueError):
        qualify.qualify(report)


def test_tuning_and_holdout_evidence_cannot_be_pooled():
    report = report_fixture(4, 2)
    report["spec"]["task_splits"]["project-3"] = "tune"
    for row in report["results"]:
        if row["task"] == "project-3":
            row["split"] = "tune"
    reseal(report)
    result = qualify.qualify(report)
    assert result["distinct_tasks"] == 3 and result["paired_cases"] == 6
    assert qualify.qualify(report, split="tune")["verdict"] == "exploratory"
    with pytest.raises(ValueError, match="never pooled"):
        qualify.qualify(report, split="all")


def test_identical_profiles_cannot_create_a_candidate_advantage():
    report = report_fixture()
    report["spec"]["profiles"][1]["reasoning_effort"] = None
    reseal(report)
    assert qualify.qualify(report)["verdict"] == "no_difference"


def test_cli_is_offline_and_exports_only_when_explicit(tmp_path, capsys, monkeypatch):
    report = report_fixture()
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network access"))
    flags = [
        str(path),
        "--json-out",
        str(tmp_path / "summary.json"),
        "--markdown-out",
        str(tmp_path / "summary.md"),
        "--export-profile",
        str(tmp_path / "selected.yaml"),
        "--select",
        "no-thinking",
    ]
    assert qualify.main(flags) == 0
    capsys.readouterr()
    assert json.loads((tmp_path / "summary.json").read_text())["report_sha256"]
    saved = (tmp_path / "selected.yaml").read_text()
    assert "reasoning_effort: none" in saved and "base_url" not in saved
    assert qualify.main(flags) == 2
    assert (tmp_path / "selected.yaml").read_text() == saved
    capsys.readouterr()
    with pytest.raises(SystemExit):
        qualify.main([str(path), "--export-profile", str(tmp_path / "unselected.yaml")])
    assert not (tmp_path / "unselected.yaml").exists()


async def test_runner_records_labeled_profiles_and_balanced_order(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "HERE", tmp_path)

    async def fake(task, config, args, destination, *, budget):
        return {
            "task": task["id"],
            "task_fingerprint": task["fingerprint"],
            "model": config.name,
            "split": task["split"],
            "passed": True,
            "check_passed": True,
            "scope": {"passed": True},
            "tool_checks_passed": True,
            "profile": run.profile_data(config),
            "verification": {"required": task["verification_commands"], "passed": True},
            "seconds": 1,
            "iterations": 1,
            "stop_reason": "complete",
            "usage": run.Ledger().export(),
        }

    monkeypatch.setattr(run, "evaluate", fake)
    flags = [
        "--suite",
        "phase11",
        "--split",
        "holdout",
        "--model",
        "local/fixture",
        "--allow-tools",
        "--allow-shell",
        "--variant",
        "baseline",
        "--variant",
        "no-thinking",
        "--repeats",
        "2",
    ]
    assert await run.main(flags) == 0
    path = next((tmp_path / "results").glob("*/report.json"))
    report = json.loads(path.read_text())
    result = qualify.qualify(report)
    assert result["planned_pairs"] == 8 and result["verdict"] == "no_clear_preference"
    assert [c["variant"] for c in report["plan"][:4]] == [
        "baseline",
        "no-thinking",
        "no-thinking",
        "baseline",
    ]
    assert [c["variant"] for c in report["plan"][8:10]] == ["no-thinking", "baseline"]
