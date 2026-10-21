# Roadmap

Based on the [supplied Smok harness game plan](harness-gameplan.pdf) (October 18, 2026). Keep each phase
usable before expanding the scope. This file distinguishes implemented code from
release exit checks and future features.

## Phase 1: terminal foundation

- [x] Python 3.12 package, uv environment, CLI entry point
- [x] Provider-neutral message blocks and events
- [x] Streaming Anthropic and OpenAI-compatible adapters
- [x] Bounded agent loop
- [x] Read, write, list, and shell tools
- [x] Per-action write and shell approval
- [x] `/model`, `/clear`, `/exit`, `/help`
- [x] Local JSONL event logs and one-task CLI mode
- [x] Protocol/tool/core tests and five coding eval tasks
- [ ] Live same-task validation on Qwen through Ollama and Claude through Anthropic

The first implementation also brings forward read-before-write hashes, file diffs,
line-range reads, and path confinement because they make the initial write tool safer.
Phase 2 extends these checks to targeted edits and undo.

## Phase 2: everyday coding

- [x] Exact, unique-string edits with unified diffs
- [x] Numbered/ranged reads and read-before-edit hashes
- [x] Ripgrep search and file globs
- [x] Ask, auto-edit, and full-auto permissions with per-project saved rules
- [x] Tab plan/build toggle with mutation enforcement in the core
- [x] Root and scoped AGENTS.md instructions, including freshness checks
- [x] Shadow Git checkpoints and conflict-aware `/undo`
- [x] LSP diagnostics, definition, and references; Python server integration
- [x] Self-check pass using actual diffs and recorded command results
- [x] Optional Docker shell backend with default network isolation
- [ ] Live Docker container validation (local daemon is stopped)

Implementation is complete; validation evidence and remaining endpoint/runtime checks
are recorded in [validation](validation.md). The GUI can begin after this phase.

## Phase 3: context and sessions

- [x] Durable JSONL state, `--resume`, `--continue`, and session listing
- [x] Provider usage, Anthropic preflight counting, and labeled local estimates
- [x] Retained large tool outputs with paginated retrieval by archive ID
- [x] Automatic/manual structured compaction at complete exchange boundaries
- [x] Anthropic prompt-cache breakpoints and cache-aware usage accounting
- [x] Tree-sitter repository map for Python, JavaScript, and TypeScript
- [x] Persistent todo tool, including plan-mode support
- [x] Editable handoff export and fresh-session import
- [x] Per-run token/dollar budgets, turn caps, and shared model-call caps
- [x] CLI context X-ray with pin/drop and configured-price comparison
- [ ] Live frontier token-count/cache-hit billing validation (API key unavailable)

Model-specific context limits and price data are explicit profile settings; built-in
working limits are conservative defaults, not model specifications. Preflight counts
and local heuristics remain estimates. See [validation](validation.md) for checks.

## Phase 4: extensions

- [x] Official Python MCP SDK; configured stdio and Streamable HTTP servers
- [x] Lazy startup, namespaced tools, per-call approvals, and local plan-mode allowlists
- [x] Skill metadata discovery and on-demand instruction loading
- [x] Before/after shell hooks, failure blocking, backend reuse, and approval scopes
- [x] Markdown slash commands and parameterized prompt templates
- [x] Declarative plugin bundles with namespaced skills, commands, hooks, and recipes
- [x] Agent-authored extensions and atomic mid-session reload
- [x] Sequential recipes sharing budgets and stopping on errors or denial
- [x] Uncommitted/branch Git review through a temporary plan-mode workflow
- [x] Bounded web fetching and Brave/SearXNG search
- [x] Playwright MCP browser navigation, interaction, snapshots, and screenshot retention
- [x] Live local-model extension workflow and isolated browser validation
- [ ] Production Brave search request (API key not configured)

Implementation and setup are documented in [extensions](extensions.md), with tests
and live evidence in [validation](validation.md). Browser/MCP effects are outside
workspace undo, and model review findings still require human judgment.
Any integration with Veil should be a separate, explicit adapter-layer feature.

