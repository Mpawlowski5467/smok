# Release and join repair follow-up

Smok 0.11.1 follows up on the release-selection and table-join failures recorded in
the [original Phase 11 comparison](model-qualification-results.md). These are now
known regression tasks. This follow-up does not qualify a model on fresh tasks or
replace the original comparison.

## Changes

The release project's public tests now reject trailing whitespace and non-ASCII
digits, including digits after an ASCII digit. The join project's public tests
mutate nested data in a many-to-many result and check that inputs and other output
rows remain independent. These tests catch the observed anchored-regex and reused
right-row defects. The task prompts, seed source, reference repairs, independent
graders, edit scopes, and permitted command are unchanged. The two task
fingerprints change because their public tests changed; results must not be pooled
with the original fixtures as matched attempts.

The first fixed follow-up run passed all three joins but none of the three releases.
It exposed RC leading-zero acceptance, missing-key and boolean-validation errors,
and incorrect stable/RC ordering; one attempt also timed out. All six outcomes and
the [first plan](phase11-followup-plan.json) are retained. Its source archive preserves
the exact initial protocol and fixtures. The final release fixture adds public
regressions for these defects, first-equal tie selection, and list-only catalogs.
The independent graders and reference repairs remain unchanged throughout.

The explicit `focused-repair` evaluation variant combines the existing lean prompt,
minimal tool set, and `reasoning_effort: none`. It offers reads, file edits, and shell
checks without todo or extension calls. This is intended for small, already scoped
repairs; projects requiring search, LSP, or extensions should select broader tools.
It does not change permissions, self-review, output allowance, or provider defaults.

Workflow guidance asks for related edits together and concise code and comments.
Within a turn, a new automatic review replaces the preceding automatic review prompt
in active history. It retains the cumulative diff, current request, and all recorded
commands; actual user messages and tool exchanges remain intact. Review events and
saved journal snapshots preserve the earlier evidence. This reduces duplicated
context without skipping review or inferring that tests passed.

The agent loop also retries one clean empty completion per turn. That request is
charged to the existing usage ledger, request/token caps, and original deadline.
No empty assistant message enters history and no tool action is replayed. A second
empty completion, a transport error, a truncated response, or a malformed tool stop
still fails. CLI, GUI, and event logs expose the recovery attempt.

## Fixed regression protocol

The [corrected Qwen plan](phase11-followup-final-plan.json) froze two tasks × three
repeats with `ollama/qwen3.6:27b-mlx`. All three joins passed; all three releases
timed out, including one with correct but unverified code. A smaller prompt and
better public checks did not make this model reliable for release selection.

Four bounded release pilots followed on other installed Qwen profiles. The 35B
coding model exhausted its response allowance with default thinking at both 4,096
and 8,192 tokens. With thinking disabled it reached the 16-call limit with incorrect
code. Qwen3.8 27B with explicit low thinking also exhausted 4,096 tokens before
editing. Truncated tool responses were never executed. Only the separate 8,192-token
pilot changed the output allowance; it failed and was not selected.

An installed `ollama/gemma4:26b` profile with thinking disabled passed the next
release pilot in 42.05 seconds. Its [first fixed validation](phase11-repair-validation-plan.json)
passed five of six attempts. All turns completed; release repeat 2 accepted a tuple,
misdescribed the failed tuple check as an empty-list check, and finished after further
edits without rerunning tests. The independent grader passed that attempt, but its
public verification failed, so the full result correctly remained a failure.

An experiment with stronger review wording reached the call limit on its first
release and join attempts. It was stopped early: two completed failures, one retained
interrupted release attempt, and three unstarted cases. This departs from that run's
[six-case plan](phase11-final-repair-plan.json); its partial results are not a complete
validation. The wording was reverted.

