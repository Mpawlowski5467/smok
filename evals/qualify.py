"""Read a fixed eval matrix and export explicitly selected, connection-free model controls."""

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import median

import yaml

from smok.models.profiles import ModelConfig

if __package__:
    from .reporting import cell, table_row
    from .suite import digest
else:
    from reporting import cell, table_row
    from suite import digest

# Export only tested runtime controls, never credentials, endpoint settings, or defaults.
PROFILE_FIELDS = (
    "token_parameter",
    "max_output_tokens",
    "timeout_seconds",
    "context_window",
    "compact_at",
    "keep_recent",
    "chars_per_token",
    "repo_map_tokens",
    "prompt_cache",
    "count_tokens",
    "local",
    "vision",
    "prompt_style",
    "tool_set",
    "edit_format",
    "reasoning_effort",
    "temperature",
    "top_p",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate(report):
    """Check internal consistency; hashes are not signatures or provider attestations."""
    require(report.get("schema_version") == 2, "Qualification requires eval report schema 2.")
    spec = report["spec"]
    require(report["fingerprint"] == digest(spec), "Run specification fingerprint differs.")
    require(report["source_fingerprint"] == spec["source"], "Source fingerprint differs.")
    plan = report["plan"]
    require(plan == spec["plan"] and 0 < len(plan) <= 1000, "Invalid or inconsistent run plan.")
    matrix = spec.get("profile_matrix")
    require(isinstance(matrix, list) and matrix, "Run again with labeled profiles from Smok 0.11+.")
    profiles = {}
    for item in matrix:
        key = (item["model"], item["variant"])
        require(
            isinstance(key[1], str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", key[1]),
            "Invalid variant label.",
        )
        require(key not in profiles, "Duplicate model/variant profile.")
        profile = item["profile"]
        ModelConfig(**profile)
        require(profile["name"] == key[0], "Profile model differs from matrix label.")
        require(
            "/" in key[0] and len(key[0]) <= 300 and not any(c.isspace() for c in key[0]),
            "Invalid model selector.",
        )
        require(
            profile["model"] == key[0].partition("/")[2], "Provider model differs from selector."
        )
        profiles[key] = profile
    require(list(profiles.values()) == spec["profiles"], "Profile matrix differs from profiles.")
    planned = {}
    for case in plan:
        identity = {k: case[k] for k in ("task", "model", "variant", "repeat")}
        require(case["id"] == digest(identity)[:20], "Case identity differs from its plan.")
        require(case["id"] not in planned, "Duplicate planned case.")
        require(type(case["repeat"]) is int and 1 <= case["repeat"] <= 10, "Invalid repeat.")
        require(
            case["task"] in spec["tasks"] and (case["model"], case["variant"]) in profiles,
            "Plan references unknown task/profile.",
        )
        planned[case["id"]] = case
    rows = {}
    for row in report["results"]:
        key = row["case_id"]
        require(key in planned and key not in rows, "Unknown or duplicate result case.")
        require(
            all(row[k] == planned[key][k] for k in ("task", "model", "variant", "repeat")),
            "Result identity differs from its plan.",
        )
        require(row["task_fingerprint"] == spec["tasks"][row["task"]], "Task fingerprint differs.")
        require(row["split"] == spec["task_splits"][row["task"]], "Task split differs.")
        require(
            row["profile"] == profiles[(row["model"], row["variant"])],
            "Result used a different model profile.",
        )
        require(number(row["seconds"]), "Invalid elapsed time.")
        require(
            all(
                type(row["usage"][k]) is int and row["usage"][k] >= 0
                for k in ("requests", "input_tokens", "output_tokens", "estimated_requests")
            ),
            "Invalid usage measurements.",
        )
        verification = row["verification"]
        require(
            isinstance(verification["required"], list) and verification["required"],
            "Qualification requires project verification evidence.",
        )
        flags = [
            row["passed"],
            row["check_passed"],
            row["scope"]["passed"],
            row["tool_checks_passed"],
            verification["passed"],
        ]
        require(all(type(flag) is bool for flag in flags), "Invalid outcome flags.")
        passed = all(flags[1:]) and row["stop_reason"] == "complete"
        require(row["passed"] == passed, "Pass disagrees with correctness/verification/completion.")
        rows[key] = row
    require(
        report["status"] in {"running", "complete", "interrupted", "budget_limit"},
        "Invalid status.",
    )
    require(
        report["status"] != "complete" or set(rows) == set(planned),
        "Complete report is missing planned cases.",
    )
    return profiles, planned, rows


def summarize(rows, planned):
    return {
        "planned": planned,
        "recorded": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "correct": sum(r["check_passed"] for r in rows),
        "verified": sum(r["verification"]["passed"] for r in rows),
        "completed": sum(r["stop_reason"] == "complete" for r in rows),
        "stops": dict(Counter(r["stop_reason"] for r in rows)),
        "total_seconds": round(sum(r["seconds"] for r in rows), 2),
        "requests": sum(r["usage"]["requests"] for r in rows),
        "tokens": sum(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] for r in rows),
        "estimated_requests": sum(r["usage"]["estimated_requests"] for r in rows),
    }


def qualify(
    report,
    *,
    model=None,
    candidate="no-thinking",
    split="holdout",
    candidate_model=None,
    baseline_variant="baseline",
):
    profiles, plan, results = validate(report)
    require(split in {"tune", "holdout"}, "Choose one split; tuning and holdout are never pooled.")
    models = sorted({k[0] for k in profiles})
    if model is None:
        require(
            candidate_model is None, "Cross-model comparison requires an explicit baseline model."
        )
        require(len(models) == 1, "Select --model for a report containing multiple models.")
        model = models[0]
    cross_model = candidate_model is not None
    if cross_model:
        require(candidate_model != model, "Choose different models for a cross-model comparison.")
        selectors = {
            "baseline": (model, baseline_variant),
            "candidate": (candidate_model, candidate),
        }
    else:
        require(baseline_variant == "baseline", "--baseline-variant requires --candidate-model.")
        require(candidate != "baseline", "Candidate must differ from baseline.")
        selectors = {"baseline": (model, "baseline"), candidate: (model, candidate)}
    variants = tuple(selectors)
    candidate_label = variants[1]
    require(
        all(key in profiles for key in selectors.values()), "Both profiles must be in this report."
    )
    # Older reports omit optional controls added later. Normalize only after
    # validating the original recorded profiles and fingerprints, without edits.
    controls = {v: asdict(ModelConfig(**profiles[key])) for v, key in selectors.items()}
    before, after = controls.values()
    changed = {
        k: {"baseline": before[k], "candidate": after[k]} for k in before if before[k] != after[k]
    }
    if not cross_model:
        require(
            set(changed) <= set(PROFILE_FIELDS),
            "Profiles differ in connection/model/cost settings.",
        )
    selected = {
        v: {
            (c["task"], c["repeat"]): c["id"]
            for c in plan.values()
            if (c["model"], c["variant"]) == selectors[v]
            and report["spec"]["task_splits"][c["task"]] == split
        }
        for v in variants
    }
    require(
        selected["baseline"] and selected["baseline"].keys() == selected[candidate_label].keys(),
        "Baseline and candidate must plan the same tasks and repeats.",
    )
    pairs, missing = [], []
    for key, baseline_id in selected["baseline"].items():
        candidate_id = selected[candidate_label][key]
        if baseline_id not in results or candidate_id not in results:
            missing.append({"task": key[0], "repeat": key[1]})
            continue
        a, b = results[baseline_id], results[candidate_id]
        outcome = (
            ("both_pass" if a["passed"] else "win")
            if b["passed"]
            else ("regression" if a["passed"] else "both_fail")
        )
        pairs.append(
            {
                "task": key[0],
                "repeat": key[1],
                "split": a["split"],
                "outcome": outcome,
                "baseline_passed": a["passed"],
                "candidate_passed": b["passed"],
                "baseline_stop": a["stop_reason"],
                "candidate_stop": b["stop_reason"],
                "baseline_seconds": a["seconds"],
                "candidate_seconds": b["seconds"],
                "code_regression": a["check_passed"] and not b["check_passed"],
                "verification_regression": a["verification"]["passed"]
                and not b["verification"]["passed"],
                "scope_regression": a["scope"]["passed"] and not b["scope"]["passed"],
            }
        )
    counts = dict(Counter(p["outcome"] for p in pairs))
    paired_times = [p for p in pairs if p["outcome"] == "both_pass" and p["baseline_seconds"] > 0]
    latency = {
        "pairs": len(paired_times),
        "median_candidate_minus_baseline_seconds": round(
            median(p["candidate_seconds"] - p["baseline_seconds"] for p in paired_times), 2
        )
        if paired_times
        else None,
        "median_candidate_time_reduction_percent": round(
            median(
                100 * (1 - p["candidate_seconds"] / p["baseline_seconds"]) for p in paired_times
            ),
            2,
        )
        if paired_times
        else None,
    }
    task_repeats = Counter(task for task, _ in selected["baseline"])
    repeated = len(task_repeats) >= 3 and all(n >= 2 for n in task_repeats.values())
    regressions = any(
        p["outcome"] == "regression"
        or p["code_regression"]
        or p["verification_regression"]
        or p["scope_regression"]
        for p in pairs
    )
    if report["status"] != "complete" or missing:
        verdict, reason = (
            "incomplete",
            "Finish the planned run before selecting from its comparison.",
        )
    elif not (set(changed) - {"name"}):
        verdict, reason = "no_difference", "The effective profiles are identical."
    elif not repeated:
        verdict, reason = (
            "exploratory",
            "Use at least three distinct tasks and two repeats per task.",
        )
    elif regressions:
        verdict, reason = (
            "tradeoff",
            "Candidate loses completion, correctness, scope, or verification in at least one pair.",
        )
    elif counts.get("win", 0):
        verdict, reason = (
            "candidate_supported",
            "Candidate gains complete passes without an observed paired regression.",
        )
    elif latency["pairs"] >= 3 and latency["median_candidate_time_reduction_percent"] >= 10:
        verdict, reason = (
            "candidate_supported",
            "No observed paired regression; median time is at least 10% lower on shared passes.",
        )
    else:
        verdict, reason = (
            "no_clear_preference",
            "This sample does not show a clear candidate advantage.",
        )
    return {
        "schema_version": 2 if cross_model else 1,
        "comparison": "models" if cross_model else "variants",
        "model": model,
        "baseline": "baseline",
        "candidate": candidate_label,
        "selections": {
            label: {
                "model": key[0],
                "variant": key[1],
                "provider_model": profiles[key]["model"],
                "adapter": profiles[key]["adapter"],
            }
            for label, key in selectors.items()
        },
        "connection_differences": sorted(
            set(changed) - set(PROFILE_FIELDS) - {"name", "model", "adapter"}
        ),
        "run_status": report["status"],
        "source_fingerprint": report["source_fingerprint"],
        "run_fingerprint": report["fingerprint"],
        "smok_version": report["smok_version"],
        "suite": report["spec"]["suite"],
        "split": split,
        "limits": report["spec"]["limits"],
        "task_fingerprints": {task: report["spec"]["tasks"][task] for task in task_repeats},
        "profiles": {v: {k: controls[v][k] for k in PROFILE_FIELDS} for v in variants},
        "changed_controls": {k: value for k, value in changed.items() if k in PROFILE_FIELDS},
        "planned_pairs": len(selected["baseline"]),
        "paired_cases": len(pairs),
        "missing_pairs": missing,
        "distinct_tasks": len(task_repeats),
        "repeated_coverage": repeated,
        "counts": counts,
        "pairs": pairs,
        "shared_pass_latency": latency,
        "summary": {
            v: summarize(
                [results[c] for c in selected[v].values() if c in results], len(selected[v])
            )
            for v in variants
        },
        "verdict": verdict,
        "reason": reason,
        "limitations": [
            "Cross-model results compare the recorded model, provider, and runtime settings "
            "together; they do not isolate the effect of model weights."
            if cross_model
            else "Variant results compare settings within the selected model.",
            "The verdict describes this recorded sample, "
            "not general model quality or statistical significance.",
            "Freshness is an evaluation protocol, not something this report "
            "can infer. Inspected tasks become known regressions.",
            "Elapsed times include client work and cleanup. Only pairs passing "
            "both profiles enter latency comparison; timeouts are never treated "
            "as successful speedups.",
            "Order, caches, sampler state, and local load can affect results. Repeats "
            "are not independent new tasks.",
            "Report hashes detect accidental changes, not fabricated evidence. No network calls "
            "or workspace preference changes occur.",
        ],
    }


def markdown(result):
    selections = result.get("selections", {})
    description = (
        " · ".join(
            f"{label.title()}: **{cell(item['model'])} / {cell(item['variant'])}**"
            for label, item in selections.items()
        )
        if result.get("comparison") == "models"
        else f"Model: **{cell(result['model'])}** · candidate: **{cell(result['candidate'])}**"
    )
    lines = [
        "# Smok profile qualification",
        "",
        description + f" · split: **{result['split']}**",
        "",
        f"Verdict: **{result['verdict']}**. {result['reason']}",
        "",
        f"Coverage: {result['paired_cases']}/{result['planned_pairs']} pairs across "
        f"{result['distinct_tasks']} tasks. Run status: {result['run_status']}.",
        "",
        "| Profile | Pass | Correct | Verified | Completed | Requests | Tokens | Elapsed |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant, row in result["summary"].items():
        lines.append(
            table_row(
                [
                    variant,
                    f"{row['passed']}/{row['planned']}",
                    row["correct"],
                    row["verified"],
                    row["completed"],
                    row["requests"],
                    row["tokens"],
                    f"{row['total_seconds']:.2f}s",
                ]
            )
        )
    lines += [
        "",
        "## Paired outcomes",
        "",
        "| Task | Repeat | Outcome | Baseline stop | Candidate stop | "
        "Baseline seconds | Candidate seconds |",
        "| --- | ---: | --- | --- | --- | ---: | ---: |",
    ]
    losses_by_pair = []
    for pair in result["pairs"]:
        lines.append(
            table_row(
                [
                    pair[k]
                    for k in (
                        "task",
                        "repeat",
                        "outcome",
                        "baseline_stop",
                        "candidate_stop",
                        "baseline_seconds",
                        "candidate_seconds",
                    )
                ]
            )
        )
        losses = [name for name in ("code", "verification", "scope") if pair[name + "_regression"]]
        if losses:
            losses_by_pair.append(
                f"{cell(pair['task'])}, repeat {pair['repeat']}: "
                + ", ".join(losses)
                + " regression."
            )
    if losses_by_pair:
        lines += [""] + losses_by_pair
    time = result["shared_pass_latency"]
    latency_text = (
        f"Shared-pass latency pairs: {time['pairs']}. Median candidate minus baseline: "
        f"{time['median_candidate_minus_baseline_seconds']} seconds; median time reduction: "
        f"{time['median_candidate_time_reduction_percent']}%."
        if time["pairs"]
        else "No pairs passed both profiles; a successful-task latency comparison is unavailable."
    )
    lines += [
        "",
        latency_text,
        "",
        "## Controls",
        "",
    ]
    for key, value in result["changed_controls"].items():
        lines.append(f"- {key}: {value['baseline']!r} → {value['candidate']!r}")
    if not result["changed_controls"]:
        lines.append("The tested runtime controls are identical.")
    if result.get("comparison") == "models":
        for label, item in selections.items():
            lines.append(
                f"- {label.title()}: adapter {cell(item['adapter'])}, "
                f"provider model {cell(item['provider_model'])}."
            )
    if result.get("connection_differences"):
        lines.append(
            "- Other differing settings: " + ", ".join(result["connection_differences"]) + "."
        )
    lines += ["", "## Interpretation", ""] + ["- " + note for note in result["limitations"]]
    lines += [
        "",
        "Profile export is an explicit selection, never automatic promotion. "
        "It contains runtime controls only and depends on your existing provider connection.",
        "",
        f"Run fingerprint: `{result['run_fingerprint']}`",
        "",
        f"Source fingerprint: `{result['source_fingerprint']}`",
        "",
    ]
    if "report_sha256" in result:
        lines += [f"Input report SHA-256: `{result['report_sha256']}`", ""]
    return "\n".join(lines)


def profile_yaml(result, selected):
    require(selected in result["profiles"], "Select baseline or the compared candidate variant.")
    model = result.get("selections", {}).get(selected, {}).get("model", result["model"])
    return (
        f"# Explicit selection: {selected}; evidence verdict: {result['verdict']}\n"
        f"# Run fingerprint: {result['run_fingerprint']}\n"
        "# Provider connection and default model are unchanged.\n"
        + yaml.safe_dump({"models": {model: result["profiles"][selected]}}, sort_keys=False)
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--model")
    parser.add_argument(
        "--candidate-model", help="Compare this model against --model in the same run"
    )
    parser.add_argument("--baseline-variant", default="baseline")
    parser.add_argument("--candidate", default="no-thinking")
    parser.add_argument("--split", choices=["tune", "holdout"], default="holdout")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--export-profile", type=Path)
    parser.add_argument("--select", help="Explicitly choose baseline or the candidate for export")
    args = parser.parse_args(argv)
    if bool(args.export_profile) != bool(args.select):
        parser.error("--export-profile and --select must be supplied together.")
    if args.candidate_model and not args.model:
        parser.error("--candidate-model requires an explicit baseline --model.")
    try:
        require(args.report.stat().st_size <= 32 * 1024 * 1024, "Report exceeds 32 MiB.")
        data = args.report.read_bytes()
        result = qualify(
            json.loads(data),
            model=args.model,
            candidate=args.candidate,
            split=args.split,
            candidate_model=args.candidate_model,
            baseline_variant=args.baseline_variant,
        )
        result["report_sha256"] = hashlib.sha256(data).hexdigest()
        rendered = markdown(result)
        outputs = []
        if args.json_out:
            outputs.append((args.json_out, json.dumps(result, indent=2) + "\n"))
        if args.markdown_out:
            outputs.append((args.markdown_out, rendered))
        if args.export_profile:
            outputs.append((args.export_profile, profile_yaml(result, args.select)))
        require(len({p.resolve() for p, _ in outputs}) == len(outputs), "Output paths must differ.")
        for path, _ in outputs:
            require(not path.exists() and not path.is_symlink(), f"Output already exists: {path}")
            require(path.parent.is_dir(), f"Output directory does not exist: {path.parent}")
        for path, value in outputs:
            with path.open("x") as stream:
                stream.write(value)
        print(rendered)
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"smok qualify: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
