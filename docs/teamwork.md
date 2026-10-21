# Local and frontier teamwork

Phase 5 adds fresh-context workers, role and mode routing, a local-first escalation
ladder, oracle advice, shadow comparisons, council worktrees, background jobs, SSH
runners, and replay. All use the existing adapters, permissions, event types, and
usage accounting. Nothing starts another model or remote runner merely on discovery.

## Start with one installed model

```sh
uv run smok -C /path/to/repository --model ollama/qwen3.6:27b-mlx
```

In the terminal:

```text
/delegate explore Find the code that handles retries and summarize its behavior.
/oracle Review the proposed retry design for failure cases.
/team
/background python -m http.server 8080
/jobs
/poll JOB_ID
/stop JOB_ID
```

Delegation and oracle requests follow the permission policy. Each privileged child
action still follows that policy; approving a worker does not grant all its commands.
Child edit approvals show the candidate workspace path and actual diff. Child commands
show the backend. Approval prompts are serialized when workers run concurrently.
`full-auto` authorizes child tools too. In headless mode, use explicit permissions.

A worker receives its task, project instructions, and its own small context. Parent
conversation history is not copied. Oracle receives a bounded recent-evidence excerpt.
Only summaries, status, usage, and artifact references return to the parent. The
`delegate` tool accepts up to three tasks and runs them with asyncio concurrency.

| Role | Available tools | Workspace |
| --- | --- | --- |
| `explore`, `plan`, `review`, `oracle` | Read, list, grep, glob, repo map, retained output reads | Current workspace, read-only |
| `edit` | Those reads plus write, exact edit, shell, todos | Separate detached Git worktree |

Workers cannot delegate again, launch background jobs, connect MCP servers, or execute
extension hooks. These restrictions apply to guessed tool calls as well as advertised
schemas. Plan mode blocks edit delegation, councils, replay edits, remote runs, and
background start/stop. Existing background processes can still be polled; exit always
cleans them up. Restricted tools are capability checks; approved host shell commands
are not an OS sandbox. Select Docker for shell isolation.

## Routes and escalation

Put a `team` object in `.smok/settings.json`. See the runnable local example in
[settings.phase5.json](../examples/settings.phase5.json). Settings are read at startup;
`/reload` continues to reload extensions only.

```json
{
  "team": {
    "routes": {
      "explore": "ollama/qwen3.6:27b-mlx",
      "plan": "anthropic/YOUR_FRONTIER_MODEL",
      "edit": "ollama/qwen3.6:27b-mlx",
      "review": "anthropic/YOUR_FRONTIER_MODEL",
      "oracle": "anthropic/YOUR_FRONTIER_MODEL"
    },
    "ladder": ["ollama/qwen3.6:27b-mlx", "anthropic/YOUR_FRONTIER_MODEL"],
    "max_workers": 3,
    "worker_iterations": 8,
    "max_requests": 48,
    "timeout_seconds": 600,
    "stall_threshold": 3
  }
}
```

Replace frontier placeholders with a model you have access to; configure its endpoint,
working context, and prices through the existing YAML model profiles. Credentials stay
in the environment. An omitted role uses the selected primary model. Normal plan-mode
tasks use the `plan` route; build-mode tasks use `edit`. Explicit `/model` changes the
fallback model. Configured routes still take precedence on the next task.

An enabled ladder takes precedence over the build route and starts each user task at
its first, locally marked profile. There are at most three distinct rungs. Smok moves
up after the configured number of failed shell commands, repeated identical tool calls,
or an iteration limit. Failure detection is mechanical: a nonzero shell command is a
failure signal, not proof that a test failed. An attempt that recovers before the
threshold stays local. Permission denial, exhausted budgets, and provider errors do
not trigger escalation.

The next model gets the original task and a bounded excerpt of actual attempts,
results, and command evidence. Full earlier history remains in the session log, while
the new request starts compact. Read grants are cleared. The toolbar flags escalation,
and JSON events contain the reason and handoff. Each rung retains its own checkpoint;
undo restores the most recent changed attempt.

