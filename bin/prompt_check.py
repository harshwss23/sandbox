#!/usr/bin/env python3
"""Is this task's prompt hard enough to be worth authoring?

The bar: someone who is not an expert in your field could not work out what
your prompt is asking, or what would count as having answered it.

The scale and the question put to the model live in prompt_taxonomy.py. This
reads prompt.md, asks the model on this machine a few times, and records the
answer in the task state, where /flc-check-inputs reads it.

    python3 bin/prompt_check.py            # classify and record
    python3 bin/prompt_check.py --json
    python3 bin/prompt_check.py --task ~/flc/task

Exit code 0 when the prompt clears, 1 when it does not, and 2 when nothing was
classified -- which is never the same thing as a prompt that was classified and
found wanting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import check_integrity as ci  # noqa: E402
import flc_state as st  # noqa: E402
import prompt_taxonomy as taxonomy  # noqa: E402

MODEL_ENV = "FLC_PROMPT_MODEL"
STATE_KEY = "prompt_check"


def prompt_text(root: Path) -> str:
    """The prompt as it will ship: prompt.md with the template guidance gone."""
    return st.contributor_prompt(root)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify(root: Path, samples: int, min_level: int,
             model: str | None = None) -> taxonomy.Verdict:
    """Classify this task's prompt against the model on this machine."""
    text = prompt_text(root)
    creds = st.gateway()
    if not creds:
        return taxonomy.Verdict(
            why="no gateway credentials were found on this machine")
    key, base = creds
    shape = st.gateway_shape()
    models = st.check_models(model, MODEL_ENV)
    answered: list[str] = []

    def send(one: str) -> str:
        return taxonomy.call_models(one, models, key, base, shape, answered=answered)

    result = taxonomy.collect(text, send, samples, min_level)
    result.model = taxonomy.answered_by(answered) or models[0]
    if result.samples:
        result.agreement += f", {result.model}"
    return result


def record(root: Path, result: taxonomy.Verdict, text: str) -> dict:
    """Write the verdict into the task state and return what was written."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": result.verdict,
        "level": result.level,
        "comprehension": result.comprehension,
        "answer_check": result.answer_check,
        "hardness": result.hardness,
        "why": result.why,
        "agreement": result.agreement,
        "model": result.model,
        "prompt_sha256": digest(text),
    }
    state = st.load(root)
    state[STATE_KEY] = entry
    st.save(root, state)
    return entry


def recorded(state: dict, text: str) -> tuple[dict | None, bool]:
    """The recorded verdict, and whether it was taken against this prompt."""
    entry = state.get(STATE_KEY)
    if not isinstance(entry, dict) or not entry.get("verdict"):
        return None, False
    return entry, entry.get("prompt_sha256") == digest(text)


REFUSAL_MARKERS = ("no JSON object", "declined", "refus", "safeguard", "aup",
                   "content_filter", "cannot help", "can't help")


def _looks_refused(why: str) -> bool:
    """Whether a failure to measure reads as the model declining to answer."""
    lowered = why.lower()
    return any(marker.lower() in lowered for marker in REFUSAL_MARKERS)


def _wrap(text: str, indent: str = "  ") -> str:
    return textwrap.fill(text, width=84, initial_indent=indent,
                         subsequent_indent=indent)


def report(result: taxonomy.Verdict) -> None:
    print()
    print("How hard is this prompt?")
    print()
    if result.verdict == "UNMEASURED":
        print("  NOT MEASURED")
        print()
        print(_wrap(f"Nothing was classified: {result.why}"))
        print()
        print(_wrap("This is our check failing, not your task."))
        if _looks_refused(result.why):
            print()
            print(_wrap(
                "A safety filter sometimes refuses to read a perfectly "
                "ordinary prompt about cells, pathogens, patients or genomes. "
                "It fires inconsistently, so running this again often works."))
        print()
        print(_wrap(
            "Either way it does not stop you: /flc-check-inputs lets a prompt "
            "through when this could not measure it, and says so."))
        print()
        return

    named = taxonomy.LEVELS[result.level]
    print(f"  {result.verdict}  Level {result.level} - {named[0]} ({named[1]})")
    print(f"        a non-expert could work out what it asks: "
          f"{result.comprehension}")
    print(f"        a non-expert could spot a wrong answer:   "
          f"{result.answer_check or 'not said'}")
    if result.hardness:
        print(f"        what makes it hard: "
              f"{taxonomy.HARDNESS[result.hardness]}")
    print(f"        {result.agreement}")
    print()
    print(_wrap(result.why))
    if result.samples:
        print()
        print(_wrap(result.samples[0]["reasoning"]))
        markers = result.samples[0].get("expertise_markers") or []
        if markers:
            print()
            print("  what it read as needing an expert:")
            for marker in markers[:6]:
                print(_wrap(f"- {marker}", "    "))
    print()
    if result.verdict == "FAIL":
        print(_wrap(
            "To clear this, the prompt has to ask for something only someone "
            "in your field could pin down: your own data rather than a public "
            "dataset, a judgement between readings that look equally "
            "reasonable, or a convention you would take for granted and an "
            "outsider would not know to apply. Edit prompt.md and run this "
            "again."))
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--samples", type=int, default=taxonomy.DEFAULT_SAMPLES)
    ap.add_argument("--min-level", type=int, default=taxonomy.DEFAULT_MIN_LEVEL,
                    choices=range(1, 7), metavar="1-6")
    ap.add_argument("--model", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    if args.samples < 1:
        print("--samples must be at least 1", file=sys.stderr)
        return 2

    ci.announce(root, "prompt_check")

    text = prompt_text(root)
    result = classify(root, args.samples, args.min_level, args.model)
    entry = record(root, result, text)
    if result.verdict == "UNMEASURED":
        st.record_issue(root, "check_unmeasured", f"prompt check: {result.why}",
                        "prompt_check.py")

    if args.json:
        print(json.dumps({**entry, "samples": result.samples}, indent=2))
    else:
        report(result)

    if result.verdict == "UNMEASURED":
        return 2
    return 0 if result.clears else 1


if __name__ == "__main__":
    sys.exit(main())
