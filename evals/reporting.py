"""Comparable measurements, paired regressions, and readable local reports."""

import json
from collections import defaultdict
from pathlib import Path


def summarize(results):
    groups = defaultdict(list)
    for row in results:
        groups[(row["model"], row["variant"], row["split"])].append(row)
    rows = []
    for (model, variant, split), cases in sorted(groups.items()):
        rows.append(
            {
                "model": model,
                "variant": variant,
                "split": split,
                "passed": sum(c["passed"] for c in cases),
                "total": len(cases),
                "completed": sum(c["stop_reason"] == "complete" for c in cases),
                "checks_passed": sum(c.get("check_passed", False) for c in cases),
                "project_checks_required": sum(
                    bool(c.get("verification", {}).get("required")) for c in cases
                ),
                "project_checks_passed": sum(
                    bool(c.get("verification", {}).get("required")) and c["verification"]["passed"]
                    for c in cases
                ),
                "requests": sum(c["usage"]["requests"] for c in cases),
                "tokens": sum(
                    c["usage"]["input_tokens"] + c["usage"]["output_tokens"] for c in cases
                ),
                "estimated_requests": sum(c["usage"]["estimated_requests"] for c in cases),
                "unpriced_requests": sum(c["usage"]["unpriced_requests"] for c in cases),
                "known_cost_usd": sum(c["usage"]["known_cost_usd"] for c in cases),
                "seconds": round(sum(c["seconds"] for c in cases), 2),
            }
        )
    return rows


def paired(results):
    baseline = {
        (r["model"], r["task"], r["repeat"]): r for r in results if r["variant"] == "baseline"
    }
    groups = defaultdict(lambda: {"compared": 0, "wins": [], "regressions": [], "token_delta": 0})
    for row in results:
        before = baseline.get((row["model"], row["task"], row["repeat"]))
        if row["variant"] == "baseline" or before is None:
            continue
        group = groups[(row["model"], row["variant"], row["split"])]
        group["compared"] += 1
        label = f"{row['task']} (repeat {row['repeat']})"
        if row["passed"] and not before["passed"]:
            group["wins"].append(label)
        if before["passed"] and not row["passed"]:
            group["regressions"].append(label)
        group["token_delta"] += sum(
            row["usage"][k] - before["usage"][k] for k in ("input_tokens", "output_tokens")
        )
    return [{"model": k[0], "variant": k[1], "split": k[2], **v} for k, v in sorted(groups.items())]


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def table_row(values):
    return "| " + " | ".join(cell(v) for v in values) + " |"


