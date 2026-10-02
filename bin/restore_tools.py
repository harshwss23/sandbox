#!/usr/bin/env python3
"""Put the sandbox's own files back the way the seed shipped them.

    restore_tools.py                 report what would be put back
    restore_tools.py --apply         put it back
    restore_tools.py --apply --blocking-only

The seed arrives as a zip and stays on the machine, so the original of every
shipped file is here for the whole session. This finds that zip, takes the one
member it needs out of it, checks those bytes against bin/seed_manifest.json
*before* writing anything, and renames the result over the file in place.

Checking the extracted copy is the step that matters. Without it a zip that
had itself been changed would be a way of laundering a modification into a
tree that then reports clean, and a truncated download would overwrite a
working file with nothing.

It restores files, not evidence. A score produced by a modified judge is still
that judge's, so the affected steps stay marked as needing to be taken again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import check_integrity as ci  # noqa: E402
import flc_state as st  # noqa: E402

# Where the platform puts a preloaded file, in the order bundle.sh searches.
# The named directories come first so a stray zip somewhere under /tmp never
# wins over the one that was provisioned.
ZIP_DIRS = ("~/.flc", "~", "/home/sandbox/.flc", "/root/.flc")
ZIP_ROOTS = ("~", "/home", "/root", "/tmp")
ZIP_DEPTH = 6

# Every bundle unpacks to this one folder whatever the domain or the version,
# which is what lets a member be addressed without knowing either.
MEMBER_ROOT = "flc_vm/"


def find_zip(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    for name in ZIP_DIRS:
        base = Path(name).expanduser()
        if not base.is_dir():
            continue
        for candidate in sorted(base.glob("*.zip")):
            if candidate.is_file():
                return candidate
    for name in ZIP_ROOTS:
        base = Path(name).expanduser()
        if not base.is_dir():
            continue
        for candidate in sorted(base.rglob("*.zip")):
            parts = candidate.relative_to(base).parts
            if len(parts) > ZIP_DEPTH or "__MACOSX" in parts or ".cache" in parts:
                continue
            if candidate.is_file():
                return candidate
    return None


def member(archive: zipfile.ZipFile, rel: str) -> bytes | None:
    """One shipped file's original bytes, addressed inside the bundle."""
    for name in (MEMBER_ROOT + rel, rel):
        try:
            return archive.read(name)
        except KeyError:
            continue
    return None


def write_over(path: Path, data: bytes) -> None:
    """Replace a file's contents, keeping its mode, without a partial state.

    Written beside the original and renamed, because a file half-replaced here
    is one of the seven the grading path depends on.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o7777 if path.exists() else None
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".flc-restore-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def targets(home: Path, task: Path, findings: list[dict],
            blocking_only: bool) -> list[tuple[dict, Path]]:
    out = []
    for f in findings:
        if f["state"] == "restored":
            continue
        if blocking_only and f["tier"] != "blocking":
            continue
        if f["where"] == "task":
            copy = ci._task_copy(f["path"], task)
            if copy is not None:
                out.append((f, copy))
        else:
            out.append((f, ci.installed_path(f["path"], home)))
    return out


def restore(home: Path, task: Path, findings: list[dict], manifest: dict,
            zip_path: Path, blocking_only: bool, apply: bool) -> dict:
    """Put each modified file back, refusing any whose original fails to verify."""
    done: list[str] = []
    refused: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        for finding, path in targets(home, task, findings, blocking_only):
            rel = finding["path"]
            data = member(archive, rel)
            if data is None:
                refused.append(f"{rel}: not in {zip_path.name}")
                continue
            actual = hashlib.sha256(data).hexdigest()
            expected = manifest["files"].get(rel)
            if actual != expected:
                # The one refusal that matters. A zip disagreeing with the
                # manifest is either not this seed or has been changed, and
                # writing from it would launder a modification into a tree
                # that then reports clean.
                refused.append(f"{rel}: the copy in {zip_path.name} does not "
                               f"match the manifest either")
                continue
            if apply:
                write_over(path, data)
            done.append(f"{rel} ({finding['where']})")
    return {"restored": done, "refused": refused}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--home", default=None)
    ap.add_argument("--zip", default=None, help="the seed bundle, if it is not found")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--blocking-only", action="store_true",
                    help="only the files that refuse a step")
    ap.add_argument("--include-repairs", action="store_true",
                    help="also put back files a recorded repair changed")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    home = Path(args.home).resolve() if args.home else st.FLC_HOME

    manifest = ci.load(home)
    if manifest is None:
        print(f"  There is no {ci.MANIFEST_NAME} in {home / 'bin'}, so there is "
              f"nothing to\n  compare against and nothing can be put back safely.")
        return 2

    report = ci.scan(home, root)
    outstanding = [f for f in report["findings"] if f["state"] != "restored"]
    # A recorded repair is left in place unless asked for: putting it back
    # brings back the fault it fixed.
    kept = [] if args.include_repairs else [f for f in outstanding
                                             if f["path"] in ci.repaired(root)]
    outstanding = [f for f in outstanding if f not in kept]
    for f in kept:
        print(f"  left alone: {f['path']} (a recorded repair; --include-repairs "
              "puts it back too)")
    if not outstanding:
        print("  Nothing to put back -- every shipped file is the one the seed "
              "put there." if not kept else "  Nothing else to put back.")
        return 0

    zip_path = find_zip(args.zip)
    if zip_path is None:
        print("  Cannot find the seed bundle on this machine, so there is no "
              "original to\n  put back. These files are modified:\n")
        for f in outstanding:
            print(f"  [{f['tier']}] {ci.describe(f)}")
        print("\n  There's a technical issue on our side, not a problem with your "
              "task.\n  Please reach out to the project team.")
        return 2

    result = restore(home, root, outstanding, manifest, zip_path,
                     args.blocking_only, args.apply)

    if args.json:
        print(json.dumps({**result, "zip": str(zip_path),
                          "applied": args.apply}, indent=2))
        return 1 if result["refused"] else 0

    print(f"  seed bundle: {zip_path}")
    print()
    verb = "put back" if args.apply else "would be put back"
    for name in result["restored"]:
        print(f"  {verb}: {name}")
    for note in result["refused"]:
        print(f"  refused:  {note}")
    print()

    if not args.apply:
        print("  Nothing has been written. Run it again with --apply.")
        return 0

    if result["restored"]:
        # Restoring is not undoing. The score a modified judge produced is
        # still that judge's, so what it invalidated stays invalidated.
        state = st.load(root)
        entry = state.get(ci.STATE_KEY) or {}
        cleared = entry.get("evidence_cleared") or []
        if cleared:
            print("  The steps below still have to be taken again -- putting a "
                  "file back does\n  not un-produce what it made:")
            for kind in cleared:
                print(f"    {ci.EVIDENCE_STEP[kind]}")
        else:
            print("  Run the step you were on again.")
    return 1 if result["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
