#!/usr/bin/env python3
"""Find the packages the solver had to install for itself, and record them.

Nobody can predict what an agent will need to solve a task -- not the
contributor, and not us. So we do not ask. The solver has a network, so when
something is missing it installs it and carries on; this reads the transcript
afterwards and reports what it installed. That is an exact answer to "what was
missing from this image", arrived at by watching rather than guessing.

Watching means what the solver *ran*, not what it *said*. A transcript is
mostly the model talking, and a sentence that mentions installing something --
"PyMuPDF needs no apt install to enable page rendering" -- is not an install.
Read as one it yields `to`, `enable`, `page` and `rendering.`, four names apt
cannot find, written into the task's package list where nothing checks whether
a package exists and the image build is the first thing to fail. So the
commands are read from the transcript's own structure, and where that cannot be
recognised, from the one thing prose does not do: start a line.

Recording them matters even though the run succeeded without it. The delivered
task must build everything it needs from `environment/` alone, or a run on a
restricted network gets a task that fails where this one passed.

    python3 bin/detect_packages.py           # report what it installed
    python3 bin/detect_packages.py --add     # and record it in the task

Run automatically at the end of every solver run, so the usual case needs no
one to remember it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402

# Where a command sits. It opens a line or follows a shell separator; prose
# does neither. In "needs no apt install to enable page rendering" the verb
# follows the word "no", and that one fact is what tells a command apart from a
# sentence about one. A pasted session's prompt, sudo with its own options, and
# leading environment assignments all sit between the two and are stepped over.
START = (r"(?:^|[\n;&|()`\"']|\\n)[ \t]*"
         r"(?:[$>#][ \t]*)?"
         r"(?:sudo[ \t]+(?:-[A-Za-z]\S*[ \t]+)*)?"
         r"(?:[A-Za-z_][A-Za-z_0-9]*=\S*[ \t]+)*")

# Package managers, as they appear in a shell command the agent ran, each with
# the ecosystem it installs into. Matches around sudo, python -m, uv, a version
# pin, and an --option between the verb and the name.
#
# The argument list stops at a newline or a shell separator. Both the real and
# the backslash-escaped forms of a newline are terminators.
STOP = r"(?:[^\n;&|\\]|\\(?!n))*"
INSTALLERS = [
    ("pip", re.compile(START + r"python3?\s+-m\s+pip\s+install\b(?P<args>" + STOP + ")")),
    ("pip", re.compile(START + r"uv\s+pip\s+install\b(?P<args>" + STOP + ")")),
    ("pip", re.compile(START + r"pip3?\s+install\b(?P<args>" + STOP + ")")),
    ("pip", re.compile(START + r"conda\s+install\b(?P<args>" + STOP + ")")),
    ("apt", re.compile(START + r"apt(?:-get)?\s+install\b(?P<args>" + STOP + ")")),
]

# Where a transcript keeps what was run. Gateways write a tool call differently
# from one another, so a command is recognised by the key it is written under
# rather than by one fixed shape, and a call whose arguments arrive as an
# unexpanded JSON string is opened rather than skipped.
COMMAND_KEYS = {"command", "cmd", "shell_command", "bash_command", "script"}
NESTED_KEYS = {"arguments", "input", "parameters", "args", "function",
               "tool_calls", "tool_use", "toolUse", "invocation"}

# Flags that take a value, so the value is not mistaken for a package name.
FLAGS_WITH_VALUES = {"-i", "--index-url", "--extra-index-url", "-c", "--constraint",
                     "-r", "--requirement", "--target", "-t", "--find-links", "-f"}

# What a package name can look like. Anything else in the argument list is the
# surrounding transcript, not something to install.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*(?:[=<>!~]=[^\s]+)?$")


def _split(args: str) -> list[str]:
    """The package names in an install command's arguments."""
    names, skip = [], False
    for token in args.strip().split():
        # A command written inside quotes -- bash -c "pip install scipy" --
        # carries the closing one on its last argument.
        token = token.strip("\"'")
        if skip:
            skip = False
            continue
        if token in FLAGS_WITH_VALUES:
            skip = True
            continue
        if token.startswith("-"):
            continue
        # A local path or a requirements file is not a package name we can pin.
        if token.startswith((".", "/")) or token.endswith((".txt", ".whl", ".tar.gz")):
            continue
        if not NAME_RE.match(token):
            continue
        names.append(token)
    return names