The public release test now separates container validation from record validation:
an empty list is valid, while empty and nonempty tuples explicitly fail as tuple
containers. This clarifies the existing list-only contract and failure diagnostic;
it does not relax acceptance or change the prompt, reference repair, or independent
grader. It changes the release task fingerprint again.

The [diagnostic pilot](phase11-diagnostic-pilot-plan.json) passed in 71.3 seconds.
The subsequent [fixed validation](phase11-diagnostic-validation-plan.json) passed
all three releases and two of three joins. Join repeat 2 omitted right-container
validation, raising `TypeError` for `None` where the contract requires `ValueError`,
and did not check its final edit. The public join fixture now checks invalid
containers on both sides, including with an empty opposite side. The saved failed
repair and a separate faulty repair exercise this regression. The join task
fingerprint changes; the contract, prompt, reference repair and grader do not.

A [Gemma thinking pilot](phase11-gemma-thinking-pilot-plan.json) exhausted 4,096
tokens before editing. A separate [8,192-token pilot](phase11-gemma-thinking-8k-plan.json)
produced code that passed the independent grader but timed out at 300 seconds before
verification. Both used the same lean prompt/minimal tools with provider-default
thinking (`reasoning_effort: null`, default enabled in the recorded model metadata).
Both failed and were not selected.

The [final join plan](phase11-join-validation-plan.json) returns to the tested
no-thinking Gemma profile, with **4,096 output tokens, 300 seconds and 16 calls**.
It freezes three join attempts against the expanded public coverage. The three
complete release passes from the previous fixed run remain applicable: their
runtime source, release fixture, effective profile and limits are unchanged.
Release and join results are reported as separate validations, not a new six-case run.

Both current tasks have **three complete passes** with that same profile and runtime.
Release attempts took **85.78, 91.40, and 67.95 seconds**; final join attempts took
**34.57, 24.90, and 42.36 seconds**. Each passed the independent grader, allowed edit
scope, final-file public verification, and turn completion. The older failed attempts
remain failures. No clean empty completion occurred during these trials; retry
behavior is covered by controlled regression tests rather than live recovery evidence.
Source/task fingerprints, the archived runtime source, the exact profile, and local
model metadata are retained. Every attempted case is recorded. Builds and regression
suites run separately from inference.

```sh
uv run python evals/run.py --suite phase11 --split holdout \
  --task table-joins \
  --model ollama/gemma4:26b --config examples/models/focused-repair-gemma.yaml \
  --variant focused-repair --repeats 3 \
  --allow-tools --allow-shell --task-timeout 300 --max-iterations 16 \
  --max-requests 96 --budget-tokens 1000000
```

The original `holdout` split label is retained for fixture compatibility; both tasks
are known regressions in this experiment. A pass still requires a completed turn,
independent correctness, allowed edit scope, and the documented public check passing
on the final source bytes. There is no concurrent control arm: changes to public
coverage, prompt, tools, and model choice prevent attributing improvement to one
control. These adaptive trials do not establish general model superiority.

## Use the explicit profile

```sh
uv run smok --config examples/models/focused-repair-gemma.yaml \
  --model ollama/gemma4:26b --turn-timeout 300 --max-iterations 16
```

Pass both turn limits shown above; they are not part of the model YAML. This selects
the already-installed Gemma model explicitly. The example contains
runtime controls only; it does not change a default model, endpoint, credentials,
or workspace preferences. The older `focused-repair.yaml` is retained as the tested
Qwen27 profile, which still failed release selection; it is not the selected repair
profile. No model was downloaded or provider sampler settings changed.

Provider support for the reasoning field is required. Ollama documents that
`reasoning_effort: none` disables thinking on boolean-thinking models; named levels
must match the model's `/api/show` capabilities. See the
[official compatibility documentation](https://docs.ollama.com/api/openai-compatibility).
The [validation record](validation.md) and
[compact follow-up evidence](phase11-followup-results.json) report measured outcomes
and their limits. The original failed generated files remain in the earlier run.
