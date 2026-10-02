#!/usr/bin/env python3
"""How the person in this sandbox wants to be spoken to.

    contributor_style.py set --background "a sentence in their words" --level plain
    contributor_style.py show
    contributor_style.py render        # write the recorded answer into CLAUDE.md again

Two answers, asked once by /flc-start or at the first conversation: their
background, in their own words, and how technical to be -- plain, some or
technical. They are kept in ~/.flc/contributor_style.json, which belongs to
the person rather than to the task and is not delivered, and written into the
marked section of ~/.claude/CLAUDE.md, which Claude Code reads at the start of
every conversation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LEVELS = {
    "plain": ("plain language",
              "No technical terms at all. Say what happened and what to do, in "
              "everyday words or the words of their own field, in one or two "
              "sentences. Never name a file, a script, a model or a mechanism "
              "unless they ask."),
    "some": ("some technical terms",
             "Short and plain first. A technical term is fine where it saves "
             "words, with a few words of explanation the first time. Name a "
             "file only when they have to open it."),
    "technical": ("fully technical",
                  "They are comfortable with technical detail: file names, "
                  "commands and exact figures are fine. Still lead with what "
                  "happened and what to do, and still keep the sandbox's own "
                  "machinery out unless they ask."),
}
STYLE_BEGIN = "<!-- flc:style:begin -->"
STYLE_END = "<!-- flc:style:end -->"
UNSET = ("No preference is recorded yet. Ask the two questions above before "
         "anything else.")


def style_dir() -> Path:
    return Path(os.environ.get("FLC_STYLE_DIR") or Path.home() / ".flc")


def memory_file() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "CLAUDE.md"


def load() -> dict | None:
    try:
        data = json.loads((style_dir() / "contributor_style.json").read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("level") in LEVELS else None


def section(style: dict | None) -> str:
    """The text between the style markers."""
    if not style:
        return UNSET
    name, how = LEVELS[style["level"]]
    background = " ".join(str(style.get("background") or "").split())
    lines = [f"Their background, in their own words: {background or 'not given'}.",
             f"How technical to be: {name}. {how}"]
    return "\n".join(lines)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".flc-style-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def render(style: dict | None) -> bool:
    """Write the style into CLAUDE.md's marked section. False when there is none."""
    path = memory_file()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if STYLE_BEGIN not in text or STYLE_END not in text:
        return False
    a = text.index(STYLE_BEGIN) + len(STYLE_BEGIN)
    b = text.index(STYLE_END)
    _write(path, text[:a] + "\n" + section(style) + "\n" + text[b:])
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="action", required=True)
    setter = sub.add_parser("set")
    setter.add_argument("--background", default="")
    setter.add_argument("--level", default="plain", choices=sorted(LEVELS))
    sub.add_parser("show")
    sub.add_parser("render")
    args = ap.parse_args()

    if args.action == "show":
        print(json.dumps(load() or {}, indent=2))
        return 0
    if args.action == "render":
        return 0 if render(load()) else 1
    style = {"background": args.background.strip(), "level": args.level,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write(style_dir() / "contributor_style.json", json.dumps(style, indent=2) + "\n")
    if render(style):
        print(f"  recorded: {LEVELS[args.level][0]}")
    else:
        print(f"  recorded: {LEVELS[args.level][0]} (CLAUDE.md has no section for "
              "it, so it applies from the next /flc-start)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
