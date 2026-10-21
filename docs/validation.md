# Validation

October 19–21, 2026 (America/Chicago). Tested locally on Apple Silicon macOS with
Python 3.12. Historical sections describe their recorded versions, not the current
runtime. For a concise comparison, see [model results](model-results.md).

## Source publication checks: Smok 0.12.1

October 21, 2026. The [current receipt](publication-validation.json) records this
source preview separately from the original 0.12.0 model comparison and artifacts.

- **580 Python tests pass in 25.00 seconds.** The latest review sequence is covered
  with and without checkpoints, after related edits/checks, when checks are skipped,
  and at the call cap. Unreviewed draft completion is withheld from output and history.
- Ruff lint passes and all **160 Python files** pass formatting. The uv lock resolves
  offline without changes. The first full run exposed four scripted expectations of
  the old review timing; the fixtures now account for the required final review while
  retaining their approval, scope, context, and completion assertions.
- TypeScript and the production frontend build pass. Both Playwright desktop/mobile
  scenarios pass in **4.2 seconds**. Documentation screenshots were refreshed from
  that deterministic run. The UI version now comes from package metadata.
- The rebuilt **0.12.1 Apple Silicon app** passes the bundled-server check: versions,
  local/ad-hoc signature, authentication, setup diagnostics, asset parity, saved
  deadlines, shutdown, listener closure, and session-lock release. It makes **zero
  generation requests**. This does not certify notarization or other platforms.

Wheel/source parity and private-file exclusion are checked with
`scripts/check_release.py`; the final local report is retained under
`dist/release-check-0.12.1.json`. The public source includes code, tests, guides,
screenshots, model profiles, and compact evidence. Generated model workspaces,
sessions, raw traces, dependency caches, environment secrets, and native binaries
remain ignored. Documentation links were checked locally before publication.

The [Phase 12 repair follow-up](phase12-repair.md) records all 13 trials and the
latest runtime changes. Its current public coverage rejects all ten incorrect
original repairs and retains all six correct repairs in an offline replay. Those
six are not six new complete passes: unfinished original attempts remain failures.

**Command-parser reliability is still unresolved.** The latest review-timing change
has not been tested with live models. Earlier Gemma rename/event successes and the
single whole-file byte-range pass belong to earlier frozen snapshots. No new model
default was selected. Hosted quality/billing/vision, live Docker/SSH, physical
microphone behavior, wider platforms, and public installer signing remain open.

## Phase 12: Smok 0.12.0

The [cross-model comparison](cross-model-qualification.md) adds four original
standard-library projects, alternating complete model/variant order, and explicit
selection of model/profile pairs. Cross-model export uses the roles `baseline` and
`candidate`, writes controls to the selected model, and excludes connection settings,
credentials, prices, and `default_model`. The original within-model qualification
interface remains supported and reproduces the Phase 11 result.

The [plan](phase12-plan.json) froze four projects × two models × two repeats before
inference. Both installed models used `focused-repair` (lean/minimal/no-thinking),
4,096 output tokens, a 300-second turn limit, and 16 calls. All 16 attempts finished;
none were rerun or replaced, and no source, fixture, profile, or limit changed during
the run. The run used 122 requests against its shared 256-request cap. Model/server
metadata matched before and after; no model was downloaded or default changed.

### Audited outcomes

| Model | Complete passes | Independent correctness | Final-file public verification | Completed turns |
| --- | ---: | ---: | ---: | ---: |
| Qwen3.6 27B MLX | **4/8** | 4/8 | 8/8 | 8/8 |
| Gemma4 26B | **1/8** | 2/8 | 5/8 | 5/8 |

| Project | Qwen passes | Gemma passes | Observed failures |
| --- | ---: | ---: | --- |
| Simultaneous renames | 2/2 | 1/2 | Gemma repeat 2 omitted change-list validation |
| Byte ranges | 1/2 | 0/2 | Gemma suffix parsing; both models omitted header-type validation in repeat 2 |
| Event replay | 1/2 | 0/2 | Qwen repeat 1 returned a forbidden deletion value field; Gemma omitted stream-list validation |
| Command arguments | 0/2 | 0/2 | Both Qwen attempts lost empty quoted words; Gemma timed out once and exhausted its response allowance once |

Gemma's first parser repair passed independent grading and final-file public checks
but timed out at 300.23 seconds before the turn completed. Its second parser attempt
stopped with `length`; pending tool calls were not executed. Its first byte-range
attempt exhausted 16 calls with incorrect code. These are distinct failure modes,
not successful repairs inferred from short elapsed time or a model's final message.

### Grading correction

The frozen grader originally counted **Qwen 5/8 and Gemma 1/8**. Source review found
that Qwen event replay repeat 1 returned `value: None` in a normalized deletion,
contrary to the existing prompt and reference. The frozen grader had not checked
that output shape. This was a grader defect, not a newly added task requirement.

After the complete fixed run and frozen-file audit, the grader was strengthened to
check exact deletion fields, a fresh output object, and unchanged input. A new
regression demonstrates a plausible faulty repair that passes public tests but
fails the corrected grader. Reference repairs still pass. All 16 saved final repairs
were then rechecked uniformly, without model calls or edits to generated files.
Exactly one full-pass result changed. The original reports, timing, completion,
verification evidence, and grader remain preserved in the frozen source archive.

The event-replay task fingerprint changes from
`118d3c41931a35a48cfebdccc93de9e8788425447bf35f2453aaaa2753f6903b` to
`f6defb661b9590fe2bf1de3e5b664c76b8f72e8809c40cd5c0a5631f08f2676b`.
Prompts, seed files, public tests, reference repairs, profiles, and limits are unchanged;
the other three task fingerprints are unchanged. The runtime source fingerprint is
unchanged. This is a post-run contract audit, not new fresh-task evidence.

Use the [contract audit](phase12-contract-audit.md) and its
[per-attempt receipt](phase12-contract-audit.json) for correctness claims. The
[frozen comparison](phase12-results.md) and [original evidence](phase12-evidence.json)
remain available with the correction prominently identified. All inspected projects
are now known regression fixtures despite retaining their original holdout label.

The comparison remains **tradeoff**. Only one pair passed both models, below the
predeclared minimum of three shared passes for latency selection. No general speed
or reliability claim is supported. Both [Qwen](../examples/models/phase12-qwen.yaml)
and [Gemma](../examples/models/phase12-gemma.yaml) profiles are exported as explicit
choices with the audit score and verdict; neither is automatically applied.

### Local validation and artifacts

The final suite passes **554 Python tests in 33.00 seconds**, with Ruff lint and
formatting clean. The new coverage includes reference/seed checks, five plausible
incorrect repairs caught independently, cross-model pairing and failure visibility,
model-specific exports, alternating execution order, and strict resume identity.
An initial sandboxed run blocked three existing local HTTP tests; the full suite
passed with loopback access, and passed again after the grading correction.

TypeScript and production frontend builds pass. Both desktop/mobile Playwright
scenarios pass in **5.7 seconds**. The rebuilt Apple Silicon 0.12.0 app passes the
complete bundled-server check: versions, local/ad-hoc signature, authentication,
workspace setup, offline diagnostics, compiled asset parity, deadline persistence,
shutdown, closed listener, and released session lock. It made zero generation
requests. Public signing/notarization and other platforms remain separate release work.

The [local validation receipt](phase12-artifacts.json) records these checks. Offline
wheel/source verification uses `scripts/check_release.py`, with the final receipt at
`dist/release-check-0.12.0.json`. The source package includes the corrected grader,
regression test, frozen plan, original comparison, contract audit, and both opt-in
profiles. Model traces and source snapshots remain retained locally under ignored
`evals/results/` rather than included in the package.

## Phase 11 repair follow-up: Smok 0.11.1

The final runtime and fixtures pass **534 Python tests in 24.74 seconds**. Ruff lint and
formatting pass for 149 Python files. Coverage includes one bounded retry of a clean
empty completion, no replay of tools, unchanged call/token/deadline limits,
transport/truncation rejection, cumulative review evidence, profile permissions,
and public tests rejecting eleven plausible incorrect repairs.

The [repair guide](repair-reliability.md) documents expanded public regressions for
strict version syntax and catalog validation, stable/RC ordering, first-equal ties,
and independent nested join rows. Original task prompts, seed source, reference
repairs, independent graders, allowed edit scope, and test command are unchanged.
The changed public tests produce new task fingerprints. These are known regression
fixtures, not fresh holdouts, even though the historical split label is retained.

