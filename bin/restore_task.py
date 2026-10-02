#!/usr/bin/env python3
"""Move a task handed to a reviewer into the sandbox that can work on it.

    restore_task.py                  say what would be moved
    restore_task.py --apply          move it
    restore_task.py --apply --from ~/handover

A review sandbox is a fresh one: it comes up with an empty scaffolded task at
~/flc/task, and the work being reviewed is dropped in beside it at ~/task and
~/jobs. Nothing in the workflow looks there, so a reviewer opening a task in
that state is told the solver never ran -- and sent to spend twelve minutes
producing a different run from the one the criteria were written against.

Four things this does that a `mv` does not:

- refuses a ~/flc/task that is not the empty scaffold, so real work is never
  merged into or written over;
- lifts a single wrapper directory, since a folder handed over as one item
  arrives one level deeper than every recorded path expects;
- re-anchors the paths recorded on the other machine, which are absolute and
  point at a directory that does not exist here;
- checks what arrived against delivery/readiness.json, which carries a sha256
  of every file the attempter submitted and was built for exactly this.

It also records that this is a review pass, so nothing downstream has to be
told by the platform which kind of session it is in.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402

STATE_KEY = "review_pass"

# Where the platform leaves the handover. Both are looked for beside each
# other, because a task and the runs that produced it are one thing.
DEFAULT_SOURCES = ("~", "/mnt/data", "/workspace")
MOVED = ("task", "jobs")

# What a freshly scaffolded task has and nothing else. Anything beyond this
# means somebody has started work, and this command must not touch it.
SCAFFOLD_EVIDENCE = ("prompt.md", "tests/rubrics.md", "solution/ground_truth.md")


def is_scaffold(root: Path, home: Path) -> bool:
    """Whether ~/flc/task is still the untouched thing this sandbox came up with.

    Compared against template_task/, which is where new_task.sh copies these
    from, rather than tested for being empty. The template is not empty: it
    ships worked criteria in tests/rubrics.md and a set of headings in
    ground_truth.md, so "has any content" reads every fresh sandbox as work in
    progress and refuses every restore there is.
    """
    if not root.exists():
        return True
    try:
        state = json.loads((root / ".flc" / "state.json").read_text())
    except (OSError, json.JSONDecodeError):
        state = {}
    else:
        if state.get("steps_done") or state.get("last_job"):
            return False
    template = home / "template_task"
    for rel in SCAFFOLD_EVIDENCE:
        here, shipped = root / rel, template / rel
        if not here.exists():
            continue
        if not shipped.exists():
            # Nothing to compare against, so fall back to whether anything was
            # written past the template's own guidance.
            if st._strip_html_comments(here.read_text(errors="replace")).strip():
                return False
        elif st.sha256_file(here) != st.sha256_file(shipped):
            return False
    workspace = root / "environment" / "workspace"
    if workspace.is_dir():
        if any(p.is_file() and p.name != "PUT_YOUR_FILES_HERE.txt"
               for p in workspace.rglob("*")):
            return False
    return True


def unwrap(path: Path, name: str) -> Path:
    """The real directory, when what arrived is one folder holding one folder.

    Compressing a folder rather than its contents is the ordinary mistake, and
    one extra level makes every path recorded in the state wrong at once.

    Lifted at most once, and only on evidence that the child is the thing
    rather than merely the only thing. Descending any single-child chain is
    what makes this dangerous in the other direction: a jobs/ directory
    holding exactly one run is the ordinary case, not a wrapper, and lifting
    it moves one run in place of the folder that holds them.
    """
    if (path / ".flc").is_dir():
        return path
    entries = [p for p in path.iterdir() if p.name != ".DS_Store"]
    if len(entries) != 1 or not entries[0].is_dir():
        return path
    child = entries[0]
    if child.name == name or (name == "task" and (child / ".flc").is_dir()):
        return child
    return path


def find_sources(explicit: str | None) -> dict[str, Path]:
    """Where `task` and `jobs` are waiting, if they are anywhere."""
    roots = ([Path(explicit).expanduser()] if explicit
             else [Path(p).expanduser() for p in DEFAULT_SOURCES])
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for name in MOVED:
            candidate = root / name
            if name not in found and candidate.is_dir():
                found[name] = candidate
        if "task" in found:
            break
    return found


def reanchor(root: Path, jobs: Path) -> list[str]:
    """Point the recorded job paths at where the runs actually landed.

    They were absolute on the other machine. Left alone, run_state() reports
    that no run exists and run_grader.py sends the reviewer to make one --
    which is the same shape of defect as a message naming a remedy that cannot
    work, and costs a run and a transcript nobody wanted.
    """
    state = st.load(root)
    changed = []
    for key in ("last_job", "last_graded_job", "run_log"):
        recorded = state.get(key)
        if not recorded:
            continue
        moved = jobs / Path(recorded).name
        if moved.exists() and str(moved) != recorded:
            state[key] = str(moved)
            changed.append(f"{key}: {recorded} -> {moved}")
    # The attempter's session, not one running here. Left set, run_state()
    # calls the run live if anything on this machine happens to hold that pid.
    if state.get("run_pid"):
        state["run_pid"] = ""
        changed.append("run_pid: cleared (it was the other machine's)")
    st.save(root, state)
    return changed


def verify(root: Path) -> dict:
    """Check what arrived against the receipt the attempter left in it."""
    receipt_file = root / "delivery" / "readiness.json"
    try:
        receipt = json.loads(receipt_file.read_text())
    except (OSError, json.JSONDecodeError):
        return {"checked": False,
                "why": "no delivery/readiness.json -- /flc-submit was never run, "
                       "or the delivery did not come across"}

    mismatched, missing = [], []
    for section, key in (("delivery", "delivery_files"), ("review", "review_files")):
        for rel, expected in sorted((receipt.get(key) or {}).items()):
            actual = st.sha256_file(root / section / rel)
            if actual == "":
                missing.append(f"{section}/{rel}")
            elif actual != expected:
                mismatched.append(f"{section}/{rel}")
    return {"checked": True, "verdict": receipt.get("verdict"),
            "at": receipt.get("checked_at"), "missing": missing,
            "mismatched": mismatched, "why": ""}


def record(root: Path, sources: dict[str, Path], verified: dict) -> dict:
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "restored_from": {k: str(v) for k, v in sources.items()},
        "receipt": verified,
    }
    state = st.load(root)
    state[STATE_KEY] = entry
    st.save(root, state)
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", default=None)
    ap.add_argument("--from", dest="source", default=None,
                    help="where the handover is, if it is not beside the home")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    home = Path(args.home).resolve() if args.home else st.FLC_HOME
    target = home / "task"

    sources = find_sources(args.source)
    if "task" not in sources:
        print("  Nothing to restore: no `task` folder was handed to this "
              "sandbox.\n"
              "  Looked in " + ", ".join(DEFAULT_SOURCES) + ".\n"
              "  If it is somewhere else, say where with --from.")
        return 2

    if not is_scaffold(target, home):
        # The one refusal with no override. Merging a handover into work that
        # is already here would leave a task made of two people's files with
        # nothing saying which is which, and no way back.
        print(f"  There is already a task at {target}, and it is not the empty\n"
              f"  scaffold this sandbox came up with. Nothing has been moved.\n\n"
              f"  If this sandbox is the one that authored it, there is nothing "
              f"to restore.\n"
              f"  If it is not, say so when you report this rather than moving "
              f"anything by\n  hand -- two people's files in one task cannot be "
              f"told apart afterwards.")
        return 1

    plan = {name: unwrap(path, name) for name, path in sources.items()}
    if not args.apply:
        print("  Would restore:")
        for name, path in plan.items():
            print(f"    {path}  ->  {home / name}")
        if any(p != sources[n] for n, p in plan.items()):
            print("\n  (one of those is wrapped in a folder of its own, which "
                  "would be lifted)")
        print("\n  Nothing has been moved. Run it again with --apply.")
        return 0

    for name, path in plan.items():
        destination = home / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(path), str(destination))
        print(f"  moved {path}  ->  {destination}")

    changed = reanchor(target, home / "jobs") if (home / "jobs").is_dir() else []
    for line in changed:
        print(f"  re-anchored {line}")

    verified = verify(target)
    record(target, sources, verified)

    print()
    if not verified["checked"]:
        # Not a refusal. The receipt is the attempter's to have left, and a
        # reviewer cannot be stopped from reviewing by its absence.
        print(f"  The handover carries no receipt ({verified['why']}), so "
              f"nothing here can\n  confirm it arrived whole. Recorded, and "
              f"not a reason to stop.")
    elif verified["mismatched"] or verified["missing"]:
        print(f"  The receipt was left at {verified['at']} and says "
              f"{verified['verdict']}, but what\n  arrived does not match it:")
        for rel in (verified["missing"] + verified["mismatched"])[:20]:
            print(f"    {rel}")
        print("\n  A mismatch under review/ most likely means the run was read "
              "again after\n  submitting, which is harmless. One under "
              "delivery/ is worth reporting.")
    else:
        print(f"  Everything the receipt lists arrived unchanged. It was left "
              f"at\n  {verified['at']}.")
        if verified["verdict"] != "PASS":
            # The receipt's verdict is about the attempter's delivery, not
            # about the move. Printed on its own line so the two are not read
            # as one: "arrived unchanged (FAIL)" reads as a failed transfer.
            print(f"\n  Their own readiness check said {verified['verdict']}, "
                  f"so this task was handed\n  over knowing it was not ready. "
                  f"delivery/readiness.json says what was wrong.")

    print()
    print("  This is recorded as a review pass. Start with /flc-status, which "
          "now reads\n  the restored run, and /flc-inspect to read it.")
    if args.json:
        print(json.dumps({"moved": {k: str(v) for k, v in plan.items()},
                          "reanchored": changed, "receipt": verified}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
