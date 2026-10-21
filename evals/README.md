# Coding evals

Start with the [model results overview](../docs/model-results.md) for recorded
outcomes and their limits. Version 0.12.2 adds bounded recovery and explicit sampling
controls. The [parser follow-up](../docs/phase12-parser-resolution.md) records **3/3**
complete passes with an explicit 64K-context Gemma profile; its 32K-context validation
remains **1/3**. These are known regressions, separate from the original comparison
and from fresh-project qualification. Failed pilots and fixed validations are retained.

Version 0.12 adds `--suite phase12`: four original projects and alternating complete
model/variant execution order. `qualify.py --candidate-model MODEL` compares two
explicit model/profile pairs within one run and exports a `baseline` or `candidate`
selection. See the [cross-model protocol](../docs/cross-model-qualification.md).

Version 0.11.1 adds `--variant focused-repair` (lean prompt, minimal tools, explicit
no-thinking). Release/join public tests now cover the observed whitespace and nested
aliasing defects; their changed fingerprints cannot be pooled with the original
Phase 11 comparison. See the [regression follow-up](../docs/repair-reliability.md).

Version 0.11 adds `--suite phase11`: four fresh project tasks for profile qualification.
`python evals/qualify.py RUN/report.json` reads a labeled matrix offline, separates
correctness/completion regressions from latency, and exports controls only after an
explicit `--export-profile FILE --select VARIANT`. See the
[qualification protocol and selection rules](../docs/model-qualification.md).

Version 0.7 adds the default `phase7` suite: 20 tasks, split into 15 tuning and five
holdout cases. It supports profile/model matrices, repeats, shared budgets, independent
graders, resumable reports, and paired comparisons. See the [evaluation guide](../docs/evaluation.md).
Older Phase 1/2 tasks and the Phase 3–6 integration scripts remain available explicitly.

Version 0.10 adds `--suite phase10`: six multi-file project workflows with public tests,
independent graders, required execution against final source, and timing evidence.
See the [project workflow guide](../docs/project-workflows.md). These fixtures require
both `--allow-tools` and `--allow-shell`; only their exact documented check command is
approved. The Phase 7 default is unchanged.

Version 0.10.1 adds `--variant no-thinking`, an explicit `reasoning_effort: "none"`
request for compatible models. Provider defaults stay unchanged. The configuration
fixture's public tests now cover CLI-port boundaries; its new task fingerprint must
not be pooled with earlier results. Independent graders are unchanged.

Each task starts in a fresh disposable fixture. The agent uses the same core and tools
as the CLI, including checkpoints and self-check. A separate deterministic check
verifies files and edge cases; a model's claim of success does not count as a pass.

```sh
uv run python evals/run.py --list --split all
uv run python evals/run.py --model ollama/YOUR_INSTALLED_MODEL --variant baseline --variant lean-coding --allow-tools
uv run python evals/run.py --suite phase1 --model anthropic/YOUR_MODEL_ID --allow-tools --task fix-addition

uv run python evals/run.py --suite phase2 --model ollama/YOUR_INSTALLED_MODEL \
  --allow-tools --allow-shell --allow-lsp --max-iterations 16 --task-timeout 360

uv run python evals/phase3.py --model ollama/YOUR_INSTALLED_MODEL \
  --allow-tools --allow-shell --timeout 900

uv run python evals/phase4.py --model ollama/YOUR_INSTALLED_MODEL \
  --allow-tools --timeout 1200

uv run python evals/phase4_browser.py --allow-browser \
  --server /absolute/path/to/playwright-mcp --browser /absolute/path/to/chrome
```

Phase 1's five tasks cover a bug fix, normalization, CSV aggregation, config editing,
and a new utility. Phase 2 adds:

- `search-edit-verify`: glob/grep discovery, scoped AGENTS.md, exact edit, a real check,
  self-review, and restoration of the original fixture through undo.
- `lsp-repair`: Python diagnostics, definitions, references, a targeted fix, refreshed
  diagnostics, self-review, and undo. Install the `lsp` extra first.

`--allow-tools` permits file writes/edits. From 0.8.1, the model sees only authorizable
built-in tools, with the execution restrictions stated before generation. Omitted
tools are also blocked in the core; extensions, hooks, MCP, and background processes
are unavailable in these fixtures. Shell calls remain disabled unless
`--allow-shell` is supplied; server startup needs `--allow-lsp`. Endpoint inference
uses the selected model; frontier runs use your API account. No models, Docker images,
or project dependencies are downloaded by the runner.

