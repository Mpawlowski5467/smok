# CLI and configuration reference

[Back to Smok](../README.md) · [Setup](setup.md) · [Documentation index](README.md)

This reference covers commands, tools, sessions, model profiles, budgets, and
execution boundaries. Start with the repository quick start for installation.

## Run

The browser app is included in the Python package. A local macOS desktop build is
available under `desktop/src-tauri/target/release/bundle/macos/Smok.app`; it includes
Python and opens a workspace picker. The native build is currently verified on Apple Silicon.

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, ripgrep (`rg`), and a
tool-capable model endpoint. The optional `lsp` extra installs the Python language server.

Use **Check setup** on the desktop welcome screen, or `smok --doctor --model
ollama/YOUR_INSTALLED_MODEL` in the CLI. Local checks create no session and make no
network request. Add `--probe-model` to request the endpoint's model list; generation
and tool support remain a separate check. `--json` emits a machine-readable report.

```sh
uv sync --dev --extra lsp
uv run smok --model ollama/qwen3.6:27b-mlx
# Or open the browser app:
uv run smok --gui --model ollama/qwen3.6:27b-mlx
```

This uses the existing Qwen model tested on the development machine. On another
machine, select the exact name from `ollama list`; Smok does not download models.
To work on another repository:

```sh
uv run smok -C /absolute/path/to/repo --model ollama/YOUR_INSTALLED_MODEL
```

Ask Smok to inspect a file, make a change, and run a check. Reads and searches run
immediately. Edits show a diff; shell commands show the command and execution backend.
The default permission mode asks before edits, shell execution, and language-server
startup. Enter `y` to allow once, `a` to remember approval, or Enter/`n` to deny.

| Command | Behavior |
| --- | --- |
| **Tab**, `/mode plan`, `/mode build` | Switch between investigation and implementation |
| `/permissions ask` | Ask for actions unless a saved rule permits them |
| `/permissions auto-edit` | Approve file edits; keep asking for commands and server startup |
| `/permissions full-auto` | Approve all available actions in the current mode |
| `/allow git status` | Save a shell argument pattern |
| `/rules`, `/rules clear` | Inspect or clear saved approvals |
| `/undo` | Restore the latest changed turn if its files still match |
| `/checkpoints` | List checkpoint history |
| `/model provider/model` | Switch model while keeping conversation history |
| `/model` | Show the selected model |
| `/sessions` | List saved sessions in this workspace |
| `/compact` | Summarize older history and retain recent exchanges |
| `/handoff` | Export an editable summary for a fresh session |
| `/context` | Inspect estimated token shares and complete history groups |
| `/context pin path/to/file` | Include fresh file contents in subsequent turns |
| `/context drop path/to/file`, `/context drop group:3` | Remove a pin or a complete history group |
| `/map [query]` | Inspect a relevance-ranked Python/JS/TS repository outline |
| `/todos` | Inspect the model-maintained task list |
| `/usage`, `/cost [provider/model]` | Inspect usage and preview configured costs |
| `/extensions`, `/reload` | Inspect or reload local extensions; reload disconnects MCP sessions |
| `/skill NAME`, `/recipe NAME key=value` | Run a skill or parameterized workflow |
| `/COMMAND key=value` | Run an installed Markdown command, including `PLUGIN/COMMAND` |
| `/mcp [SERVER]` | List servers or request a connection |
| `/review [BASE]` | Review uncommitted changes or committed changes against a branch |
| `/clear` | Clear conversation, pins, todos, and file reads; retain usage totals |
| `/help`, `/exit` | Show help or leave Smok |

Plan mode removes `write_file`, `edit_file`, and `run_shell` from the model's tools
and rejects calls to them in the core, even under full-auto. Hooks are suspended;
MCP tools require an explicit local `read_only` list. Server startup still follows
permissions. Tab toggles mode at the prompt; Ctrl-Space completes slash commands.

## Extensions and review

Put skills, commands, recipes, and declarative plugin bundles in `.smok-extensions/`.
Only skill names and descriptions enter the prompt; full instructions load on demand.
The agent can author these files and call `reload_extensions` mid-session. Matching
hooks require approval alongside the action, including edits under `auto-edit`.

MCP stdio and Streamable HTTP servers are configured in `.smok/settings.json` and
started on demand. Tools are namespaced by server and keep the same approval path.
Playwright MCP provides browser navigation, accessibility snapshots, interactions,
and saved screenshots. `web_fetch` retrieves bounded source text; `web_search` uses
Brave or a configured SearXNG JSON endpoint. Brave requires an environment API key.

