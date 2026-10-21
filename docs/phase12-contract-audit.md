# Phase 12 contract audit

The frozen independent grader missed a forbidden value field in normalized deletions. The correction checks exact deletion fields, fresh output identity, and unchanged input, as required by the original prompt.

All 16 saved final repairs were rechecked after the fixed run. No model was called, no repair was edited, and no finished attempt was retried. Original reports, model timing, completion, and final-file public verification remain intact.

| Model | Frozen passes | Audited passes | Audited correct | Public verified | Completed |
| --- | ---: | ---: | ---: | ---: | ---: |
| ollama/qwen3.6:27b-mlx | 5/8 | **4/8** | 4/8 | 8/8 | 8/8 |
| ollama/gemma4:26b | 1/8 | **1/8** | 2/8 | 5/8 | 5/8 |

## Per-attempt audit

| Task | Model | Repeat | Frozen pass | Audited pass | Original stop |
| --- | --- | ---: | --- | --- | --- |
| batch-renames | ollama/qwen3.6:27b-mlx | 1 | True | True | complete |
| batch-renames | ollama/gemma4:26b | 1 | True | True | complete |
| byte-windows | ollama/gemma4:26b | 1 | False | False | iteration_limit |
| byte-windows | ollama/qwen3.6:27b-mlx | 1 | True | True | complete |
| event-replay | ollama/qwen3.6:27b-mlx | 1 | True | False | complete |
| event-replay | ollama/gemma4:26b | 1 | False | False | complete |
| command-arguments | ollama/gemma4:26b | 1 | False | False | time_limit |
| command-arguments | ollama/qwen3.6:27b-mlx | 1 | False | False | complete |
| batch-renames | ollama/gemma4:26b | 2 | False | False | complete |
| batch-renames | ollama/qwen3.6:27b-mlx | 2 | True | True | complete |
| byte-windows | ollama/qwen3.6:27b-mlx | 2 | False | False | complete |
| byte-windows | ollama/gemma4:26b | 2 | False | False | complete |
| event-replay | ollama/gemma4:26b | 2 | False | False | complete |
| event-replay | ollama/qwen3.6:27b-mlx | 2 | True | True | complete |
| command-arguments | ollama/qwen3.6:27b-mlx | 2 | False | False | complete |
| command-arguments | ollama/gemma4:26b | 2 | False | False | error |

Only Qwen event replay repeat 1 changes from a full pass to a failure. Its normalized deletion adds `value: None`, violating the existing contract. The strengthened grader also rejects a controlled faulty repair that passes public tests. The reference repair still passes both checks.

The event-replay task fingerprint changes because its grader changed. Prompts, seed files, public tests, references, profiles, and limits are unchanged. The other three task fingerprints are unchanged. Treat these inspected fixtures as known regressions in future runs.

The original comparison verdict is **tradeoff**. The correction does not establish a preferred model or general reliability. Only one pair passed both models; there is insufficient shared-pass coverage for the predeclared latency selection rule.

See the [machine-readable audit](phase12-contract-audit.json), [frozen comparison](phase12-results.md), [protocol](cross-model-qualification.md), and [validation](validation.md).