Token and dollar allowances reserve in-flight requests before awaiting a model, then
settle to reported usage. Parent, workers, compaction, oracle, judge, shadow, and replay
share the invocation budget. Failed/cancelled requests without final usage retain a
conservative allowance charge. `team.max_requests` caps total model requests across
the invocation; `--max-iterations` still bounds each primary attempt, and
`worker_iterations` bounds each child turn. Internal turns do not consume extra user
turns. Dollar caps require configured prices. Estimates cannot guarantee provider billing.

## Shadow comparisons

Configure `team.shadow_model` or pass `--shadow-model ollama/YOUR_MODEL`. When the
selected primary profile is marked non-local, a local read-only worker answers the
same task concurrently from an isolated snapshot. The primary retains normal tools.
Shadow writes and shell commands are unavailable, so coding and conversational answers
are not equivalent experiments.

The report retains both summaries, status, usage, normalized exact match, and text
similarity. These are **text comparisons, not correctness scores**. `/team` aggregates
eligible shadow comparisons from up to 100 retained reports. Use the results as leads
for representative tests before changing the ladder. Shadow model usage counts against
the shared budget; on a small budget it can leave less capacity for the primary.

## Model council

Councils run two or three model profiles on the same snapshot, including current dirty
and non-ignored untracked files. Main-workspace files, real index, and HEAD stay intact.

```sh
uv run smok -C /path/to/repository --json --permissions auto-edit \
  --council 'Fix the parser edge case and add an appropriate regression check.' \
  --council-model ollama/YOUR_MODEL \
  --council-model anthropic/YOUR_FRONTIER_MODEL \
  --check 'python -m pytest -q'
```

`auto-edit` allows file changes but requires saved command grants for unattended checks.
Use `--yes` only when you intend to authorize all available actions for this run.
Councils require a check command, a `--judge MODEL`, or both. Checks execute separately
inside each candidate workspace. Without a judge, the first completed candidate in
requested order whose check passes is selected. A judge sees bounded diffs and evidence;
it can select only eligible candidates. Failed/denied/incomplete candidates cannot win.
A judge-only selection is an opinion and is labeled accordingly. Invalid judge output
leaves an existing test-based selection intact, or selects nothing.

Worktrees, patch files, checks, usage, and the report remain under
`.smok/team/runs/RUN_ID/`. Interrupted councils retain a report and their worktrees.
Selection never applies a patch automatically. Inspect the candidate, then use:

```sh
uv run smok -C /path/to/repository --accept RUN_ID:0
```

Or `/accept RUN_ID:0` in the terminal. Acceptance compares the current workspace to
the original baseline, rejects intervening changes, recomputes the candidate patch,
refuses candidates changed since their recorded checks, checks that the patch applies,
and creates an undo checkpoint when checkpoints are enabled.
Any candidate can be explicitly accepted after review; a passing test is not a guarantee.

