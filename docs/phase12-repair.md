# Phase 12 input and parser repair follow-up — Smok 0.12.1

This follows the [audited Phase 12 results](phase12-contract-audit.md). The four
projects are now known regressions. Expanded public feedback supports repair;
it does not turn these cases into fresh qualification evidence.

## Public regressions

The public fixtures now check invalid containers and fields at both rename entry
points, range/header/response input types, list-only event streams, exact normalized
deletion fields, empty quoted words, adjacent quoted fragments, quote/escape errors,
and complete ASCII assignment keys. Invalid inputs must raise the contract's
`ValueError`, including when an input is empty. A deletion's normalized output must
omit `value`; a put with `value=None` remains valid.

The prompt, seed modules, reference repairs, permitted edits, permitted shell
command, and audited independent graders are unchanged. Each task fingerprint
changes because its public tests changed. The independent checks still cover cases
outside the public examples, including nested aliasing and Unicode boundaries.

Thirteen controlled faulty repairs verify that public failures identify the observed
defects, including dropped plain word separators, reordered duplicate keys, and an
empty header treated as absent. The
[current offline coverage receipt](phase12-repair-empty-header-coverage.json) replays the
expanded public tests against copies of all 16 saved repairs: all 10 incorrect
repairs fail and all 6 correct repairs pass. No model was called and no original
repair or result was edited. A correct repair from an unfinished turn remains an
original failure; this coverage audit does not count as new model verification.

## Live protocol

The [four-case pilot](phase12-repair-pilot-plan.json) freezes one attempt per project
with the installed `ollama/gemma4:26b` and the existing `focused-repair` variant.
It uses lean guidance, minimal tools and disabled thinking, with 4,096 output tokens,
300 seconds and 16 model calls per attempt. The shared pilot cap is 64 requests and
800,000 tokens. Runtime source and per-attempt limits match the original Phase 12
run. No sampler or default setting changes.

Runs execute serially without concurrent builds or regression suites. A complete
pass requires independent correctness, allowed edit scope, public verification on
the final source bytes, and a completed turn. Every planned outcome is retained.
Separate fixed repetitions follow a successful pilot; changes after a failure
require a new frozen plan and remain separate evidence.

## Pilot findings

The first pilot completed all four planned attempts: renaming and event replay
passed; byte ranges and command parsing failed. Its [results](phase12-repair-pilot-results.json)
remain intact. Byte ranges accepted Unicode digits despite the ASCII-only contract.
The parser preserved empty words but repeatedly edited its lexer while leaving a
trailing-newline key accepted. It reached the 16-call limit with incorrect,
unverified final code at 250.64 seconds.

The public byte-range checks now reject Unicode digits in every range form and
trailing characters. Parser diagnostics demonstrate that escaped or quoted newlines
are correctly retained by the lexer but invalid inside the assignment key. Input
validation failures name the called function, its arguments, and the actual result
or exception type. Each new validation test reports its first failure, avoiding
long repeated tracebacks while still checking every case once preceding cases pass.
These changes preserve all original public examples and acceptance requirements.
The [initial coverage receipt](phase12-repair-coverage.json) and first source archive
retain the previous public-test version.

The [diagnostic pilot](phase12-diagnostic-pilot-plan.json) freezes the two failed
projects with the same model, runtime and per-attempt limits, sharing 32 requests
and 400,000 tokens. No reference repair or independent grader changed.
Its [results](phase12-diagnostic-pilot-results.json) show a complete byte-range pass
in 59.22 seconds and a parser timeout at 300.20 seconds with incorrect, unverified
code. Clearer feedback did not establish Gemma parser reliability.

The separate [Qwen parser pilot](phase12-parser-qwen-pilot-plan.json) uses the
installed `ollama/qwen3.6:27b-mlx`, the same final parser fixture and the same runtime
controls and per-attempt limits. It shares at most 16 requests and 300,000 tokens.
This is an adaptive repair experiment, not a new paired qualification comparison.
Its [result](phase12-parser-qwen-pilot-results.json) also timed out at 300.23 seconds,
with incorrect and unverified code after five model calls. Public checks identified
lost empty quoted words and an accepted trailing-newline key.

## Runtime guidance

Smok 0.12.1 adds concise shared coding guidance: validate types before operating on
inputs, track presence separately from truthiness when empty values are valid, and
use full-string validation for exact grammars. It calls out Python's `$` match before
a final newline and `\d` accepting non-ASCII digits. This applies to both full and
lean prompts; it supplies no fixture solution or private test. In this first runtime
snapshot, review timing, permissions, output allowance, completion requirements and
deadlines were unchanged. The later review-sequencing change is documented below.