def markdown(report):
    lines = [
        "# Smok coding evaluation",
        "",
        f"Status: **{report['status']}** · "
        f"{len(report['results'])}/{len(report['plan'])} cases recorded.",
        "",
        "| Model | Variant | Split | Pass | Calls | Tokens | Estimated calls "
        "| Known API cost | Seconds |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summarize(report["results"]):
        cost = f"${row['known_cost_usd']:.4f}" + (" + unpriced" if row["unpriced_requests"] else "")
        lines.append(
            table_row(
                [
                    row["model"],
                    row["variant"],
                    row["split"],
                    f"{row['passed']}/{row['total']}",
                    row["requests"],
                    row["tokens"],
                    row["estimated_requests"],
                    cost,
                    row["seconds"],
                ]
            )
        )
    lines += ["", "## Paired comparisons with baseline", ""]
    for row in paired(report["results"]):
        lines.append(
            f"- {cell(row['model'])} / {row['variant']} / {row['split']}: "
            f"{row['compared']} paired cases, {len(row['wins'])} wins, "
            f"{len(row['regressions'])} regressions, {row['token_delta']:+,} tokens."
        )
        if row["regressions"]:
            lines.append("  Regressions: " + ", ".join(row["regressions"]) + ".")
    lines += [
        "",
        "## Case results",
        "",
        "| Task | Split | Variant | Repeat | Pass | Code check | Project checks "
        "| Stop | Calls | Seconds | Evidence |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in report["results"]:
        lines.append(
            table_row(
                [
                    row["task"],
                    row["split"],
                    row["variant"],
                    row["repeat"],
                    "PASS" if row["passed"] else "FAIL",
                    "PASS"
                    if row.get("check_passed")
                    else "FAIL"
                    if "check_passed" in row
                    else "unrecorded",
                    ("PASS" if row["verification"]["passed"] else "FAIL")
                    if row.get("verification", {}).get("required")
                    else "not required",
                    row["stop_reason"],
                    row["usage"]["requests"],
                    row["seconds"],
                    row["evidence"],
                ]
            )
        )
    timed = [row for row in report["results"] if "timing" in row]
    if timed:
        lines += [
            "",
            "## Observed time",
            "",
            "| Task | Variant | Repeat | Model wait/stream | Tools (including approvals) "
            "| Other work | Interrupted stage |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for row in timed:
            timing = row["timing"]
            interrupted = [
                kind
                for kind, key in (("model", "model_requests"), ("tool", "tool_calls"))
                if any(item["outcome"] == "interrupted" for item in timing[key])
            ]
            lines.append(
                table_row(
                    [
                        row["task"],
                        row["variant"],
                        row["repeat"],
                        f"{timing['model_seconds']:.2f}s",
                        f"{timing['tool_seconds']:.2f}s",
                        f"{timing['other_work_seconds']:.2f}s",
                        ", ".join(interrupted) or "none",
                    ]
                )
            )
        lines += [
            "",
            "Times are observed by the eval client, including event handling and stream cleanup; "
            "they are not server compute measurements. Approval time is included in tool time. "
            "Setup and grading/cleanup are recorded separately in JSON. Older attempts without "
            "timing data are omitted. Project checks must succeed against the final file snapshot; "
            "an earlier success followed by changed files does not qualify.",
        ]
    lines += [
        "",
        "Tuning and holdout results are separate. Pass means independent correctness, scope, "
        "and completion checks passed. These small fixtures are not a public benchmark or proof "
        "of general model quality. One repetition is exploratory; repeat before adopting a "
        "profile. Local API cost excludes hardware and electricity. Cache usage and execution "
        "order affect timing. No defaults are changed by this report.",
        "",
    ]
    return "\n".join(lines)


def save_report(directory, report):
    report["summary"] = summarize(report["results"])
    report["paired"] = paired(report["results"])
    for name, value in (
        ("report.json", json.dumps(report, indent=2) + "\n"),
        ("report.md", markdown(report)),
    ):
        temporary = directory / (name + ".tmp")
        temporary.write_text(value)
        temporary.replace(directory / name)


def compare_reports(paths):
    reports = [json.loads(Path(p).read_text()) for p in paths]
    if not reports or any(r.get("schema_version") != 2 for r in reports):
        raise ValueError("Comparison requires Phase 7 report schema 2.")
    fingerprints = {}
    lines = [
        "# Smok report comparison",
        "",
        "| Report | Status | Source | Model | Variant | Split | Pass | Calls | Tokens |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for path, report in zip(paths, reports, strict=True):
        for case in report["results"]:
            previous = fingerprints.setdefault(case["task"], case["task_fingerprint"])
            if previous != case["task_fingerprint"]:
                raise ValueError(f"Task {case['task']} changed; its scores are not comparable.")
        for row in summarize(report["results"]):
            lines.append(
                table_row(
                    [
                        Path(path).parent.name,
                        report["status"],
                        report["source_fingerprint"][:10],
                        row["model"],
                        row["variant"],
                        row["split"],
                        f"{row['passed']}/{row['total']}",
                        row["requests"],
                        row["tokens"],
                    ]
                )
            )
    lines += [
        "",
        "Only overlapping task fingerprints are comparable. Compare the same task set and "
        "repeats; incomplete runs and source revisions are shown above. Totals alone do not "
        "establish a quality improvement.",
        "",
    ]
    return "\n".join(lines)
