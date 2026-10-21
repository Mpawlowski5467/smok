# Smok profile qualification

Model: **ollama/qwen3.6:27b-mlx** · candidate: **no-thinking** · split: **holdout**

Verdict: **candidate_supported**. Candidate gains complete passes without an observed paired regression.

Coverage: 8/8 pairs across 4 tasks. Run status: complete.

| Profile | Pass | Correct | Verified | Completed | Requests | Tokens | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 2/8 | 3 | 5 | 3 | 37 | 183219 | 1790.57s |
| no-thinking | 5/8 | 5 | 6 | 6 | 45 | 221981 | 1735.23s |

## Paired outcomes

| Task | Repeat | Outcome | Baseline stop | Candidate stop | Baseline seconds | Candidate seconds |
| --- | ---: | --- | --- | --- | ---: | ---: |
| stock-reservations | 1 | both_pass | complete | complete | 127.89 | 158.08 |
| document-splices | 1 | win | time_limit | complete | 300.57 | 274.12 |
| release-selection | 1 | both_fail | time_limit | time_limit | 300.61 | 300.31 |
| table-joins | 1 | both_fail | error | time_limit | 39.35 | 300.16 |
| stock-reservations | 2 | both_pass | complete | complete | 127.19 | 118.5 |
| document-splices | 2 | win | complete | complete | 294.39 | 267.29 |
| release-selection | 2 | both_fail | time_limit | complete | 300.24 | 167.58 |
| table-joins | 2 | win | time_limit | complete | 300.33 | 149.19 |

Shared-pass latency pairs: 2. Median candidate minus baseline: 10.75 seconds; median time reduction: -8.39%.

## Controls

- reasoning_effort: None → 'none'

## Interpretation

- The verdict describes this recorded sample, not general model quality or statistical significance.
- Freshness is an evaluation protocol, not something this report can infer. Inspected tasks become known regressions.
- Elapsed times include client work and cleanup. Only pairs passing both profiles enter latency comparison; timeouts are never treated as successful speedups.
- Order, caches, sampler state, and local load can affect results. Repeats are not independent new tasks.
- Report hashes detect accidental changes, not fabricated evidence. No network calls or workspace preference changes occur.

Profile export is an explicit selection, never automatic promotion. It contains runtime controls only and depends on your existing provider connection.

Run fingerprint: `2b5d60a93c4bbffb036e6ee7ed46f74f815993d808723abe7fab4a5d33e04a5c`

Source fingerprint: `c6aa1f5ff58b013cde36cebc3206aeddd1eeb865e8a019b92ad088ab4a1da8f5`

Input report SHA-256: `937eeb94f7edc7feb44e3d49dd921dafe75f3b3b98bda0ad6a45b9f0a9b4b77d`
