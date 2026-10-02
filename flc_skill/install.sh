#!/usr/bin/env bash
# Install the /flc-* slash commands and their skill into ~/.claude/.
#
# Usage:
#   bash install.sh                  # install from this extracted tree
#   bash install.sh --from-url URL   # fetch and extract a new bundle, then install
#
# --from-url fetches and installs a new bundle, so a version bump on a running
# VM is one curl rather than a Preloaded Files change and a reprovision.
#
# CLAUDE_SKILLS_DIR / CLAUDE_COMMANDS_DIR override the destinations.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
CLAUDE_COMMANDS_DIR="${CLAUDE_COMMANDS_DIR:-$HOME/.claude/commands}"
FROM_URL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --from-url)   FROM_URL="${2:?}"; shift 2 ;;
    --from-url=*) FROM_URL="${1#*=}"; shift ;;
    -h|--help)    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install.sh: unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -n "$FROM_URL" ]; then
  command -v curl  >/dev/null 2>&1 || { echo "install.sh: curl is required for --from-url" >&2; exit 1; }
  command -v unzip >/dev/null 2>&1 || { echo "install.sh: unzip is required for --from-url" >&2; exit 1; }
  FETCH_DIR="$(mktemp -d)"
  trap 'rm -rf "$FETCH_DIR"' EXIT
  echo "[install] fetching $FROM_URL"
  curl -fsSL -o "$FETCH_DIR/bundle.zip" "$FROM_URL"
  unzip -q -o "$FETCH_DIR/bundle.zip" -d "$FETCH_DIR/extracted"
  # The bundle wraps everything in one top-level folder; find it rather than
  # assuming its name.
  SRC_DIR="$(find "$FETCH_DIR/extracted" -maxdepth 3 -name install.sh -exec dirname {} \; | head -1)"
  [ -n "$SRC_DIR" ] || { echo "install.sh: the fetched zip has no install.sh" >&2; exit 1; }
  echo "[install] extracted to $SRC_DIR"
fi

echo "[install] source:   $SRC_DIR"
echo "[install] skills:   $CLAUDE_SKILLS_DIR"
echo "[install] commands: $CLAUDE_COMMANDS_DIR"

mkdir -p "$CLAUDE_SKILLS_DIR" "$CLAUDE_COMMANDS_DIR"

installed_skills=()
if [ -d "$SRC_DIR/skills" ]; then
  for skill_dir in "$SRC_DIR"/skills/*/; do
    [ -d "$skill_dir" ] || continue
    name="$(basename "$skill_dir")"
    rm -rf "$CLAUDE_SKILLS_DIR/$name"
    cp -R "$skill_dir" "$CLAUDE_SKILLS_DIR/$name"
    installed_skills+=("$name")
  done
fi

installed_commands=0
if [ -d "$SRC_DIR/commands" ]; then
  # Commands are versioned as a set: a bundle that drops a command must not
  # leave the old file behind pointing at a workflow that no longer exists.
  # Only cleared when this bundle actually ships commands, so installing a
  # commands-less bundle never wipes a working set.
  rm -f "$CLAUDE_COMMANDS_DIR"/flc-*.md
  for cmd_file in "$SRC_DIR"/commands/*.md; do
    [ -f "$cmd_file" ] || continue
    cp "$cmd_file" "$CLAUDE_COMMANDS_DIR/"
    installed_commands=$((installed_commands + 1))
  done
fi

for f in "$CLAUDE_SKILLS_DIR"/*/*.sh "$CLAUDE_SKILLS_DIR"/*/*.py; do
  [ -f "$f" ] && chmod +x "$f" 2>/dev/null || true
done

# The instructions Claude Code reads at the start of every conversation, merged
# into the user's own file as one marked block: anything outside the markers is
# left alone, and a style already recorded between the style markers is kept.
CLAUDE_MEMORY_FILE="${CLAUDE_MEMORY_FILE:-$HOME/.claude/CLAUDE.md}"
memory="not installed"
if [ -f "$SRC_DIR/CLAUDE.md" ] && command -v python3 >/dev/null 2>&1; then
  if python3 - "$SRC_DIR/CLAUDE.md" "$CLAUDE_MEMORY_FILE" <<'PY'
import os, sys, tempfile
src, dest = sys.argv[1], sys.argv[2]
BEGIN, END = "<!-- flc:begin", "<!-- flc:end -->"
SBEGIN, SEND = "<!-- flc:style:begin -->", "<!-- flc:style:end -->"
block = open(src, encoding="utf-8").read().strip()
try:
    old = open(dest, encoding="utf-8").read()
except FileNotFoundError:
    old = ""
if SBEGIN in old and SEND in old and SBEGIN in block and SEND in block:
    kept = old[old.index(SBEGIN):old.index(SEND) + len(SEND)]
    block = block[:block.index(SBEGIN)] + kept + block[block.index(SEND) + len(SEND):]
if BEGIN in old and END in old:
    a, b = old.index(BEGIN), old.index(END) + len(END)
    new = old[:a] + block + old[b:]
else:
    new = (old.rstrip() + "\n\n" if old.strip() else "") + block + "\n"
os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest) or ".", prefix=".flc-claude-")
with os.fdopen(fd, "w", encoding="utf-8") as out:
    out.write(new)
os.replace(tmp, dest)
PY
  then
    memory="$CLAUDE_MEMORY_FILE"
  fi
fi

echo "[install] done."
echo "[install] skills:   ${installed_skills[*]:-(none)}"
echo "[install] commands: $installed_commands file(s)"
echo "[install] CLAUDE.md: $memory"
