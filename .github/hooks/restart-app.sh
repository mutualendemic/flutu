#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="$ROOT/.git"
STATE_FILE="$STATE_DIR/copilot-app-source.sha256"
LOG_FILE="${TMPDIR:-/tmp}/flutu-server.log"

mkdir -p "$STATE_DIR"
source_hash="$(find "$ROOT/app" -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | sort -z | xargs -0 sha256sum; sha256sum "$ROOT/run.py" "$ROOT/requirements.txt" "$ROOT/start_server.sh" "$ROOT/Dockerfile" "$ROOT/.dockerignore")"
source_hash="$(printf '%s\n' "$source_hash" | sha256sum | cut -d ' ' -f 1)"

# Record a baseline on first use; only restart after one of the app files changes.
if [[ ! -f "$STATE_FILE" ]]; then
  printf '%s\n' "$source_hash" > "$STATE_FILE"
  exit 0
fi

previous_hash="$(cat "$STATE_FILE")"
if [[ "$source_hash" == "$previous_hash" ]]; then
  exit 0
fi

# Stop only this workspace's server process, leaving unrelated Python services alone.
for process_dir in /proc/[0-9]*; do
  [[ -r "$process_dir/cmdline" && -e "$process_dir/cwd" ]] || continue
  process_cwd="$(readlink -f "$process_dir/cwd" 2>/dev/null || true)"
  [[ "$process_cwd" == "$ROOT" ]] || continue
  command_line="$(tr '\0' ' ' < "$process_dir/cmdline" 2>/dev/null || true)"
  [[ "$command_line" == *" run.py"* || "$command_line" == *"$ROOT/run.py"* ]] || continue
  process_id="${process_dir##*/}"
  [[ "$process_id" == "$$" ]] || kill "$process_id" 2>/dev/null || true
done

nohup bash "$ROOT/start_server.sh" > "$LOG_FILE" 2>&1 < /dev/null &
printf '%s\n' "$source_hash" > "$STATE_FILE"
