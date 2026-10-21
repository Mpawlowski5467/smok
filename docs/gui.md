# Smok GUI and desktop

Smok provides a local browser app and a Tauri macOS wrapper. The React client
uses accessible Radix/shadcn component patterns, the supplied dragon artwork, and
the same core events and approval policy as the CLI.

![Smok's reviewed diff and approval controls](screenshots/approval-desktop.png)

The browser checks also capture the [desktop welcome screen](screenshots/workspace-desktop.png)
and [mobile layout](screenshots/workspace-mobile.png).

## Start the app

```sh
uv sync --locked --dev --extra lsp
uv run smok --gui --model ollama/qwen3.6:27b-mlx
# Choose a different workspace, or print the launch link without opening a browser:
uv run smok --gui -C /path/to/project --no-browser --port 8765
```

The tested local model is an existing installation on this machine; choose your own
installed model name. Smok does not download models. `smok-gui` is an equivalent
entry point. `--port 0` chooses an available port. The Python wheel already contains
the built frontend; Node is needed only when changing the frontend or rebuilding it.

For a first task, choose **Check setup** on the welcome screen or **Setup checks** in
the sidebar. Local checks inspect dependencies, configuration, and credential presence.
**Check model connection** explicitly requests a model list with the configured
credentials; it does not generate tokens or verify tool support. The report links
back to model settings and explains fixes. See [setup guidance](setup.md).

Open the **exact launch link**, including its fragment token. The app exchanges it
for a browser-session cookie and removes the token from the address bar. Only
127.0.0.1 is supported; binding to the LAN or using a reverse proxy is not supported.
A restart creates a new launch token. No cloud service is needed for the interface.

The native build is at:

```text
desktop/src-tauri/target/release/bundle/macos/Smok.app
```

Open it and choose a workspace in the native picker. The app bundles Python, the
server, and the frontend. Git and ripgrep must still be installed on the computer;
Homebrew's standard bin locations are included in the native server's PATH. The tray
menu offers **Show Smok** and **Quit Smok**. Closing the window hides it; quitting
stops turns and background processes and releases session locks. The server also
monitors the native parent process and shuts down if it disappears. There is one
workspace per native launch. This local build is ad-hoc signed, not notarized for
external distribution. Apple Silicon macOS is the verified native target.

## Chat, approvals, and sessions

- Choose **Plan** for investigation or **Build** for changes. Core enforcement stays
  in place even when a client sends a guessed or stale action.
- Choose a model in the toolbar. Models, endpoints, vision capability, context/output
  limits, and configured prices are editable in **Settings → Models**.
- Version 0.7 adds prompt style, tool set, and edit format to the same form. See
  [evaluation and tuning](evaluation.md) for their behavior and measured comparisons.
- Version 0.10.1 adds **Reasoning effort** for compatible models. **Provider default**
  leaves server behavior unchanged; choose another value only when the model supports
  it. The [local workflow guide](project-workflows.md#reasoning-control-for-the-local-model)
  documents the tested `none` option and its quality/completion measurements.
- Submit text with Enter; Shift+Enter adds a line. Command/Ctrl+Enter creates a new
  session, and Command/Ctrl+, opens Settings. Turns continue when a browser reloads
  or disconnects. **Stop turn** cancels the active work and settles reserved usage.
- Tool calls expand to show arguments, outputs, diffs, and approval results. Pending
  edits offer **Accept change**, **Always allow**, and **Reject change**. Saved rules
  and auto-edit/full-auto modes can approve changes without another prompt.
- Always allow saves the core's exact action/file scope, including hook/server context
  where applicable. Approvals use unique live request IDs; stale IDs cannot grant a
  later action. Pending approvals survive reconnects and deny after ten minutes.
- The session list includes CLI journals. Selecting a session watches it without
  acquiring the CLI's writer lock. **Resume here** succeeds only after the other
  owner releases it. Use **Release session** in the header to keep history while
  releasing GUI ownership and stopping that session's background processes.

Up to 12 sessions can be open in one server, with one active GUI action per workspace.
There can be separate active workspaces for branches. Shared checkpoint locks also
protect against overlapping Smok turns in other processes. A browser displays the
latest 400 coalesced events; the full bounded JSONL journal stays on disk.

## Context, work, and checkpoints

The right panel shows estimated token shares, pinned files, history groups, routing,
checkpoints, session totals, and configured-price previews. Preflight counts are
labeled separately from estimates. Costs with missing prices remain visibly incomplete;
local inference is $0 **API** cost, excluding hardware/electricity. Run budgets include
worker calls and preserve consumption when their limits change.

**Set run budget** also offers an optional **Turn time limit in seconds**. It covers
routing, approval waits, and active work. Expiry retains completed edits, checkpoints,
and usage and marks the turn incomplete. The limit is saved with the session; reopen
the dialog to change it or leave it blank to clear it. See [reliability](reliability.md).

Pin a relative file path to retain its fresh contents. Drop a pin or a complete
history group to remove it from the model context. **Compact context** uses the core's
validated summary workflow. Vision bytes are not included in text summaries; an explicit
marker tells the next turn to ask for the image again when necessary.

**Restore** returns files to the end of a completed checkpoint. It checks later file
changes first and records the restoration as a new checkpoint, so it can be undone.
Background processes in the same GUI workspace must be stopped first. Changes made
outside Smok can prevent automatic restoration.

**Branch** exports a completed checkpoint and its saved conversation state into
`.smok/branches/<id>`. The branch has its own files, sessions, and checkpoints. It does
not change the source workspace or its real Git HEAD/index. This is an independent
folder, not a Git branch; it does not copy ignored dependencies or external effects,
and it has no automatic merge-back. Branch lineage and session mapping persist.

**Tools** exposes review, compaction, handoff, skill/recipe/custom-command parameters,
MCP connection, extension reload, oracle, delegate, council, candidate acceptance,
replay, and background commands. Core approvals still apply. Team configuration
continues to use the Phase 5 settings described in [teamwork](teamwork.md). The left
panel shows worker progress, saved team runs, and background jobs. **Output** reads
a bounded page of process output; **Refresh latest output** reads the current tail.

## Settings and credentials

MCP forms accept a local executable and one argument per line, or a Streamable HTTP
URL. Environment variable names and read-only tool lists are separate fields. HTTP
header values refer to environment variables. Saving configuration never starts a
server; use the Tools menu or let the agent request a connection.

Permission forms manage the default mode, shell backend, and allow rules. Settings
reload the current saved rules before editing and reject a stale form revision.
The active model's plan/build mode and the per-session permission selector remain
explicit controls. Docker must already be available and its image installed; there
is no automatic pull or host fallback. MCP processes still run on the host.

Model preferences are saved in `.smok/gui.json`; ordinary permissions and MCP
configuration remain in `.smok/settings.json`. The CLI reads these GUI model defaults
and profiles as well. Explicit `--model`, `--config`, and `--base-url` remain available.

Keys entered in the UI are stored in `.smok/gui-keys.json` with mode 0600 and private
parent directories. They are excluded from workspace tools and Git/checkpoint snapshots.
This is a private local file, **not encrypted storage or the OS keychain**. The API
returns only configured/saved status. Environment keys also work. Removing a saved
key restores any environment value present before it was loaded. Settings changes
apply between turns; model-profile and key changes also apply to subsequent CLI starts.

## Images and voice

Attach or drop up to four still PNG/JPEG/WebP files, at most 2 MiB each, 4096 pixels
per dimension and 16 megapixels. Retained image context is capped at 6 MiB. The server
validates decoded bytes and media type, rejects animations and URL/path inputs, and
preserves images in the private journal. Enable **Vision input** only on a compatible
model profile. Both Anthropic and OpenAI-compatible adapters send native image blocks.
A text-only profile refuses image history before a model request.

Image estimates use pixels rather than base64 length; they are not provider-specific
billing formulas. Text handoffs and oracle evidence omit image bytes with a marker.
New image input skips text-only shadow comparisons. Images are not silently forwarded
to delegated text-only workers or reconstructed by session replay.

**Voice input** starts only after the user chooses **Start dictation**. Speech
recognition fills the composer and never submits automatically. The browser may use
an online speech service; the UI discloses this before starting. Support and microphone
permission vary by browser/webview. If unavailable, use the operating system's dictation
shortcut. Smok's server receives the submitted text, not raw microphone audio. Browser
event handling is tested with a speech fixture; physical microphone transcription and
provider vision interpretation remain manual runtime checks.

## Read-only sharing

**Share session → Preview transcript** shows the exact text projection before a link
is created. Tool calls/outputs are optional. Images, settings, pins, permission grants,
and artifact URLs are omitted; configured key values are redacted. Review other project
secrets yourself—automatic redaction is not a general secret detector. The server checks
that the preview digest still matches before creating the immutable snapshot.

Links use random read-only capabilities, expire after seven days, and can be revoked
in the share dialog. They grant no session actions, files, tools, or settings access.
Links work on this computer while its local server runs; they are not public hosting.
The port must match the active server. A new native launch may use another port;
reopen Share to obtain current links. Starting another authenticated browser tab does
not make a shared page editable.

## Development and checks

```sh
npm ci --prefix web
npm --prefix web run build
npm --prefix web run check
npm --prefix web test
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Browser tests start a disposable server with a deterministic model, never a paid API.
They cover the visible diff lines, reconnect, always-allow rules, pinning, settings,
sharing/revocation, branching, mobile layout, image attachment, and dictation text flow.
On macOS they use installed Chrome; set `SMOK_BROWSER` to another executable, or use
Playwright's bundled Chromium on Linux. No user browser profile is used.

A live, restricted fixture check is available:

```sh
uv run python evals/phase6.py --model ollama/qwen3.6:27b-mlx --allow-tools
```

Build the native app on macOS with Rust, Xcode command-line tools, Node, and Python:

```sh
uv sync --locked --dev --group desktop
npm ci --prefix web
npm ci --prefix desktop
uv run --group desktop python scripts/build_desktop.py
uv run python scripts/check_desktop.py
```

The script builds the frontend into `src/smok/gui/static`, freezes the server with
PyInstaller, and bundles the matching target-triple sidecar with Tauri. The macOS
configuration uses an ad-hoc signing identity, and the script verifies the complete
bundle signature. This local build keeps hardened runtime disabled so the one-file
Python sidecar can load its extracted libraries; a release signing configuration must
handle those libraries before enabling hardened runtime and notarization.
Developer ID signing, notarization, package naming, source/artwork licensing, and
package distribution remain release work. These build commands create local artifacts;
they do not publish a package, deploy a service, or upload a desktop installer.

`scripts/check_desktop.py` verifies the built app in a temporary workspace, including
offline setup checks, authentication, assets, saved deadlines, and clean shutdown.
`scripts/check_release.py` checks wheel/source-archive contents and version alignment
after `uv build`; CI runs it after compiling the frontend. See [local release checks](setup.md#verify-a-local-build).

References: [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/),
[shadcn Vite setup](https://ui.shadcn.com/docs/installation/vite),
[Tauri sidecars](https://v2.tauri.app/develop/sidecar/),
[Tauri tray](https://v2.tauri.app/learn/system-tray/),
[OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision),
[Anthropic vision](https://platform.claude.com/docs/en/build-with-claude/vision).
