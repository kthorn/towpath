#!/usr/bin/env bash
set -euo pipefail

source_home="${CODEX_SOURCE_HOME:-${CODEX_HOME:-$HOME/.codex}}"
worker_home="${CODEX_WORKER_HOME:-}"
if [[ -z "$worker_home" ]]; then
  tmp_root="${TMPDIR:-/tmp}"
  mkdir -p "$tmp_root"
  worker_home="$(mktemp -d "$tmp_root/towpath-codex-worker.XXXXXX")"
  trap 'rm -rf -- "$worker_home"' EXIT
fi

for required in auth.json config.toml; do
  if [[ ! -f "$source_home/$required" ]]; then
    printf 'missing Codex worker configuration: %s\n' "$source_home/$required" >&2
    exit 2
  fi
done

mkdir -p "$worker_home"
chmod 700 "$worker_home"
install -m 600 "$source_home/auth.json" "$source_home/config.toml" "$worker_home/"

shopt -s nullglob
profiles=("$source_home"/*.config.toml)
if ((${#profiles[@]})); then
  install -m 600 "${profiles[@]}" "$worker_home/"
fi

export CODEX_HOME="$worker_home"
codex "$@"
