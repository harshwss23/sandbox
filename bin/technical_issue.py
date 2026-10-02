#!/usr/bin/env python3
"""Record a fault in the sandbox's own tooling, or a repair made to it.

    technical_issue.py --command "rubric_check.py" --error "the last lines of the error"
    technical_issue.py --command ... --error ... --repaired bin/status.py --what "one line"
    technical_issue.py --list

The record goes into the task's issue log, which travels with the task folder,
so whoever maintains the sandbox sees what went wrong without the contributor
relaying anything. A repair is recorded with the diff against the file the
seed shipped, read out of the seed zip on this machine, and with whether the
file was one that may be repaired at all.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import zipfile
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import check_integrity as ci  # noqa: E402
import flc_state as st  # noqa: E402

MAX_DIFF_CHARS = 20_000


def shipped_diff(rel: str, current: Path) -> str:
    """The change against the seed's own copy, or "" when either cannot be read."""
    try:
        import restore_tools as rt
        archive_path = rt.find_zip()
        if archive_path is None:
            return ""
        with zipfile.ZipFile(archive_path) as archive:
            original = rt.member(archive, rel)
        if original is None:
            return ""
        before = original.decode("utf-8", "replace").splitlines(keepends=True)
        after = current.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        return ""
    return "".join(difflib.unified_diff(before, after, f"shipped/{rel}", f"now/{rel}"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--command", default="")
    ap.add_argument("--error", default="")
    ap.add_argument("--repaired", default=None, metavar="PATH")
    ap.add_argument("--what", default="", help="the repair, in one line")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    if args.list:
        for entry in st.issues(root):
            print(json.dumps(entry))
        return 0
    if not (args.error or args.repaired):
        print("give --error, --repaired, or both", file=sys.stderr)
        return 2

    repair = None
    allowed = None
    if args.repaired:
        allowed = ci.may_edit(args.repaired, st.FLC_HOME, root)
        rel = allowed["path"]
        path = Path(args.repaired).expanduser()
        if not path.is_absolute():
            path = ci.installed_path(rel, st.FLC_HOME)
        repair = {"file": rel, "what": args.what, "allowed": allowed["verdict"],
                  "diff": shipped_diff(rel, path)[:MAX_DIFF_CHARS]}
    st.record_issue(root, "repair" if repair else "fault", args.error, args.command,
                    repair)
    print("  recorded for the project team")
    if allowed and allowed["verdict"] == "no":
        print(f"  {allowed['path']} is not a file that may be repaired "
              f"({allowed['why']}).")
        print("  Put it back with /flc-restore-tools.")
        return 1
    if allowed and allowed["then"]:
        print(f"  then: {allowed['then']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