Reports contain pass/fail, call count, token totals, timing, successful tool counts,
self-check count, check output, and Phase 2 undo results. Phase 2 additionally requires
specified tools to have succeeded. Events and pre-undo generated files are saved under
Git-ignored `evals/results/`. `check_passed` measures file correctness even at a limit;
`passed` additionally requires a completed turn and the task's tool/undo checks.

These are smoke evals, not a general coding benchmark. Temporary directories separate
fixture data but do not sandbox host commands or generated Python. Usage includes
repeated context and final/review calls; provider counts are used when available.
The Phase 3 ledger distinguishes provider usage from reserved estimates.

The Phase 3 runner uses a dedicated fixture under its results directory so the actual
resumable sessions and output archives remain inspectable. The fixture has its own
Git repository so parent ignore rules do not suppress checkpoints. It plans a small repair,
retrieves a marker beyond a long tool preview, saves and reopens the session, lowers
the configured working limit to force automatic compaction, and continues the repair.
An independent check verifies arithmetic behavior, the public name, and an unchanged
docstring. It then exports a handoff and checks recall in a fresh session. All model
history comes from the live run; no synthetic warm-up messages are inserted.

The report records each stage, invariant checks, usage ledgers, and both session IDs.
The fixture, JSONL journal, handoff, and archived output remain in `results/.../workspace`.
Do not use these generated files as general configuration or instructions. Run limits
and provider protocol/cache contracts are tested independently in the automated suite.

If the overall deadline interrupts handoff after the repair stages passed, continue
only the export/recall check with `--finish-handoff results/PRIOR_RUN` (use the path
relative to your current directory). The continuation writes a separate report linked
to the initial result; it does not erase the timeout or rerun completed coding stages.

## Phase 4

`phase4.py` creates a separate Git fixture with a declarative plugin, skill, command,
formatter hook, and two-step recipe. The live model repairs arithmetic through the
command/skill, calls a real stdio MCP fixture, searches and fetches a local HTTP source,
writes its exact marker, authors and reloads a skill, runs the recipe, and reviews a
newly introduced regression. Independent checks verify the repair, hook marker,
successful tool calls, retrieved source marker, new catalog entry, completed recipe
steps, and unchanged files during review. A simple finding-content check verifies
that review identified the seeded arithmetic defect; it does not grade general
review quality or severity calibration. Every stage and JSONL event is retained.

`--allow-tools` explicitly approves tools in this disposable fixture, including shell
hooks and local MCP/web operations. It is not an OS sandbox. The local search service
implements the SearXNG JSON response shape; it does not exercise a production search
account. The runner never downloads models, browsers, or MCP servers.

`phase4_browser.py` uses a separately installed Playwright MCP executable and an
existing Chrome/Chromium binary. It launches an isolated headless profile, visits a
temporary loopback counter page, reads its accessibility snapshot, clicks its button,
checks the counter change, and retains a screenshot through Smok's artifact handling.
It does not connect to existing personal tabs or logins. The tested server is
`@playwright/mcp@0.0.83`; schemas are discovered through the same registry as model tools.

## Phase 5

```sh
uv run python evals/phase5.py --model ollama/qwen3.6:27b-mlx --allow-tools
```

Runs parallel fresh-context exploration, council repair/check selection, a routed
primary task, replay of that real task, oracle advice, a shadow comparison, and a
background process in a disposable Git fixture. The council/shadow profiles are aliases
of the same installed local model so the runner needs no frontier key. This validates
coordination, not cross-model quality. Reports distinguish the seven checks and retain
usage, child sessions/worktrees, patches, and the original session. No live SSH or
Docker claim is made by this evaluation; the automated suite validates their protocol
and lifecycle behavior separately.

## Phase 6 GUI

`uv run python evals/phase6.py --model ollama/qwen3.6:27b-mlx --allow-tools`
starts a real local HTTP/WebSocket server around a retained fixture. It approves only
`calculator.py` edits and `python3 -m unittest -q`, then checks streaming, diff review,
workspace assertions, provider usage, a revoked read-only share, and branch/undo.
Reports go to `evals/results/*-phase6/report.json`. The verified run is 6/6 with five
local model requests; details are in `docs/validation.md`.

The independent `npm --prefix web test` suite uses a disposable deterministic model
and installed Chrome on macOS. It does not contact a model provider or record audio.
