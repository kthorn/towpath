#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
default_documents=(
  "$repo_root/docs/completed/2026-07-12-osm-poi-ingest-design.md"
  "$repo_root/docs/completed/2026-07-14-osm-poi-multipass-memory-design.md"
)
documents=()
model=""
output=""
timeout_seconds=180
repo_tools=false

usage() {
  cat <<'EOF'
Usage: scripts/review_design.sh --model MODEL --output FILE [--document FILE ...] [--timeout SECONDS] [--repo-tools]

Runs a read-only PI convergence review of the supplied documents and writes the final model response
to FILE. --document may be repeated; by default the completed OSM POI design and memory plan are used.
EOF
}

while (($#)); do
  case "$1" in
    --model)
      model="${2:?--model requires a value}"
      shift 2
      ;;
    --output)
      output="${2:?--output requires a value}"
      shift 2
      ;;
    --document)
      documents+=("${2:?--document requires a value}")
      shift 2
      ;;
    --timeout)
      timeout_seconds="${2:?--timeout requires a value}"
      shift 2
      ;;
    --repo-tools)
      repo_tools=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$model" || -z "$output" ]]; then
  usage >&2
  exit 2
fi
if ((${#documents[@]} == 0)); then
  documents=("${default_documents[@]}")
fi
document_args=()
for document in "${documents[@]}"; do
  if [[ ! -f "$document" ]]; then
    printf 'document not found: %s\n' "$document" >&2
    exit 2
  fi
  document_args+=("@$document")
done
if [[ ! "$timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
  printf 'timeout must be a positive integer: %s\n' "$timeout_seconds" >&2
  exit 2
fi
if [[ -e "$output" || -L "$output" ]]; then
  printf 'output already exists: %s\n' "$output" >&2
  exit 2
fi
command -v pi >/dev/null || { printf 'pi is not installed\n' >&2; exit 2; }
command -v timeout >/dev/null || { printf 'timeout is not installed\n' >&2; exit 2; }

output_dir="$(dirname -- "$output")"
output_name="$(basename -- "$output")"
mkdir -p "$output_dir"
tmp="$(mktemp --tmpdir="$output_dir" "$output_name.tmp.XXXXXX")"
trap 'rm -f -- "$tmp"' EXIT

printf 'Reviewing %s document(s) with %s (timeout: %ss)...\n' \
  "${#documents[@]}" "$model" "$timeout_seconds" >&2

tool_args=(--no-tools)
review_scope="Review only the supplied design and implementation documents and the established code facts below."
if [[ "$repo_tools" == true ]]; then
  tool_args=(--tools read,grep,find,ls)
  review_scope="Inspect repository files only when needed to verify the supplied design."
fi

set +e
timeout "${timeout_seconds}s" pi \
  --model "$model" \
  --thinking off \
  --no-session \
  --no-extensions \
  --no-skills \
  --no-context-files \
  "${tool_args[@]}" \
  --approve \
  --system-prompt "You are a read-only technical design reviewer. Do not modify files, invoke workflows, request more context, or narrate your process. Return the requested findings directly." \
  --print \
  "${document_args[@]}" \
  "$review_scope Established code facts: Pound is Python 3.12; routing uses an immutable NetworkX graph loaded from a trusted local pickle artifact; graph handles are artifact-scoped integers; graph edge geometry is stored as (lat, lon); Overpass retains parsed POIs; production bulk England builds use a separate multi-pass POI accumulator rather than the graph-only WaterwayFeatures IR; candidate lookup uses GraphSpatialIndex. Check both internal design consistency and whether the implementation plan faithfully realizes it. Identify at most three remaining issues that would materially block or misdirect implementation. Do not repeat concerns already addressed by the documents. Format each as SEVERITY | SECTION | ISSUE | REQUIRED EDIT. Output CONVERGED if no material issues remain."  \
  > "$tmp"
review_status=$?
set -e

if [[ "$review_status" -eq 124 ]]; then
  printf 'review timed out after %s seconds\n' "$timeout_seconds" >&2
  exit 124
fi
if [[ "$review_status" -ne 0 ]]; then
  printf 'pi failed with exit code %s\n' "$review_status" >&2
  exit "$review_status"
fi

if [[ ! -s "$tmp" ]]; then
  printf 'reviewer returned no final text\n' >&2
  exit 1
fi

if ! mv -n -- "$tmp" "$output" || [[ -e "$tmp" ]]; then
  printf 'output appeared during review: %s\n' "$output" >&2
  exit 2
fi
trap - EXIT
printf 'Review written to %s\n' "$output"
