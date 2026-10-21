# Model results and methodology

These are measurements from Smok's development on Apple Silicon macOS, not a public
benchmark or a general ranking of model families. Model names are the exact installed
endpoint selectors. The plans record the effective controls and, for later runs,
model/server metadata. Provider sampling defaults, local load, cache state, and small
sample sizes limit comparisons. Historical results belong to their frozen runtime.

## What counts as success

**Complete pass = independent correctness + allowed edit scope + completed turn.**
Phase 10–12 additionally require the permitted public test command to succeed on the
final source snapshot. A later edit invalidates an earlier passing check. A timeout,
call limit, truncated response, invalid compaction, or missing final check remains a
failed attempt even if an independent grader finds correct code.

All attempts are counted, including failed trials. Repeated tasks are not independent
new projects. Once a task is inspected for tuning, it becomes a known regression;
its historical `holdout` label does not make later runs fresh qualification evidence.
Adaptive pilots and fixed repeated validations are reported separately.

## Original controlled comparisons

| Suite / version | Design and controls | Outcome | Evidence |
| --- | --- | --- | --- |
| Phase 7 / 0.7 | Qwen3.6 27B MLX, baseline vs lean/coding; 15 tuning + 5 holdout tasks, one repeat; 180 seconds, 12 calls | Tuning **11/15 vs 13/15**; holdout **4/5 vs 4/5**. Candidate reduced accounted tokens by 32.8% / 17.6%, but regressed natural-sort correctness. Both held-out dependency-order repairs timed out. | [Guide](evaluation.md), [receipt](evaluation-results.json) |
| Phase 10 / 0.10 | Qwen3.6 27B MLX baseline; six multi-file projects, one repeat; 300 seconds, 16 calls | **4/6** complete passes. CLI-port validation and manifest completion failed. | [Guide](project-workflows.md), [receipt](project-workflow-results.json) |
| Phase 11 / 0.11 | Qwen3.6 27B MLX, default vs no thinking; four new projects × two repeats; 300 seconds, 16 calls | **2/8 vs 5/8**. Three paired gains, no paired full-pass regression. Release selection failed; joins were inconsistent. | [Paired results](model-qualification-results.md), [receipt](model-qualification-results.json) |
| Phase 12 / 0.12 | Qwen3.6 27B MLX vs Gemma4 26B, both lean/minimal/no thinking; four new projects × two repeats; 300 seconds, 16 calls | Audited **4/8 vs 1/8**. Insufficient shared-pass coverage to select on latency. | [Contract audit](phase12-contract-audit.md), [receipt](phase12-contract-audit.json) |

The original Phase 12 grader counted one Qwen event replay as a pass despite an
extra forbidden deletion field. The post-run audit corrected the grader and rechecked
all 16 saved repairs without inference or file edits. Qwen changed from 5/8 to 4/8;
Gemma remained 1/8. Original reports remain intact and are labeled with the correction.

Phase 11's qualification verdict is `candidate_supported` for that sample. Phase 12's
verdict is `tradeoff`; one shared-pass pair is below the declared three-pair minimum
for latency selection. Neither result changes defaults or establishes general quality.

## Known-regression follow-ups