The [guidance pilot](phase12-guidance-pilot-plan.json) freezes a new runtime snapshot
for Gemma on the unchanged final parser fixture. Earlier outcomes remain attached
to their original runtime fingerprints. The focused runtime/fixture regression
suite passed 93 tests; lint and formatting passed before this pilot.
The [guidance-pilot result](phase12-guidance-pilot-results.json) passed correctness,
scope, final-file public verification and completion in 176.38 seconds (12 calls).

The [parser validation plan](phase12-parser-validation-plan.json) freezes three new
attempts with that same runtime, fixture, profile and per-attempt limits, with a
shared cap of 48 requests and 700,000 tokens. These repetitions are separate from
the adaptive pilots. The [fixed results](phase12-parser-validation-results.json)
contain one full pass out of three: one response exhausted its output allowance,
one completed and passed in 150.35 seconds, and one produced independently correct
code but omitted public verification after its final edit. The last attempt remains
a failure even though its code was correct.

The [coding-model pilot](phase12-parser-coding-pilot-plan.json) tests the already
installed `ollama/qwen3.6:35b-a3b-coding` on the same final parser fixture and 0.12.1
runtime. Its model metadata, including the installed sampler defaults, is recorded
in the plan. Runtime controls and per-attempt limits are unchanged. The failed
Gemma validation is retained rather than pooled with this separate pilot.
Its [result](phase12-parser-coding-pilot-results.json) timed out after 13 calls
with incorrect, unverified code. One command outside the allowlist was denied and
was not executed.

## Stable request prefixes

The turn countdown previously changed near the start of the system prompt on every
request. Version 0.12.1 now adds that countdown to the request tail as a transient
runtime note. Saved history and tool results stay unchanged. Token accounting
includes the note exactly once, including provider-counted requests, context limits,
and usage reservations. Compaction and handoff keep their JSON-only requests.
Anthropic cache markers stop before the transient note, including when adjacent
user messages or tool results are merged. This adapter behavior is tested locally;
no live Anthropic request was made.

The shared workflow guidance also asks for concise code and permitted checks before
speculative rewrites. It remains approximately the size of the original guidance;
the existing small-context compaction regression passes with its original limit.
In this snapshot, review timing, permissions, samplers, output allowances, and
deadlines were unchanged.
The public parser checks now explicitly cover plain ASCII separators and quoted
literal newlines. No prompt contract, reference repair, or independent grader changed.

Eight runtime tests cover prefix stability, unchanged history, token accounting,
context limits, cache boundaries, and compaction. The full suite passed **573 tests**;
Ruff lint and formatting passed for all 160 Python files before live trials.

The [Qwen27 completion pilot](phase12-completion-pilot-results.json) and
[Gemma completion pilot](phase12-completion-gemma-pilot-results.json) both timed out
at 300 seconds. Their raw cache counters show reuse of conversation tokens, but
these adaptive trials do not isolate a speed effect or establish parser reliability.
Gemma narrowed its public failures to the trailing-newline assignment key and did
not complete its correction. Both failures remain part of the evidence.

The [Qwen3.8 pilot plan](phase12-parser-qwen38-pilot-plan.json) freezes one attempt
with the already installed `ollama/qwen3.8:27b`, the same current runtime and task,
and the original per-attempt limits. It uses the same explicit no-thinking profile;
provider metadata and unchanged sampler defaults are recorded. This is an additional
repair experiment, not a replacement for the original paired comparison.
Its [result](phase12-parser-qwen38-pilot-results.json) completed in 188.34 seconds
and passed the public checks, but independent grading caught duplicate-key ordering:
deleting a prior key before assigning its new value moved it to the end. The existing
contract requires the position of the first occurrence to remain unchanged.

A new public case compares ordered key/value pairs after two replacements. It
exposes that failure without changing the contract, seeds, references, or independent
grader. The controlled mutation is rejected by both checks. All 40 focused
fixture/runtime tests pass, and the final offline coverage still rejects the 10
incorrect original repairs while retaining the six correct ones.

## Original-limit validation and interruption

The [repair validation plan](phase12-repair-validation-plan.json) freezes **four
projects × two repeats = eight attempts** using the installed Qwen3.8 model and
the current 0.12.1 runtime. The shared cap is 128 requests and 1,400,000 tokens.
The original 4,096-output, 180-second request, 300-second turn, and 16-call
per-attempt limits remain in force. Source, task, model metadata, and profile
fingerprints are recorded before inference. Every attempt is retained; no edits,
profile changes, result-dependent retries, builds, or test suites occur during this
fixed run. These are known-regression measurements, not new qualification tasks.

The [recorded results](phase12-repair-validation-results.json) contain three
timeouts and one complete byte-range pass from the first four attempts. The run
was then deliberately stopped for poor results: repeat 2 renames was interrupted,
and three cases were unstarted. This departs from the eight-case plan and provides
no complete-run or repeatability claim. Source, fixtures, profiles, and limits stayed
unchanged. All four finished outcomes and the interrupted event/session logs remain
intact. The runner did not copy the interrupted temporary workspace; its two
successful writes were reconstructed separately from immutable seeds and exact tool
events, with that provenance recorded. They are not graded as a finished attempt.

