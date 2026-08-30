#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

die() {
	printf 'dev: %s\n' "$*" >&2
	exit 1
}

[[ -f "$repo_root/.env.sh" ]] || die "missing $repo_root/.env.sh"
# shellcheck disable=SC1091
source "$repo_root/.env.sh"

command -v uv >/dev/null 2>&1 || die "uv is required"
command -v npm >/dev/null 2>&1 || die "npm is required"
[[ -n "${POUND_ARTIFACT_PATH:-}" ]] || die "POUND_ARTIFACT_PATH is not set"
[[ -f "$POUND_ARTIFACT_PATH" ]] || die "artifact not found: $POUND_ARTIFACT_PATH"
[[ -n "${POUND_BOAT_HIRE_ENRICHMENT_PATH:-}" ]] || \
	die "POUND_BOAT_HIRE_ENRICHMENT_PATH is not set"
[[ -f "$POUND_BOAT_HIRE_ENRICHMENT_PATH" ]] || \
	die "boat-hire enrichment not found: $POUND_BOAT_HIRE_ENRICHMENT_PATH"
[[ -d "$repo_root/web" ]] || die "frontend directory not found: $repo_root/web"

backend_pid=""
frontend_pid=""

cleanup() {
	local status="${1:-0}"
	local child_status
	local backend_running=0
	local frontend_running=0
	trap - EXIT INT TERM

	if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
		backend_running=1
	fi
	if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
		frontend_running=1
	fi

	for pid in "$frontend_pid" "$backend_pid"; do
		if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
			if wait "$pid"; then
				child_status=0
			else
				child_status=$?
			fi
			if ((status == 0 && child_status != 0)); then
				status=$child_status
			fi
		fi
	done

	if ((frontend_running)); then
		kill "$frontend_pid" 2>/dev/null || true
	fi
	if ((backend_running)); then
		kill "$backend_pid" 2>/dev/null || true
	fi
	for pid in "$frontend_pid" "$backend_pid"; do
		if [[ -n "$pid" ]]; then
			wait "$pid" 2>/dev/null || true
		fi
	done
	exit "$status"
}

trap 'cleanup "$?"' EXIT
trap 'cleanup 130' INT
trap 'cleanup 143' TERM

printf 'Starting backend on http://127.0.0.1:8000\n'
uv run uvicorn pound_web.app:app --host 127.0.0.1 --port 8000 --reload &
backend_pid=$!

printf 'Starting frontend on http://127.0.0.1:5173\n'
(
	cd "$repo_root/web"
	exec npm run dev -- --host 127.0.0.1 --port 5173
) &
frontend_pid=$!

set +e
wait -n "$backend_pid" "$frontend_pid"
status=$?
set -e
cleanup "$status"