Detached worktrees share Git metadata and objects with their repository, as described
in the [Git worktree documentation](https://git-scm.com/docs/git-worktree). They are not
security boundaries for host commands. Snapshot/checkouts disable configured Git hooks
and content filters. Snapshots require the Git repository root, reject submodules, and
cap capture at 20,000 paths / 50 MiB. Private revisions are pinned under
`refs/smok/snapshots/`; they do not update branch HEAD or the real index. Git may apply
normal attribute/EOL normalization. Ignored untracked dependencies are not copied;
use a preinstalled interpreter or explicitly approve setup inside each candidate.
Tracked ignored files are included, so review tracked secrets before remote transfer.

Retained candidate cleanup is explicit: use `git worktree remove PATH` after preserving
needed changes. Git refuses a dirty worktree unless removal is forced. Reports and
snapshot refs remain until explicitly removed; Smok does not silently discard work.

## Background processes

`start_process`, `poll_process`, and `stop_process` use the selected host/Docker backend.
At most four jobs run concurrently, with 32 jobs per session and a one-hour maximum
lifetime (ten minutes by default). A 64 KiB output ring is drained continuously. Polls
return up to 12,000 bytes, the next byte offset, and an explicit lost-byte count when
older output has rolled off. Exit status and timeout/stop state are separate fields.

Jobs belong to the current process, stop on exit/cancellation cleanup, and are not
resumed from a log. Process groups are killed; Docker containers also receive explicit
removal. Background mutations can occur after a turn's checkpoint closes. Stop a
writer before undo or candidate acceptance; background effects are not fully covered
by per-turn undo.

## Homelab runner

A runner is a fixed command executed over authenticated SSH. There is no new HTTP
service or automatic credential provisioning. Preinstall Smok, the configured model
access, Docker, and the Docker image on the host. Add an entry such as:

```json
{
  "team": {
    "remote_runners": {
      "lab": {
        "host": "smok-lab",
        "command": ["/opt/smok/bin/smok", "--runner", "--runner-root", "/srv/smok/jobs",
                    "--model", "ollama/YOUR_INSTALLED_MODEL",
                    "--sandbox-image", "python:3.12-slim"]
      }
    }
  }
}
```

The SSH alias and verified host key must already be configured. Smok uses `BatchMode=yes`
and `StrictHostKeyChecking=yes`; see the [OpenSSH configuration manual](https://man.openbsd.org/ssh_config).
Remote argv is shell-quoted as a fixed command, while task and snapshot travel as JSON
on stdin. Secrets from `.smok/settings.json`, credentials, saved approvals, and Git
metadata are not included in the snapshot. Ordinary tracked files can still contain
secrets. The transfer uses `git archive`, including its export attributes. Approval displays the destination, configured command, and transfer scope.

```sh
uv run smok -C /path/to/repository --json --yes --budget-tokens 50000 \
  --remote-runner lab --remote-task 'Fix the failing parser test and verify it.'
```

To dispatch up to three jobs concurrently, save a JSON array of objects with `runner`
and `task` keys, then use `--remote-batch jobs.json --budget-tokens 100000 --yes --json`.
The model can use `remote_batch` with the same per-job approval scope. Each job reserves
its own allocation; budget exhaustion fails that job without spending another job's allowance.

Remote execution requires an explicit token budget. The client reserves up to 50,000
remaining tokens and the available worker request slots before transport. The server
enforces those limits, a bounded deadline, and Docker-only shell execution without
host fallback or image pulling. Remote shells use full-auto within this authorized
job; there is no remote interactive approval channel in Phase 5. Networking stays off
unless the fixed server command explicitly enables it.

The uncompressed archive is limited to 8 MiB and 2,000 entries; paths, duplicates,
metadata, symlinks, hard links, devices, and traversal are rejected. Work happens in a
disposable server directory. A bounded patch, summary, errors, and usage come back;
patches are never applied automatically. Interrupted/unparseable transport results
retain the full budget allocation charge because remote usage may be unknown. The
server deadline bounds model work even when SSH disconnects; cleanup can take longer.
Request slots remain conservatively consumed even if the remote model used fewer.

## Replay lab and headless mode

With logs and checkpoints enabled, a normal team task records its initial snapshot.
Replay uses only recorded user tasks, creates a new worktree, and calls the selected
model with fresh permissions. Logged tool calls/results and saved grants are never
executed as instructions. Up to 50 tasks / 100,000 prompt characters are supported.

```sh
uv run smok -C /path/to/repository --sessions --json
uv run smok -C /path/to/repository --model ollama/NEW_MODEL --json --yes \
  --replay SESSION_ID --check 'python -m pytest -q'
```

Old logs, mixed legacy sessions without an initial snapshot, or runs with checkpoints disabled require `--replay-base REVISION`. Choose
the actual starting revision, not today's checkout. `--replay-system FILE` adds up to
16 KiB of explicit experimental system guidance. Reports retain the patch, new usage,
original session usage, final-answer text comparison, and optional check result.
External services, dependencies, and tool behavior may have changed; replay is a new
experiment, not deterministic playback. Original session usage can include auxiliary
workers, so it is not automatically an equivalent cost comparison.

`smok -p 'task'` now emits JSONL by default. `--json` does the same for other one-shot
actions. New approvals are denied in JSON mode; selected policies and saved rules
remain active. Worker/council/replay failures return a nonzero status. Reports are local
artifacts; no sharing or publication occurs.
