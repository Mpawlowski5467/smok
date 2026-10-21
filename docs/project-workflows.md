# Project workflow reliability

Phase 10 (0.10.0) adds six original project fixtures to the existing twenty coding
tasks. These are small standard-library projects, not evaluations on external
production repositories or a public benchmark.

| Task | Split | Behavior checked |
| --- | --- | --- |
| `config-precedence` | tune | Typed environment settings and explicit CLI overrides |
| `invoice-totals` | tune | CSV quoting, decimal sums, filtering, and final rounding |
| `catalog-pages` | tune | API query parsing, deterministic ordering, and page metadata |
| `redact-jsonl` | tune | Recursive redaction, input preservation, and line-stream errors |
| `manifest-paths` | holdout | Relative-path validation, normalized deduplication, and line numbers |
| `retry-client` | holdout | Retry status policy, delays, attempt limits, and exceptions |

Each fixture includes two repairable source modules, public project tests, root and
scoped `AGENTS.md` guidance, and a documented check command. Tests and guidance are
outside the allowed edit scope. Separate graders exercise additional edge cases;
their code and the reference repairs never enter the model's workspace or prompt.
Deterministic regression checks require both the public tests and independent grader
to reject the seed and accept the reference repair.

## Run the suite

From a source checkout, with an already installed model:

```sh
uv run python evals/run.py --suite phase10 --list --split all
uv run python evals/run.py --suite phase10 --split tune \
  --model ollama/YOUR_INSTALLED_MODEL --allow-tools --allow-shell
uv run python evals/run.py --suite phase10 --split holdout \
  --model ollama/YOUR_INSTALLED_MODEL --allow-tools --allow-shell
```

The explicit `--allow-shell` opt-in is required before any model request. The only
permitted shell command is printed in the prompt and enforced by the approver:

```sh
python3 -B -m unittest discover -s tests -q
```

No installation, network request, or arbitrary shell command is approved by this
suite. The model can still repair allowed source modules which these tests import;
generated Python runs on the host. Temporary fixtures and command allowlists do not
provide an adversarial sandbox. Public tests exercise behavior, not a grader hidden
inside the model's workspace.

Use `--repeats 2` for independent repetitions, `--task ID` to select cases, and the
existing matrix/budget/resume flags for controlled runs. Runs are retained under
`evals/results/<timestamp>-phase10/`. The default task deadline remains 180 seconds;
reports record any explicitly selected alternative. Changing a deadline changes
the completion criterion and must remain visible in comparisons.

## What a passing result means

An attempt passes only if all of these hold:

1. The agent finishes its turn within the call and time limits.
2. Only allowed files changed, and no unsafe generated files were found.
3. The independent grader accepts the resulting code.
4. Every required project command's latest attempt succeeded, the command did not
   change the workspace snapshot, and that snapshot matches the final files.

An unrun check, a later failed check, or a pass followed by additional source changes
does not qualify. Re-run checks after further edits. Comparison uses file-content
hashes, excluding `.git`, `.smok`, and Python bytecode caches; identical restored bytes
can reuse the same evidence. This is verification evidence, not a guarantee against
malicious Python or flaky tests. Reports retain failed command attempts and preserve
the separate `check_passed`, `verification.passed`, and `stop_reason` outcomes.

## Timing and deadlines

Every new evaluation log includes monotonic `elapsed_seconds`. Attempt JSON records
each model request and tool call, whether it returned or was interrupted, total model
wait/stream time, tool time, approval time, and other active work. Tool time includes
approval time; do not add those values together. Setup and grading/cleanup are recorded
separately. These client-observed durations include event handling and cleanup and do
not measure server compute time. Older reports remain readable without inventing
missing timing measurements.

For a bounded turn, Smok now tells the model approximately how many seconds remain
before each coding request. The hint asks it to use existing evidence and prioritize the
requested change, required checks, and a concise result. The original deadline,
permissions, self-review, and completion requirements remain enforced. The hint is
temporary runtime context, outside the stable Anthropic cache block: it does not become
saved conversation history or leak into the caller between events. Routed primary
requests retain the outer turn's deadline; work without an active deadline receives
no hint.

Remaining-time guidance can help the model plan; it cannot guarantee completion or
correctness. Follow [validation](validation.md) for measured outcomes, including all
retained failures and interrupted attempts. Known Phase 7 dependency-ordering cases
are regression measurements after their outcomes have informed changes, not fresh
held-out evidence.

The first six-project run passed four cases. One repair missed a configuration edge
case, and one correct, tested repair timed out during its final response. See the
[recorded evidence](project-workflow-results.json) for the fixed source, task limits,
verification, and timing; a passing public test command alone is insufficient.

The 0.10.1 follow-up keeps the current request in change reviews and asks the model
to apply constraints across all affected input paths. It also avoids requiring a
todo list for small repairs and encourages independent calls in the same response.
The configuration fixture now has public regression tests for valid boundary ports
and out-of-range CLI overrides. This changes its task fingerprint; the earlier trial
with the original public tests remains separate. Its independent grader and user
prompt are unchanged. The manifest fixture, full prompt, tool set, output allowance,
and 300-second deadline are retained. The reasoning setting is explicit, as described
below. These are now known regression tasks; their outcomes are not fresh held-out
measurements.

## Reasoning control for the local model

Smok 0.10.1 exposes an optional `reasoning_effort` for compatible model profiles.
Omitting it leaves the endpoint's default unchanged. Smok validates effort names and
forwards the selected setting; the endpoint determines model support. Endpoint
rejections are surfaced without retrying at a different effort. The direct Anthropic
adapter rejects this compatibility option.

The installed Ollama 0.40.4 server reports that `qwen3.6:27b-mlx` supports thinking
on/off and defaults to on. Its compatibility API accepts `reasoning_effort: "none"`
to request thinking off. See [Ollama's compatibility documentation](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx).
Support and the meaning of other effort names vary by model.

For an explicitly bounded local coding turn:

```sh
uv run smok --model ollama/qwen3.6:27b-mlx --reasoning-effort none --turn-timeout 300
```

The CLI saves the override with the session; `--reasoning-effort default` clears it.
In the desktop/browser app, select **Workspace settings → Models → Reasoning effort →
none** for this model. **Provider default** clears the profile setting. The
[opt-in YAML profile](../examples/local-fast.yaml) is also usable with `--config`.
No built-in provider or model default is changed.

For reproducible evaluations, use `--variant no-thinking`. The full prompt, available
tools, output allowance, deadline, independent grader, and project verification remain
in force. The report records this reasoning setting in the profile and run fingerprint.
Reduced thinking can change correctness, so compare both quality and completion results;
the setting is not a general recommendation for every task or endpoint.

On the final 0.10.1 source, the two known regressions each passed all three repeats
with this explicit profile: CLI-port runs took 113.20–269.59 seconds and manifest
runs took 167.38–196.86 seconds under the original 300-second limit. Earlier default
thinking failures remain recorded. See [validation](validation.md#repeated-cli-port-and-manifest-checks)
and the [compact follow-up evidence](project-workflow-followup-results.json) for the
individual outcomes and comparison limits.
