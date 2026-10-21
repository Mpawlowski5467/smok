# Phase 12 command-parser follow-up

This follows the [0.12.1 repair experiments](phase12-repair.md). The parser is a
known regression, not a fresh qualification task. The original contract, allowed
edits, public tests, reference repair, and independent grader remain unchanged in
this follow-up. A complete pass still requires correctness, allowed scope, a
successful public check on the final files, and a completed turn.

## Published runtime baseline

The [review-sequence pilot](phase12-review-parser-pilot-results.json) passed in
220.30 seconds with 11 requests. Its separate
[three-repeat plan](phase12-review-parser-validation-plan.json) keeps the same
runtime, model, fixture, and original limits: 4,096 output tokens, 180 seconds per
request, 300 seconds per turn, and 16 calls including compaction and review.
The [fixed results](phase12-review-parser-validation-results.json) contain **one
complete pass out of three**: two call-limit failures at 206.19 and 281.55 seconds,
then a pass at 106.44 seconds with 10 calls. Every planned attempt finished and was
audited against its frozen source and unchanged model metadata before edits began.

The first repeat exposed a recovery problem: compaction cleared file-read hashes,
then two edits to `arguments/options.py` were rejected because the model had not
reread the file. The proposed second edit would have corrected the trailing-newline
key defect, but no edit was applied. The turn exhausted its call budget. File-read
checks must remain enforced; compaction needs to tell the model that fresh reads
are required before further edits.

Another attempt repeatedly wrote unfinished, duplicate lexer implementations and
consumed calls on compaction. This is a model failure, not evidence that the
completion requirements or independent grader should be relaxed.

## Sampling audit

