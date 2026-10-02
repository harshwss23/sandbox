#!/usr/bin/env python3
"""The record of which workspace files carry the answer and which do not.

Written into delivery/authoring/ at packaging time. It reports and never
gates: the required/distractor split is a design prompt whose answer is a
matter of opinion for the kind of folder this project asks people to build,
and nothing downstream may depend on it being right.

What makes it worth writing down is that the task states it twice. The split
is recorded at check-inputs, before the answer exists; the ground truth's
"What should mislead a careless model" section names each distractor together
with the wrong answer it leads to, a step later, when the contributor knows.
A reviewer reading only one of them cannot see the two disagree.
"""

from __future__ import annotations

import re
from pathlib import Path

DISTRACTOR_HEADING = "What should mislead a careless model"

# The template's heading, and then anything that reads like it. Keying on the
# one exact string looked right and was not: the worked example this project
# ships calls the same section "Traps, and what each one catches", so a task
# written before the template settled, or by anyone who reworded a heading,
# would have been reported as having no distractors at all -- a confident
# absence, which is the failure this repository keeps finding.
DISTRACTOR_PATTERNS = (
    re.escape(DISTRACTOR_HEADING),
    r".*\b(mislead|misleading)\b.*",
    r".*\btraps?\b.*",
    r".*\bdistractors?\b.*",
)


def heading(root: Path) -> str | None:
    """The ground truth heading that introduces the distractors, if any."""
    src = root / "solution" / "ground_truth.md"
    if not src.exists():
        return None
    body = src.read_text(errors="replace")
    for pattern in DISTRACTOR_PATTERNS:
        match = re.search(r"^##\s+(" + pattern + r")\s*$", body,
                          re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def prose(root: Path) -> str | None:
    """The ground truth's distractor section, or None if it has none.

    None is "there is no such section" rather than "the section is empty", and
    the two read differently below: one is a task with no distractors written
    down, the other is a heading somebody left as they found it.
    """
    src = root / "solution" / "ground_truth.md"
    if not src.exists():
        return None
    body = src.read_text(errors="replace")
    found = heading(root)
    if not found:
        return None
    match = re.search(r"^##\s+" + re.escape(found) + r"\s*$", body,
                      re.MULTILINE)
    if not match:
        return None
    rest = body[match.end():]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    section = rest[:nxt.start()] if nxt else rest
    # The template's own guidance is a comment, and a contributor who wrote
    # nothing leaves it behind. Stripping it is what tells an unwritten section
    # from a written one.
    section = re.sub(r"<!--.*?-->", "", section, flags=re.DOTALL)
    return section.strip()


def mentions(text: str, rel: str) -> bool:
    """Whether the prose names this file.

    Substring matching over prose, so it is trustworthy saying a file is
    mentioned and untrustworthy saying one is not -- the same asymmetry the
    trajectory helpers carry. Both the full path and the bare filename count,
    since a contributor writing about their own material uses the short name.
    """
    if not text:
        return False
    low = text.lower()
    return rel.lower() in low or Path(rel).name.lower() in low


def build(root: Path, required: list[str], distractors: list[str]) -> str:
    """The record, as Markdown."""
    out = ["# The material", ""]
    out.append("Which files in the workspace carry the answer, and which are "
               "there to be read and set aside.")
    out.append("")
    out.append("This is the contributor's own account, recorded at "
               "`/flc-check-inputs` before the answer was written down. It is "
               "a description of the task's design, not a measurement of it, "
               "and nothing in the grading depends on it: every file in the "
               "workspace counts towards the context the model was given, "
               "whether it is named required here or not.")
    out.append("")

    if not required and not distractors:
        out.append("**No split was recorded.** `/flc-check-inputs` asks for "
                   "one, so this is a task delivered without that step having "
                   "run, or a state file that lost it.")
        out.append("")
    else:
        out.append(f"## Required ({len(required)})")
        out.append("")
        if required:
            out.extend(f"- `{rel}`" for rel in required)
        else:
            out.append("None recorded, which is unusual: a task whose answer "
                       "rests on no particular file is worth a second look.")
        out.append("")

        out.append(f"## Distractors ({len(distractors)})")
        out.append("")
        if distractors:
            out.extend(f"- `{rel}`" for rel in distractors)
        else:
            out.append("None recorded. Every file was marked as carrying the "
                       "answer, so there is no triage in this task -- nothing "
                       "for the model to rule out.")
        out.append("")

    section = prose(root)
    out.append("## What the ground truth says about them")
    out.append("")
    found = heading(root)
    if section is None:
        out.append("`solution/ground_truth.md` has no section describing the "
                   f"distractors -- nothing headed *{DISTRACTOR_HEADING}*, or "
                   "anything else naming traps or misleading material.")
    elif not section:
        out.append(f"The *{found}* section is empty.")
    else:
        out.append(f"Reproduced from the *{found}* section of "
                   "`solution/ground_truth.md`, which names "
                   "each distractor together with the wrong answer it leads "
                   "to. This is the later and fuller account of the two.")
        out.append("")
        out.append(section)
    out.append("")

    if section:
        unmentioned = [r for r in distractors if not mentions(section, r)]
        called_out = [r for r in required if mentions(section, r)]
        if unmentioned or called_out:
            out.append("## Where the two accounts differ")
            out.append("")
            out.append("Advisory, and worth no more than a look. This is a "
                       "search for filenames in prose, so it is reliable "
                       "saying a file is mentioned and unreliable saying one "
                       "is not -- a contributor can describe a file without "
                       "naming it.")
            out.append("")
            # The stronger finding first. A file the contributor called
            # answer-bearing and then described as a trap is a real tension in
            # the task's design and is worth a reviewer's minute; the list
            # below it is mostly ordinary and would bury this if it came
            # first.
            if called_out:
                out.append("**Marked required, and described as something "
                           "that should mislead.** Both can be true of one "
                           "file -- a published figure can be the evidence "
                           "and the trap -- but it is worth knowing which was "
                           "meant:")
                out.extend(f"- `{rel}`" for rel in called_out)
                out.append("")
            if unmentioned:
                out.append(f"The other {len(unmentioned)} distractor(s) are "
                           "not discussed in that section. This is usually "
                           "nothing: material a reader opens and sets aside "
                           "does not need a wrong answer attached to it, and "
                           "a folder made only of traps is the shape this "
                           "project asks contributors to avoid. Listed in "
                           "case one of them was meant to be a trap:")
                out.extend(f"- `{rel}`" for rel in unmentioned)
                out.append("")

    return "\n".join(out).rstrip() + "\n"


def write(root: Path, dest: Path, state: dict) -> dict:
    """Write the record and report what went into it."""
    required = sorted(state.get("required_files") or [])
    distractors = sorted(state.get("distractor_files") or [])
    dest.write_text(build(root, required, distractors))
    section = prose(root)
    return {
        "required": len(required),
        "distractors": len(distractors),
        "ground_truth_section": section is not None and bool(section),
    }
