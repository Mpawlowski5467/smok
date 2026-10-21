# Model qualification

For the 0.12 cross-model comparison and role-based export, see
[cross-model qualification](cross-model-qualification.md). The within-model interface
and the original Phase 11 results below remain available.

Smok 0.11.0 compares two explicitly recorded profiles on fresh project tasks and turns
that run into a readable selection report. It exports a profile only when a variant
is explicitly selected. It never edits workspace settings, changes the default model,
downloads a model, or runs inference while reading a report.

## Four new projects

The Phase 11 suite contains four original standard-library projects. Each has two
repairable modules, immutable public tests and guidance, and a separate independent
grader. These are small fixtures, not external production repositories or a public
benchmark. Their prompts define the full contract; independent graders do not enter
the model's workspace.

| Task | Contract |
| --- | --- |
| `stock-reservations` | Aggregate order lines, validate inventory, preserve inputs on failure |
| `document-splices` | Apply changes at original Unicode character offsets, detect overlap, preserve document mappings |
| `release-selection` | Parse a deliberately limited version grammar, order numerically, validate excluded records |
| `table-joins` | Stable many-to-many left joins, strict keys, independent copies of nested rows |

All four initially belong to the holdout split. Once their results are inspected,
they become known regression tasks for future tuning. Two repeats of the same task
are two trials, not two new tasks. Reference tests also inject one plausible faulty
repair per project: each passes the public tests but fails the independent grader.
This checks that private grading adds coverage without changing the visible contract.

## Fixed comparison protocol

The initial local protocol is four tasks × two profiles × two repeats: **16 attempts**.
The profiles use the same installed `ollama/qwen3.6:27b-mlx` model, full prompt and tool
set, 4,096 output tokens, a **300-second task limit**, and **16 model calls per task**.
The candidate changes only `reasoning_effort` from provider default to `none`.
No prompt, model, fixture, grader, or limit is adjusted after outcomes are inspected.
Failures are retained; completion is never inferred from correct edits alone.

Run from a source checkout with the model already installed:

```sh
uv run python evals/run.py --suite phase11 --split holdout --list
uv run python evals/run.py --suite phase11 --split holdout \
  --model ollama/qwen3.6:27b-mlx --variant baseline --variant no-thinking \
  --repeats 2 --allow-tools --allow-shell --task-timeout 300 \
  --max-iterations 16 --max-requests 256 --budget-tokens 2000000
```

The runner alternates profile order across tasks and repeats. It records labeled
resolved profiles, task splits, the full plan, source/task fingerprints, limits,
per-request timing, and successful tests on the final source snapshot. The shared
request/token caps can stop a run; that yields incomplete evidence rather than a
recommendation. `--resume RUN_DIRECTORY` requires the same flags and unchanged source,
fixtures, profiles, and limits. Interrupted attempts remain retained.

`baseline` means the resolved configuration supplied to that run. If you pass a
custom `--config`, inspect the recorded control differences; it may already disable
thinking. The report detects identical effective profiles. Provider support varies;
see the [reasoning control guide](project-workflows.md#reasoning-control-for-the-local-model).

The only approved shell command in each fixture is:

```sh
python3 -B -m unittest discover -s tests -q
```

Independent grading, allowed edit scope, successful project verification on final
bytes, and a completed turn are all required for a pass. Generated Python executes
on the host; fixture directories and command allowlists are not an adversarial sandbox.
Builds and regression suites should run separately from live inference.

## Read the evidence

```sh
uv run python evals/qualify.py evals/results/RUN/report.json \
  --model ollama/qwen3.6:27b-mlx --candidate no-thinking --split holdout \
  --json-out qualification.json --markdown-out qualification.md
```

This is an offline operation. It reads one fixed run with labeled profiles from 0.11
or later. It refuses inconsistent task/profile/source identities, duplicate or missing
completed cases, unbalanced pairs, connection changes between variants, and invalid
outcomes or measurements. Hashes establish internal consistency, not authenticity.
Tuning and holdout evidence are analyzed separately; the tool does not infer whether
a task was previously inspected. It does not pool reports from different runs.

The report shows planned versus recorded cases, independent correctness, project
verification, completed turns, timeouts, calls, tokens, and every paired outcome.
A candidate win is a completed pass where baseline failed; a regression is the reverse.
Correctness, verification, and scope regressions are also reported when both attempts
failed to finish. Latency comparisons use only pairs where **both profiles passed**.
A quick failure cannot become a speed win, and an unstarted case receives no outcome.

Selection rules are fixed before the live run:

- Incomplete plans produce `incomplete`; identical effective profiles produce
  `no_difference`.
- Fewer than three distinct tasks or fewer than two repeats for any task produce
  `exploratory`.
- Any paired pass, correctness, verification, or scope regression produces `tradeoff`.
- With sufficient complete coverage and no observed regression, a candidate pass gain
  produces `candidate_supported`. Without a pass gain, at least three shared passing
  pairs and a median per-pair time reduction of 10% or more produce the same verdict.
- Otherwise the verdict is `no_clear_preference`.

These are transparent selection heuristics, not statistical significance tests or a
claim of general reliability. A supported candidate may still fail cases that baseline
also failed. Always inspect the individual results and remaining failures. Cache state,
sampling, machine load, and execution order affect timing; no server compute-time claim
is made. Local API cost excludes hardware and electricity.

## Export an explicit selection

After reviewing the result, choose either `baseline` or the named candidate:

```sh
uv run python evals/qualify.py evals/results/RUN/report.json \
  --candidate no-thinking --export-profile selected-model.yaml --select no-thinking
uv run smok --config selected-model.yaml --model ollama/qwen3.6:27b-mlx
```

The YAML contains the exact model selector and tested runtime controls, with the run
fingerprint and verdict in comments. It omits provider endpoints, credentials, pricing,
and `default_model`; it depends on your existing provider connection. No settings are
applied automatically. Selecting `baseline` exports its actual recorded settings,
including null to restore provider-default reasoning when that was tested.

Explicit export is allowed even for exploratory or inconclusive results; the verdict
remains visible and export does not imply qualification. Output paths must be new and
have existing parent directories, so earlier reports or profiles are never overwritten.
In the desktop app, the same controls remain available in **Workspace settings → Models**;
use the report to choose settings rather than treating them as universal model defaults.

Live outcomes and local artifact checks are recorded in [validation](validation.md).
