# Smok documentation

[Project overview and quick start](../README.md)

## Use Smok

| Guide | Covers |
| --- | --- |
| [Setup and troubleshooting](setup.md) | First task, diagnostics, model discovery, common fixes, and local release checks. |
| [CLI and configuration](cli.md) | Commands, providers, permissions, context, budgets, sessions, tools, and undo. |
| [Browser and desktop](gui.md) | Launching the app, approvals, models/keys, images, voice, sharing, and native builds. |
| [Extensions](extensions.md) | MCP, skills, hooks, commands, recipes, plugins, web tools, and browser integration. |
| [Teamwork](teamwork.md) | Routes, workers, councils, candidate review, background work, replay, and SSH runners. |
| [Deadlines and completion](reliability.md) | Turn limits, denial handling, review, interrupted work, and recovery. |

## Understand the evidence

Start with [model results](model-results.md) for the measured outcomes and their limits.

| Guide | Evidence |
| --- | --- |
| [Evaluation and tuning](evaluation.md) | Phase 7's 20 tasks, tool/prompt/edit controls, bounded runs, and reports. |
| [Project workflows](project-workflows.md) | Six Phase 10 multi-file projects and verification on final source bytes. |
| [Within-model qualification](model-qualification.md) | Phase 11 default/no-thinking comparison and explicit profile export. |
| [Release/join repair follow-up](repair-reliability.md) | Known regressions, failed pilots, stronger coverage, and fixed validations. |
| [Cross-model qualification](cross-model-qualification.md) | Phase 12 model/profile pairing and selection rules. |
| [Phase 12 contract audit](phase12-contract-audit.md) | Corrected grading and all 16 original attempts. |
| [Phase 12 repair follow-up](phase12-repair.md) | Input-validation results, parser failures, runtime changes, and retained trials. |
| [Command-parser recovery](phase12-parser-resolution.md) | Compaction recovery, sampling audit, explicit profiles, and subsequent parser trials. |
| [Validation log](validation.md) | Dated automated, browser, native, package, and live integration checks. |
| [Evaluation commands](../evals/README.md) | Running suites, opt-ins, artifacts, and historical integration scripts. |

Committed JSON receipts summarize local measurements and identify source/configuration
snapshots by hash. Their raw `evals/results/` paths identify local retained evidence,
not files available in a fresh clone. Repeated known tasks and adaptive pilots are
kept separate from the original fresh-task comparisons.

## Develop Smok

- [Contributing](../CONTRIBUTING.md): development setup, checks, and evaluation rules.
- [Architecture](architecture.md): shared agent core, adapters, tools, persistence, and UI.
- [Roadmap](roadmap.md): implemented phases, remaining validation, and release work.
- [Brand assets](brand.md): supplied dragon artwork and its uses.
- [Original game plan](harness-gameplan.pdf): the source design document; current behavior
  and remaining work are described by the guides and roadmap.
