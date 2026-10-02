#!/usr/bin/env python3
"""Grade a finished solver run, when the contributor asks for it.

    run_grader.py                  grade the last run
    run_grader.py --job PATH       grade a specific one
    run_grader.py --force          grade even if the criteria look half-written

Grading is a separate act from running the solver, and this is what makes it
one. The solver run produces a transcript and nothing else; the hallucination
criteria are written afterwards, from that transcript; and
only then is there anything worth grading against. A score taken before the
non-hallucination criteria existed would be a score for half a rubric, and
`/flc-grade` would report it as though it were the result.

It runs the same verifier the bundle carries -- the task's own image, with
`tests/` mounted at /tests and the run's logs and finished workspace mounted
where the judge expects them -- and writes the results into the run's own
`logs/verifier/`, which is where `grade_report.py` and `/flc-deliver` look.
Grading twice overwrites cleanly, results and record together.

This is the only place a task is scored. Delivery reads what is left here
rather than grading again, so the fingerprint of what was graded is recorded
alongside the score -- see `flc_state.GRADE_INPUTS`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import context_report as cr  # noqa: E402
import check_integrity as ci  # noqa: E402
import flc_state as st  # noqa: E402
import solver_answer as sa  # noqa: E402
from package_delivery import find_run, trial_logs  # noqa: E402

TAG = "flc-grade-check"

# Named, never given a value on the command line: `docker run -e KEY` takes it
# from this process's environment, while `-e KEY=value` puts the secret in argv
# where any other process can read it and where `docker inspect` keeps it.
OURS = ("  There's a technical issue on our side, not a problem with your task.\n"
        "  If it happens again, please reach out to the project team.")
PASS_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE",
            "EVAL_API_KEY", "EVAL_BASE_URL", "EVAL_MODEL")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def rubrics_are_final(root: Path) -> tuple[bool, str]:
    """Whether the criteria look finished enough to be worth spending a grade on.

    The check is for a negative criterion under Non-hallucination, the half
    written from the run. A rubric with none of them has been through its first
    sitting only, and grading it would measure the completion half alone.

    The label is read rather than the sign alone. A negative criterion is also
    a legitimate thing to write under Clarification -- a question the model
    should have asked and did not -- so a rubric can carry one of those and
    still have nothing at all to say about what the model made up.
    """
    path = root / "tests" / "rubrics.json"
    if not path.exists():
        return False, "tests/rubrics.json does not exist yet. Run /flc-rubrics."
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False, "tests/rubrics.json is not readable. Run /flc-rubrics."
    criteria = payload if isinstance(payload, list) else payload.get("rubrics", [])
    if not criteria:
        return False, "There are no criteria to grade against. Run /flc-rubrics."
    if not any(int(c.get("weight", 0)) < 0
               and "hallucination" in (c.get("type") or [])
               for c in criteria):
        return False, ("There are no non-hallucination criteria yet, so grading "
                       "now would score the completion half alone. Write them "
                       "against what the model claimed -- /flc-inspect shows "
                       "you -- then run /flc-rubrics and come back.")
    return True, ""


def file_criteria(root: Path) -> int:
    """How many criteria are about a file the model wrote, rather than its answer."""
    try:
        payload = json.loads((root / "tests" / "rubrics.json").read_text())
    except (OSError, ValueError):
        return 0
    criteria = payload if isinstance(payload, list) else payload.get("rubrics", [])
    return sum(1 for c in criteria if "state change" in (c.get("type") or []))


def enough_checks(root: Path) -> tuple[bool, str]:
    """Whether the task carries the floor of checks before a grade is spent.

    Counted across the criteria and the suite together, because they are one
    instrument. Below the floor the score is a number over too little of the
    task to say where the answer went wrong, which is the whole deliverable.
    """
    counted = st.check_count(root)
    if counted["enough"]:
        return True, ""
    parts = f"{counted['rubrics']} criteria"
    if counted["tests"]:
        parts += f" and {counted['tests']} unit tests"
    return False, (
        f"This task has {parts} -- {counted['total']} checks, and "
        f"{counted['floor']} is the floor.\n\n"
        "  A score over this few says where the answer landed and not how it\n"
        "  got there, and the route is where the failures worth collecting\n"
        "  are. The checks worth adding are the steps the answer depended on:\n"
        "  the file it had to open, the figure it had to work out first, the\n"
        "  procedure it had to follow. An answer that skipped any of those\n"
        "  cannot be right, so each one is a real check rather than padding.\n\n"
        "  Add them in tests/rubrics.md, then: /flc-rubrics")


def write_grade_page(root: Path, job: Path, quiet: bool) -> None:
    """Render the grade to a page, and never fail the grade over it.

    The score is in hand by the time this runs and the page is a rendering of
    it, so a broken renderer must not turn a graded run into a failed command.
    """
    try:
        import view_grade
        out = root / "review" / f"grade-{job.name}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        logs = view_grade.gr.find_logs(job)
        if not logs:
            return
        out.write_text(view_grade.render(job, logs, root), encoding="utf-8")
    except Exception:
        return
    if not quiet:
        print(f"\n  The whole grade as a page:  {out}")
        print("  Download it and open it in your own browser. It has every")
        print("  criterion with the judge's reasoning for reaching its verdict.")
        print("\n  Then check those verdicts:  /flc-check-grade")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="a job directory (default: the last run)")
    ap.add_argument("--task", help="the task folder")
    ap.add_argument("--force", action="store_true",
                    help="grade even if the criteria look half-written")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    # Before anything is measured: a score is only comparable with another
    # score if the same machinery produced both.
    ci.announce(root, "grade")
    state = st.load(root)

    # The image is built from environment/ below and the judge reads
    # tests/prompt.txt, so both are brought up to date with the state before
    # anything is measured against them.
    st.regenerate(root)

    ready, why = rubrics_are_final(root)
    if not ready and not args.force:
        print(f"  not grading yet.\n\n  {why}\n", file=sys.stderr)
        return 2

    # Free, so it goes before the fingerprints and a long way before docker.
    ready, why = enough_checks(root)
    if not ready and not args.force:
        print(f"  not grading yet.\n\n  {why}\n", file=sys.stderr)
        return 2

    # What runs the tests is whatever tests/verifier.py is on disk, and nothing
    # in that chain reads the state, so a task recorded as graded by rubrics
    # alone with a suite still there would be scored on it.
    if state.get("unit_tests") == "skipped" \
            and (root / "tests" / "verifier.py").exists() and not args.force:
        print("  not grading: this task is recorded as graded by rubrics alone,\n"
              "  and tests/verifier.py is still there.\n\n"
              "  What runs the tests reads that file and never the record, so\n"
              "  the score would count a suite this task decided against and\n"
              "  the delivery will not carry.\n\n"
              "    /flc-skip-tests     set it aside, as intended\n"
              "    /flc-enable-tests   keep it, then /flc-check-tests\n\n"
              "  (--force grades it anyway, to look at. /flc-deliver still\n"
              "  refuses a score taken over a suite it will not ship.)\n",
              file=sys.stderr)
        return 2

    # Refused when the prompt or the material has moved since the run, since
    # the model never saw what would be graded here. Before the build rather
    # than after.
    current = st.fingerprint(root)
    recorded = state.get("run_fingerprint")
    if not isinstance(recorded, dict) and not args.force:
        # Never true of a run this sandbox started. Reported as a missing
        # record rather than as everything having changed.
        print("  not grading: there is no record of what this run was given.\n\n"
              "  Start a fresh run, which records it:\n\n    /flc-run-solver\n",
              file=sys.stderr)
        return 2
    moved = st.fingerprint_drift(recorded, current, st.RUN_INPUTS)
    if moved and not args.force:
        what = {"prompt": "prompt.md", "workspace": "environment/workspace/"}
        changed = ", ".join(what.get(k, k) for k in moved)
        print(f"  not grading: {changed} changed after this run.\n\n"
              "  The model was given the earlier version, so a score now would\n"
              "  measure a task nobody ran. Start a fresh run:\n\n"
              "    /flc-run-solver\n\n"
              "  (--force grades it anyway, to look at. /flc-deliver still\n"
              "  refuses a score taken against a run that did not see this.)\n",
              file=sys.stderr)
        return 2

    job = Path(args.job).resolve() if args.job else (
        Path(state["last_job"]) if state.get("last_job") else None)
    if not job or not job.is_dir():
        print("  no solver run found. Run /flc-run-solver first.", file=sys.stderr)
        return 2
    trial = find_run(job)
    if trial is None:
        print(f"  no finished run inside {job}.\n"
              "  If it is still going, /flc-status says so; grade it once it has finished.",
              file=sys.stderr)
        return 2

    # Before the build and before any judge call. Only a measured shortfall
    # refuses; a run that could not be measured is left to delivery to raise.
    context = cr.measure(job)
    added = context["context_added"]
    if added is not None and added < st.CONTEXT_ADDED_FLOOR and not args.force:
        print("  not grading yet.\n", file=sys.stderr)
        print("  " + cr.summary(context).replace("\n", "\n  "), file=sys.stderr)
        print("\n  (--force grades it anyway, to look at. /flc-deliver still\n"
              "  refuses a task that did not reach the floor.)\n", file=sys.stderr)
        st.mark_failed(root, "grade", "context_floor",
                       f"context_added {added:,} is below "
                       f"{st.CONTEXT_ADDED_FLOOR:,}")
        return 2

    logs = trial_logs(trial)
    # Checked before docker and before the build, since it is a property of the
    # run rather than of this machine. Refused rather than skipped: the answer
    # the judge grades is the agent's final message, read out of the
    # trajectory, and without one every criterion is scored against an empty
    # answer.
    if not (logs / "agent").is_dir():
        print(f"  no agent logs under {trial}.\n"
              "  There is a run here, but not the transcript the judge grades, so\n"
              "  grading it would score every criterion against an empty answer.\n"
              "  Nothing was measured; this is not a result about the model.\n"
              "  The run did not finish properly: run /flc-run-solver again.",
              file=sys.stderr)
        return 2

    # No copy of the workspace means the verifier never saw it, which is our
    # tooling rather than the model: a model that wrote nothing still leaves an
    # empty copy. It only refuses where it would change the score -- every
    # criterion about a file the model wrote would fail however well it did,
    # and the difficulty bar would believe that number.
    about_files = 0
    if sa.finished_workspace(job) is None:
        st.record_issue(root, "no_workspace",
                        f"no copy of the model's files came back from {trial.name}",
                        "run_grader.py")
        about_files = file_criteria(root)
        if about_files and not args.force:
            print("  not grading: the model's files did not come back from this run, and\n"
                  f"  {about_files} of your criteria are about a file it wrote, so they would\n"
                  "  fail however well it did. That is a technical issue on our side, not\n"
                  "  your task, and the run does not count towards your five. Run\n"
                  "  /flc-run-solver again.  (--force grades it anyway, to look at.)",
                  file=sys.stderr)
            st.mark_failed(root, "grade", "no_workspace",
                           "the run brought back no copy of the model's files")
            return 2

    if not shutil.which("docker"):
        print("  docker is not available, so the grading cannot run here.\n"
              + OURS, file=sys.stderr)
        return 2

    if not args.quiet:
        counted = st.check_count(root)
        against = f"{counted['rubrics']} criteria"
        if counted["tests"]:
            against += f" and {counted['tests']} unit tests"
        print(f"  grading {trial.name} against {against}")
        print("  building the task image...")
    build = run(["bash", str(BIN_DIR / "build_image.sh"), str(root),
                 "--quiet", "--tag", TAG])
    if build.returncode != 0:
        print("  the task image did not build:\n" + build.stderr[-2000:],
              file=sys.stderr)
        return 1
    tag = build.stdout.strip().splitlines()[-1]

    verifier_out = logs / "verifier"
    verifier_out.mkdir(parents=True, exist_ok=True)
    # A previous grade's results would otherwise be read as this one's if the
    # judge fell over before writing.
    for stale in ("evaluation_results.json", "reward.json", "ctrf.json",
                  "grading_summary.json"):
        (verifier_out / stale).unlink(missing_ok=True)

    mounts = ["-v", f"{root / 'tests'}:/tests:ro", "-v", f"{verifier_out}:/logs/verifier",
              "-v", f"{logs / 'agent'}:/logs/agent:ro"]
    # What the judge is shown as "the model's output". A run that brought none
    # of the workspace back is reported as that rather than graded against
    # nothing.
    workspace = sa.finished_workspace(job)
    if workspace is not None:
        mounts += ["-v", f"{workspace}:/workspace:ro"]
    elif not args.quiet:
        print("  note: this run brought back no copy of the files the model wrote "
              "(a technical\n        issue on our side, noted for the project team). "
              + ("Criteria about those\n        files cannot be graded."
                 if about_files else
                 "None of your criteria\n        is about a file, so the grade is "
                 "unaffected."))

    env_args = []
    for key in PASS_ENV:
        if os.environ.get(key):
            env_args += ["-e", key]

    # The judge is an API call, and on this VM the gateway is published on the
    # host's loopback. `--network host` below shares the host's network
    # namespace, so `localhost` here is the host's localhost rather than the
    # container's own.
    endpoint = (os.environ.get("EVAL_BASE_URL") or os.environ.get("OPENAI_API_BASE")
                or os.environ.get("OPENAI_BASE_URL") or "")
    if not args.quiet:
        print(f"  judge endpoint: {endpoint or '(none set -- grading will fail)'}")
    # The sentinel that says a person asked for this. Without it the verifier
    # defers, which is what keeps the solver run from grading half a rubric.
    env_args += ["-e", "FLC_GRADE_NOW=1"]

    if not args.quiet:
        print("  running the verifier...\n")
    verify = run(["docker", "run", "--rm", "--network", "host",
                  *mounts, *env_args, tag, "bash", "/tests/test.sh"])
    (verifier_out / "verifier_stdout.txt").write_text(verify.stdout + verify.stderr)
    if not args.quiet:
        print(verify.stdout[-4000:])

    results = verifier_out / "evaluation_results.json"
    if not results.exists():
        print("  the verifier produced no results:\n"
              + (verify.stderr[-2000:] or verify.stdout[-2000:]), file=sys.stderr)
        blob = verify.stdout + verify.stderr
        if any(w in blob.lower() for w in
               ("connection", "refused", "timed out", "unreachable", "getaddrinfo")):
            print(f"\n  That reads like the judge could not reach {endpoint}.\n"
                  "  Nothing was measured, so this is not a result about the model.\n"
                  "  Try /flc-grade once more.\n" + OURS,
                  file=sys.stderr)
        return 1

    # Grading is the act that completes the step, and the fingerprint of what
    # was graded goes with it -- this score is what /flc-deliver gates on
    # instead of buying a second one. Recorded after the verifier has produced
    # results, so a failed grade leaves no record of a score.
    state = st.load(root)
    state["last_graded_job"] = str(job)
    state["grade_fingerprint"] = current
    state["graded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    import grade_report as gr  # noqa: PLC0415
    rows, reward, _ = gr.load(verifier_out)
    state.setdefault(gr.GRADES_KEY, []).append(gr.grade_record(job, rows, reward))
    st.save(root, state)
    st.mark_done(root, "grade")
    write_grade_page(root, job, args.quiet)
    drop = gr.weights_only_for(state, job)
    if drop:
        print("\n  WARNING: this grade will be refused at delivery.\n  "
              + gr.weights_only_text(drop, reward["reward"]).replace("\n", "\n  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