## Phase 5: local and frontier teamwork

- [x] Fresh-context workers with enforced tool restrictions and asyncio concurrency
- [x] Model routes per role and plan/build mode
- [x] Local-first escalation on failed commands, repeated calls, or iteration limits
- [x] Compact evidence handoffs, denial-aware routing, and shared concurrent budgets
- [x] On-demand oracle and read-only local shadow comparisons
- [x] Two/three-model councils with isolated worktrees, checks, and optional judge
- [x] Explicit candidate acceptance with conflict checks and undo
- [x] Session-owned background processes with bounded output polling and cleanup
- [x] Bounded SSH runner protocol with Docker-only remote shells and patch return
- [x] Logged-task replay on isolated snapshots with optional system-prompt experiments
- [x] JSONL by default for `smok -p`, CLI commands, examples, and validation
- [ ] Live local-to-frontier comparison (frontier API key unavailable)
- [ ] Live homelab SSH/Docker validation (runner not configured; daemon stopped)

See [teamwork](teamwork.md) and [validation](validation.md). Shadow scores measure
text agreement, not correctness. Worktrees isolate files but are not host-command
sandboxes. Remote jobs return reviewable patches and never merge automatically.

## Phase 6: GUI and desktop

- [x] Loopback FastAPI server and React/shadcn-style Radix components over WebSockets
- [x] Streaming chat, collapsible tool calls, and per-change accept/reject approvals
- [x] Reconnectable approval controls with exact-scope always-allow rules
- [x] Model/session pickers, CLI watching, context pin/drop, usage and cost previews
- [x] Checkpoint restoration and isolated branches with saved conversation context
- [x] Settings forms for model profiles, API keys, MCP servers, and permission rules
- [x] Validated drag/drop images and vision payloads in both provider adapters
- [x] Reviewed, revocable, expiring read-only local session links
- [x] Browser dictation with review-before-send and explicit compatibility handling
- [x] Background activity, workflow controls, and bounded process output inspection
- [x] Self-contained Tauri macOS app with workspace picker, native window, and tray
- [x] Backend tests, desktop/mobile browser checks, and live local-model GUI evaluation
- [ ] Live frontier vision and physical microphone transcription checks
- [ ] Native validation on Intel macOS/Linux; signing and notarization for distribution

See [GUI setup and boundaries](gui.md) and [validation](validation.md). Share links
remain on loopback. Voice availability and speech-service privacy depend on the browser.
The local native build is usable; external distribution remains a release task.

## Phase 7: evaluation and model tuning

This milestone extends the original six-phase plan, as requested after Phase 6.

- [x] Twenty coding tasks with independent graders and explicit changed-file scope
- [x] Fifteen tuning tasks and five separate holdout tasks
- [x] CI checks that reject broken fixtures and accept reference solutions
- [x] Lean/full prompts, enforced tool-set presets, and exact/whole-file edit controls
- [x] Settings forms, routed model behavior, session persistence, and profile-aware previews
- [x] Repeated model/profile matrices with recorded source/task/config fingerprints
- [x] Atomic JSON/Markdown reports, paired comparisons, and complete usage/cost accounting
- [x] Shared run budgets, per-task deadlines, and compatible interrupted-run resume
- [x] Live local-model tuning and held-out validation, with failures retained
- [ ] Frontier model comparison and repeated multi-model quality measurements

See [evaluation and model tuning](evaluation.md). Small fixture results are not public
benchmark scores; profiles are never silently promoted to workspace defaults.

## Phase 8: reliability and completion

This milestone follows the Phase 7 timeout findings and the user's selected scope.