```sh
uv run smok --extensions
uv run smok --command dev/check --param target=src/app.py
uv run smok --recipe dev/change --param task="Add pagination"
uv run smok --review
uv run smok --review main
```

The `dev` commands require installing the bundled example. See the
[extension setup guide](extensions.md) for its layout, settings, permissions,
Playwright installation, hooks, and complete examples. Review runs in plan mode and
reports findings with file/line references; its findings and severity are model judgments.

## Coding tools

- `read_file` returns numbered lines with `offset` and `limit`; UTF-8 files up to
  16 MiB are supported, with bounded output. Existing files must be read before edits.
- `edit_file` replaces one exact, unique string and shows a unified diff. Ambiguous
  matches, stale reads, and files changed during approval are refused. `write_file`
  supports new files and complete replacements. Both write atomically.
- Successful writes retain their exact known contents for follow-up edits. External
  changes still require a fresh read; hooks, context resets, and resumed sessions
  invalidate that knowledge.
- `grep` and `glob` use ripgrep with bounded output. Ordinary traversal honors ignore
  files; explicit include globs follow ripgrep's override behavior. `.git`, `.smok`,
  `.venv`, `node_modules`, and Python caches stay excluded from search.
- Root `AGENTS.md` is loaded into the system prompt. Nested instructions are loaded
  as their scopes are visited, and file edits are blocked until applicable new or
  changed guidance has been read. Deeper guidance applies within its directory.
- `lsp_diagnostics`, `lsp_definition`, and `lsp_references` use stdio LSP. Position
  inputs are 1-based Unicode characters; locations return 1-based UTF-16 columns.
  Raw diagnostic ranges follow LSP's 0-based convention. Open documents are refreshed
  after changes. Unversioned reports are marked `version_verified: false`. Missing reports and timeouts are errors, not clean checks.
- After changed work, a self-check pass supplies the actual checkpoint diff and
  recorded command results to the model before turn completion. Related edits can
  reach a shell check before review; without a shell tool, review starts immediately.
  If the model skips checks, its draft completion is withheld until review. Further
  edits require a fresh review. The pass shares the turn's iteration budget; it does not
  guarantee correctness or turn unrun checks into passing checks.
- `write_todos` maintains up to 30 session tasks, with at most one in progress.
  It works in plan mode and does not grant file permissions.
- `repo_map` extracts names and line numbers using Tree-sitter for Python,
  JavaScript/JSX, and TypeScript/TSX. Outlines rank prompt terms, pinned paths, and
  symbol references. Discovery honors ignore rules and caps at 500 supported files;
  each file is limited to 256 KiB. Outlines do not satisfy read-before-edit checks.
- Results longer than 12,000 characters have a saved output ID. `read_output`
  retrieves pages by character offset, including after resume. Selected file ranges
  and command/search capture are retained up to 16 MiB; exceeding that cap is explicitly
  marked and the remainder cannot be recovered. Archives live under `.smok/outputs/`.

## Sessions and context

Every logged session has an ID, displayed at startup and in the `turn_started` JSON
event. Resume within the same workspace:

```sh
uv run smok -C /path/to/repo --sessions
uv run smok -C /path/to/repo --continue
uv run smok -C /path/to/repo --resume SESSION_ID -p "Continue the repair."
uv run smok -C /path/to/repo --continue --compact
uv run smok -C /path/to/repo --continue --export-handoff
uv run smok -C /path/to/repo --handoff /path/to/summary.json -p "Continue."
```

Resume restores history, todos, pinned paths, mode, model selection, working context
limits, and cumulative usage. Current project permissions and environment credentials
are loaded again. File-read grants are cleared, pinned files are refreshed, and pending
tools are never replayed automatically. Reuse `--config` for custom endpoints/profiles.
One process can open a given session at a time. A partial final JSONL record from a
crash is discarded; a damaged complete record is rejected. Older 0.1/0.2 event-only
logs can be listed but cannot be resumed.

At 80% of the configured context allowance, Smok summarizes older history into goal,
files touched, decisions, open todos, and notes. It retains the last four complete
history groups by default; a tool call and all its results always stay together.
Compaction clears file-read grants and preserves original history if generation or
validation fails. Summaries are lossy: the append-only journal retains earlier states.
Pins, the current todo list, and project guidance stay outside the summarized history.
If a recent exchange or fixed context cannot fit, Smok stops before generation and
asks you to drop context or adjust the working limit.