The separate [input-validation plan](phase12-input-validation-plan.json) freezes
two attempts each for renames, byte ranges, and event replay with Gemma. It follows
the stopped Qwen3.8 process, with the same runtime, fixtures, and per-attempt limits,
and a shared 96-request/1,100,000-token cap. Gemma passed these projects in earlier
individual pilots; this run checks repeatability on the final runtime. The two
plans remain separate reports and are not a matched qualification comparison.

The [Gemma results](phase12-input-validation-results.json) contain **2/2 complete
rename passes** (35.72 and 34.19 seconds) and **2/2 complete event-replay passes**
(44.66 and 41.63 seconds). Both byte-range attempts remain failures. The first
completed and passed public checks but treated an empty header as absent, contrary
to the contract. The second produced independently correct code at its 16-call
limit, after its last public check; it was neither verified on final bytes nor
completed. Its correct code is not counted as a complete pass.

## Explicit reasoning experiment

The [parser reasoning pilot](phase12-parser-deliberate-pilot-plan.json) is a separate
one-attempt plan using installed Qwen3.8 with `reasoning_effort: low`, an **8,192-token
output allowance and 600-second turn limit**. The 180-second request timeout and
16-call limit remain unchanged. Its shared cap is 16 requests and 600,000 tokens.
The exact YAML is retained beside its frozen source archive. The run follows the
Gemma input validation without overlap. This tests an explicit latency/quality
tradeoff after repeated no-thinking failures; any success would not be a pass under
the original 300-second/4,096-token controls. No default or sampler is changed.

The [reasoning result](phase12-parser-deliberate-pilot-results.json) timed out at
600.18 seconds after two requests, without applying a repair. The interrupted
request's output allowance is recorded as an estimate, not observed generated
tokens. This profile is not selected.

## Whole-file repair experiment

The byte public tests now distinguish `header=None`, which permits a full response,
from `header=''`, which must fail, for both empty and nonempty byte data. The task
contract, seed, reference, and independent grader are unchanged. The complete suite
passes **575 tests in 35.21 seconds**, including 13 controlled faulty repairs and
the request-prefix regressions. Ruff lint and formatting pass for 160 Python files.

The [whole-file pilot](phase12-whole-file-pilot-plan.json) freezes one byte-range and
one parser attempt using Gemma's existing lean/minimal/no-thinking controls with
`edit_format: whole_file`. This removes `edit_file` from both the offered tools and
the execution guard, while retaining reads, approved writes, and permitted checks.
The 4,096-output and 300-second turn limits are restored; the **call cap is explicitly
20**, allowing final verification after repairs that previously reached 16 calls.
The shared cap is 40 requests and 800,000 tokens. This tests the existing edit-mode
option after ambiguous and identical replacement calls; it does not alter runtime
review timing or supply a task solution.

The [whole-file results](phase12-whole-file-pilot-results.json) contain a complete
byte-range pass in **53.16 seconds / eight calls**, and an incorrect, unverified
parser attempt stopped at **194.04 seconds / ten calls** by an invalid compaction
summary. Original history was retained. The model repeatedly rewrote the lexer before
finishing the options module. This pilot does not establish repeatability or fix the
parser failures. No new model profile was selected.

## Review sequencing and publication checks

The latest runtime lets related edits reach a shell check before inserting automatic
review. If no shell tool is available, review still starts immediately. If the model
tries to finish without that check, the final-response guard requires review: its
unreviewed draft is neither emitted to the user nor saved as an assistant completion.
Tool-bearing progress remains available. Reviews still include the actual cumulative
diff, the current request, recorded command results, and denials. Further edits need
a fresh review. Request limits, token budgets, deadlines, approvals, and independent
grading are unchanged; insufficient remaining calls still mean an incomplete turn.

Five new runtime cases cover related edits and checks with/without checkpoints,
withheld completion under two call limits, and immediate review without a check tool.
Existing review and remote-runner fixtures now include the extra review request when
their scripted model skips checks. Their approval, scope, context, and completion
assertions remain in force. The final full suite passes **580 tests in 25.00 seconds**,
with Ruff lint and formatting clean for 160 Python files. See [validation](validation.md)
for browser, native, and packaging checks.

**No live model trial has run on this latest review sequence.** The earlier live
outcomes remain attached to their original source fingerprints. Command-parser
reliability and repeated byte-range validation remain open; a new fixed plan and
fresh-project qualification are still needed before claiming a broader improvement.

The [evidence index](phase12-repair-evidence.json) links all 13 retained trials and
checks their plan/report/archive hashes. It records 28 finished attempts, one
interrupted attempt, and three unstarted cases without pooling different runtimes,
models, fixtures, or budgets into a score. Full traces remain local and Git-ignored.