def readable_text(raw: str) -> str:
    """The transcript as text, with escaped newlines turned back into newlines.

    A transcript is JSON, so a shell session inside it is a single line with its
    newlines written as two characters. Left that way, an install command has no
    visible end and the match runs on into the rest of the file.
    """
    try:
        data = json.loads(raw)
    except Exception:
        return raw.replace("\\n", "\n")

    chunks: list[str] = []

    def walk(node):
        if isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return "\n".join(chunks)


def commands(raw: str) -> list[str]:
    """Every shell command the transcript records the solver running.

    Empty when the transcript is not JSON, or is JSON in a shape none of
    `COMMAND_KEYS` appears in. The caller falls back to the whole text then,
    which is weaker and is why `START` exists.
    """
    try:
        data = json.loads(raw)
    except Exception:
        return []

    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in COMMAND_KEYS and isinstance(value, str):
                    out.append(value)
                elif isinstance(value, str) and key in NESTED_KEYS:
                    try:
                        walk(json.loads(value))
                    except Exception:
                        pass
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return out


def from_trajectory(raw: str) -> dict[str, list[str]]:
    """The packages the solver installed, read from what it ran."""
    ran = commands(raw)
    texts = ran if ran else [readable_text(raw)]
    found: dict[str, list[str]] = {"pip": [], "apt": []}
    for text in texts:
        for ecosystem, pattern in INSTALLERS:
            for match in pattern.finditer(text):
                for name in _split(match.group("args")):
                    if name not in found[ecosystem]:
                        found[ecosystem].append(name)
    return found


# Signs that the solver wanted something and could not get it. These matter far
# more than the successful installs: a run stopped by its environment produces
# the same thing a run that failed the task produces -- failed criteria -- and
# without this it reads as a model that could not do the work.
# A dead end: the solver asked for something and the answer was no.
HARD = [
    (re.compile(r"No matching distribution found for ([\w.\-]+)"), "pip could not find {0}"),
    (re.compile(r"Could not find a version that satisfies the requirement ([\w.\-]+)"),
     "pip could not find {0}"),
    (re.compile(r"E: Unable to locate package ([\w.\-+]+)"), "apt could not find {0}"),
    (re.compile(r"externally-managed-environment"), "pip refused to install (managed environment)"),
    (re.compile(r"Temporary failure resolving '([^']+)'"), "could not reach {0}"),
    (re.compile(r"E: Could not open lock file[^\n]*"), "apt needed privileges it did not have"),
]

# Something was missing at the moment this was printed, which is only worth
# reporting if the solver never went on to install it. Hitting an ImportError
# and then installing the package is the system working, not a problem, and a
# warning that fires on it is one contributors learn to ignore.
SOFT = [
    (re.compile(r"ModuleNotFoundError: No module named '([^']+)'"), "no module {0}"),
    (re.compile(r"ImportError: No module named ([\w.]+)"), "no module {0}"),
    (re.compile(r"([\w.\-]+): command not found"), "{0} is not installed"),
]


# The dead ends that name a package, rather than a host or a privilege. What a
# manager already said no to must never be recorded as something to install:
# the delivered image would fail on it exactly where this run did, and the
# contributor meets it as a broken build rather than as this warning.
NOT_FOUND = [pattern for pattern, _ in HARD[:3]]


def unavailable(raw: str) -> set[str]:
    """The packages the run proved cannot be installed, lowercased."""
    text = readable_text(raw)
    return {match.group(1).lower() for pattern in NOT_FOUND
            for match in pattern.finditer(text)}


