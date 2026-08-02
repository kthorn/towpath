# Local development launcher design

## Goal

Provide one Linux Bash command that launches the existing FastAPI backend and Svelte/Vite frontend for local testing.

## Chosen approach

Add a tracked `scripts/dev.sh` Bash script. It is a small process supervisor rather than a new dependency or a `tmux`/Node-based launcher.

The script will:

1. Resolve the repository root from the script location and run from there.
2. Require and source the existing `.env.sh` file.
3. Verify `uv`, `npm`, and the configured `POUND_ARTIFACT_PATH` are available.
4. Start FastAPI with Uvicorn on `127.0.0.1:8000` using the repository's development reload command.
5. Start Vite from `web/` on `127.0.0.1:5173`.
6. Leave both processes' output attached to the terminal.
7. Stop the sibling process when either child exits and stop both children on Ctrl-C or termination.
8. Return a non-zero status if a child fails.

The script will not install Python or Node dependencies, build artifacts, open a browser, or add configurable command-line flags. Existing environment variables remain the source of runtime and public frontend configuration.

## Error handling

Missing `.env.sh`, missing required commands, or a missing artifact will fail before either server starts with an actionable message. A backend startup failure (including an invalid artifact) or frontend startup failure will terminate the other process and propagate failure to the shell.

## Verification

Add a focused shell-script test that checks the script is executable, uses strict Bash mode, sources `.env.sh`, launches the expected backend/frontend commands, and cleans up child processes. Run the focused test, Ruff's existing checks, and the default Python suite; do not install dependencies or run a live Google smoke test as part of this change.
