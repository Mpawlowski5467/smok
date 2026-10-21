# Developing Smok

Smok is a development preview. Start with the [architecture](docs/architecture.md)
and [roadmap](docs/roadmap.md); the [documentation index](docs/README.md) covers each
subsystem. A source/artwork license has not yet been selected.

## Local setup

Use Python 3.12+, uv, Git, and ripgrep. Node 24 is used in CI.

```sh
uv sync --locked --dev --extra lsp
npm ci --prefix web
uv run smok --gui --model ollama/YOUR_INSTALLED_MODEL
```

Select an installed tool-capable model or a configured hosted endpoint. No model
download is required by the deterministic test suite. The browser UI is built into
`src/smok/gui/static`; rebuild it after changing `web/src`:

```sh
npm --prefix web run build
```

The [GUI guide](docs/gui.md#development-and-checks) covers the Vite development server
and the Rust/Tauri/PyInstaller desktop build. The local macOS app uses ad-hoc signing;
it is not a notarized public installer.

## Checks before a change is ready

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
npm --prefix web run build
npm --prefix web test
uv build
uv run python scripts/check_release.py
```

Python tests use disposable workspaces and local fixture servers. Allow loopback
network access. They do not contact a live model provider. Browser tests also use a
deterministic fixture and two desktop/mobile scenarios. On macOS they default to
installed Google Chrome; set `SMOK_BROWSER=/absolute/path/to/browser` to use another
compatible binary. On Linux, install Playwright's browser first:

```sh
cd web
npx playwright install --with-deps chromium
```

Return to the repository root for the remaining commands. CI runs the Python and
web/package jobs in [.github/workflows/checks.yml](.github/workflows/checks.yml).
Changes to the native wrapper should also run `scripts/build_desktop.py` and
`scripts/check_desktop.py` on a supported local macOS host.

## Add or run an evaluation

The [evaluation guide](docs/evaluation.md) describes controls, budgets, and reporting.
List tasks without inference:

```sh
uv run python evals/run.py --suite phase12 --list --split all
```

An explicit live run of the four known Phase 12 projects:

```sh
uv run python evals/run.py --suite phase12 --split all \
  --model ollama/YOUR_INSTALLED_MODEL --variant focused-repair \
  --allow-tools --allow-shell --repeats 1 \
  --max-iterations 16 --task-timeout 300 \
  --max-requests 64 --budget-tokens 1000000
```

This performs inference and executes the fixtures' permitted commands. Hosted
endpoints may charge for it. `focused-repair` requests no-thinking support; select a
compatible model or a different explicit profile. The disposable fixtures are not
an operating-system sandbox.

When adding a case or reporting an improvement:

1. Define the contract, seed, allowed edits/checks, reference repair, and independent
   grader before inference. Prove the seed fails and the reference passes.
2. Freeze the source, task/profile fingerprints, order, repeats, and limits. Keep
   correctness, final-file verification, and turn completion separate.
3. Retain failures and interrupted attempts. Do not retry until success and report
   only the final attempt, or count correct-but-unfinished code as a full pass.
4. Treat inspected cases as known regressions. Qualify a tuned profile on additional
   fresh tasks before making broader claims. Explicitly export a profile; do not
   silently promote it to a workspace default.
5. Commit concise plans/results and interpretation under `docs/`. Keep raw journals,
   generated workspaces, source archives, and credentials out of Git.

## Repository layout

```text
src/smok/        Shared loop, adapters, tools, sessions, approvals, and server
web/             React interface and browser checks
desktop/         Tauri host and native configuration
evals/           Fixtures, reference repairs, graders, runners, qualification
tests/           Deterministic Python regression suite
scripts/         Desktop build and native/package verification
examples/        Opt-in profiles, settings, and extensions
docs/            Guides, screenshots, plans, and compact results
assets/          Supplied dragon artwork
```

Keep `.smok/`, `.env` credentials, local model traces, dependency caches, and build
outputs ignored. Package checks verify source parity and reject those private or
generated paths. Desktop binaries are built locally and are not committed.
