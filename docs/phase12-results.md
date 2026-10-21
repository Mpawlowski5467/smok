> **Grading correction:** the [post-run contract audit](phase12-contract-audit.md) gives **Qwen 4/8 and Gemma 1/8** complete passes. The frozen grader below counted one incorrect Qwen deletion-normalization repair as a pass. Original results remain visible; use the audited scores when assessing correctness. The comparison remains a tradeoff.

# Smok profile qualification

Baseline: **ollama/qwen3.6:27b-mlx / focused-repair** · Candidate: **ollama/gemma4:26b / focused-repair** · split: **holdout**

Verdict: **tradeoff**. Candidate loses completion, correctness, scope, or verification in at least one pair.

Coverage: 8/8 pairs across 4 tasks. Run status: complete.

| Profile | Pass | Correct | Verified | Completed | Requests | Tokens | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 5/8 | 5 | 8 | 8 | 46 | 200509 | 1537.46s |
| candidate | 1/8 | 2 | 5 | 5 | 76 | 397490 | 871.32s |

## Paired outcomes

| Task | Repeat | Outcome | Baseline stop | Candidate stop | Baseline seconds | Candidate seconds |
| --- | ---: | --- | --- | --- | ---: | ---: |
| batch-renames | 1 | both_pass | complete | complete | 143.5 | 43.93 |
| byte-windows | 1 | regression | complete | iteration_limit | 199.24 | 168.23 |
| event-replay | 1 | regression | complete | complete | 249.43 | 58.79 |
| command-arguments | 1 | both_fail | complete | time_limit | 210.18 | 300.23 |
| batch-renames | 2 | regression | complete | complete | 172.11 | 53.51 |
| byte-windows | 2 | both_fail | complete | complete | 147.97 | 72.32 |
| event-replay | 2 | regression | complete | complete | 233.32 | 51.77 |
| command-arguments | 2 | both_fail | complete | error | 181.71 | 122.54 |

byte-windows, repeat 1: code, verification regression.
event-replay, repeat 1: code regression.
batch-renames, repeat 2: code regression.
byte-windows, repeat 2: verification regression.
event-replay, repeat 2: code regression.
command-arguments, repeat 2: verification regression.

Shared-pass latency pairs: 1. Median candidate minus baseline: -99.57 seconds; median time reduction: 69.39%.

## Controls

The tested runtime controls are identical.
- Baseline: adapter openai_compat, provider model qwen3.6:27b-mlx.
- Candidate: adapter openai_compat, provider model gemma4:26b.

## Interpretation

- Cross-model results compare the recorded model, provider, and runtime settings together; they do not isolate the effect of model weights.
- The verdict describes this recorded sample, not general model quality or statistical significance.
- Freshness is an evaluation protocol, not something this report can infer. Inspected tasks become known regressions.
- Elapsed times include client work and cleanup. Only pairs passing both profiles enter latency comparison; timeouts are never treated as successful speedups.
- Order, caches, sampler state, and local load can affect results. Repeats are not independent new tasks.
- Report hashes detect accidental changes, not fabricated evidence. No network calls or workspace preference changes occur.

Profile export is an explicit selection, never automatic promotion. It contains runtime controls only and depends on your existing provider connection.

Run fingerprint: `bcb4501238f905660e48a15fc97a63f1f96aaf0c510d1516890f329a99b38644`

Source fingerprint: `4d3f65606405befb5d96bec54142ebe55ae57731ced928a76e90a0c939deba2b`

Input report SHA-256: `22aba3633d36d8ea3ebff37a0bc2a174747d134751adaa5f40277355c23a68c8`