| Work | Model and profile | Complete passes | Interpretation / evidence |
| --- | --- | ---: | --- |
| Interval merging and CSV aggregation / 0.8.1 | Qwen3.6 27B MLX | 3/3 each on the final respective fixtures | Interval grading was strengthened after earlier false passes. Fresh repetitions on that clarified contract took 77–96 seconds. [Validation](validation.md#stronger-interval-grading) |
| CLI-port and manifest / 0.10.1 | Qwen3.6 27B MLX, no thinking | 3/3 each | Known projects under the original 300-second turn limit; public port coverage expanded. [Receipt](project-workflow-followup-results.json) |
| Release selection and table joins / 0.11.1 | Gemma4 26B, focused repair | 3/3 each | Separate fixed validations on the same runtime/profile and respective final fixtures; not one new six-attempt run. Qwen release failures and unsuccessful Gemma trials remain recorded. [Follow-up](repair-reliability.md) |
| Input validation / 0.12.1, before latest review timing | Gemma4 26B, focused repair | Renames 2/2; events 2/2; byte ranges 0/2 | Byte failures were empty-header validation and correct-but-unverified work at the call limit. [Receipt](phase12-input-validation-results.json) |
| Whole-file pilot / 0.12.1, before latest review timing | Gemma4 26B, no thinking, whole-file writes | Byte ranges 1/1; parser 0/1 | Explicit 20-call cap rather than 16; byte pass 53.16 seconds, parser stopped on invalid compaction at 194.04 seconds. This is a pilot, not repeated validation. [Receipt](phase12-whole-file-pilot-results.json) |

### Parser recovery trials

These follow-ups use the same final parser fixture and independent grader. Every
attempt is retained; adaptive pilots and fixed validations are separate rows. The
explicit-sampling trials use installed Gemma4 26B with temperature 1.0 / top-p 0.95
unless the row says otherwise. Time, output, and call limits remain 300 seconds,
4,096 tokens, and 16 calls.

| Frozen configuration | Design | Complete passes | Evidence |
| --- | --- | ---: | --- |
| Published 0.12.1 review sequence; sampler fields omitted | Pilot | 1/1; 220.30 s / 11 calls | [Receipt](phase12-review-parser-pilot-results.json) |
| Same published controls | Fixed three repeats | 1/3; two call-limit failures | [Receipt](phase12-review-parser-validation-results.json) |
| 0.12.2 compaction read notice + newest-check preview; explicit sampling | Pilot | 1/1; 176.87 s / 13 calls | [Receipt](phase12-parser-recovery-pilot-results.json) |
| Same recovery controls | Fixed three repeats | 1/3; truncation and call-limit failures | [Receipt](phase12-parser-recovery-validation-results.json) |
| Same recovery runtime, temperature 0.0 | Pilot | 0/1; truncation at 88.27 s / 5 calls | [Receipt](phase12-parser-greedy-pilot-results.json) |
| Bounded truncation retry + call-budget hint + impossible-compaction skip | Pilot | 0/1; invalid compaction at 75.42 s / 14 calls | [Receipt](phase12-parser-budget-pilot-results.json) |
| Same recovery plus concise implementation/whole-string guidance; 32K context | Pilot | 1/1; 90.55 s / 16 calls | [Receipt](phase12-parser-focused-pilot-results.json) |
| Same focused controls; 32K context | Fixed three repeats | 1/3; two call-limit failures, one with independently correct code | [Receipt](phase12-parser-focused-validation-results.json) |
| Same focused runtime/sampling; **64K context** | Fixed three repeats | **3/3**; 89.16, 87.88, 98.68 s; 14, 13, 13 calls | [Receipt](phase12-parser-context-validation-results.json) |

The [parser follow-up](phase12-parser-resolution.md) records the diagnoses, frozen
plans, sampling audit, and later context-profile validation. Omitted sampler fields
use endpoint behavior; installed metadata alone did not establish the effective
historical values. No default model or profile is selected by these trials.
The [follow-up evidence index](phase12-parser-evidence.json) links all nine new runs
and 17 finished attempts without pooling their differing configurations.

## Models exercised during repair experiments

| Exact local selector | Recorded experience |
| --- | --- |
| `ollama/qwen3.6:27b-mlx` | Main Phase 7/10/11/12 comparisons. No-thinking helped selected known repairs, but release selection and parser follow-ups still failed. |
| `ollama/gemma4:26b` | Repeated release/join and rename/event successes. Original Phase 12 score was 1/8; the latest known-parser validation passed 3/3 with 64K context, while 32K remained 1/3. Byte handling needs current-runtime coverage. |
| `ollama/qwen3.6:35b-a3b-coding` | Release-selection pilots failed with truncation or incorrect repairs; Phase 12 no-thinking parser pilot timed out after 13 requests. |
| `ollama/qwen3.8:27b` | Parser pilot completed but reordered duplicate keys incorrectly. A planned eight-case repair run was stopped after three timeouts and one byte-range pass; one case was interrupted and three unstarted. A separate low-reasoning/8,192-output/600-second parser pilot timed out without applying a repair. |

The [Phase 11 follow-up](repair-reliability.md) and
[Phase 12 repair guide](phase12-repair.md) retain failures and changed controls.
The [Phase 12 evidence index](phase12-repair-evidence.json) links all 13 follow-up
trials: 28 finished attempts, one interrupted attempt, and three unstarted cases.
These heterogeneous trials are not pooled into a model success rate.

## Current limitations and next validation

Parser completion with the original 32K working context remains inconsistent: the
published review sequence and both fixed recovery validations each passed 1/3.
The latest runtime adds bounded recovery, explicit sampling, and call-budget guidance;
those mechanics do not guarantee a correct, completed model repair.
The separate 64K-context validation passed all three attempts with correct code,
allowed scope, final-file public verification, and completed turns. This small known-task
sample supports documenting that opt-in configuration; it does not establish a causal
effect, general model ranking, or fresh-project reliability.

Further validation must keep the runtime and controls frozen, retain every result,
and use new projects for fresh qualification after this known regression is tuned.
More reasoning, a larger output allowance, or more calls are separate configurations;
success under those settings cannot be credited to the original limits.

The live results use local models. Hosted adapter protocol tests, mock workers,
browser fixtures, and native packaging checks do not establish live frontier model
quality, Docker/SSH operation, microphone transcription, or vision interpretation.

## Reproduce and inspect

Start with [contributing](../CONTRIBUTING.md#add-or-run-an-evaluation) and the
[eval commands](../evals/README.md). Configuration examples live in
[`examples/models`](../examples/models). Exporting a profile is an explicit action;
connection settings, keys, and the default model are not exported.

Committed JSON receipts include per-attempt outcomes, limits, source/task/profile
fingerprints, usage, and hashes. Full raw events, generated files, and frozen archives
are retained locally under ignored `evals/results/`, not published in this checkout.
Those paths and hashes identify the development evidence; they are not downloadable
attachments or an independent audit. Running the suites creates new evidence and
does not promise identical model output. See [validation](validation.md) for the
separate automated and packaging results.