- [x] Review current edits before the next response, with fresh review after further changes
- [x] Avoid redundant final-response review requests and repeated scans after reads
- [x] Remember denied actions per turn across equivalent file tools and shell timeouts
- [x] Optional turn deadlines spanning routing, approvals, tools, and model responses
- [x] Preserve partial edits, checkpoints, valid history, and usage on expiry
- [x] CLI flags, saved session limits, GUI controls, and explicit incomplete outcomes
- [x] Cancellation, denial, review, CLI, and GUI regression coverage
- [x] Focused live replay of selected Phase 7 failures, including retained failures
- [x] Rebuilt and verified native/package artifacts, including the macOS bundle signature
- [x] Retain known written bytes for consecutive edits while detecting external changes
- [x] Advertise and enforce fixture execution capabilities before generation
- [x] Repeated interval/CSV completion under the original 180-second deadline
- [x] Stronger interval boundary checks, saved-repair rescoring, and fresh validation

See [reliable completion and turn limits](reliability.md). In 0.8.1, all six original
interval/CSV replay turns completed within the deadline, and CSV passed all three
checks. Stronger grading exposed two interval boundary errors; three fresh attempts
then passed the clarified contract in 77–96 seconds. Historical failures and grading
limitations remain recorded in [validation](validation.md). Broader repeated,
multi-model, and fresh held-out measurements remain open work.

## Phase 9: setup and release readiness

This milestone builds on Phase 8 with first-use guidance and repeatable local validation.

- [x] Read-only `--doctor` diagnostics with human-readable and JSON output
- [x] Explicit, bounded model discovery without generation or automatic installation
- [x] Configuration/credential checks with secret-safe reports and actionable fixes
- [x] Desktop welcome/sidebar setup checks and a path back to model settings
- [x] Reusable archive verification for source parity, version alignment, and private-file exclusion
- [x] Reusable native bundled-server checks in a disposable workspace
- [x] Package checks in CI after frontend and distribution builds
- [x] Setup guide separating local checks, model discovery, and actual generation

Validation and built artifacts are recorded in [validation](validation.md). Local
artifact checks do not certify public-release readiness; signing, licensing, other
platforms, and the outstanding live integrations remain explicit release work.

## Phase 10: project workflow reliability

This milestone extends evaluation to multi-file changes with real project test commands.

- [x] Six new standard-library projects, with four tuning and two held-out cases
- [x] Read-only public tests, scoped guidance, and separate independent graders
- [x] Explicit shell opt-in and exact permitted check commands in the model's context
- [x] Successful project checks must cover the final source snapshot
- [x] Monotonic event times and per-request/tool timing, including interrupted work
- [x] Remaining-time guidance during bounded turns, including routed primary work
- [x] Source package validation includes the new suite, references, and graders
- [x] Regression, live replay, workflow, and local artifact validation
- [x] Public CLI-port boundary regressions and current-request coverage in reviews
- [x] Explicit reasoning control in compatible profiles, CLI sessions, and model settings
- [x] Three complete passing replays each for CLI-port and manifest regressions
- [ ] Further completion and correctness tuning, validated on additional fresh tasks

See [project workflow reliability](project-workflows.md). Evaluation distinguishes
correctness, actual verification, and completion. The original dependency-ordering
holdout is now a known regression case; further tuning on it is not held-out evidence.
Both final dependency-ordering replays passed within 180 seconds. The six new project
attempts passed four cases under a separate 300-second limit. The 0.10.1 follow-up
passed all three repeats each for configuration CLI-port validation and manifest
completion under that same limit, using the opt-in no-thinking profile. The public
configuration tests were strengthened; its task fingerprint changed. Model defaults
remain unchanged. Full outcomes, retained failures, and the limits of these known-task
measurements are recorded in [validation](validation.md).

## Phase 11: model qualification and profile selection

This milestone compares provider-default and no-thinking settings on new projects,
then makes explicit profile selection easier without changing workspace defaults.

