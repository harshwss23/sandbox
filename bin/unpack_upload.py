#!/usr/bin/env python3
"""Unpack an uploaded archive into the workspace, and clear up after it.

    unpack_upload.py                 unpack every archive in the workspace
    unpack_upload.py mine.zip        unpack one, wherever it was uploaded to
    unpack_upload.py --keep-archive  unpack but leave the archive in place
    unpack_upload.py --dry-run       say what would happen, change nothing

Uploading one archive is the only practical way to get a folder tree in, since
the file browser takes files rather than folders. This is the other half of
that: it unpacks in place, removes the archive, and deletes the sidecar files
the operating system put in it -- __MACOSX, .DS_Store, AppleDouble ._ stubs,
Thumbs.db -- none of which the contributor put there and all of which the model
would otherwise see as task material and count towards the context floor.

What it will not do is change the contributor's own files. Nothing is renamed,
rewritten or reorganised; the one structural change is lifting the contents out
of a single wrapper folder when the archive has exactly one, which is what
compressing a folder rather than its contents produces, and even that is
reported and can be turned off with --no-flatten.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402

ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tar.xz")

# Put there by an operating system, not by a person. Deleting these is not
# touching the contributor's material.
JUNK_DIRS = {"__MACOSX", ".Spotlight-V100", ".Trashes", "$RECYCLE.BIN"}
JUNK_FILES = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}


def is_archive(p: Path) -> bool:
    name = p.name.lower()
    return any(name.endswith(s) for s in ARCHIVE_SUFFIXES)


def is_junk(rel: str) -> bool:
    parts = Path(rel).parts
    if any(part in JUNK_DIRS for part in parts):
        return True
    base = parts[-1] if parts else ""
    return base in JUNK_FILES or base.startswith("._")


def safe_members(names: list[str], dest: Path) -> tuple[list[str], list[str]]:
    """Split archive members into ones safe to write and ones to refuse.

    An archive is contributor-supplied data, and a member named ../../x or
    /etc/x would write outside the workspace. Refusing is the whole check: the
    goal is that an ordinary archive built on someone's laptop cannot reach past
    the folder it is unpacked into, not that a hostile one is made safe.
    """
    ok, refused = [], []
    dest = dest.resolve()
    for n in names:
        if n.startswith("/") or ".." in Path(n).parts:
            refused.append(n)
            continue
        try:
            target = (dest / n).resolve()
        except OSError:
            refused.append(n)
            continue
        if target != dest and dest not in target.parents:
            refused.append(n)
        else:
            ok.append(n)
    return ok, refused


def list_members(archive: Path) -> list[str]:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            return z.namelist()
    with tarfile.open(archive) as t:
        return t.getnames()


def extract(archive: Path, dest: Path, members: list[str]) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest, members=members)
        return
    with tarfile.open(archive) as t:
        picked = [t.getmember(m) for m in members]
        # safe_members() resolves each name before extraction, which a symlink
        # member defeats: the link is created first and the next member follows
        # it out of the workspace. The "data" filter refuses links that point
        # outside, and is the default from Python 3.14.
        try:
            t.extractall(dest, members=picked, filter="data")
        except TypeError:
            t.extractall(dest, members=[m for m in picked
                                        if not (m.issym() or m.islnk())])


def sweep_junk(root: Path) -> list[str]:
    """Delete OS sidecar files anywhere under root. Returns what went."""
    removed = []
    for d in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        rel = d.relative_to(root).as_posix()
        if not is_junk(rel):
            continue
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
        else:
            d.unlink(missing_ok=True)
        removed.append(rel)
    return removed


def top_level(root: Path) -> list[Path]:
    return [p for p in sorted(root.iterdir()) if p.name != "PUT_YOUR_FILES_HERE.txt"]


def flatten(ws: Path, wrapper: Path) -> bool:
    """Lift a single wrapper folder's contents up into the workspace.

    Compressing a folder rather than its contents is the ordinary mistake and it
    buries everything one level deeper than the model expects. Only done when
    the wrapper is the sole thing in the workspace, so nothing can collide.
    """
    for child in list(wrapper.iterdir()):
        target = ws / child.name
        if target.exists():
            return False
    for child in list(wrapper.iterdir()):
        shutil.move(str(child), str(ws / child.name))
    wrapper.rmdir()
    return True


def tree(root: Path, limit: int = 24) -> list[str]:
    entries = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        entries.append(rel + ("/" if p.is_dir() else ""))
    if len(entries) > limit:
        return entries[:limit] + [f"... and {len(entries) - limit} more"]
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive", nargs="*", help="archive to unpack (default: every one found)")
    ap.add_argument("--keep-archive", action="store_true", help="do not delete the archive")
    ap.add_argument("--no-flatten", action="store_true",
                    help="leave a single wrapper folder where it is")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--task")
    args = ap.parse_args()

    root = st.task_root(args.task)
    ws = root / "environment" / "workspace"
    if not ws.is_dir():
        print(f"  no workspace at {ws}", file=sys.stderr)
        return 1

    # Uploads land wherever the file browser put them, which is usually the
    # workspace but not always -- the home directory and the task root are the
    # other two places people drop things.
    if args.archive:
        found = []
        for a in args.archive:
            p = Path(a)
            for base in (Path.cwd(), ws, root, Path.home()):
                if (base / p).is_file():
                    found.append((base / p).resolve())
                    break
            else:
                print(f"  cannot find {a}", file=sys.stderr)
                return 1
    else:
        found = sorted({p.resolve() for p in ws.rglob("*") if p.is_file() and is_archive(p)})
        if not found:
            outside = [p for base in (root, Path.home())
                       if base.is_dir()
                       for p in sorted(base.glob("*"))
                       if p.is_file() and is_archive(p)]
            if outside:
                print("  no archive in the workspace, but there is one here:")
                for p in outside[:5]:
                    print(f"    {p}")
                print("\n  unpack it with:  python3 ~/flc/bin/unpack_upload.py "
                      f"{outside[0].name}")
                return 1
            print("  no archive found in environment/workspace/")
            print("  upload your zip there first, then run this again.")
            return 1

    before = set(st.workspace_files(root))
    print(f"  workspace: {ws}")

    for archive in found:
        dest = archive.parent if archive.parent.is_relative_to(ws) else ws
        names = list_members(archive)
        ok, refused = safe_members(names, dest)
        keep = [n for n in ok if not is_junk(n)]
        skipped_junk = len(ok) - len(keep)

        print(f"\n  {archive.name}  ({len(names)} entries)")
        if refused:
            print(f"    refused {len(refused)} member(s) with paths outside the workspace:")
            for n in refused[:5]:
                print(f"      {n}")
        if skipped_junk:
            print(f"    skipped {skipped_junk} operating-system file(s)")
        if args.dry_run:
            print(f"    would unpack {len(keep)} file(s) into {dest}")
            if not args.keep_archive:
                print(f"    would delete {archive.name}")
            continue

        extract(archive, dest, keep)
        print(f"    unpacked {len(keep)} file(s)")
        if not args.keep_archive:
            archive.unlink()
            print(f"    deleted {archive.name}")

    if args.dry_run:
        return 0

    removed = sweep_junk(ws)
    if removed:
        print(f"\n  cleared {len(removed)} operating-system file(s) "
              f"({', '.join(sorted({Path(r).parts[0] for r in removed})[:3])})")

    entries = top_level(ws)
    if not args.no_flatten and len(entries) == 1 and entries[0].is_dir():
        wrapper = entries[0]
        if flatten(ws, wrapper):
            print(f"\n  everything was inside '{wrapper.name}/', so it was lifted up a "
                  "level.\n  The model sees the workspace itself as /workspace, and a "
                  "single\n  wrapper folder would have put your files one step deeper "
                  "than\n  your prompt describes.")

    placeholder = ws / "PUT_YOUR_FILES_HERE.txt"
    if placeholder.exists() and top_level(ws):
        placeholder.unlink()
        print("\n  removed PUT_YOUR_FILES_HERE.txt, now that there are real files")

    after = set(st.workspace_files(root))
    print(f"\n  workspace now holds {len(after)} file(s), {len(after - before)} new\n")
    for line in tree(ws):
        print(f"    {line}")
    print("\n  next: /flc-check-inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