The loop retries a clean empty completion once within existing budgets, displays the
retry in CLI/GUI, and replaces superseded automatic review prompts while preserving
the current cumulative diff, request, command evidence, and actual tool exchanges.
Shared guidance asks for batched related edits and concise code. A `focused-repair` variant selects the lean
prompt, minimal tools, and explicit no-thinking control without granting permissions.

### Retained trials

Each run was frozen before inference and executed serially, separately from builds
and regression suites. Every attempt remains recorded. All used **300 seconds and
16 calls per task**; only the explicitly labeled 8,192-token experiments varied the normal
4,096-token response allowance.

| Trial | Model/settings | Release passes | Join passes | Outcome |
| --- | --- | ---: | ---: | --- |
| Initial follow-up | Qwen3.6 27B, focused repair | 0/3 | 3/3 | One timeout; invalid release repairs |
| Corrected public coverage/review context | Qwen3.6 27B, focused repair | 0/3 | 3/3 | All three releases timed out |
| Default-thinking pilot | Qwen3.6 35B coding | 0/1 | — | Response truncated before editing |
| 8,192-output pilot | Qwen3.6 35B coding, default thinking | 0/1 | — | Response truncated before editing |
| No-thinking pilot | Qwen3.6 35B coding | 0/1 | — | Incorrect code; 16-call limit |
| Low-thinking pilot | Qwen3.8 27B | 0/1 | — | Response truncated before editing |
| No-thinking pilot | Gemma4 26B | 1/1 | — | Complete pass in 42.05 seconds |
| First fixed Gemma validation | Gemma4 26B, focused repair | 2/3 | 3/3 | All turns completed; one public verification failure |
| Stopped wording experiment | Gemma4 26B, stronger guidance | 0/1 completed | 0/1 | Two call-limit failures; one interrupted release, three unstarted cases |
| Explicit-container pilot | Gemma4 26B, focused repair | 1/1 | — | Complete pass in 71.3 seconds |
| Fixed validation with release diagnostics | Gemma4 26B, focused repair | 3/3 | 2/3 | Missing right-container validation; final edit unverified |
| Default-thinking pilot | Gemma4 26B | 0/1 | — | Response truncated before editing |
| 8,192-output pilot | Gemma4 26B, default thinking | 0/1 | — | Independent grader passed; timed out before verification |
| Final join validation | Gemma4 26B, focused repair | — | 3/3 | Complete passes with expanded container coverage |

The first Gemma validation's release repeat 2 accepted tuples and misread the failing
`records=()` case as an empty-list case. It then changed files without a final test
run. The independent grader passed, but public verification failed; the full result
remained a failure. A stronger-guidance experiment then reached the 16-call limit on
its first release and join attempts. It was stopped with two completed failures,
one interrupted release attempt, and three unstarted cases. This is an explicitly
recorded deviation from its [six-case plan](phase11-final-repair-plan.json), not a
complete validation. Its wording was reverted.

The public release fixture now separates list-container validation from record
validation and reports empty and nonempty tuples explicitly as invalid tuples,
while confirming that an empty list is valid. The earlier saved tuple-accepting
repair fails with this diagnostic. This clarifies the existing rule without
loosening it; the release task fingerprint changes again. The
[diagnostic pilot](phase11-diagnostic-pilot-plan.json) records its preflight and
conditional validation protocol.

That pilot passed, and its six-case validation passed all three releases and two
joins. Join repeat 2 raised `TypeError` for an invalid right container instead of
the required `ValueError` and finished without verifying its last edit. A new public
join regression checks invalid containers in indexing and on either side of a join,
including when the opposite side is empty. Both the saved repair and a separate
faulty repair are rejected. This changes the join task fingerprint, while the
prompt, contract, reference repair and independent grader remain unchanged.

Gemma's thinking-enabled pilots also failed: 4,096 tokens truncated before editing,
and 8,192 tokens produced an independently passing repair but timed out before
verification at 300.17 seconds. The selected profile retains no-thinking and 4,096
output tokens. The [final join plan](phase11-join-validation-plan.json) freezes three
attempts on the expanded join fixture. It reuses all three complete release passes
from the earlier fixed run because the runtime, release fixture, effective profile
and limits are unchanged. These are separate validations, not one new six-case run.

### Current task validation

| Task | Complete passes | Seconds per attempt | Model calls per attempt |
| --- | ---: | --- | --- |
| Release selection | 3/3 | 85.78, 91.40, 67.95 | 11, 11, 8 |
| Table joins | 3/3 | 34.57, 24.90, 42.36 | 8, 8, 10 |

Every selected attempt passed independent grading, allowed edit scope, the public
test command on final source bytes, and turn completion. The current task
fingerprints, runtime, profile, and limits match the retained receipts. No live
attempt exercised the clean-empty retry; controlled tests cover that behavior.
Local model metadata matched before and after all sampled model groups. The Gemma
profile is explicit and opt-in; Qwen27 still failed release selection. No model was
downloaded, and no provider or workspace model defaults were changed.

The [compact evidence](phase11-followup-results.json) retains per-attempt correctness,
verification, scope, completion, timing, usage, errors, raw report hashes, archived
source receipts, and model metadata. The original 0.11.0 qualification and all its
failed attempts remain unchanged. This adaptive process does not isolate the effect
of any individual change or establish general model superiority or a speed advantage.

### Local artifacts

TypeScript and production frontend builds pass. Both desktop/mobile Playwright
scenarios pass in **5.0 seconds**. The rebuilt Apple Silicon 0.11.1 app passes bundle
and server versions, its complete local/ad-hoc signature, authentication, workspace
bootstrap, offline diagnostics, compiled asset byte parity, deadline persistence,
shutdown, listener closure, and session-lock release. Native verification makes
zero generation requests; notarization and public distribution remain separate work.

The wheel and source archive are built offline and checked with
`scripts/check_release.py`; the final version/byte-parity receipt is
`dist/release-check-0.11.1.json`. The source archive includes the repair profiles,
all frozen plans, regression coverage, and compact evidence. Runtime traces, model
sessions, native binaries, and build caches remain excluded from the source package.

## Phase 11: Smok 0.11.0

- Python suite: **510 passed in 31.33 seconds**, including 40 new cases for fresh
  project contracts, reference repairs, public-test-passing faulty repairs, report
  consistency, paired regressions, incomplete plans, split separation, timing, and
  explicit offline profile export. The first restricted run passed 507 tests but
  could not bind three local HTTP/MCP test servers; the full rerun with loopback
  access passed.
- Ruff lint and formatting pass for 145 Python files. Locked offline dependency
  synchronization, TypeScript checks, and the production frontend build pass. Both
  desktop/mobile Playwright scenarios pass in **10.3 seconds** with a deterministic
  model fixture.
- The rebuilt 0.11.0 Apple Silicon app passes version/signature, authentication,
  bootstrap, offline diagnostics, compiled asset parity, deadline persistence,
  shutdown, listener closure, and session-lock checks. Native verification makes
  zero generation requests; signing remains local/ad-hoc.

The [fixed protocol](model-qualification.md) and [plan receipt](phase11-plan.json)
were saved before live inference. The four projects were new at the start; all
16 attempts use two predefined profiles, two repeats, the same installed model,
300-second deadlines, and 16-call limits. Selection rules and all source/task/grader
fingerprints are frozen. Builds and regression suites run separately from inference.

### Fixed profile comparison

All **16 planned attempts** finished their recorded outcome; none was removed or
retried in response to a result. Source, prompts, public tests, graders, limits, and
selection rules stayed fixed. The local Ollama server version, model digest, thinking
capabilities, and sampler metadata matched before and after the run.

| Profile | Full passes | Correct code | Verified final files | Completed turns | Timeouts | Other errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Provider default | 2/8 | 3/8 | 5/8 | 3/8 | 4 | 1 |
| Explicit `reasoning_effort: none` | 5/8 | 5/8 | 6/8 | 6/8 | 2 | 0 |

| Project | Default passes | No-thinking passes |
| --- | ---: | ---: |
| Stock reservations | 2/2 | 2/2 |
| Document splices | 0/2 | 2/2 |
| Release selection | 0/2 | 0/2 |
| Table joins | 0/2 | 1/2 |

