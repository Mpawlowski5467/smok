# Cross-model qualification

Smok 0.12.0 adds four original projects and comparison of explicitly selected
model/profile pairs in one frozen run. The report can export either selection to a
new YAML file. It does not apply settings, change the default model, or run inference.

This guide preserves the original fresh-task protocol. After inspection, these cases
became known regressions. Use the [contract audit](phase12-contract-audit.md) for the
corrected original scores and the [0.12.1 repair follow-up](phase12-repair.md) for later
public-test changes and failures. The latest review sequence has automated coverage
but no live model qualification yet.

## Fresh project contracts

| Task | Contract |
| --- | --- |
| `batch-renames` | Simultaneous registry renames, cycles, collisions, original order, independent nested values |
| `byte-windows` | A defined single-byte-range grammar, inclusive bounds, clipping, response metadata |
| `event-replay` | Idempotent event IDs, per-key versions, deletion tombstones, input isolation |
| `command-arguments` | Quote/escape state, empty words, ASCII delimiters, validated assignments |

Each project has two repairable modules, read-only public tests and guidance, a
complete prompt contract, and a separate independent grader. Seeds fail both checks;
reference repairs pass both. Four deliberately incorrect repairs pass public tests
but fail independent grading (nested aliases, boolean size/version acceptance, and
discarded empty quoted words). These are small original fixtures, not external
production projects or a public benchmark. They were not used in earlier tuning.
After inspecting this run, treat them as known regressions for subsequent work.

## Fixed local protocol

The initial comparison is **four projects × two models × two repeats = 16 attempts**.
Baseline is the installed `ollama/qwen3.6:27b-mlx`; candidate is the installed
`ollama/gemma4:26b`. Both use `focused-repair`: lean prompt, minimal tools, and explicit
no-thinking. Runtime controls are the same: 4,096 output tokens, 300 seconds per turn,
16 model calls, and the existing 180-second individual request timeout. A shared
256-request/2,000,000-token cap bounds the run. Provider model digests, capabilities,
thinking support, and sampler defaults are recorded before and after the run.
Model-specific server sampler defaults remain in effect and differ between models.

The runner reverses the complete model/variant order on alternate task/repeat pairs.
With these two models and two repeats, each model runs first once per project.
Attempts run serially without overlapping builds or test suites. Source, tasks,
graders, profiles, limits, and selection rules are frozen before any inference.
No result-dependent repairs, retries of finished failures, or budget increases are
part of this comparison. Every outcome is retained. Existing task deadlines and the
bounded clean-empty retry remain active. An infrastructure interruption is recorded;
resume requires the original source, task, profile, and limit fingerprints.

```sh
uv run python evals/run.py --suite phase12 --split holdout --list
uv run python evals/run.py --suite phase12 --split holdout \
  --model ollama/qwen3.6:27b-mlx --model ollama/gemma4:26b \
  --variant focused-repair --repeats 2 --allow-tools --allow-shell \
  --task-timeout 300 --max-iterations 16 --max-requests 256 --budget-tokens 2000000
```

Only `python3 -B -m unittest discover -s tests -q` is permitted as a shell command
in these disposable projects. A pass requires independent correctness, allowed edit
scope, a successful public test command covering the final source bytes, and a
completed turn. Generated Python runs on the host; fixture directories and command
allowlists are not an adversarial sandbox. No model downloads or frontier API calls
are part of this local protocol.

## Compare and select

```sh
uv run python evals/qualify.py evals/results/RUN/report.json \
  --model ollama/qwen3.6:27b-mlx --baseline-variant focused-repair \
  --candidate-model ollama/gemma4:26b --candidate focused-repair \
  --json-out comparison.json --markdown-out comparison.md
```

Both model/profile pairs must occur in the same report, with identical planned tasks
and repeats in the chosen split. The report validates identities and fingerprints;
it does not combine separate runs. The existing within-model variant interface
remains supported. `--candidate-model` requires an explicit baseline `--model`.

Cross-model output uses the unambiguous roles `baseline` and `candidate` even when
both variants have the same name. It shows the actual selectors, provider model IDs,
adapters, runtime-control differences, and names of differing connection/cost
settings. Connection values are omitted from the comparison and exported YAML.
Comparisons across providers describe the complete recorded model/provider/profile
combination; they do not isolate model weights or sampling effects.

Selection follows the [existing qualification rules](model-qualification.md): at
least three projects and two repeats each; incomplete coverage is inconclusive;
any paired completion, correctness, verification, or scope loss is a tradeoff.
Without a regression, a complete pass gain supports the candidate, or at least three
shared passing pairs with a median time reduction of 10% or more. Fast failures never
count as latency wins. These are sample-selection heuristics, not statistical tests
or a claim of general reliability. Repeats are not new projects.

After reviewing the evidence, explicitly select a role:

```sh
uv run python evals/qualify.py evals/results/RUN/report.json \
  --model ollama/qwen3.6:27b-mlx --baseline-variant focused-repair \
  --candidate-model ollama/gemma4:26b --candidate focused-repair \
  --export-profile selected-model.yaml --select candidate
uv run smok --config selected-model.yaml --model ollama/gemma4:26b \
  --turn-timeout 300 --max-iterations 16
```

Use `--select baseline` and the corresponding Qwen selector to export the baseline.
The selected model receives its exact tested runtime controls; provider connections,
credentials, prices, and `default_model` are excluded. Turn/call limits are CLI options,
not model-profile fields, so pass them explicitly to reproduce the evaluation limits.
Exports are permitted for inconclusive or tradeoff results only as explicit choices;
the verdict is retained in comments and does not imply qualification. Output paths
must be new, with existing parent directories. Nothing is automatically promoted.

The [frozen plan](phase12-plan.json), [paired results](phase12-results.md), and
[validation](validation.md) record the actual run and local artifact checks.