`/handoff` summarizes the whole conversation, folding large histories in bounded
requests, and saves an owner-only JSON file in `.smok/handoffs/`. Edit that file before
using `--handoff FILE`; the fresh session starts with that reference text and its own
history and usage totals. A handoff does not transfer approvals or replay actions.

## Usage and budgets

```sh
uv run smok --context-window 32768 --max-output-tokens 4096 --max-turns 8 \
  --budget-tokens 150000 --model ollama/YOUR_INSTALLED_MODEL
```

`--max-iterations` caps model requests per user turn, including compaction and review.
`--turn-timeout 180` adds a saved 180-second turn deadline covering routing, approvals,
and active work. `--turn-timeout 0` clears a saved deadline. Expiry preserves partial
work and usage and reports an incomplete turn; see [reliability](reliability.md).
`--max-turns`, `--budget-tokens`, and `--budget-usd` apply to the current CLI invocation;
resuming starts a new run budget while retaining session totals. `/clear` does not reset
either usage ledger or the run's turn count. Before each generation, Smok reserves the
input estimate plus the full output allowance. An interrupted request without final
usage is charged that reserved estimate so it cannot silently become free.

Final usage comes from the provider when available. Anthropic also supports a
preflight token-count request; that count is provider-estimated, not an exact billing
promise. Other endpoints use a configurable UTF-8 byte heuristic (default 3 bytes per
token). `/context` always labels its component breakdown as estimated. Model working
limits default to 32,768 tokens, not an advertised context window. Verify limits with
your endpoint before increasing them.

Cost previews and dollar budgets require explicit per-million-token prices in your
model profile; unknown prices display as `null` and block dollar-budget requests.
Cache reads and writes are counted separately, and preview reservations assume a cold
cache. `local: true` means zero API inference cost, excluding hardware and electricity;
set it to `false` with prices for a paid compatible endpoint. Estimates and configured
prices are guardrails, not a provider billing cap. `/cost` compares the current model
with named models in the supplied config, or one explicitly selected model.

## Checkpoints and undo

By default, every turn captures before/after snapshots in a separate Git object
store under `.smok/checkpoints/`. Smok does not commit, stash, or reset your repository
and does not change its Git index or HEAD. Pre-existing staged and dirty changes survive
undo. `smok -C /path/to/repo --undo` also works without contacting a model.

Undo preflights every changed path and refuses the operation if any differs from the
end-of-turn snapshot. Files created during the turn are removed; deleted files and
previous contents/modes/symlinks are restored. Unrelated later files remain untouched.
Snapshots include tracked files and nonignored untracked files, up to 5,000 files,
16 MiB per file, and 128 MiB total. Ignored/generated files, excluded metadata, empty
directories, and effects outside the workspace are not restored. File-to-directory
replacements may require manual recovery. Avoid concurrent manual edits during a
turn: snapshots capture workspace changes, not authorship.

Cancelled turns retain an end snapshot when cleanup succeeds. A hard crash has no
reliable end boundary; Smok preserves the before snapshot and refuses automatic undo
of that interrupted turn. A later turn archives it as abandoned. `--no-checkpoints`
explicitly disables snapshots and undo. Without checkpoints, self-check can review
file-tool diffs but cannot discover shell-only changes.

## Project settings and shell execution

`/permissions`, `/allow`, and remembered approvals are saved in `.smok/settings.json`.
CLI overrides apply only to that run. An example configuration:

```json
{
  "permissions": "ask",
  "allow_rules": [
    {"tool": "run_shell", "match": "argv", "command": "git status"},
    {"tool": "run_shell", "match": "argv", "command": "pytest tests/*"}
  ],
  "sandbox": {"backend": "host", "image": "python:3.12-slim", "network": false}
}
```

Argument rules match the complete token count; a wildcard matches within one
argument. Shell operators, substitution, pipelines, redirection, and newlines require
separate approval. Remembered commands match the exact command string; remembered
file grants match the exact resolved file. Manually configured `file_edit` rules can
use `"match": "glob"`. Review local settings before using an unfamiliar workspace.

The default **host** backend runs commands with your user's permissions and network
access. Approval and workspace file checks do not provide OS isolation. To use the
optional Docker shell backend, start Docker and install the chosen image yourself:

```sh
uv run smok --sandbox docker --sandbox-image python:3.12-slim \
  --model ollama/YOUR_INSTALLED_MODEL
```