- [x] Four fresh project fixtures with public checks and independent graders
- [x] Reference checks and plausible faulty repairs exposing independent coverage
- [x] Labeled effective profiles and task splits in the frozen evaluation plan
- [x] Offline qualification with complete paired coverage and separate split analysis
- [x] Separate correctness/completion regressions and shared-pass latency comparisons
- [x] Explicit YAML export of tested controls without connection or default settings
- [x] Fixed local comparison: four tasks, two profiles, two repeats, original 300-second limit
- [x] Updated validation evidence and verified local app/packages
- [x] Release/join regression coverage, bounded empty-response recovery, and explicit repair profile
- [x] Three complete passes for each current regression fixture with the same opt-in Gemma profile
- [x] Additional fresh tasks across models in Phase 12

See [model qualification](model-qualification.md) for the predeclared comparison and
selection rules. No profile is automatically promoted; inspected cases become known
regressions rather than remaining fresh holdouts.

The original local comparison passed 5/8 no-thinking attempts and 2/8 default attempts:
three paired gains and no paired regressions. The candidate remains opt-in. Release
selection failed all attempts, and join completion was inconsistent; there is no
general reliability or speed claim. The [paired results](model-qualification-results.md)
and [validation](validation.md) retain these failures and explain the selection limits.

The 0.11.1 [repair follow-up](repair-reliability.md) records three complete release
passes and three complete join passes in separate fixed validations using the same
Gemma no-thinking profile, runtime, and 300-second/16-call limits. Public regressions
now cover the observed syntax, validation, ordering, and nested-copy defects.
All failed trials and the interrupted wording experiment remain recorded; the
Qwen27 profile still failed release selection. Model defaults remain unchanged,
and these known-task results do not establish general model reliability.

## Phase 12: fresh-project qualification across models

This milestone compares the installed Gemma and Qwen repair profiles on four new
projects and makes the model/profile pair an explicit selection.

- [x] Four fresh projects with immutable public checks and independent graders
- [x] Failing seeds, passing references, and faulty repairs proving independent coverage
- [x] Alternating complete model/variant order across tasks and repeats
- [x] Cross-model qualification with matched coverage and separate regression/latency evidence
- [x] Explicit role-based YAML export to the selected model without default changes
- [x] Fixed comparison: four projects, two installed models, two repeats
- [x] Recorded results, local package/app checks, and updated usage guidance

See [cross-model qualification](cross-model-qualification.md). These projects become
known regressions after inspection; the milestone does not imply general model
superiority or automatically promote a model.

The run recorded all 16 planned attempts without adaptive changes or reruns. The
[post-run contract audit](phase12-contract-audit.md) gives **Qwen 4/8 and Gemma 1/8**
complete passes. It corrected one false pass in the frozen grader's deletion-shape
coverage and rechecked every saved repair without inference. Original reports remain
intact. The comparison verdict is a tradeoff; defaults remain unchanged.

## Phase 12 repair follow-up: 0.12.1

- [x] Public input/parser regressions and thirteen faulty repairs rejected by both checks
- [x] Offline coverage replay of all sixteen original saved repairs, without inference
- [x] Stable request prefixes with transient, accounted countdown hints
- [x] Related edits reach a check before review; unreviewed completion stays withheld
- [x] Complete automated regression suite, retained trial receipts, and model results guide
- [x] Repeated Gemma rename/event passes on the recorded earlier runtime
- [ ] Repeated byte-range and command-parser completion on the final runtime
- [ ] Live qualification of the latest review sequence, followed by additional fresh tasks

See the [repair follow-up](phase12-repair.md) and [model results](model-results.md).
All failed pilots, the interrupted Qwen3.8 run, and changed experimental limits remain
visible. Historical live results must not be attributed to the latest review timing.

## Source preview and future releases

The public source repository is [Mpawlowski5467/smok](https://github.com/Mpawlowski5467/smok).
It is a development preview with setup, capability, evaluation, and contribution guides.
This does not publish a package or a signed desktop installer.

Before wider distribution, select a source/artwork license, confirm package naming,
complete live provider and platform exit checks, and finish signing/notarization.
Measured local model support and remaining reliability work are documented separately
from implemented adapter routes in the [model results](model-results.md).