Previous receipts correctly captured installed model metadata and omitted sampler
fields in Smok's request profiles. That metadata did **not** establish which
sampling values the compatibility endpoint applied. In
[Ollama 0.40.4's compatibility conversion](https://github.com/ollama/ollama/blob/v0.40.4/openai/openai.go#L706-L727),
omitted `temperature` and `top_p` become `1.0`, overriding model parameters for
those fields. Gemma's recorded model parameters include `top_p=0.95`.

[Google's Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4#best_practices)
recommends temperature 1.0, top-p 0.95, and top-k 64. A trial with explicit
temperature/top-p is a changed configuration. Historical results remain attached
to their original requests; they cannot be relabeled as tests of the new controls.
No evidence here isolates a causal sampling effect or supports changing the
default model.

## Runtime recovery and explicit controls — 0.12.2

Compaction now appends a runtime notice after the retained history, telling the
model to reread existing files before editing. The notice is included in the
compaction size calculation and saved conversation. File-read hashes still clear;
failed compaction preserves both history and prior reads. The turn countdown no
longer discourages reads needed after compaction or stale-read errors.

Review lists recorded commands newest first, so a long earlier failure cannot push
the final check out of the bounded review preview. Original command evidence stays
in chronological order in logs and state. Checks, permissions, deadlines, and
completion requirements are unchanged.

Optional `temperature` and `top_p` controls are validated, sent on compatible API
requests, exposed in model Settings, retained on CLI resume, and included in eval
fingerprints and selected-profile exports. Null omits a field; zero is preserved.
Older reports are validated against their original hashes before absent optional
controls are normalized for comparison/export. No saved report is rewritten.

The [recovery pilot](phase12-parser-recovery-pilot-plan.json) uses the new runtime
with [this explicit Gemma profile](../examples/models/phase12-parser-gemma.yaml):
temperature 1.0, top-p 0.95, lean/minimal/no thinking, and the original per-attempt
limits. Installed top-k metadata remains 64; Smok does not send a top-k override.
This combines runtime and profile changes, so its result cannot isolate either effect.

Before live inference, **605 Python tests**, Ruff checks, the production web build,
and **two Playwright tests** passed. The new coverage includes actual compaction
followed by a fresh read/edit, retained stale-read rejection, newest-check review,
exact sampling request fields, invalid controls, saved settings, CLI resume, and
qualification export from legacy reports. Browser checks save and reload zero
temperature and top-p 0.95. These automated checks establish mechanics, not live
model repair quality.

## Recovery trial results

The [recovery pilot result](phase12-parser-recovery-pilot-results.json) is a complete
pass in **176.87 seconds / 13 calls**. It recovered from two malformed tool calls,
fixed the parser, checked the final files, and completed within the original limits.

The separate [fixed validation](phase12-parser-recovery-validation-results.json)
finished all three planned repetitions at **1/3 complete passes**. Repeat 1 exhausted
the response allowance before applying a repair (115.54 seconds, four calls).
Repeat 2 passed (129.65 seconds, 12 calls). Repeat 3 reached the call limit with an
incorrect repair (200.50 seconds, 16 calls). After compaction, that last attempt did
reread `arguments/options.py`; the runtime recovery path worked, but repeated lexer
rewrites still consumed the available calls. The pilot is not pooled with this run,
and these results do not establish an improvement over the earlier 1/3 baseline.

## Lower-temperature experiment

The [temperature-zero pilot plan](phase12-parser-greedy-pilot-plan.json) changes only
the profile's temperature from 1.0 to 0.0 relative to the recovery trials. It retains
top-p 0.95, the same runtime and final fixture, and 4,096 output tokens / 300 seconds
/ 16 calls. This tests whether more concentrated sampling reduces unfinished drafts;
it does not supply a parser solution or alter the checks. The
[separate opt-in profile](../examples/models/phase12-parser-gemma-greedy.yaml) keeps
this experimental setting distinct from the vendor-sampling trial and global defaults.
Even repeated success on this known task would not establish fresh-project quality
or guarantee deterministic output.

The [temperature-zero result](phase12-parser-greedy-pilot-results.json) failed after
**88.27 seconds / five calls** with an output-token truncation. No repair was applied.
It does not support selecting temperature zero, and no repeated validation was run
for that profile.

## Bounded recovery and focused edits

The next runtime revision exposes the remaining model-call count, allows one bounded
retry of a truncated task response, and skips automatic compaction when even the
smallest valid summary could not shrink history. A truncated response executes none
of its pending tool calls; earlier successful actions remain, and the retry consumes
the original time, token, and request limits. A second truncation fails. Structured
summaries retain their existing validation and do not use the task-response retry.

The [budget pilot](phase12-parser-budget-pilot-results.json) still failed: invalid
compaction after **75.42 seconds / 14 calls**, with the original history retained.
It rewrote the lexer but left an invalid newline in an assignment key accepted.
This failed pilot remains part of the evidence.

Shared coding guidance was then shortened to ask for one complete implementation,
narrow changes to the failing function, and `re.fullmatch` for whole-string Python
validation. The [focused pilot](phase12-parser-focused-pilot-results.json) passed in
**90.55 seconds / 16 calls**, including independent correctness, final-file public
verification, and turn completion. It had no call-budget margin. No task-specific
solution, generated-file edit, reference repair, or grader change was supplied.

Before this pilot, the runtime passed **614 Python tests**, Ruff checks, the production
web build, and **two Playwright tests**. The subsequent guidance-only change passed
52 focused context/runtime/tuning tests. The new mechanical coverage checks discarded
truncated tool calls, retained earlier work, the single-retry cap, original deadlines,
shared budgets, exact context-hint accounting, and skipped impossible compaction.
These tests do not establish model repair quality.

The separate [focused validation](phase12-parser-focused-validation-results.json)
finished at **1/3 complete passes**. Repeat 1 passed in 133.79 seconds / 13 calls.
Repeat 2 reached 16 calls in 167.22 seconds with an incorrect lexer. Repeat 3 reached
16 calls in 148.37 seconds with independently correct code, but its final edit had
no subsequent passing public check and the turn did not complete. Earlier passing
checks do not verify those later bytes. All failures count; the successful pilot is
not pooled into the fixed run. These results do not establish improved completion.

## Separate working-context validation

The [64K-context plan](phase12-parser-context-validation-plan.json) freezes three
repetitions on the same runtime, task, model, and sampling controls. It changes only
Smok's working context from **32,768 to 65,536**. The installed model's `/api/show`
metadata reports a 262,144-token capacity. This profile changes the harness's working
limit; it does not request a different server-side model configuration.

The failed second focused repeat spent three model calls on compaction, then needed
fresh reads. The wider working limit tests whether retaining more history reduces
that overhead. The plan records the context change explicitly; it is not a result
under all original Phase 12 controls. Per-attempt limits remain 4,096 output tokens,
180 seconds per request, 300 seconds per turn, and 16 calls. The shared budget remains
48 requests / 800,000 accounted tokens. All three attempts must finish unchanged and
be audited before any further runtime edits. No model default is changed.

The [fixed results](phase12-parser-context-validation-results.json) are **3/3 complete
passes**: **89.16 / 87.88 / 98.68 seconds**, using **14 / 13 / 13 calls**. All three
passed independent correctness, scope, tool checks, verification on their final files,
and turn completion. The run used 40 of 48 requests and 379,993 accounted input/output
tokens. Runtime, task, profile, source archive, and model/server metadata matched the
frozen plan at completion. No attempt was replaced or omitted.

The 64K configuration is therefore available as an explicit, measured option for
this known regression. The smaller-context fixed run remains 1/3, and a three-attempt
sample does not establish general reliability or isolate causation. Fresh-project
qualification and current-runtime byte-range repetitions remain open. The
[evidence index](phase12-parser-evidence.json) retains all nine new runs and 17 finished
attempts, alongside the prior trial index, without pooling their outcomes.

Final publication checks passed **614 Python tests in 29.65 seconds**, Ruff lint and
formatting for 166 Python files, the offline lock check, the production frontend,
and **two browser tests in 5.4 seconds**. The rebuilt 0.12.2 Apple Silicon app passed
the bundled-server check without generation. See [validation](validation.md) and the
[receipt](phase12-parser-artifacts.json) for scope and package checks.

To create a new local run with these controls:

```sh
uv run python evals/run.py --suite phase12 --split holdout \
  --model ollama/gemma4:26b --variant focused-repair \
  --config examples/models/phase12-parser-gemma-context.yaml \
  --task command-arguments --repeats 3 --allow-tools --allow-shell \
  --task-timeout 300 --max-iterations 16 \
  --max-requests 48 --budget-tokens 800000
```

This requires the exact installed model selector and creates new evidence. It does
not reproduce identical outputs or make the inspected task fresh again. A larger
working context can consume more memory and input tokens; the profile is an explicit
choice for this experiment, not a universal setting.
