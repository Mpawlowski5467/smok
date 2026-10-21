# Extensions

Smok 0.4 adds skills, Markdown commands, hook commands, plugin bundles, recipes,
MCP, web tools, and Git review. These capabilities use the existing model/tool loop,
permission policy, output archives, session journal, and run budgets.

## A first bundle

Copy the example into the **target workspace**, then list it without a model call:

```sh
mkdir -p /path/to/workspace/.smok-extensions/plugins
cp -R examples/extensions/plugins/dev /path/to/workspace/.smok-extensions/plugins/
uv run smok -C /path/to/workspace --extensions
uv run smok -C /path/to/workspace --model ollama/YOUR_MODEL \
  --command dev/check --param target=src/app.py
```

In the REPL use `/extensions`, `/reload`, `/dev/check target=src/app.py`, or
`/recipe dev/change task="Add pagination"`. Extra words become `{{args}}`; named
arguments use `key=value` with shell-style quoting. Values are substituted as text
once, never evaluated as code. `--arguments TEXT` and repeated `--param KEY=VALUE`
provide the same inputs in one-shot mode. `/skill NAME` or `--skill NAME` runs a skill
directly. `/reload` also disconnects existing MCP sessions; reconnect explicitly.

The example's hook is inactive until `hooks.example.yaml` is copied to `hooks.yaml`.
That optional formatter needs `python3` and `ruff` in the selected shell backend.
Installing a bundle does not execute its code.

## Layout and validation

```text
.smok-extensions/
  skills/NAME/SKILL.md
  commands/NAME.md
  recipes/NAME.yaml
  hooks.yaml
  plugins/PLUGIN/
    plugin.yaml
    skills/NAME/SKILL.md
    commands/NAME.md
    recipes/NAME.yaml
    hooks.yaml
    supporting_files.py
```

Names are lowercase `[a-z][a-z0-9_-]{0,39}`. Plugin entries are namespaced as
`PLUGIN/NAME`; top-level commands cannot replace built-ins. A plugin manifest has
exactly `name` and `description`. Manifests/instructions are capped at 64,000 bytes,
the catalog at 100 skills/commands/recipes and 30 hooks, and each directory at 100
entries. Discovery rejects symlinks, malformed YAML, duplicates, missing fields,
unknown template variables, and missing required parameters. A failed reload leaves
the previous catalog and connections intact. Supporting files are ordinary workspace
files; there are no automatic Python imports or plugin installation scripts.

Skills and commands use YAML front matter:

```markdown
---
name: explain
description: Explain one source file
parameters:
  path: null
  style: concise
---
Read {{path}} and give a {{style}} explanation. {{args}}
```

`null` marks a required parameter; string values are defaults. Skill names and
descriptions alone enter the system prompt. `load_skill` reads the full body on
demand. Skills generally need no parameters; parameterized direct invocations use
`/skill NAME key=value`. Changed instructions must be reloaded before use. Neither
skill text nor retrieved web/MCP data can grant permissions or override the user.

## Hooks and permissions

```yaml
- name: prevent-removal
  event: before_tool
  tools: [run_shell]
  command: python3 .smok-extensions/check_command.py
  timeout_seconds: 10
```

Hook events are `before_tool` and `after_tool`. `tools` contains name glob patterns,
including exported MCP names if desired. The shell command is fixed configuration;
tool arguments are passed as JSON on **stdin**, without shell interpolation:

```json
{
  "event": "after_tool",
  "tool": "edit_file",
  "arguments": {"path": "src/app.py", "old_text": "...", "new_text": "..."},
  "truncated_arguments": [],
  "result": "...",
  "is_error": false
}
```

Top-level string arguments and results are clipped at 12,000 characters; clipped
argument names are listed. Hooks run sequentially in the workspace, through the
configured host/Docker backend, with bounded output and process-group cleanup.
They receive that backend's environment, like shell commands. A nonzero exit or
timeout before a tool blocks it. After-hooks also receive tool failures. An after-hook
failure reports that the tool already finished and preserves its original result;
it does not pretend to roll back the action. Hook evidence joins self-check evidence.
Remembered file-read hashes are invalidated after hook execution.

A matching hook makes the whole action require approval, including reads and edits
under `auto-edit`. The approval display includes arguments, hook commands and backend.
An “always” grant matches the exact action/arguments, hook configuration, and backend.
MCP grants additionally bind the configured server and discovered input schema.
Changing a command, argument, backend, or schema needs a new grant. Like saved shell
grants, these trust the named executable/script; they do not pin its binary or imported
source files. Full-auto authorizes these actions explicitly. **Plan mode suspends
all hooks**, blocks file/shell mutations, and applies the MCP rules below.

Hooks are trusted automation, not an OS security boundary. Without checkpoints,
self-check evidence contains tool diffs and hook command results, not a complete diff
of arbitrary files changed by a hook. Undo cannot reverse external services or browser
actions. Docker integration for hooks is covered by construction tests; a live container
check remains pending because the development daemon is stopped.

## Recipes and self-authored extensions

```yaml
name: inspect-and-check
description: Inspect a file and verify its behavior
parameters:
  target: null
steps:
  - Read {{target}} and identify the relevant existing check.
  - Run that check if permitted, then report its actual result.
```

Recipes contain 1–20 prompt steps and share conversation, permissions, context,
checkpoints, and usage budgets. Each step is a user turn; failed/denied tools or
iteration/budget limits stop the workflow. A recipe cannot elevate plan mode.
Cancellation closes the active turn normally. These are prompt workflows, so model
judgment still determines whether the requested work is correct.

