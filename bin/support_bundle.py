#!/usr/bin/env python3
"""Everything the project team needs to debug a fault, in one file they get.

    support_bundle.py --command "/flc-grade" --error "the last lines"

`technical_issue.py` records a fault into the task's issue log, and the log
reaches us inside `validation.json`, which `package_delivery.py` writes. That
works for every fault a contributor gets past. It does not work for the one
kind that matters most: a fault that stops the task. No delivery is built, so
no `validation.json` is written, so nothing reaches us -- and the assistant was
telling contributors to get in touch because "they already have the details".
They did not. Nobody had them.

So this writes the details into a file instead, and puts it where the platform
is already looking. The collection takes `task/delivery/` and `task/review/`
from the VM and nothing else, so a zip anywhere else is collected by nobody;
this one goes in `review/`, which is collected whether or not a delivery was
ever built. The contributor can also send it on directly, and is told where it
is, because a task that expires may never be collected at all.

What goes in is what a fault is diagnosed from and nothing else. Not the
workspace: it can be 500 MB, it is the contributor's own material, and no fault
in our tooling has ever been diagnosed from it. Every part is capped and
optional -- a bundle missing a piece is worth having, and a bundle that fails
to build because one file was unreadable is worth nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402

# A transcript is the biggest thing here by far and the most useful for a
# grading fault, so it is carried but cut; the tail is where the error is.
CAPS = {"trajectory": 2_000_000, "log": 200_000, "text": 100_000}
MAX_LOGS = 12


def _tail(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return f"[... {len(text) - cap} characters cut from the start ...]\n" + text[-cap:]


def _read(path: Path, cap: int) -> str | None:
    try:
        return _tail(path.read_text(errors="replace"), cap)
    except Exception:
        return None


def _facts(root: Path, home: Path) -> dict:
    """What the machine was, which is half of every report that needs chasing."""
    out = {
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "task": str(root),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    try:
        usage = shutil.disk_usage(str(home))
        out["disk_free_gb"] = round(usage.free / 1e9, 1)
    except Exception:
        pass
    for tool in ("docker", "apt-cache", "git"):
        out[f"has_{tool.replace('-', '_')}"] = bool(shutil.which(tool))
    return out


def _integrity(root: Path, home: Path) -> dict | None:
    """Which of our own files differ from the ones the seed shipped."""
    try:
        import check_integrity as ci
        report, _ = ci.check(root, home)
        return report
    except Exception as exc:  # noqa: BLE001 - a missing part is not a failure
        return {"could_not_run": f"{type(exc).__name__}: {exc}"}


def _run_files(root: Path) -> list[tuple[str, str]]:
    """The last run's transcript and logs, capped, as (name in zip, text)."""
    out: list[tuple[str, str]] = []
    try:
        import solver_answer as sa
        job = sa.find_job(root, None)
    except Exception:
        return out
    if job is None:
        return out

    try:
        transcript = sa.find_trajectory(job)
    except Exception:
        transcript = None
    if transcript is not None and transcript.exists():
        text = _read(transcript, CAPS["trajectory"])
        if text is not None:
            out.append((f"run/{transcript.name}", text))

    for path in sorted(job.rglob("*.log"))[:MAX_LOGS]:
        text = _read(path, CAPS["log"])
        if text is not None:
            out.append((f"run/logs/{path.name}", text))
    return out


# What each part is, for whoever opens the zip. A part that could not be read
# is left out rather than written empty, and the contents list is built from
# what actually went in: a README naming a transcript that is not there sends
# the reader looking for it.
DESCRIBED = {
    "issues.json": "every fault and repair recorded for this task",
    "state.json": "the task's state, which records what each step decided",
    "profile.json": "the seed and the models it was built for",
    "integrity.json": "which of our files differ from the ones shipped",
    "machine.json": "the sandbox: python, platform, disk, tools present",
    "error.txt": "the error the contributor was stopped by",
}


def readme(root: Path, command: str, issues: list[dict], names: list[str]) -> str:
    profile = st.profile()
    lines = [
        "# Support bundle",
        "",
        "A fault in the sandbox's own tooling stopped this task and could not be",
        "repaired in the sandbox. Everything needed to diagnose it is in here.",
        "",
        f"- task: `{root.name}`",
        f"- task id: `{st.load(root).get('task_id') or 'unknown'}`",
        f"- seed version: `{profile.get('seed_version') or 'unknown'}`",
        f"- solver model: `{profile.get('solver_model') or 'unknown'}`",
        f"- stopped at: `{command or 'unknown'}`",
        f"- faults recorded: {len(issues)}",
        "",
        "## What is here",
        "",
    ]
    for name in names:
        if name in DESCRIBED:
            lines.append(f"- `{name}` -- {DESCRIBED[name]}")
    runs = [n for n in names if n.startswith("run/")]
    if runs:
        lines.append(f"- `run/` -- the last run's transcript and logs, tails "
                     f"only ({len(runs)} files)")
    else:
        lines.append("- no run files: this task has no solver run on disk, or "
                     "it could not be read")
    lines += [
        "",
        "The contributor's workspace is deliberately not here. It can be very",
        "large and it is their own material; no fault in the tooling is",
        "diagnosed from it. Ask for it if it turns out to be needed.",
    ]
    return "\n".join(lines) + "\n"


def build(root: Path, home: Path, command: str, error: str) -> Path:
    """Write the bundle into the task's review/ and return where it landed."""
    issues = []
    try:
        issues = st.issues(root)
    except Exception:
        pass

    parts: list[tuple[str, str]] = [
        ("issues.json", json.dumps(issues, indent=2)),
        ("machine.json", json.dumps(_facts(root, home), indent=2)),
        ("integrity.json", json.dumps(_integrity(root, home), indent=2, default=str)),
    ]
    if error:
        parts.append(("error.txt", _tail(error, CAPS["text"])))
    for name, path in (("state.json", st.issues_path(root).parent / "state.json"),
                       ("profile.json", home / "bin" / "profile.json")):
        text = _read(path, CAPS["text"])
        if text is not None:
            parts.append((name, text))
    parts += _run_files(root)
    parts.insert(0, ("README.md",
                     readme(root, command, issues, [n for n, _ in parts])))

    # review/ is collected from the VM whether or not a delivery was built, so
    # this reaches us even if the contributor can get nothing out by hand.
    out_dir = root / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"support-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts:
            archive.writestr(name, text)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--command", default="", help="the step that stopped")
    ap.add_argument("--error", default="", help="the last lines of the error")
    args = ap.parse_args()

    root = st.task_root(args.task)
    out = build(root, st.FLC_HOME, args.command, args.error)
    size = out.stat().st_size

    print(f"  wrote {out}")
    print(f"  {size / 1000:.0f} KB")
    print()
    print("  It is in the task's review/ folder, which the platform collects, so")
    print("  it reaches the project team when the task is collected. Send it on")
    print("  as well if you can -- a task that is never finished is never")
    print("  collected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