Across eight matched pairs there were **three candidate gains, zero regressions,
two shared passes, and three shared failures**. The predeclared heuristic returns
`candidate_supported` because complete passes improved without an observed paired
correctness, verification, scope, or completion regression. This describes one small
local sample; it does not establish broad reliability. These four projects are now
known regression cases for subsequent tuning.

Only two pairs passed both profiles, both on stock reservations. Their time ordering
reversed between repeats: 127.89 versus 158.08 seconds, then 127.19 versus 118.50 seconds
(default versus candidate). Median candidate-minus-baseline time was **+10.75 seconds**.
The support for the candidate comes from additional complete passes. These measurements
do not establish a general speed advantage.

The default profile used 37 requests and 183,219 accounted tokens; the candidate used
45 requests and 221,981 accounted tokens. Six interrupted requests have estimated usage
(four default, two candidate). Summed recorded attempt durations were 1,790.57 and
1,735.23 seconds respectively; failed attempts remain included. Local API cost was $0,
excluding hardware and electricity. A single mid-run host-load observation is retained,
with thermal status unavailable; it cannot isolate the cause of timing or errors.

### Retained failures and explicit selection

- Default document repeat 1 produced correct, verified code but timed out while
  finishing. Repeat 2 completed and passed public tests, but raised `KeyError` for a
  non-string edit filename where the contract requires `ValueError`.
- Both default release attempts and candidate release repeat 1 timed out without
  passing independent correctness and final-file verification. Candidate repeat 2
  completed in 167.58 seconds and passed public tests, but its anchored regex with
  `match` accepted a version ending in a newline. The saved regex was inspected and
  that acceptance was confirmed without modifying the attempt.
- Default join repeat 1 returned an empty model response. Repeat 2 timed out and
  failed independent grading: matched right-hand rows were shared between output
  records, violating the independent nested-copy contract despite passing public tests.
- Candidate join repeat 1 timed out. Repeat 2 passed all checks and completed in
  149.19 seconds. The earlier failure remains part of its 1/2 result.

The [paired report](model-qualification-results.md) and its
[machine-readable form](model-qualification-results.json) show every pair, controls,
usage, source/run/report fingerprints, and interpretation limits. An explicit
[candidate profile](../examples/models/phase11-no-thinking.yaml) is available for
the same installed model:

```sh
uv run smok --config examples/models/phase11-no-thinking.yaml \
  --model ollama/qwen3.6:27b-mlx --turn-timeout 300
```

The export contains tested runtime controls and provenance, without provider
connection settings or `default_model`. No built-in or workspace model defaults
were changed. Release selection and join completion remain follow-up work; further
tuning should use these as known regressions and reserve additional fresh tasks.

The [compact evidence](phase11-results.json) preserves all 16 outcomes, final-file
verification, timing, usage estimates, the native receipt, and the before/after model
metadata check. Raw attempts remain locally in Git-ignored
`evals/results/20261020T023623.302756Z-phase11/`. The plan receipt records the hash of
the source snapshot saved before inference.

Offline wheel/source builds and `scripts/check_release.py` pass. All **61 wheel
source/asset files and 242 source-archive files** match the checkout. The archive
contains the three suites, all 30 graders/reference repairs, the qualification tool,
protocol, results, and exported profile; private traces and build caches are excluded.
Python, uv, npm, Cargo, and Tauri versions agree on 0.11.0. Final archive hashes are
recorded locally in `dist/release-check-0.11.0.json`.

## Phase 10 follow-up: Smok 0.10.1

- Python suite: **470 passed in 34.09 seconds**, including 18 new cases for
  retaining the current request in review after history dropping, full/lean profiles,
  separate approvals for batched edits, rejection of the observed CLI-port omission,
  explicit reasoning fields on the wire, invalid/unsupported settings, profile
  persistence, CLI resume/reset, and rejection without silent fallback.
- Ruff lint and formatting pass for 139 Python files. Locked offline dependency
  synchronization passes with the 0.10.1 package metadata.

The original manifest attempt used four model requests solely to maintain todos,
including one after successful tests. Small repairs no longer require a todo list;
full and lean prompts encourage independent calls with known inputs in one response.
All calls retain their own approvals and content checks. Review now includes the
current user request and asks the model to apply constraints across affected input
sources; tests only establish the behavior they exercise.

An initial follow-up candidate completed the configuration turn in five requests
and 252.41 seconds, but still missed CLI-port validation. The run was stopped after
that failure: one finished case, one retained interrupted manifest attempt, and four
unstarted cases. This failure remains recorded, with its original fixtures and source.

The configuration fixture now includes public regression tests accepting ports 1 and
65535 and rejecting CLI overrides -1, 0, and 65536. They also check that valid overrides
preserve the environment mapping. The original task prompt, allowed files, independent
grader, and reference repair are unchanged. **Its task fingerprint changed**; the new
results are not paired scores against the original fixture. The manifest fixture is
unchanged. Both tasks are now known regressions, not fresh holdout evidence.

With the new public tests and default model thinking, the next configuration attempt
produced correct code but hit 300.28 seconds before rerunning the tests after its last
repair. It remains a failed completion and failed final-file verification. That run
also retains one interrupted manifest attempt and four unstarted cases.

The installed Ollama 0.40.4 endpoint reports thinking on/off support and a default of
on for `qwen3.6:27b-mlx`. Smok now exposes an explicit `reasoning_effort` setting in
compatible profiles, the main CLI session, and desktop model settings. A separate
tiny probe with `none` returned `READY` in 0.82 seconds, one completion token, and no
streamed reasoning content. A separate tool-enabled probe returned the requested
`read_file` call in 4.38 seconds, with 25 completion tokens and no streamed reasoning
content; no tool was executed. These probes are distinct from the coding trials below.
Built-in provider/model defaults are unchanged; the new local profile is opt-in.

### Repeated CLI-port and manifest checks

The final `no-thinking` variant uses the same installed model, full prompt/tool set,
4,096-token output allowance, **300-second deadline**, and **16-call cap**. The only
profile override is `reasoning_effort: "none"`. All six attempts passed their independent
grader, scope check, project tests against the final files, and completed turn.

| Task | Repeat | Requests | Seconds | Result |
| --- | ---: | ---: | ---: | --- |
| Configuration precedence | 1 | 5 | 138.17 | Pass, complete |
| Manifest paths | 1 | 6 | 188.09 | Pass, complete |
| Configuration precedence | 2 | 9 | 269.59 | Pass, complete |
| Manifest paths | 2 | 6 | 167.38 | Pass, complete |
| Configuration precedence | 3 | 4 | 113.20 | Pass, complete |
| Manifest paths | 3 | 8 | 196.86 | Pass, complete |

The last manifest attempt initially failed its public check because an error omitted
the source line number. It repaired that error, passed the tests at 154.09 seconds,
and completed at 196.86 seconds. That intermediate failure remains in the evidence.
There were no denials. The second configuration attempt still made four todo calls;
workflow guidance does not guarantee their elimination.

These six attempts used 38 requests and 172,081 accounted tokens in 1,073.29 seconds.
Builds and regression suites ran separately from inference. Local API cost was $0,
excluding hardware and electricity. The small known-task sample does not isolate
the effects of prompt guidance, public tests, and reasoning control, or establish
reliability on other tasks/models. No profile was promoted to the default.