The agent can create `.smok-extensions` files using ordinary read/edit/write tools,
then call `reload_extensions` during the same session. The next request sees updated
metadata; `load_skill` reads new instructions. Newly discovered hook code runs only
through the permission rules above. Project settings and credentials remain in the
protected `.smok` directory and environment.

## MCP servers

Merge the relevant fields into `.smok/settings.json`:

```json
{
  "mcp_servers": {
    "local": {
      "command": "/absolute/path/to/mcp-server",
      "args": ["--stdio"],
      "env_vars": ["SERVICE_API_KEY"],
      "timeout_seconds": 30,
      "read_only": ["lookup"]
    },
    "remote": {
      "url": "https://mcp.example.com/mcp",
      "headers_env": {"Authorization": "SMOK_MCP_AUTHORIZATION"},
      "timeout_seconds": 30
    }
  }
}
```

Set `SMOK_MCP_AUTHORIZATION` to the complete header value (for example `Bearer …`).
Secrets are resolved at connection time and are not put into the approval display.
Stdio inherits the SDK's small default environment plus explicitly listed variables;
it does not inherit every API key in your shell. Remote HTTP endpoints require HTTPS;
plain HTTP is limited to loopback. URLs cannot embed credentials or query tokens,
and HTTP redirects are disabled. OAuth login flows are not implemented.

`/mcp` lists configured servers. `/mcp local` or the `mcp_connect` tool requests
startup approval, discovers tools, and retains the connection. Discovery never runs
automatically at launch, reload, or session resume. Tool names have the form
`mcp__SERVER__TOOL_HASH`, bounded to provider naming limits. Each call is independently
approved; approval to start a server does not approve its tools. The official Python
SDK is used with the legacy handshake for interoperability with current and older
servers; both stdio and Streamable HTTP are tested. One owning task handles each
connection so cancellation and cleanup respect the SDK's context lifetime.

Plan mode permits only tool names explicitly listed in the server's local `read_only`
configuration. Server-provided read-only hints alone do not grant access. Starting
such a server still needs approval; the list is a user assertion about the server's
behavior, not a sandbox. MCP subprocesses run on the **host**, even when shell tools
use Docker. HTTP servers execute remotely. Sampling, elicitation, and automatic
side-effect retries are not enabled. Timeout/disconnect requires explicit reconnect;
inspect state before retrying an action that may already have completed.

Discovery is capped at 200 tools and 10 pages per server. Local JSON Schema references
are supported; external references are refused. Text and structured results use the
normal output archive. Supported image/audio blocks up to about 6 MB are saved under
`.smok/artifacts/` with absolute paths; oversized/unsupported media and binary embedded
resources are explicitly omitted. Model image input remains a future phase.

## Playwright browser integration

The browser is an MCP server, with the same startup/call approval path. A tested setup
uses **@playwright/mcp 0.0.83**, Node 18+, and an existing Chrome installation:

```sh
npm install --prefix .smok/browser --save-exact @playwright/mcp@0.0.83
```

Merge the `playwright` entry from [the example settings](../examples/settings.phase4.json)
into your settings. It selects a headless isolated profile, blocks service workers,
and disables page-provided WebMCP tools. It does not attach to your personal browser
or import existing login state. No npm package or browser is installed by Smok itself.
For a different installed Chromium executable, replace `--browser chrome` with
`--executable-path /absolute/path/to/browser`.

Connect with `/mcp playwright`, then ask Smok to inspect your application URL. Use
the discovered tool schemas: this tested version's click tool accepts `target`, and
screenshots require `scale`. Navigation may return a snapshot file link; an explicit
`browser_snapshot` call returns the accessibility tree inline. Browser operations
remain in build mode by default. Screenshot artifacts can be opened from their saved
paths. Browser/network access is governed by the server and browser, independently of
`web_fetch`'s public-address checks and the Docker shell backend.

## Web and review

`web_fetch(url)` retrieves text, HTML, JSON, or XML without executing JavaScript.
It strips script/style content, returns the final source URL and links, uses a 30-second
overall timeout and a 2 MiB body cap, and follows at most five redirects. DNS answers
are checked before connecting to a numeric address; TLS still verifies the original
hostname. Private/loopback/reserved addresses are blocked at every new connection,
and HTTPS-to-HTTP redirects are refused. There is no environment proxy or cookie jar.

Search defaults to Brave with `BRAVE_SEARCH_API_KEY`; no key means an actionable error.
Alternatively configure your own SearXNG JSON endpoint:

```json
{
  "web": {
    "search_provider": "searxng",
    "search_url": "http://127.0.0.1:8888/search",
    "allow_hosts": ["127.0.0.1"]
  }
}
```

`allow_hosts` is an explicit exact-host override for local/internal services; no
wildcards. Search credentials are environment-only and never follow redirects.
Both web tools require approval and return source attribution. Search-service charges
are separate from model-token budgets. Live validation uses a local SearXNG-shaped
fixture; a production Brave API run remains pending an API key.

`/review` or `--review` reviews staged, unstaged, and untracked non-ignored changes.
`/review BASE` or `--review BASE` reviews committed changes from the merge-base with
BASE to HEAD, excluding current working changes. The workspace must be the repository
root. Git external diff/textconv drivers are disabled, metadata is excluded, and the
diff is bounded with explicit truncation. The `review_diff` tool collects evidence;
the model inspects relevant code and reports actionable findings with priority and
file/line references. Review temporarily enters plan mode, shares the run budget,
and restores the prior mode afterward. Review findings and severity remain model
judgments; passing a smoke eval does not establish general review accuracy.

## References

- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Official Playwright MCP](https://github.com/microsoft/playwright-mcp)
- [Brave Search API](https://api-dashboard.search.brave.com/api-reference/web/search/post)
