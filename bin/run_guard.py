#!/usr/bin/env python3
"""Whether another solver run is worth starting, asked before one starts.

    python3 run_guard.py                        # the checks, before a run
    python3 run_guard.py --confirm-rerun        # a near-identical rerun, confirmed
    python3 run_guard.py --limit-reason "..."   # past the run limit, and why
    python3 run_guard.py --dry-run              # say what would happen, refuse nothing
    python3 run_guard.py --record [--job DIR]   # after a run: whether it counts
    python3 run_guard.py --history [--json]     # every run, as delivery reads them

Called by run_solver.sh before the job directory exists. Every check is
deterministic and none of them calls a model.

  - The ground truth's answer and how it is derivable have to be written down
    before any run. No override: the remedy is the contributor's own writing.
  - A counted run is one that produced a final answer. A run that crashed,
    never answered, came back without the model's files, or was refused for
    reading the answer off the web is not counted, and neither is a run
    nothing recorded the inputs of.
  - A run whose files, packages and block list match an earlier counted run,
    and whose prompt differs from it by at most MINOR_PROMPT_WORDS words, waits
    for --confirm-rerun (exit 3). Nothing else is ever held back as minor.
  - After RUN_LIMIT counted runs, another needs --limit-reason in the
    contributor's own words, which is recorded and printed in AUDIT.md.

Exit codes: 0 go ahead, 1 refused, 3 waiting on the contributor's confirmation.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402
import solver_answer as sa  # noqa: E402

RUN_LIMIT = 5
WARN_FROM = 3
MINOR_PROMPT_WORDS = 2
CONFIRM_EXIT = 3
OVERRIDE = "solver_run_limit"
PENDING = "run_guard_pending"

SEAL_NAMES = {"answer": "The answer", "derivation": "How it is derivable",
              "unknowable": "What the model cannot know"}


def seal_missing(root: Path) -> list[str]:
    """The sealed sections that still have nothing written in them."""
    sealed = st.sealed_sections(root)
    return [SEAL_NAMES[k] for k in st.SEALED_REQUIRED if k not in sealed]


def jobs_dir(state: dict, explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    last = state.get("last_job")
    return Path(last).parent if last else st.FLC_HOME / "jobs"


def assess(root: Path, job: Path, *, lookups: bool = True) -> tuple[bool, str]:
    """Whether a finished run counts towards the limit, and if not, why."""
    transcript = sa.find_trajectory(job) if job.is_dir() else None
    if transcript is None:
        return False, "it left no transcript"
    if not sa.final_message(transcript):
        return False, "it never gave a final answer"
    if sa.finished_workspace(job) is None:
        return False, "the model's files did not come back, which is fixed by another run"
    if lookups:
        try:
            import review_run as rr
            found, _ = rr.run_lookups(root, job, transcript)
        except Exception:
            found = []
        if found:
            return False, "its answer was read off the web, which is fixed by another run"
    return True, ""


def runs(root: Path, state: dict | None = None,
         jobs: Path | None = None) -> list[dict]:
    """Every recorded run, oldest first, with whether it counts."""
    state = state if state is not None else st.load(root)
    base = jobs or jobs_dir(state)
    recorded = state.get("runs") if isinstance(state.get("runs"), dict) else {}
    out = []
    for name, entry in recorded.items():
        if not isinstance(entry, dict):
            continue
        if "counted" in entry:
            counted, why = bool(entry["counted"]), entry.get("counted_why") or ""
        elif "prompt" not in entry:
            counted, why = False, "nothing recorded what it was run against"
        else:
            counted, why = assess(root, base / name, lookups=False)
        out.append({**entry, "job": name, "counted": counted, "why": why})
    out.sort(key=lambda r: str(r.get("started") or ""))
    return out


def prompt_change(before: str, after: str) -> tuple[int, list[str]]:
    """How many words differ between two prompts, and what the changes were."""
    a, b = (before or "").split(), (after or "").split()
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    words, shown = 0, []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        words += max(i2 - i1, j2 - j1)
        old = " ".join(a[i1:i2]) or "(nothing)"
        new = " ".join(b[j1:j2]) or "(nothing)"
        shown.append(f'"{old}" -> "{new}"')
    return words, shown


def near_identical(now: dict, earlier: list[dict]) -> dict | None:
    """The earlier counted run this one would all but repeat, if there is one."""
    best = None
    for run in earlier:
        if not run["counted"] or run.get("prompt") is None:
            continue
        if run.get("workspace_sha256") != now["workspace_sha256"]:
            continue
        if run.get("environment_sha256") != now["environment_sha256"]:
            continue
        words, shown = prompt_change(run["prompt"], now["prompt"])
        if words <= MINOR_PROMPT_WORDS and (best is None or words < best["words"]):
            best = {"job": run["job"], "words": words, "changes": shown}
    return best


def laundering(history: list[dict]) -> list[dict]:
    """Where the sealed answer changed between two runs of all but the same task.

    For the reviewer and nothing else. Running again with a one-word prompt
    change and a new answer is how a result the author did not like becomes
    one they did, and it is only visible from the run records.
    """
    out = []
    recorded = [r for r in history if "sealed_sha256" in r]
    for before, after in zip(recorded, recorded[1:]):
        if before.get("sealed_sha256") == after.get("sealed_sha256"):
            continue
        if before.get("workspace_sha256") != after.get("workspace_sha256"):
            continue
        words, shown = prompt_change(before.get("prompt", ""), after.get("prompt", ""))
        if words <= MINOR_PROMPT_WORDS:
            out.append({"from": before["job"], "to": after["job"],
                        "words": words, "changes": shown})
    return out


def _same(a: str, b: str) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split())


def seal_report(root: Path, state: dict, job: str | Path | None) -> dict:
    """The sealed sections at the start of a run, against the ground truth now."""
    entry = st.run_record(state, job)
    if "sealed" not in entry:
        return {"recorded": False}
    then = entry.get("sealed") or {}
    now = st.sealed_sections(root)
    moved = [k for k in st.SEALED_SECTIONS
             if not _same(then.get(k, ""), now.get(k, ""))]
    whole = entry.get("ground_truth_sha256")
    return {"recorded": True,
            "moved": [SEAL_NAMES[k] for k in moved],
            "before": {SEAL_NAMES[k]: then.get(k, "") for k in moved},
            "after": {SEAL_NAMES[k]: now.get(k, "") for k in moved},
            "other_sections_moved": bool(not moved and whole
                                         and whole != st.ground_truth_digest(root))}


def _say(lines: list[str]) -> None:
    print("\n".join(lines))


def check(root: Path, *, job_name: str, confirm: bool, reason: str,
          dry_run: bool, jobs: Path | None) -> int:
    refuse = 0 if dry_run else 1

    missing = seal_missing(root)
    if missing:
        _say([
            "",
            "  Write the answer down before the model runs.",
            "",
            f"  solution/ground_truth.md has nothing under: {', '.join(missing)}.",
            "  A short version is enough: the answer, and which files it comes from",
            "  and roughly what you do with them. The rest of the ground truth, the",
            "  justification and the labels can wait until a run shows the task holds.",
            "  Run /flc-ground-truth.",
            ""])
        return refuse

    state = st.load(root)
    history = runs(root, state, jobs)
    counted = [r for r in history if r["counted"]]
    number = len(counted) + 1
    now = st.run_inputs(root)
    pending: dict = {}

    if len(counted) >= RUN_LIMIT:
        reason = (reason or "").strip()
        if len(reason) < st.MIN_OVERRIDE_REASON:
            _say([
                "",
                f"  This would be solver run {number}, and a task gets {RUN_LIMIT}.",
                "",
                "  The limit keeps budget back for grading and delivery: the sandbox",
                "  has a spending cap, and reaching it stops those too. Runs that",
                "  crashed, never answered, came back without the model's files, or",
                "  read the answer off the web are not counted.",
                "",
                "  If another run is needed, say why in your own words, and it is",
                "  recorded with the task (Claude Code passes it on as",
                '  --limit-reason "your reason", exactly as you said it).'
                + ("" if not reason else
                   f"\n\n  That reason is {len(reason)} characters; it needs at least "
                   f"{st.MIN_OVERRIDE_REASON}."),
                ""])
            return refuse
        pending["limit_reason"] = reason

    match = near_identical(now, counted)
    if match:
        if not confirm:
            what = ("the prompt is the same" if not match["words"] else
                    f"the prompt differs by {match['words']} word(s): "
                    + "; ".join(match["changes"][:3]))
            _say([
                "",
                f"  This run would be almost the same as {match['job']}: the files,",
                f"  packages and block list are unchanged, and {what}.",
                "",
                "  Running the same task again mostly shows the same thing again, and",
                f"  runs are limited -- this would be run {number} of {RUN_LIMIT}. A run is",
                "  worth it when the prompt or the files change what the model has to do.",
                "",
                "  If you still want this run, say so (Claude Code then starts it",
                "  with --confirm-rerun).",
                ""])
            return 0 if dry_run else CONFIRM_EXIT
        pending["confirmed_rerun"] = {"matches": match["job"], "words": match["words"],
                                      "changes": match["changes"], "at": st._now()}

    if not dry_run:
        if "limit_reason" in pending:
            st.record_override(root, OVERRIDE, pending["limit_reason"], "run_solver")
        state = st.load(root)
        if pending:
            state[PENDING] = {"job": job_name, **pending}
        else:
            state.pop(PENDING, None)
        st.save(root, state)

    if number > RUN_LIMIT:
        print(f"  Solver run {number}, past the limit of {RUN_LIMIT}; your reason is recorded.")
    elif number >= WARN_FROM:
        print(f"  Solver run {number} of {RUN_LIMIT}. Runs are limited so there is budget "
              "left to grade and deliver.")
    else:
        print(f"  Solver run {number} of {RUN_LIMIT}.")
    return 0


def record(root: Path, job: Path) -> tuple[bool, str]:
    """Write whether a finished run counts into its record."""
    counted, why = assess(root, job)
    state = st.load(root)
    recorded = state.get("runs") if isinstance(state.get("runs"), dict) else {}
    entry = recorded.get(job.name)
    entry = entry if isinstance(entry, dict) else {}
    entry.update({"counted": counted, "counted_why": why})
    recorded[job.name] = entry
    state["runs"] = recorded
    st.save(root, state)
    return counted, why


def summary(root: Path, state: dict | None = None) -> dict:
    """How many runs count, and the last run's token total, for /flc-status."""
    history = runs(root, state)
    counted = [r for r in history if r["counted"]]
    last = history[-1] if history else {}
    return {"counted": len(counted), "limit": RUN_LIMIT,
            "last_tokens": (last.get("tokens") or {}).get("total")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--job", default=None, help="with --record: the job directory")
    ap.add_argument("--job-name", default="", help="the name the run is about to take")
    ap.add_argument("--jobs-dir", default=None)
    ap.add_argument("--confirm-rerun", action="store_true")
    ap.add_argument("--limit-reason", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    if args.record:
        state = st.load(root)
        job = Path(args.job) if args.job else (
            Path(state["last_job"]) if state.get("last_job") else None)
        if job is None:
            return 0
        counted, why = record(root, job)
        if not args.json:
            print(f"  counts towards the limit: {'yes' if counted else 'no, ' + why}")
        return 0
    if args.history:
        state = st.load(root)
        history = runs(root, state, Path(args.jobs_dir) if args.jobs_dir else None)
        if args.json:
            print(json.dumps(history, indent=2))
        else:
            for run in history:
                print(f"  {run['job']:<12} {'counted' if run['counted'] else 'not counted'}"
                      + (f"  ({run['why']})" if run["why"] else ""))
        return 0
    return check(root, job_name=args.job_name, confirm=args.confirm_rerun,
                 reason=args.limit_reason, dry_run=args.dry_run,
                 jobs=Path(args.jobs_dir) if args.jobs_dir else None)


if __name__ == "__main__":
    sys.exit(main())