Containers mount only the selected workspace, with existing `.git` and `.smok`
metadata overlaid read-only. They run as the current UID/GID with dropped capabilities,
resource limits, a read-only root filesystem, and a temporary `/tmp`. Networking is
disabled by default; `--sandbox-network` explicitly enables it. Smok neither pulls
images nor falls back to the host when Docker fails. Timeout/cancellation removes the
named container. Choose an image with the tools your project needs; host virtual
environments usually cannot run in Linux containers.

Docker applies to `run_shell`. Model HTTP calls and configured language servers run
on the host. LSP server startup is executable code and needs approval; the LSP client
rejects server-initiated workspace edits. Additional servers can be configured with
`lsp_servers` entries containing `language`, `extensions`, `command` (an argv list),
and optional `settings`. The default Python command is `pylsp`.

## Providers

Use actual model IDs available to your account or endpoint. Set credentials in your
shell; `.env.example` documents variables but `.env` is not automatically loaded.

| Prefix | Endpoint | Key variable |
| --- | --- | --- |
| `ollama/` | `http://127.0.0.1:11434/v1` | Optional `OLLAMA_API_KEY` |
| `anthropic/` | Anthropic Messages | `ANTHROPIC_API_KEY` |
| `openai/` | OpenAI Chat Completions | `OPENAI_API_KEY` |
| `gemini/` | Gemini OpenAI-compatible endpoint | `GEMINI_API_KEY` |
| `openrouter/` | OpenRouter | `OPENROUTER_API_KEY` |
| `local/` | `http://127.0.0.1:1234/v1` | Optional `SMOK_API_KEY` |

```sh
uv run smok --model anthropic/YOUR_MODEL_ID
uv run smok --model openai/YOUR_MODEL_ID
uv run smok --model local/YOUR_MODEL_ID --base-url http://127.0.0.1:1234/v1
```

Optional YAML overrides (`--config models.yaml`) merge into bundled profiles:

```yaml
default_model: ollama/my-coder
models:
  ollama/my-coder:
    context_window: 32768
    max_output_tokens: 8192
    timeout_seconds: 300
    compact_at: 0.8
    keep_recent: 4
    chars_per_token: 3.0 # UTF-8 bytes per estimated token
    repo_map_tokens: 1500 # set 0 to disable automatic outlines
```

For paid models, add a `prices` mapping with verified `input`, `output`, `cache_read`,
and `cache_write` USD rates per million tokens. No remote rates are bundled or guessed.
Anthropic profiles enable `count_tokens` and `prompt_cache`; either can be disabled in
an override. Explicit ephemeral cache markers cover the tool schema, stable system
prefix, and history boundary. Cache hits depend on the endpoint's minimum sizes and
prefix reuse; sending a marker does not prove a hit. Compatible endpoints accept
optional `reasoning_effort` controls; supported values depend on the model. GUI image
input requires an explicitly vision-capable profile. These adapter paths have local
protocol tests; live frontier reasoning, vision, and cache billing remain unverified.
Gemini/OpenRouter/LM Studio routes have not been verified against live endpoints.

Since 0.12.2, compatible profiles also accept optional `temperature` (0–2) and
`top_p` (0–1). Set these under the model's YAML entry or in Settings → Models.
Null omits a field; zero is sent explicitly. CLI session resume retains the selected
values. Omitting a field uses endpoint behavior, which may override installed model
parameters. See [evaluation controls and the sampling audit](evaluation.md).

## One task or JSON events

```sh
uv run smok --mode plan -p "Read README.md and explain this project."
uv run smok --json --permissions auto-edit -p "Fix the typo in README.md."
```

`-p` emits JSONL by default. `--json` and `--no-input` deny **new approval requests**; saved rules and selected
permission modes still apply. `--yes` aliases `--permissions full-auto` for this run.
Exit statuses: `0` model/action completed, `1` setup or standalone action error, `2`
turn provider/context error, time/iteration/run budget cap, or failed recipe step; `130` interrupted.
Completion still requires checking the model's work.
`--no-self-check` disables the automatic review pass.

Sessions write owner-only JSONL files under `.smok/sessions/`, including conversation
state, prompts, and tool outputs. `--no-log` disables session persistence and cannot
be combined with resume; checkpoints and output archives remain enabled. Add `.smok/`
to the repository's ignore file. JSONL records are capped at 16 MiB and sessions at
256 MiB; start a handoff session before reaching the storage limit.
