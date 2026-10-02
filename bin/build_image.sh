#!/usr/bin/env bash
# Build the task's image from environment/, exactly as Harbor would.
#
# Used by check_tests and by delivery.
#
# Usage:
#   build_image.sh [TASK] [--tag NAME] [--no-cache] [--quiet]
#
# Prints the image tag on stdout; everything else goes to stderr, so callers can
# capture the tag with $(...).

set -euo pipefail

FLC_HOME="${FLC_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TASK_PATH="${FLC_TASK:-$FLC_HOME/task}"
TAG=""
EXTRA=()
QUIET=0

die() { echo "build_image.sh: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --tag)      TAG="${2:?}"; shift 2 ;;
    --no-cache) EXTRA+=(--no-cache); shift ;;
    --quiet)    QUIET=1; shift ;;
    -h|--help)  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)         die "unknown option: $1" ;;
    *)          TASK_PATH="$1"; shift ;;
  esac
done

command -v docker >/dev/null 2>&1 || die "docker is not available"
TASK_PATH="$(cd -- "$TASK_PATH" && pwd)"
[ -f "$TASK_PATH/environment/Dockerfile" ] || die "no environment/Dockerfile in $TASK_PATH"

if [ -z "$TAG" ]; then
  TAG="flc-task:$(python3 -c '
import json, sys
print(json.load(open(sys.argv[1]))["task_id"].rsplit("-", 1)[-1])
' "$TASK_PATH/.flc/state.json" 2>/dev/null || echo local)"
fi

log_file="$FLC_HOME/.build.log"
if [ "$QUIET" -eq 1 ]; then
  if ! docker build -t "$TAG" "${EXTRA[@]+"${EXTRA[@]}"}" "$TASK_PATH/environment" >"$log_file" 2>&1; then
    echo "the image failed to build. Last 40 lines of $log_file:" >&2
    tail -n 40 "$log_file" >&2
    exit 1
  fi
else
  docker build -t "$TAG" "${EXTRA[@]+"${EXTRA[@]}"}" "$TASK_PATH/environment" 2>&1 | tee "$log_file" >&2
  # tee would otherwise mask a build failure behind its own exit status.
  [ "${PIPESTATUS[0]}" -eq 0 ] || die "the image failed to build (full log: $log_file)"
fi

echo "$TAG"
