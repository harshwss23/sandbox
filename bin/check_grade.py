#!/usr/bin/env python3
"""Check the judge's verdicts, one criterion at a time.

The score is worth what the judge's reading of each criterion is worth. It
answers each one on its own, from the criterion's wording alone, and where it
read a criterion differently from the way it was meant the verdict is about the
wording rather than about the model. This is what catches that.

    python3 bin/check_grade.py                 # walk the verdicts
    python3 bin/check_grade.py --status        # what is on record, and stop
    python3 bin/check_grade.py --confirm-all   # every verdict read correctly
    python3 bin/check_grade.py --flag N:case   # flag criterion N, and record it
    python3 bin/check_grade.py --json          # the verdicts, machine-readable

Nothing here edits tests/rubrics.md. A flag names a criterion and the remedy;
the criterion is the contributor's to change.
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

import flc_state as st  # noqa: E402
import grade_report as gr  # noqa: E402
import labels as lb  # noqa: E402

STATE_KEY = "grade_review"
WIDTH = 78

# Whether this sandbox has the unit-test path at all. A criterion that belongs
# in a suite is not a case to offer where there is no suite to move it into.
HAS_TESTS = (BIN_DIR / "check_tests.py").exists()

# The ones a contributor actually hits. Each is a different repair, and naming
# them is the whole point of asking: "this criterion is wrong" and "the judge
# misread it" lead to different edits.
CASES = {
    "ambiguous": (
        "the criterion was ambiguous, or carried two facts",
        "Reword it in tests/rubrics.md so it states one fact plainly, run "
        "/flc-rubrics to rebuild and lint it, then grade again."),
    "misread": (
        "the criterion is sound and the judge got it wrong",
        "Grade again -- one attempt, not a loop. The judge is not "
        "deterministic. If it reads the same way a second time, the criterion "
        "has to name the fact more plainly; that is the part you control."),
    "unsupported": (
        "it asks for something the ground truth does not support",
        "Then the criterion is wrong rather than the model. "
        "solution/ground_truth.md is the fixed point of the task and does not "
        "move to accommodate a criterion; fix the criterion against it, then "
        "grade again."),
}

if HAS_TESTS:
    CASES["belongs_in_a_test"] = (
        "it checks an exact value in a file the model produced",
        "That is an automated check, not a criterion: a program can compare "
        "the value exactly, where the judge is being asked to eyeball it. Move "
        "it into tests/verifier.py, delete the criterion, run "
        "/flc-check-tests, then grade again.")


def wrap(text: str, indent: str = "      ") -> str:
    return textwrap.fill(text, width=WIDTH, initial_indent=indent,
                         subsequent_indent=indent)


def digest_of(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def recorded(state: dict, results: Path) -> tuple[dict | None, bool]:
    """The recorded review, and whether it was taken against this grade.

    Pinned to the results file rather than to the job, because the commonest
    sequence here is flag, reword, grade again -- and a review carried over
    from the previous grade would report criteria nobody has looked at as
    checked.
    """
    entry = state.get(STATE_KEY)
    if not isinstance(entry, dict) or not entry.get("at"):
        return None, False
    return entry, entry.get("results_sha256") == digest_of(results)


def rows(logs: Path) -> list[dict]:
    """Every criterion with its verdict, in the order the judge took them."""
    results, _, _ = gr.load(logs)
    out = []
    for entry in results:
        mark, why = gr.verdict(entry)
        out.append({
            "criterion": str(entry.get("title") or "(untitled)"),
            "weight": int(entry.get("weight", 5)),
            "kind": gr.kind(entry),
            "verdict": mark,
            "why": why,
            "unmeasured": entry.get("unmeasured") or "",
        })
    return out


def carried_over(previous: dict | None, current: list[dict]) -> set[str]:
    """Criteria already confirmed, whose text and verdict have not moved.

    A re-grade after fixing one criterion should not mean walking forty again.
    Confirmations are held against the criterion text and the verdict it was
    confirmed under, so a criterion that came back differently is asked again
    and everything untouched carries.
    """
    if not isinstance(previous, dict):
        return set()
    was = {str(c.get("criterion")): str(c.get("verdict"))
           for c in previous.get("confirmed_detail") or []
           if isinstance(c, dict)}
    return {row["criterion"] for row in current
            if was.get(row["criterion"]) == row["verdict"]}


def show(index: int, row: dict, total: int) -> None:
    mark = row["verdict"]
    print()
    print(f"  {index} of {total}   {mark}  [{row['weight']:+d}]  "
          f"{row.get('kind', '')}")
    print(wrap(row["criterion"], "      "))
    if row["weight"] < 0:
        print("      (a mistake the answer was meant to avoid)")
    print()
    if row["unmeasured"] or mark == "UNSCORED":
        print("      This one was never graded, so there is no verdict to")
        print("      check. It is reported by /flc-grade and blocks delivery.")
    if row["why"]:
        print("      the judge's reasoning:")
        print(wrap(row["why"], "        "))
    else:
        print("      the judge gave no reasoning.")


def preamble(total: int) -> None:
    print()
    print("=" * WIDTH)
    print("Checking the verdicts")
    print("=" * WIDTH)
    print()
    print(wrap("You are checking whether the judge understood each criterion "
               "the way you meant it -- not whether you like the verdict it "
               "reached. A criterion the model genuinely failed is the task "
               "working.", "  "))
    print()
    print(wrap("Read the reasoning, not the verdict. The reasoning is the only "
               "thing that says which criterion the judge thought it was "
               "answering.", "  "))
    print()
    print(f"  {total} criterion(s) to go through.")


def remedies() -> None:
    print()
    print("  If one was misjudged, which is it:")
    for key, (label, _) in CASES.items():
        print(f"    {key:<18} {label}")


def report_flag(row: dict, case: str) -> None:
    label, remedy = CASES[case]
    print()
    print("  " + "-" * (WIDTH - 2))
    print(wrap(f"FLAGGED: {row['criterion']}", "  "))
    print(f"  because {label}")
    print()
    print(wrap(remedy, "  "))


def closing(flagged: list[dict]) -> None:
    print()
    print("=" * WIDTH)
    if not flagged:
        print("Every verdict checked. Nothing flagged.")
        print()
        print(wrap("The score describes what you built. Before /flc-deliver, "
                   f"answer the last two headings of {lb.LABELS}: what went "
                   "wrong in this run, and why.", "  "))
        return
    print(f"{len(flagged)} criterion(s) flagged.")
    print()
    print(wrap("Each one needs its criterion changed, and then the run needs "
               "grading again. That is not optional: the score on record is "
               "tied to the criteria it was taken against, and /flc-deliver "
               "refuses a score taken against criteria that have since moved. "
               "So editing the rubric without grading again leaves you unable "
               "to deliver, with a message about a stale score.", "  "))
    print()
    print("  In order:")
    print("    1. make the edits below")
    print("    2. /flc-rubrics     rebuild and lint them")
    print("    3. /flc-grade       take the score again")
    print("    4. /flc-check-grade come back through here")
    print()
    for row in flagged:
        label, remedy = CASES[row["case"]]
        print(wrap(f"- {row['criterion']}", "  "))
        print(wrap(f"{label} -- {remedy}", "      "))
        print()


def labels_after(root: Path, job: Path, flagged: list[dict]) -> None:
    """The labels written after grading, once the verdicts stand."""
    if flagged:
        return
    findings = lb.check(root, "post", lb.run_requests(root, job))
    lb.report(findings, "post")


def save(root: Path, job: Path, results: Path, confirmed: list[dict],
         flagged: list[dict]) -> None:
    state = st.load(root)
    state[STATE_KEY] = {
        "job": str(job),
        "results_sha256": digest_of(results),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "confirmed": len(confirmed),
        # The verdict each was confirmed under, so a re-grade can tell a
        # criterion that came back the same from one that moved.
        "confirmed_detail": confirmed,
        # The verdict at the time of flagging travels with the flag. A task
        # that could not clear the difficulty bar and flagged only the criteria
        # the model passed is a different thing from one that found a genuine
        # misreading, and only this tells them apart afterwards.
        "flagged": flagged,
    }
    st.save(root, state)


def parse_flags(values: list[str], total: int) -> dict[int, str]:
    """`--flag 3:misread` into {3: "misread"}, refusing anything else."""
    out: dict[int, str] = {}
    for value in values or []:
        number, _, case = value.partition(":")
        if not case:
            raise SystemExit(f"--flag wants N:case, got {value!r}. "
                             f"Cases: {', '.join(CASES)}")
        if case not in CASES:
            raise SystemExit(f"unknown case {case!r}. "
                             f"Cases: {', '.join(CASES)}")
        try:
            index = int(number)
        except ValueError:
            raise SystemExit(f"--flag wants a criterion number, got {number!r}")
        if not 1 <= index <= total:
            raise SystemExit(f"there is no criterion {index}; there are {total}")
        out[index] = case
    return out


def ask(row: dict, index: int, total: int) -> str | None:
    """One criterion, until an answer that means something comes back."""
    show(index, row, total)
    while True:
        print()
        answer = input("      read correctly? [y]es / [n]o / [q]uit: ").strip().lower()
        if answer in ("y", "yes", ""):
            return None
        if answer in ("q", "quit"):
            raise KeyboardInterrupt
        if answer in ("n", "no"):
            remedies()
            while True:
                case = input("      which: ").strip().lower()
                if case in CASES:
                    return case
                print(f"      one of: {', '.join(CASES)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="a job directory (default: the last graded run)")
    ap.add_argument("--task", help="the task folder")
    ap.add_argument("--status", action="store_true",
                    help="what is on record for this grade, and stop")
    ap.add_argument("--confirm-all", action="store_true",
                    help="record every verdict as read correctly")
    ap.add_argument("--flag", action="append", metavar="N:case",
                    help="flag criterion N; repeatable")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    root = st.task_root(args.task)
    job = Path(args.job).resolve() if args.job else gr.latest_job(root)
    if not job or not job.is_dir():
        print("No solver run found. Start one with /flc-run-solver.",
              file=sys.stderr)
        return 2
    logs = gr.find_logs(job)
    if not logs:
        print("This run has not been graded, so there are no verdicts to "
              "check.\nGrade it with /flc-grade.", file=sys.stderr)
        return 2

    results = logs / "evaluation_results.json"
    verdicts = rows(logs)
    state = st.load(root)
    entry, current = recorded(state, results)

    if args.as_json:
        print(json.dumps({"job": str(job), "criteria": verdicts,
                          "recorded": entry, "current": current}, indent=2))
        return 0

    if args.status:
        if entry and current:
            print(f"Checked on {entry['at']}: {entry.get('confirmed', 0)} "
                  f"confirmed, {len(entry.get('flagged') or [])} flagged.")
            return 0
        if entry:
            print("The verdicts were checked against an earlier grade, so that "
                  "record\ndoes not describe this one. Run /flc-check-grade.")
            return 1
        print("The verdicts have not been checked. Run /flc-check-grade.")
        return 1

    if not verdicts:
        print("Nothing was graded on this run, so there are no verdicts to "
              "check.", file=sys.stderr)
        return 2

    already = carried_over(entry, verdicts)
    flags = parse_flags(args.flag, len(verdicts))

    confirmed: list[dict] = []
    flagged: list[dict] = []

    if args.confirm_all or flags:
        for index, row in enumerate(verdicts, start=1):
            if index in flags:
                flagged.append({"criterion": row["criterion"],
                                "verdict": row["verdict"],
                                "case": flags[index]})
                report_flag(row, flags[index])
            elif args.confirm_all:
                confirmed.append({"criterion": row["criterion"],
                                  "verdict": row["verdict"]})
        if not args.confirm_all:
            # Flags on their own leave the rest as they were, so a second pass
            # naming one more criterion does not discard the first pass. Only
            # criteria that came back unchanged carry, which is what keeps a
            # confirmation from surviving the grade it was taken against.
            named = {row["criterion"] for row in flagged}
            confirmed = [{"criterion": row["criterion"],
                          "verdict": row["verdict"]}
                         for row in verdicts
                         if row["criterion"] in already
                         and row["criterion"] not in named]
        save(root, job, results, confirmed, flagged)
        closing(flagged)
        labels_after(root, job, flagged)
        return 0

    preamble(len(verdicts))
    if already:
        print(f"  {len(already)} carried over from the last check, unchanged "
              "since.")
    try:
        for index, row in enumerate(verdicts, start=1):
            if row["criterion"] in already:
                confirmed.append({"criterion": row["criterion"],
                                  "verdict": row["verdict"]})
                continue
            case = ask(row, index, len(verdicts))
            if case is None:
                confirmed.append({"criterion": row["criterion"],
                                  "verdict": row["verdict"]})
            else:
                flagged.append({"criterion": row["criterion"],
                                "verdict": row["verdict"], "case": case})
                report_flag(row, case)
    except (KeyboardInterrupt, EOFError):
        # Nothing is recorded from a walk that stopped partway. A partial
        # review saved as a review would read as the whole rubric having been
        # checked.
        print("\n\n  Stopped. Nothing recorded -- run it again to check them "
              "all.")
        return 1

    save(root, job, results, confirmed, flagged)
    closing(flagged)
    labels_after(root, job, flagged)
    return 0


if __name__ == "__main__":
    sys.exit(main())
