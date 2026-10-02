#!/usr/bin/env python3
"""Copy what the model produced into the verifier's log directory.

Runs from test.sh on every run, before the deferral check. Creates nothing when
/workspace is absent, and never fails the verifier: a snapshot that cannot be
taken is a note in the output.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("FLC_WORKSPACE", "/workspace"))
LOGS = Path(os.environ.get("FLC_LOGS", "/logs/verifier"))
MANIFEST = Path(os.environ.get("FLC_INPUTS_MANIFEST", "/tests/inputs_manifest.json"))

# Reported in snapshot.json whenever they trigger, so a truncated snapshot
# cannot be mistaken for a complete one.
MAX_FILE_BYTES = int(os.environ.get("FLC_SNAPSHOT_MAX_FILE", 25 * 1024 * 1024))
MAX_TOTAL_BYTES = int(os.environ.get("FLC_SNAPSHOT_MAX_TOTAL", 200 * 1024 * 1024))


def inputs() -> dict[str, str]:
    """The uploaded files, as {relative path: sha256}."""
    try:
        payload = json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    if not WORKSPACE.is_dir():
        print("  no workspace was mounted, so nothing could be kept from it.")
        print("  (This is 'cannot tell what it wrote', not 'it wrote nothing'.)")
        return 0

    given = inputs()
    dest = LOGS / "workspace"
    kept: list[str] = []
    skipped: list[str] = []
    total = 0

    for base, _, names in os.walk(WORKSPACE):
        for name in sorted(names):
            full = Path(base) / name
            rel = str(full.relative_to(WORKSPACE))

            # Skipped rather than followed, so a link out of the workspace is
            # not materialised here.
            if full.is_symlink():
                skipped.append(f"{rel} (symlink)")
                continue
            try:
                raw = full.read_bytes()
            except OSError as exc:
                skipped.append(f"{rel} ({exc.strerror or 'unreadable'})")
                continue

            # New or changed against the uploaded inputs, the same test the
            # judge applies.
            if rel in given and given[rel] and hashlib.sha256(raw).hexdigest() == given[rel]:
                continue
            if len(raw) > MAX_FILE_BYTES:
                skipped.append(f"{rel} ({len(raw) // 1024 // 1024} MB, over the per-file cap)")
                continue
            if total + len(raw) > MAX_TOTAL_BYTES:
                skipped.append(f"{rel} (the total cap was reached)")
                continue

            target = dest / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            except OSError as exc:
                skipped.append(f"{rel} ({exc.strerror or 'could not be written'})")
                continue
            kept.append(rel)
            total += len(raw)

    # Created even when nothing was produced: the directory existing is what
    # says the workspace was seen.
    dest.mkdir(parents=True, exist_ok=True)
    (LOGS / "snapshot.json").write_text(json.dumps({
        "workspace_seen": True,
        "produced": sorted(kept),
        "skipped": sorted(skipped),
        "bytes": total,
        "complete": not skipped,
    }, indent=2, sort_keys=True) + "\n")

    if kept:
        print(f"  kept {len(kept)} file(s) the model produced ({total // 1024} KB):")
        for rel in kept[:20]:
            print(f"    {rel}")
        if len(kept) > 20:
            print(f"    ... and {len(kept) - 20} more")
    else:
        print("  the model added nothing to the workspace.")
    for note in skipped[:10]:
        print(f"  not kept: {note}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never cost a grading run
        print(f"  the workspace snapshot failed ({exc}); grading continues.")
        sys.exit(0)