def blocked(raw: str) -> list[str]:
    """Everything the solver reached for and never got."""
    text = readable_text(raw)
    out: list[str] = []
    dead_ends: set[str] = set()

    for pattern, template in HARD:
        for match in pattern.finditer(text):
            note = template.format(*match.groups()) if match.groups() else template
            if match.groups():
                dead_ends.add(match.group(1).lower())
            if note not in out:
                out.append(note)

    # Whatever it managed to install, by whichever manager.
    installed = {re.split(r"[=<>!~]", name, 1)[0].lower()
                 for names in from_trajectory(raw).values() for name in names}

    for pattern, template in SOFT:
        for match in pattern.finditer(text):
            name = match.group(1).lower()
            # The top-level import name is not always the package name, so a
            # prefix match keeps this from warning about "no module cv2" when
            # opencv-python was installed under a different name.
            resolved = name.split(".")[0]
            if resolved in installed and resolved not in dead_ends:
                continue
            note = template.format(*match.groups())
            if note not in out:
                out.append(note)
    return out


def latest_trajectory(root: Path) -> Path | None:
    """The transcript of the run this task last started.

    Resolved through `solver_answer`, so what is read here is the attempt the
    grade and the delivery were taken from rather than whichever attempt of
    whichever job happens to carry the newest file.
    """
    import solver_answer as sa

    job = sa.find_job(root, None)
    if job is None:
        return None
    return sa.find_trajectory(job)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task")
    ap.add_argument("--trajectory", help="read this transcript instead of the newest")
    ap.add_argument("--add", action="store_true", help="record what it finds")
    ap.add_argument("--quiet", action="store_true", help="say nothing if it finds nothing")
    args = ap.parse_args()

    root = st.task_root(args.task)
    path = Path(args.trajectory) if args.trajectory else latest_trajectory(root)
    if not path or not path.exists():
        if not args.quiet:
            print("no solver transcript found; nothing to check.")
        return 0

    def base(spec: str) -> str:
        return re.split(r"[=<>!~]", spec, 1)[0].strip().lower()

    raw = path.read_text(errors="replace")
    found = from_trajectory(raw)
    recorded = {(p["ecosystem"], base(p["spec"]))
                for p in st.load(root).get("packages", [])}
    dead = unavailable(raw)
    missing = {eco: [n for n in names
                     if (eco, base(n)) not in recorded and base(n) not in dead]
               for eco, names in found.items()}

    stuck = blocked(raw)
    if stuck:
        print("WARNING: the solver could not get something it went looking for:")
        print()
        for note in stuck:
            print(f"  {note}")
        print()
        print("A run stopped by its environment fails criteria the same way a run")
        print("that got the answer wrong does. Check the failures below are really")
        print("about the task before concluding anything about the model.")
        print()

    if not any(missing.values()):
        if not (args.quiet and not stuck):
            print("The solver installed nothing that the image was missing.")
        return 0

    print("The solver installed these itself, so the image did not have them:")
    print()
    for ecosystem, names in missing.items():
        for name in names:
            print(f"  {ecosystem} {name}")
    print()

    if not args.add:
        print("The run still worked -- it has a network. But the delivered task")
        print("should not depend on that, so add them with:")
        print()
        print("  python3 bin/detect_packages.py --add")
        return 0

    # add-package refuses a name no package manager here can find. Read what
    # it said rather than passing over it: these are read out of a transcript,
    # so a name that does not exist is a misreading on our side, and silence
    # leaves the contributor to meet it as a failed image build.
    refused = []
    for ecosystem, names in missing.items():
        for name in names:
            done = subprocess.run(
                [sys.executable, str(BIN_DIR / "task_config.py"), "--task", str(root),
                 "add-package", name] + (["--apt"] if ecosystem == "apt" else []),
                capture_output=True, text=True, check=False)
            if done.returncode != 0:
                refused.append((ecosystem, name, done.stderr.strip().splitlines()))
            else:
                print(done.stdout.rstrip())

    if refused:
        print()
        print("These were read out of the run but no package manager here has them,")
        print("so they were not recorded:")
        print()
        for ecosystem, name, why in refused:
            print(f"  {ecosystem} {name}" + (f"  -- {why[0]}" if why else ""))
        print()
        print("That is a misreading on our side, not something you did. If one of")
        print("them really is a package, add it with --force.")

    print()
    print("Recorded. The next build installs them, and /flc-deliver checks that")
    print("they install from scratch. To see the whole list, or take one off:")
    print()
    print("  python3 bin/task_config.py check-packages")
    print("  python3 bin/task_config.py remove-package NAME [--apt]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
