#!/usr/bin/env bash
# Scaffold the task folder from template_task/.
#
# Provisioning runs this once so ~/flc/task/ exists before the contributor ever
# opens the IDE. Run it by hand only to start over.
#
# Usage:
#   new_task.sh                 # create ~/flc/task, refuse if it exists
#   new_task.sh --force         # archive the existing one first
#   new_task.sh --quiet
#   new_task.sh --into PATH

set -euo pipefail

FLC_HOME="${FLC_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TEMPLATE="$FLC_HOME/template_task"
TARGET="${FLC_TASK:-$FLC_HOME/task}"
FORCE=0
QUIET=0

die() { printf 'new_task.sh: %s\n' "$*" >&2; exit 1; }
say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --quiet) QUIET=1; shift ;;
    --into)  TARGET="${2:?--into needs a path}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -d "$TEMPLATE" ] || die "no template at $TEMPLATE"

if [ -e "$TARGET" ]; then
  if [ "$FORCE" -ne 1 ]; then
    die "$TARGET already exists. Use --force to archive it and start over."
  fi
  # Moved, never deleted. The files in there are the only thing on this VM that
  # cannot be recreated.
  archive="$TARGET.replaced-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$TARGET" "$archive"
  say "existing task moved to $archive"
fi

mkdir -p "$(dirname "$TARGET")"
cp -a "$TEMPLATE" "$TARGET"

# The generated files that depend on the id minted right here: state.json,
# task.toml, the Dockerfile, instruction.md.
python3 "$FLC_HOME/bin/flc_scaffold.py" "$TARGET"

say "task created at $TARGET"
say
say "Next: put your files in ${TARGET#"$HOME"/}/environment/workspace/"
say "Then, in Claude Code: /flc-check-inputs"