Use the explicit CLI flag or desktop model setting described in the
[project workflow guide](project-workflows.md#reasoning-control-for-the-local-model)
to select the tested mode.

- TypeScript and the production frontend build pass. Both desktop/mobile Playwright
  scenarios pass in **10.8 seconds**, using a deterministic model fixture. The new
  reasoning setting survives save/reload; its [settings view](screenshots/settings-tuning.png)
  was visually inspected.

- The rebuilt 0.10.1 Apple Silicon app passes the reusable native check: bundle and
  server versions, complete bundle signature, authentication, bootstrap, offline
  diagnostics, compiled asset parity, deadline persistence, shutdown, listener closure,
  and session lock release. It made zero generation requests. Signing remains local/ad-hoc.

- Offline wheel/source builds and `scripts/check_release.py` pass. All 61 wheel
  source/asset files and 228 source-archive files match the checkout, including the
  new tests, opt-in profile, compact evidence, and all 26 independent graders.
  Private eval traces and build caches are excluded. Python, uv, npm, Cargo, and
  Tauri versions agree on 0.10.1. Archive hashes are recorded locally in
  `dist/release-check-0.10.1.json`.

The [compact follow-up evidence](project-workflow-followup-results.json) retains the
original run, both failed candidate runs, final repeats, source/task/run fingerprints,
report hashes, timing, verification, probes, and native receipt. Raw reports remain
under Git-ignored `evals/results/`:

- Guidance-only candidate: `20261019T222631.887907Z-phase10/report.json`
- Public regression with default thinking: `20261019T223303.479430Z-phase10/report.json`
- Final opt-in profile: `20261019T224250.060416Z-phase10/report.json`

Interrupted candidate workspaces and source snapshots are retained; unstarted cases
have no assigned outcome. The earlier 0.10.0 evidence below remains historical.

## Phase 10: Smok 0.10.0

- Python suite: **452 passed in 30.56 seconds**, including 29 new workflow/evidence
  cases. Both public tests and independent graders reject all six broken seeds and
  accept their reference repairs. Coverage includes missing, failed, stale, interrupted,
  and superseded project checks; real shell verification on final bytes; command
  opt-in and schema validation; interrupted timing; nested deadline hints; cleanup
  of context between consumers; and the stable Anthropic cache block.
- Ruff lint and formatting pass for 137 Python files. Locked offline dependency sync,
  TypeScript checks, and the production frontend build pass. Both desktop/mobile
  Playwright scenarios pass in **5.4 seconds** using a deterministic model fixture.
- The final 0.10.0 Apple Silicon app was rebuilt and passed the reusable native check:
  bundle/server versions, full bundle signature, authentication, offline diagnostics,
  compiled asset parity, deadline persistence, shutdown, listener closure, and session
  lock release. These checks made zero generation requests. Signing remains local/ad-hoc.
- Offline wheel/source builds and `scripts/check_release.py` pass. All 61 wheel
  source/asset files and 224 source-archive files match the checkout. The source archive
  includes both evaluation suites, all 26 graders/reference repairs, the workflow
  regression tests, and compact results. Private eval traces, credentials, dependencies,
  and build caches are excluded. Python, uv, npm, Cargo, and Tauri agree on 0.10.0.

### Dependency-ordering regression

The pre-change 0.9.0 replay timed out in both initial attempts (full and lean-coding),
although both repairs passed the independent code check. The remaining baseline
repeats were stopped after reproduction: two completed failures, one retained interrupted
attempt, and three unstarted cases. No outcome is assigned to unstarted cases.

An initial remaining-time-hint candidate completed **3/4** attempts; all four repairs
passed code checks. That candidate's changing countdown was then moved out of the
stable cacheable system prefix into runtime context. Its trial remains separate from
the final source, and a regression test checks the stable Anthropic payload block.
Live frontier cache billing was not tested.

On the final implementation, both new attempts completed and passed under the original
**180-second deadline**: **160.40 seconds** for the default profile and **132.60 seconds**
for lean-coding. The independent grader and task prompt were unchanged. Earlier
timeouts remain in the evidence; these small samples do not establish a reliable
speed gain or a guarantee of completion. No model profile was promoted to the default.
Dependency ordering is now a known regression case, not fresh held-out evidence.

### New project workflows

The six-project run used the unchanged baseline profile, a separately recorded
**300-second deadline** and **16-call cap**, and one attempt per task. Four tasks are
in the tuning split and two in a new holdout split. Each must pass its independent
grader, preserve file scope, run the documented project tests against its final files,
and finish its turn. The tasks are small original fixtures, not external production
repositories or general benchmark scores.

| Task | Split | Code check | Project tests | Stop | Seconds |
| --- | --- | --- | --- | --- | ---: |
| Configuration precedence | tune | Fail | Pass | Complete | 264.09 |
| Invoice totals | tune | Pass | Pass | Complete | 220.37 |
| Catalog pagination | tune | Pass | Pass | Complete | 292.47 |
| JSONL redaction | tune | Pass | Pass | Complete | 235.26 |
| Manifest paths | holdout | Pass | Pass | Time limit | 300.15 |
| Retry client | holdout | Pass | Pass | Complete | 190.94 |

Overall, **4/6 attempts passed**: **3/4 tuning** and **1/2 holdout**. Five produced
correct code, five finished their turns, and all six ran successful public project
tests covering the final files. Scope checks passed throughout, with no tool errors
or denials. The public checks alone would have missed both failing outcomes.

- The configuration repair validated environment ports but accepted out-of-range CLI
  overrides. Its independent grader reported `invalid CLI port accepted`. This is a
  defect in the model-generated fixture repair, not Smok's own CLI.
- The manifest repair passed the independent grader and completed its public tests at
  267.41 seconds. It then updated its task list and started its final response at
  285.57 seconds; that response was interrupted by the original 300-second limit.
  Correct, tested edits are retained, but the turn is explicitly incomplete.

The six cases used 55 requests and 246,847 accounted input/output tokens, including
one estimated request from the interrupted response. Total elapsed time was 1,503.28
seconds. Client-observed model wait/stream time was 1,497.73 seconds; all tools together
took 0.73 seconds. These observations identify model response time as the dominant
cost in this run, not a guarantee about other projects or machines. Local API cost
was $0, excluding hardware and electricity. Builds and regression checks ran
separately from live inference.

No fixture, profile, or source change was made during this six-case run. The failures
remain recorded; the manifest timeout and configuration edge case need follow-up
before claiming broader reliability. After inspecting their outcomes, these six cases
should serve as regression fixtures; further tuning needs additional fresh holdouts.

Evidence: [compact project workflow results](project-workflow-results.json), including
source/task fingerprints, limits, separate completion/correctness/verification outcomes,
timing, usage, report hashes, and the native app receipt. The 300-second workflow
results must not be pooled with the 180-second dependency-ordering replays.

Raw evidence is retained locally under Git-ignored `evals/results/`:

- Pre-change replay: `20261019T210411.614056Z-phase7/report.json`
- Initial hint candidate: `20261019T211439.142217Z-phase7/report.json`
- Final dependency-ordering validation: `20261019T212559.472653Z-phase7/report.json`
- Project workflows: `20261019T213103.943864Z-phase10/report.json`

## Phase 9: Smok 0.9.0

- Python suite: **423 passed in 27.96 seconds**, including 34 new setup/release cases.
  Coverage includes offline/no-write behavior, saved credentials without environment
  mutation, missing keys/tools, malformed settings, metadata symlinks, bounded model
  discovery, redirect refusal, secret-safe errors, CLI conflicts/exit status, GUI
  authentication, and archives with stale bytes, missing modules, private files,
  symlinks, or mismatched versions.
- `ruff check .` and `ruff format --check .` pass; 128 Python files are formatted.
  Locked offline dependency sync and TypeScript/production frontend builds pass.
- Both Playwright desktop/mobile scenarios pass in **5.0 seconds**, including local
  setup results, a simulated model-connection failure, return to model settings, and
  connection controls visible without scrolling on both layouts. The reviewed
  [desktop](screenshots/setup-desktop.png) and [mobile](screenshots/setup-mobile.png)
  screenshots are retained. Browser tests use a deterministic model fixture.
- The CLI's offline and explicit connection checks passed against the installed
  `ollama/qwen3.6:27b-mlx` configuration. The explicit check obtained its model listing
  from the local endpoint. Both left an empty temporary workspace unchanged and made
  **zero generation requests**. Human-readable output was also checked in this project.
- The final 0.9.0 Apple Silicon app was rebuilt and passed the reusable
  `scripts/check_desktop.py` check: bundle/server versions, full signature, authentication,
  offline setup without a session, compiled asset parity, deadline save/resume/clear,
  graceful shutdown, listener closure, and writer-lock release. No generation request
  was made. The native app remains locally ad-hoc signed.
- Wheel/source distribution builds and `scripts/check_release.py` pass. All 61 wheel
  source/asset files match the checkout. The source archive contains the setup guide,
  screenshots, diagnostics, new regression tests, reusable verification scripts,
  compact evidence, and all 20 graders/reference repairs; private files and build
  caches are excluded. Python, uv, npm, Cargo, and Tauri versions agree on 0.9.0.

The setup guide and CLI/GUI distinguish local checks from model discovery and actual
generation/tool support. Default checks inspect PATH/configuration/credential presence
without creating a session or starting executables. Connection checks are explicit,
bounded, and omit credentials, URLs, and response bodies from reports. Unsupported
discovery remains visibly unverified. The new archive check is included in CI;
the workflow itself has not been run on a remote CI host in this workspace.

Evidence: [setup and native results](setup-results.json), with runtime/source hashes,
the two CLI reports, reviewed screenshot hashes, and bundled executable hashes.
Rerun the commands in [setup and local release checks](setup.md) for the current build.
Model discovery verifies catalog availability only. Actual generation/tool behavior,
public-release signing/notarization, other native targets, and the previously recorded
live integration checks remain separate validations.

## Phase 8 follow-up: Smok 0.8.1

- Python regression suite: **388 passed in 26.74 seconds**, with 11 additional
  cases covering consecutive reviewed writes, concurrent/unobserved-file protection,
  context invalidation, advertised execution capabilities, guessed tools, and
  out-of-scope file denials. Existing hook invalidation and approval-time checks pass.
- `ruff check .` and `ruff format --check .` pass; 122 Python files are formatted.
  Locked offline dependency sync, TypeScript checking, frontend compilation, and
  both Playwright scenarios pass (9.7 seconds for the browser run).
- The 0.8.1 Apple Silicon app was rebuilt before live inference. Its complete bundle
  signature and bundled-server checks pass: authentication, compiled assets, deadline
  validation/save/clear/resume, clean shutdown, listener closure, and writer-lock
  release. These checks made no model requests.
- Wheel and source distribution builds pass. All 60 wheel source/asset files and
  202 source-archive files match the working bytes. The archive includes the stronger
  interval fixture, all 20 graders/reference repairs, tests, and compact follow-up
  evidence. Private session/eval data, dependencies, and build caches remain excluded.

The interval timeout included 76.51 seconds generating a shell command that the
runner was configured to deny. The CSV attempt discarded knowledge of its own write,
then rejected a follow-up write and spent two additional model calls rereading and
retrying. Version 0.8.1 preserves known written bytes while retaining current-content
guards, focuses review on concrete defects, and exposes only the runner's authorizable
tools. Execution restrictions are stated before generation; graders and reference
solutions remain outside the model context.

### Original-task replay

All **six turns completed within the unchanged 180-second deadline**, with no tool
errors or denials. The run used three attempts per task, the same installed
`ollama/qwen3.6:27b-mlx` model, baseline profile, original task fingerprints,
12-iteration cap, and 4,096-token output allowance. Builds and tests did not overlap
inference. The runner's advertised tools and execution guidance changed in 0.8.1;
this is a workflow comparison, not an isolated measurement of the write-hash fix.

| Task | Repeat 1 | Repeat 2 | Repeat 3 | Completion |
| --- | ---: | ---: | ---: | --- |
| Interval merging | 160.71 s | 40.28 s | 46.94 s | 3/3 |
| Sales by region | 106.62 s | 100.23 s | 132.64 s | 3/3 |

The six attempts used 21 requests, 43,173 input and 7,175 output tokens, with 33,326
cache-read tokens and no estimated requests. Total elapsed time was 587.42 seconds;
local API cost was $0, excluding hardware and electricity. Fresh review corrected
an interval boundary error in the first attempt. A later CSV follow-up edit succeeded
without the previous read/retry failure.

### Stronger interval grading

The original grader accepted all six repairs, but it missed disjoint ranges with
consecutive integer endpoints. Expanded checks revealed that two interval repairs
incorrectly merged a positive gap: **4/6 original repairs pass the stronger checks**.
All three CSV repairs pass. Rescoring the saved 0.8.0 interval repair also exposes
this boundary error; its CSV repair passes. Raw reports remain unchanged.

The public interval prompt now specifies closed intervals on the number line:
touching means a shared endpoint, and every positive gap stays separate. The grader
adds adjacent-integer ranges and single-point intervals, plus a regression test
rejecting the erroneous `end + 1` implementation. The targeted evaluation test suite
passes **39 tests in 4.06 seconds**, including this additional test, after the full
388-test regression run. This changes the task fingerprint; fresh attempts are
recorded separately rather than presented as a paired quality comparison.

All **three fresh interval attempts completed and passed the expanded grader** in
76.84, 84.08, and 96.42 seconds, with 3, 4, and 3 model requests respectively. They
stayed in scope and recorded zero tool errors or denials. Together they used 22,480
accounted tokens, no estimated requests, and 257.34 seconds, under the same model,
baseline profile, and 180-second deadline. Review remained enabled throughout.

The original six replay turns and these three fresh turns all completed within the
deadline. These are selected, known tuning fixtures on one local installation;
repeated multi-model and fresh held-out measurements remain future work. No default
profile was changed, and individual effects of the combined fixes are not isolated.

Evidence: [compact follow-up results](reliability-followup-results.json),
[original-task replay](../evals/results/20261019T191420.278961Z-phase7/report.json),
[offline expanded checks](../evals/results/20261019T191420.278961Z-phase7/expanded-checks.json),
and [clarified interval run](../evals/results/20261019T192511.017206Z-phase7/report.json).
The compact artifact includes unchanged historical outcomes, expanded grading,
source/task fingerprints, profile/limits, usage, raw report SHA-256 hashes, and
native checks. Saved histories parse correctly and match recorded request counts.
Both new live runs exited successfully; raw attempts remain local and Git-ignored.

## Phase 8: Smok 0.8.0

- Python regression suite: **377 passed in 26.26 seconds**, including 20 new
  reliability cases. Coverage includes review before the first final response,
  external changes during generation, denied-action identity/reset, pending approval
  cancellation, saved deadlines, retained edits/usage, valid resumed history, undo,
  slow event consumers, routed GUI cleanup, and CLI incomplete exit status.
- `ruff check .` and `ruff format --check .` pass; 121 Python files are formatted.
  Locked offline dependency sync, TypeScript checking, and the production frontend
  build pass. Both Playwright browser scenarios pass in 5.5 seconds. The desktop
  scenario sets and reopens a 180-second turn limit. The reviewed control screenshot
  is retained at [turn limits](screenshots/turn-limits.png).
- The existing remote-workflow regression now completes with three model requests
  instead of four. Automatic review precedes the first final response after changes,
  while further edits still require fresh review. Permission and independent-grader
  boundaries remain in place.
- The Apple Silicon `Smok.app` was rebuilt as 0.8.0. Its complete ad-hoc bundle
  signature verifies. The bundled server passes authentication, compiled-asset byte
  parity, deadline validation/save/clear/resume, clean shutdown, listener closure,
  and writer-lock release checks, with no model request. The build script now verifies
  bundle signatures. Developer ID signing, hardened-runtime packaging, and notarization
  remain release work; see [native build details](gui.md).
- Wheel and source distribution builds pass. All 60 wheel source/asset files match
  the working source bytes. The source archive includes the reliability module,
  tests, guides, screenshot, compact evidence, all 20 graders and reference solutions,
  and the desktop build configuration. Private session/eval data, dependencies, and
  native build caches remain excluded.

### Focused timeout replay

Replayed three known Phase 7 baseline tuning failures using the same installed
`ollama/qwen3.6:27b-mlx` model, full prompt/tool profile, task fingerprints, 180-second
work deadline, 12-iteration cap, 4,096-token output allowance, and shared request/token
limits. Only declared file edits were approved. Shell and language-server requests
remained denied. The new runner permits ten seconds after the work deadline for
cleanup/reporting. No build or test job ran alongside this replay's inference.

| Task | Phase 7 completion | Phase 8 completion | Phase 8 code check |
| --- | --- | --- | --- |
| Deep merge | Timeout, 180.15 s | Complete, 128.29 s | Pass |
| Interval merging | Timeout, 180.23 s | Time limit, 180.14 s | Pass |
| Sales by region | Timeout, 180.18 s | Time limit, 180.24 s | Pass |

Completed passes increased from **0/3 to 1/3** on these selected cases; independent
code and file-scope checks remained **3/3**. Calls changed from 18 to 15, and accounted
tokens from 80,229 to 68,049. Both runs include two estimated requests. Cache-read input
counts were 47,543 and 33,640; elapsed totals were 540.56 and 488.67 seconds. Local API
cost was $0, excluding hardware and electricity.

**At 0.8.0, timeouts were only partly resolved.** Interval merging reached the deadline during
the model request following a denied shell check. Sales aggregation made further
edits, received a second review, and timed out in its sixth model request. Both retained
repairs that passed the checks available then, retained valid saved state, and
reported `time_limit`, not completion. The stronger 0.8.1 interval checks above
subsequently exposed a boundary error in that saved repair.
Fresh review after additional edits remains intentional; it was not disabled to
improve the completion count.

This is one attempt per selected known tuning failure, not fresh holdout evidence or
a general quality/speed claim. Core changes were evaluated together. Sampling/cache
effects remain uncontrolled, and the original Phase 7 tuning run initially overlapped
a native build. The default model profile is unchanged. Remaining completion failures
and repeated validation were the scope of the 0.8.1 follow-up above.

Evidence: [compact comparison and native checks](reliability-results.json),
[Phase 8 raw replay](../evals/results/20261019T183726.343379Z-phase7/report.json), and
[original Phase 7 tuning report](../evals/results/20261019T165203.572316Z-phase7/report.json).
The compact comparison records source/task fingerprints, exact profile/limits, usage
provenance, and raw report SHA-256 hashes. Original reports remain unchanged; no replay
case was retried. The replay's exit code 1 reflects its two recorded time limits, not a
runner crash. Raw attempts remain local and Git-ignored.

## Phase 7: Smok 0.7.0

- Python regression suite: **357 passed in 21.92 seconds**, including 46 new tuning
  and evaluation cases. All 20 graders reject broken seeds and accept their reference
  repairs. Coverage includes premature grader exits, file scope/symlink handling,
  profile validation, model switches during approval, worker/Plan intersections,
  candidate context estimates, actual usage, interrupted resume, and fingerprint checks.
- TypeScript checking, production frontend build, and both Playwright scenarios pass.
  The desktop scenario saves and reopens the prompt style, tool set, and edit format.
  A reviewed Settings image is retained at `docs/screenshots/settings-tuning.png`.
- The self-contained Apple Silicon `Smok.app` was rebuilt as 0.7.0. Its bundled server
  passed authentication, static asset, saved profile, context preview, and shutdown
  checks. A fresh fixture's estimated input context changed from 4,396 to 1,088 tokens
  when switching full guidance/all tools to lean guidance/minimal tools. These are
  local estimates, not provider billing counts. No model request was used for this check.
- Wheel/source distribution builds pass. The wheel matches source bytes and includes
  the tuning module and compiled GUI. The source archive includes all 20 graders,
  reference solutions, eval tooling, and documentation, with private state/results,
  dependency folders, and native build caches excluded.

### Local tuning and held-out comparison

Model: `ollama/qwen3.6:27b-mlx`, one attempt per task/profile. Both profiles used
the same 180-second task deadline, 12-iteration cap, 4,096-token output allowance,
240-request run cap, and two-million-token run budget. Only the declared file edits
were approved; shell and language-server requests were denied. Variant order alternated
across tasks. `lean-coding` changes the prompt and tool set together, with both edit
formats retained. Sampling used provider defaults; no deterministic seed was set.

| Split | Profile | Completed passes | Code checks | Calls | Accounted tokens | Estimated calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Tuning | baseline | 11/15 | 15/15 | 97 | 358,171 | 3 |
| Tuning | lean-coding | 13/15 | 14/15 | 89 | 240,817 | 2 |
| Holdout | baseline | 4/5 | 5/5 | 32 | 135,934 | 1 |
| Holdout | lean-coding | 4/5 | 5/5 | 32 | 111,968 | 1 |

The candidate used **32.8% fewer accounted tokens** on the tuning set and completed
deep merge and interval merging within the deadline where baseline timed out. All six
failed tuning attempts were timeouts. Baseline's four timed-out repairs passed their code
checks; the candidate's CSV repair also passed, while its natural-sort repair was
unfinished. Every attempt stayed within the allowed file scope.

Token totals combine provider usage with reserved estimates when an interrupted
request had no final usage. Tuning included 265,361 baseline and 168,806 candidate
cache-read input tokens. Total measured time was 1,828.29 versus 1,780.53 seconds;
one repetition, cache effects, and a native build overlapping the first four minutes
of tuning do not support a reliable speed claim. Local API cost was $0, excluding
hardware and electricity. Held-out inference ran without concurrent build or test jobs.

On the five untouched held-out tasks, both profiles completed **4/5** and passed
**5/5** independent code checks. Both dependency-ordering turns timed out after making
correct repairs. The unchanged candidate used **17.6% fewer accounted tokens** with
the same 32 requests. Baseline/candidate cache-read counts were 94,881/70,316, and
elapsed totals were 656.26/602.14 seconds. All 40 attempts stayed within task file scope.

This supports keeping lean-coding as an opt-in candidate for this installation, with
no demonstrated held-out completion gain. It does not establish general coding quality
or a reliable speed advantage. The original default profile is retained. Frontier
comparisons, repeated trials, and live edit-format comparisons remain future measurements;
the edit-format enforcement itself is covered by the regression suite.

Evidence: [compact results and case outcomes](evaluation-results.json),
[tuning report](../evals/results/20261019T165203.572316Z-phase7/report.json), and
[held-out report](../evals/results/20261019T175223.395010Z-phase7/report.json).
The compact artifact preserves source/task fingerprints, exact client profiles/limits,
usage provenance, and SHA-256 references to the complete raw reports. The raw runs and
attempt logs remain local and Git-ignored; the compact artifact is included in the source
distribution. Both matrices finished; their nonzero command exits reflect the recorded
timeouts, not runner crashes. No completed case was retried.

## Phase 6: Smok 0.6.0

- The 296-test Phase 5 suite continued to pass after the initial core image changes.
  The completed suite has 311 tests, including 15 new GUI/backend cases.
- Frontend TypeScript checking and Vite production compilation pass. Two Playwright
  browser scenarios pass on installed Chrome, covering desktop and 390px mobile
  layouts, live diff approval/reconnect, exact saved rules, settings, pinning,
  share preview/revocation, branch controls, image upload, and speech-event handling.
- GUI/backend cases cover Host/Origin/auth checks, websocket authorization, stale
  decisions, cancellation without granting, CLI writer-lock isolation, image format
  validation/capability gating/provider serialization, key permissions/redaction,
  stale settings revisions, CLI/GUI profile reuse, share immutability, and checkpoint
  restore/branch behavior, including background jobs in other workspace sessions.
  Slow-client queues use explicit snapshot resynchronization.
- The packaged native app launched its bundled Python server, served the compiled
  React assets, and opened a native workspace window. Native accessibility inspection
  confirmed the chat, mode/model selectors, Settings, and composer. Command-Q shut
  down the app and its loopback listener. The tray/menu and close-to-hide behavior
  are implemented; a separate manual tray-click test remains useful before release.
- A final bundled-server smoke check authenticated, loaded the compiled assets, and
  received `SMOK_READY` from the installed local Qwen model: one request, 2,416 input /
  38 output tokens, no estimated usage or tool calls. Parent-process disappearance
  shut down the server; SIGTERM closed its listener and released the session writer
  lock without server errors.
- The final wheel and source distribution include the built frontend and new sources;
  private workspace metadata, node_modules, build caches, and native target files
  remain excluded. The native macOS app is a local ad-hoc-signed build, not notarized.

Live local-model GUI evaluation: **6/6 stages passed** in **27.71 seconds**, using
`ollama/qwen3.6:27b-mlx`. It streamed real text over the WebSocket, reviewed an exact
edit, ran two unit checks, recorded provider usage, created/revoked a read-only share,
and branched/undid the fixture without changing the branch. Usage: **5 requests,
16,598 input / 394 output tokens**, 12,723 cache-read tokens, zero estimated requests.
Only `calculator.py` edits and the exact `python3 -m unittest -q` command could be
approved by this eval; no frontier endpoint or microphone was used.

Evidence: [live Phase 6 report](../evals/results/20261019T162012.237437Z-phase6/report.json).
Browser screenshots are saved under `web/test-results/` during tests, with reviewed
copies under `docs/screenshots/`. The native app is under
`desktop/src-tauri/target/release/bundle/macos/Smok.app`.

Remaining runtime checks: real frontier vision interpretation, physical microphone
transcription, native Intel macOS/Linux operation, and release signing/notarization.
Earlier Docker/homelab and frontier billing checks remain open as documented below.

## Phase 5: Smok 0.5.0

- `pytest -q`: **296 passed in 12.46 seconds** on the final source, including the
  earlier LSP/MCP/HTTP integration tests and 52 new Phase 5 cases.
- `ruff check .` and `ruff format --check .`: passed; 79 Python files formatted.
- Locked offline sync with the development group and optional LSP extra passed.
- Wheel and source distribution built; package inspection checks source-byte parity,
  bundled profiles/team modules/docs/examples, and exclusion of local state/eval results.
- Interactive PTY smoke passed: `/team`, `/jobs`, `/background`, `/poll`, `/stop`, `/exit`.
- Runner stdin framing was checked through both a pipe and a regular file; malformed
  requests were rejected before any model execution. `-p` JSON-by-default is covered.

New tests exercise concurrent independent contexts, enforced worker tools, role/mode
routes, evidence handoffs, denial-aware escalation, shared token/dollar reservations,
cancellation accounting, parent mode and permission changes, child diff approvals,
background output rings/deadlines/process cleanup, real Git snapshot/index/HEAD
isolation, tracked ignored files, staged deletions, disabled Git filters, candidate
selection/acceptance/undo, interrupted runs, fresh-permission replay, mixed older logs,
shadow comparison, remote archive validation, strict SSH argv, parallel remote
allocations, protocol execution, and conservative accounting after transport failure.

### Live local teamwork

`evals/phase5.py` passed **7/7 checks in 231.32 seconds** using the installed
`ollama/qwen3.6:27b-mlx` endpoint:

| Check | Independent evidence |
| --- | --- |
| Parallel fresh workers | Exact `COPPER-RAVEN-5197` marker; read-only main file unchanged |
| Council | Both independent worktree implementations passed arithmetic assertions; main untouched |
| Routed primary | Actual arithmetic repair and model-reported completion |
| Real-session replay | Recorded task replayed from its initial snapshot; check passed; main unchanged |
| Oracle | Fresh-context second opinion completed |
| Shadow | Local read-only answer contained the marker; exact text match reported as a heuristic |
| Background job | Polled `background-ok`, exit code zero |

Evidence: [Phase 5 report](../evals/results/20261019T152729.453642Z-phase5/report.json),
with retained worktrees, patches, per-worker sessions, and parent session
`20261019T152729Z-d9378d16`. These local artifacts are intentionally Git-ignored.
The endpoint reported **30 requests, 60,251 input tokens, 2,214 output tokens**, and
47,179 cache-read tokens; no usage estimates were needed. Two requests use a deliberately
non-local-marked test profile to exercise shadow routing and lack cache-price entries,
so their ledger cost is marked unpriced. All requests reached the same local endpoint.

Council and shadow use different profiles of the **same installed model**, not distinct
frontier models. This tests coordination, not comparative coding quality. Escalation
is covered with controlled provider fixtures; actual local-to-frontier handoff, live
frontier billing, and a real SSH homelab/Docker job remain unverified because credentials,
a runner, and a running Docker daemon are unavailable. Remote transport concurrency,
protocol, and Docker-only policy are tested without claiming a live container run.

## Phase 4: Smok 0.4.0

- `pytest -q`: **244 passed**, including real Python LSP, stdio MCP, Streamable HTTP
  MCP, local HTTP fetch/search, and Git review fixtures.
- `ruff check .` and `ruff format --check .`: passed.
- Locked offline sync with the development group and optional LSP extra passed.
- Wheel/source distributions build with the extension modules, examples, and docs;
  package inspection excludes local state, browser data, and eval results.
- Interactive PTY checks passed: `/extensions`, `/mcp`, `/reload`, `/help`, and `/exit`.
  One-shot command parameters, missing parameters, recipe denial exit status, and
  conflicting CLI actions are also covered by tests.
- All four supplied PNGs remain byte-identical.

New tests cover lazy skill disclosure, same-turn self-authoring/reload, atomic reload
failure, plugin namespaces, parameter substitution, symlink rejection, inactive
example hooks, and preservation of independently edited server settings. Hook tests
verify separate approval under auto-edit, stdin data without shell interpolation,
pre-action blocking, truthful post-action failures, timeout cleanup, read-hash
invalidation, plan-mode suspension, rejection of stale prepared actions, and Docker
stdin forwarding/cleanup through a mocked Docker command boundary.

MCP tests exercise real subprocess discovery/calls, error results, startup/call denial,
local plan-mode allowlists, timeout/cancellation and process cleanup, configuration
approval fingerprints, schema/argument validation, recursive schema recovery, external
reference refusal, and a real loopback Streamable HTTP server. Web tests cover private
DNS answers, numeric-address pinning, redirect checks, HTML extraction, body limits,
configured search, and credentials that cannot follow redirects. Git tests cover
staged/unstaged/untracked changes, an unborn repository, merge-base review, disabled
external diff drivers, untracked symlinks, and large-file truncation.

### Live extension workflow

Model: `ollama/qwen3.6:27b-mlx`. **5/5 stages passed** in **368.75 seconds**:

| Stage | Evidence |
| --- | --- |
| Markdown command → skill → exact repair → formatter hook | Arithmetic independently checked; hook marker and required calls verified |
| MCP and web | Real stdio echo, local search/fetch, exact `EMBER-QUARTZ-6284` saved to `proof.txt` |
| Agent-authored extension | New SKILL.md written, reloaded, and loaded in the same session |
| Parameterized recipe | Both steps completed with shared history and run accounting |
| Git review | Seeded subtraction regression identified at `calc.py:4`; file unchanged |

Evidence: `evals/results/20261019T053926.201069Z-phase4/report.json`, plus its event log,
Git fixture, plugin files, and session `20261019T053926Z-0289cfcb`. Usage was **23 model
requests, 105,911 input tokens and 2,560 output tokens**, all provider-reported; the
local endpoint also reported 74,986 cache-read input tokens. This does not validate
frontier cache billing or estimate general coding quality.

The initial review found the real defect but overstated severity as P0 and speculated
about files from earlier conversation. The review prompt now defines priorities and
requires the current diff as the scope source. A fresh CLI `--review --json` run
completed in four requests, reported only the changed file/line, assigned P1 with a
severity rationale, and stated coverage limits. Its original output is retained in
`evals/results/20261019T053926.201069Z-phase4/review-calibration.jsonl`. This is a focused
check; finding quality and severity remain model judgments, not guaranteed grades.

### Live browser integration

The **official Playwright MCP 0.0.83** server, installed in a temporary directory,
controlled an existing Chrome binary with a new isolated headless profile. Smok
discovered its tools, navigated a temporary loopback page, read its accessibility
snapshot, clicked “Add one,” verified `Count: 1`, and saved a returned PNG through
its MCP artifact handling. No personal browser profile or account was used.

The successful run took **1.42 seconds** after local fixture setup; evidence is
`evals/results/20261019T144233.444864Z-phase4-browser/report.json`. Its screenshot is
under that fixture's `.smok/artifacts/`. Earlier browser probes are retained: the
evaluation was adapted to this server version's file-linked navigation snapshots,
`target` click argument, and required screenshot `scale`; the explicit snapshot,
click, and screenshot then passed through the normal registry schemas.

### Remaining external checks

The live web search fixture implements the SearXNG JSON shape. **No production Brave
request was made** because its API key is not configured; auth/header/result contracts
are tested locally. MCP OAuth is not implemented. Browser/MCP processes are separate
from Docker shell isolation, and external effects are outside workspace undo. Docker
hook stdin/command routing uses the existing shell backend, but the earlier live Docker
check remains open because its daemon is stopped. Live frontier API and remote GitHub
CI checks also remain open. Phase 4 has not been published.

## Phase 3: Smok 0.3.0

- `pytest -q`: **179 passed**, including the real Python LSP integration.
- `ruff check .` and `ruff format --check .`: passed.
- Locked offline dependency sync passed with the optional LSP extra.
- Wheel/source builds and package inspection cover the context/session modules,
  Tree-sitter dependencies, CLI entry point, and excluded local state/results.
- Interactive PTY checks passed: Tab plan toggle, file pin/drop, repository map,
  cost preview, usage, todos, session listing, clear, mode, and exit. A separate
  `--continue --json --compact` process reopened that session successfully.
- All four original PNG assets remain byte-identical.

New coverage exercises session locks, partial-record recovery, damaged records,
foreign workspaces, older event-only logs, interrupted tool placeholders, and resume
without replay or old read grants. A 20-turn deterministic regression repeatedly
compacts and resumes four times while retaining the task constraint and usage totals.
Compaction tests cover complete tool groups, failed/truncated/tool-bearing summaries,
nonrecursive summary reuse, context limits, concurrent-turn exclusion, and handoff
folding without altering original history.

Output tests verify retained tails of reads, failed shell commands, and schema errors;
archive paging across registry lifetimes; explicit storage caps; and metadata/path
boundaries. Repo-map tests cover Python, JS, TS/TSX, ranking, ignores, symlinks, content
refresh, and outlines not granting edit access. Todo tests cover plan mode and invalid
states. Budget tests cover preflight rejection, unknown prices, cache accounting,
disconnected/invalid-usage reservations, and clear preserving run caps.

Anthropic count requests, stable cache markers, cache usage normalization, and
OpenAI-compatible cache counters are covered by mocked HTTP/SSE. Preflight counts
remain estimates; only final response usage is provider-reported. No live frontier
count/cache-hit billing validation was run because a frontier API key is not available
in this shell. The earlier live Docker and remote CI checks remain open.

### Phase 3 live local session

Model: `ollama/qwen3.6:27b-mlx`. The live run verified planning/todos, a retained
output tail, session recovery without stale read grants, automatic compaction,
continuation of a coding task, and editable handoff into a fresh session.

| Check | Result |
| --- | --- |
| Plan and persistent todos without file changes | Pass |
| Retrieve `BRONZE-PINE-4721` beyond a 12,000-character preview | Pass |
| Resume and auto-compact older history | Pass; estimate reduced from 6,439 to 526 tokens |
| Preserve goal, exact public name/docstring, and pending work | Pass |
| Fix addition; independently verify positive, negative, zero, and float cases | Pass |
| Keep changes confined to `calc.py`; leave `notes.txt` intact | Pass |
| Export handoff and recall the exact function/docstring in a fresh session | Pass after continuation |

The initial evaluation reached its **600-second overall deadline during handoff**,
after its repair stages and independent check passed. A separate continuation resumed
the saved session, completed export, and verified fresh-session recall in **118.91
seconds**. Both reports remain intact:

- Initial run and timeout: `evals/results/20261019T050803.488176Z-phase3/report.json`
- Successful continuation: `evals/results/20261019T051853.311891Z-phase3/report.json`

The original session ledger records 15 requests, 44,975 input tokens and 7,644 output
tokens, including **one reserved estimate** for the interrupted request. The fresh
session records one request with 1,891 input and 125 output tokens, all provider-reported.
The fixture, journals, archived output, and handoff remain alongside the initial report.
Final independent checks again verified arithmetic, exact name/docstring, unchanged
notes, change scope, and exact handoff recall after continuation.

The runner now defaults to 900 seconds and initializes its fixture as a separate Git
repository. The initial fixture inherited the parent results-directory ignore rule,
so its checkpoint manifests were empty; that run adds no checkpoint/undo coverage.
The corrected setup passed a direct before/after checkpoint-diff check. Existing
checkpoint/self-check integration coverage remains in the automated suite and Phase 2
live evals. These are focused smoke checks, not general coding benchmarks.

## Phase 2: Smok 0.2.0

- `pytest -q`: **114 passed**, including the real Python LSP integration.
- `ruff check .` and `ruff format --check .`: passed.
- `uv build --offline`: wheel and source distribution built successfully.
- Wheel inspection confirmed Phase 2 modules, bundled model profiles, version, and
  optional LSP dependency metadata. The source archive includes the new eval suite
  and excludes local state, environments, results, and caches.
- Interactive PTY check passed: startup, Tab plan toggle, `/mode`, persisted
  `/permissions auto-edit`, `/allow git status`, `/rules`, `/checkpoints`, `/help`,
  and clean exit. Headless undo is also covered by the automated suite.
- All four original PNG assets remain byte-identical.

New coverage includes exact/overlapping matches, CRLF preservation, large ranged
reads, changed hashes and symlink targets during approval, metadata exclusions in
search, full-argv permission matching, literal remembered file grants, plan-mode
mutation rejection under full-auto, scoped instruction freshness, and settings
persistence. Checkpoint tests exercise real staged/dirty Git state, non-Git workspaces,
repository subdirectories, deletion/symlink/mode restoration, later-edit conflicts,
changed ignore rules, locks, cancellation, and repeated self-checks after further edits.

The real Python LSP check verifies undefined-name diagnostics, definition and reference
locations, edits clearing diagnostics, external edits reintroducing diagnostics, and
server cleanup. Protocol tests cover stale/unversioned reports, missing reports,
UTF-16 columns, rejected server edits, malformed frames, and missing servers.

### Phase 2 live local evals

Model: `ollama/qwen3.6:27b-mlx`, using disposable fixtures with approved file edits,
local test commands, and Python server startup. Each task passed an independent Python
check, its required successful tool calls, a self-check pass, and full fixture restoration
through undo.

| Task | Result | Calls | Input tokens | Output tokens | Seconds | Undo |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Search, edit, verify | Pass | 6 | 12,477 | 595 | 67.21 | Pass |
| LSP repair | Pass | 7 | 13,945 | 1,140 | 96.15 | Pass |

**2/2 passed.** Evidence: `evals/results/20261019T043918.476888Z/report.json`, with
per-task JSONL logs and produced files alongside it. These small smoke tasks are not
estimates of general coding performance.

### Remaining runtime checks

Docker sandbox argument construction, network defaults, metadata mounts, no-pull/no-
fallback behavior, timeout/cancellation cleanup, and missing-Docker errors passed
mocked tests. **No real container was run:** the Docker CLI is installed but the local
OrbStack/Docker daemon is stopped. Live Docker validation remains open.

The earlier live Claude/Qwen comparison remains open because no frontier API key is
configured in this shell. Remote GitHub CI has not been run. The Phase 2 implementation
is local and has not been published.

## Phase 1 historical checks

- `pytest -q`: **61 passed**.
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `uv build --offline`: wheel and source distribution built successfully.
- Wheel inspection confirmed the CLI and bundled YAML model profiles are included.
- Source distribution inspection found no virtual environment, session logs, eval
  results, Python caches, or test caches.
- Interactive terminal smoke: startup, `/help`, `/model`, `/clear`, `/exit` passed.
- All four supplied PNG assets match the originals byte for byte.

Tests cover both streaming protocols, fragmented and interleaved tool calls,
truncated/error streams, resource cleanup, cross-provider message serialization,
endpoint override isolation, approval denial, stale writes, path traversal and
symlinks, shell timeout/cancellation/output bounds, JSONL logs, and iteration caps.

## Phase 1 historical live local coding evals

Endpoint: local Ollama at `127.0.0.1:11434`. Model: `qwen3.6:27b-mlx`.
File writes were approved in fresh temporary fixtures; model shell calls were denied.
Each outcome was checked by a separate deterministic Python check.

| Task | Result | Model calls | Input tokens | Output tokens | Seconds |
| --- | --- | ---: | ---: | ---: | ---: |
| Fix addition | Pass | 3 | 2,557 | 289 | 42.04 |
| Normalize slug | Pass | 5 | 5,359 | 826 | 60.88 |
| Summarize CSV | Pass | 3 | 2,600 | 414 | 27.19 |
| Update config | Pass | 3 | 2,601 | 225 | 16.86 |
| Implement chunks | Pass | 3 | 3,018 | 477 | 42.18 |

**5/5 passed.** These are small smoke tasks, not evidence of general coding benchmark
performance. Token counts are provider-reported totals across the requests, including
repeated context. No frontier API was used for these runs.

Local evidence (Git-ignored, available in this checkout):

- `evals/results/20261019T040809.685216Z/report.json` — first task
- `evals/results/20261019T040939.746477Z/report.json` — remaining four tasks

Those directories also contain event logs and generated files. UTC timestamps in
their names fall on October 19; the local test date was October 18.

## Provider coverage

Anthropic and OpenAI adapters passed synthetic protocol tests. Neither has been
tested against a live frontier API because no corresponding API key was configured
in this shell. The Phase 1 exit check requiring the same task on Claude and Qwen is
therefore still open. Gemini, OpenRouter, and LM Studio routes also need live checks.

The GitHub workflow installs ripgrep and the LSP extra. The GUI was added in Phase 6; see the evidence above.
Routing and shadow comparisons are implemented in Phase 5; sessions and compaction
are implemented in Phase 3.
