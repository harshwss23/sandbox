#!/usr/bin/env python3
"""Where the task stands and what to do next.

Reads the task rather than the state file's step list wherever it can: a file
that exists is stronger evidence than a flag saying a command once ran.

Usage:
    status.py [--task PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402
import labels as lb  # noqa: E402
import run_guard as rg  # noqa: E402

STEPS = [
    ("Files and prompt", "/flc-check-inputs"),
    ("The answer written down", "/flc-ground-truth"),
    ("Solver run", "/flc-run-solver"),
    ("Grading criteria", "/flc-rubrics"),
    ("Unit tests", "/flc-check-tests"),
    ("Results reviewed", "/flc-grade"),
    ("Packaged", "/flc-deliver"),
    ("Handed over", "/flc-submit"),
]


# Roughly what each command costs to run again, in minutes. The solver figure
# is the one that matters and is the observed twelve; the others are there so
# a cascade adds up to something a person can weigh against their afternoon.
REDO_MINUTES = {"/flc-run-solver": 12, "/flc-grade": 3, "/flc-deliver": 6}

# The files a contributor opens, against the evidence each one invalidates.
# GRADE_INPUTS names the generated copy -- instruction.md, rubrics.json -- and
# nobody edits those, so the mapping is stated here in the terms of the file
# they would actually change.
EDIT_SOURCES = [
    ("prompt.md", "prompt"),
    ("environment/workspace/", "workspace"),
    ("tests/rubrics.md", "rubrics"),
    ("tests/verifier.py", "unit_tests"),
    ("tests/test_weights.md", "test_weights"),
]


def edit_costs(root: Path, state: dict) -> list[dict]:
    """What changing each file would cost, now that there is evidence to lose.

    Empty until the solver has run. Before that every edit is free, and a list
    of costs would read as a reason to leave things alone at exactly the point
    where changing them is what the workflow is asking for.
    """
    if st.run_state(root) == "none":
        return []
    done = set(state.get("steps_done", []))
    later = [c for c, ok in (("/flc-grade", "grade" in done),
                             ("/flc-deliver",
                              (root / "delivery" / "validation.json").exists()))
             if ok]
    rows = []
    for name, key in EDIT_SOURCES:
        if key in ("unit_tests", "test_weights") \
                and not (root / "tests" / "verifier.py").exists():
            continue
        if key in st.RUN_INPUTS:
            cascade = ["/flc-run-solver"] + later
        elif "grade" in done:
            cascade = later
        else:
            continue
        rows.append({"file": name, "cascade": cascade,
                     "minutes": sum(REDO_MINUTES.get(c, 0) for c in cascade)})
    return rows


def _verdicts_note(state: dict) -> str:
    """Whether the judge's verdicts have been checked against this grade.

    A note on the grading step rather than a step of its own: checking them is
    part of reading the result, and it does not gate anything.
    """
    recorded = state.get("last_graded_job")
    if not recorded or not Path(recorded).is_dir():
        return ""
    try:
        import check_grade
        import grade_report as gr
        logs = gr.find_logs(Path(recorded))
        if not logs:
            return ""
        entry, current = check_grade.recorded(
            state, logs / "evaluation_results.json")
    except Exception:
        return ""
    if entry and current:
        flagged = len(entry.get("flagged") or [])
        return f"{flagged} criterion(s) flagged" if flagged else ""
    return "verdicts unchecked -- /flc-check-grade"


def _answer_note(root: Path, state: dict) -> str:
    """Whether a check confirmed something in the answer is wrong."""
    try:
        import rubric_check
        found = rubric_check.answer_inaccuracies(root, state)
    except Exception:  # noqa: BLE001 -- the rest of the status still prints
        return ""
    if found["verdict"] == "FAIL":
        return ("your answer states something a check shows is wrong, and graded "
                "material repeats it -- fix it in " + st.GROUND_TRUTH)
    if found["verdict"] == "WARN":
        return "your answer states something a check shows is wrong -- fix it"
    return ""


def _justification_note(state: dict) -> str:
    """What /flc-check-justification left for the contributor to fix."""
    entry = state.get("justification_check") or {}
    if entry.get("blocking"):
        return "the justification has something to fix -- /flc-check-justification"
    still = len(entry.get("open") or [])
    if still:
        return (f"{still} justification finding(s) to fix unless wrong -- "
                "/flc-check-justification")
    return ""


def unit_test_points(root: Path) -> dict:
    """How many tests there are and what they are worth, or None for no suite."""
    try:
        data = json.loads((root / "tests" / "test_weights.json").read_text())
        weights = data["weights"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(weights, dict) or not weights:
        return None
    return {"count": len(weights), "total": sum(weights.values())}


def _first_step(root: Path, state: dict, files: list) -> str:
    """The command the first step still needs: the files, the prompt's check, or both together."""
    if not files:
        return "/flc-unpack"
    try:
        import prompt_check
        _, current = prompt_check.recorded(state, prompt_check.prompt_text(root))
    except Exception:
        current = True
    if not st.contributor_prompt(root) or not current:
        return "/flc-prompt-check"
    return "/flc-check-inputs"


def separate_checks(root: Path, state: dict) -> dict:
    """The check count, with lines that only repeat another counted apart."""
    try:
        import rubric_check
        return rubric_check.distinct(root, state)
    except Exception:  # noqa: BLE001 -- the plain count still prints
        return st.check_count(root)


def collect(root: Path) -> dict:
    state = st.load(root)
    done = set(state.get("steps_done", []))
    files = st.workspace_files(root)

    rubrics = root / "tests" / "rubrics.json"
    rubric_count = 0
    if rubrics.exists():
        try:
            rubric_count = len(json.loads(rubrics.read_text()))
        except Exception:
            pass

    skipped = state.get("unit_tests") == "skipped"
    # A skipped task with a suite still on disk would be graded on it, since
    # nothing in what runs the tests reads this flag. Reported here, where it
    # costs nothing, rather than only at the grade that pays for it.
    stray_suite = skipped and (root / "tests" / "verifier.py").exists()
    jobs = state.get("last_job")
    phase = st.run_state(root)

    # The run comes before the rubrics and is not waited on: it is started, and
    # the completion criteria get written while it goes. So the run counts as
    # done once it is under way, or the contributor would be told to start it
    # again while it is running.
    #
    # A run that ended without a transcript is "none" with a note rather than
    # an unexplained empty box: it did happen, and what to do about it is not
    # the same as never having started.
    if phase == "running":
        run_note = "still going"
    elif phase == "none" and st.run_attempted(root):
        run_note = "a run was started but produced no transcript -- start it again"
    else:
        run_note = ""

    status = [
        ("Files and prompt", bool(files) and bool(st.contributor_prompt(root))
         and "check_inputs" in done, _first_step(root, state, files), ""),
        ("The answer written down", not rg.seal_missing(root),
         "/flc-ground-truth", _answer_note(root, state) or _justification_note(state)),
        ("Solver run", phase != "none", "/flc-run-solver", run_note),
        ("Grading criteria", "rubrics" in done,
         "/flc-inspect, then /flc-rubrics" if phase == "finished" else "/flc-rubrics",
         "completion only so far" if rubric_count and "rubrics" not in done else ""),
        ("Unit tests", (skipped and not stray_suite) or "check_tests" in done,
         "/flc-skip-tests" if stray_suite else "/flc-check-tests",
         "skipped, but tests/verifier.py is still there and would be graded"
         if stray_suite else ""),
        ("Results reviewed", "grade" in done, "/flc-grade",
         _verdicts_note(state) if "grade" in done else ""),
        ("Packaged", (root / "delivery" / "validation.json").exists(),
         "/flc-deliver", ""),
        ("Handed over", "submit" in done, "/flc-submit", ""),
    ]

    next_cmd = next((cmd for name, ok, cmd, _ in status
                     if not ok and name != "Handed over"), None)
    return {
        "task_id": state["task_id"],
        "seed_version": st.profile().get("seed_version") or state.get("seed_version"),
        "files": len(files),
        "required_files": len(state.get("required_files", [])),
        "material_estimate": state.get("material_estimate"),
        "context_added": state.get("context_added"),
        "context_band": state.get("context_band"),
        "rubrics": rubric_count,
        "checks": separate_checks(root, state),
        "labels": lb.summary(root),
        "unit_tests": state.get("unit_tests"),
        "unit_test_points": unit_test_points(root),
        "packages": len(state.get("packages", [])),
        "blocked_domains": state.get("blocked_domains", []),
        "last_job": jobs,
        "run": phase,
        "solver_runs": rg.summary(root, state),
        "review_usage": (state.get("rubric_check") or {}).get("usage") or {},
        "steps": [{"name": n, "done": ok, "command": c, "note": note}
                  for n, ok, c, note in status],
        "edit_costs": edit_costs(root, state),
        "next": next_cmd,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    s = collect(root)

    if args.json:
        print(json.dumps(s, indent=2))
        return 0

    print(f"  task {s['task_id']}"
          + (f"  (seed {s['seed_version']})" if s.get("seed_version") else ""))
    print()
    for step in s["steps"]:
        note = f"  ({step['note']})" if step["note"] else ""
        print(f"  [{'x' if step['done'] else ' '}] {step['name']}{note}")
    print()
    print(f"  files            {s['files']}"
          + (f" ({s['required_files']} needed to solve)" if s["required_files"] else ""))
    # Before the run, the estimate of how much material is here; after it, the
    # measurement of how much reached the model. Only one of the two is shown.
    if s["context_added"]:
        band = (s["context_band"] or "").replace("_", "-")
        print(f"  context          {s['context_added']:,} tokens measured"
              + (f"  ({band})" if band else ""))
    elif s["material_estimate"]:
        print(f"  material         ~{s['material_estimate']:,} tokens estimated"
              " (the run measures the real figure)")
    runs = s.get("solver_runs") or {}
    if runs.get("counted") or s["run"] != "none":
        tokens = runs.get("last_tokens")
        print(f"  solver runs      {runs.get('counted', 0)} of {runs.get('limit')}"
              + (f"  (the last used {tokens:,} tokens)" if tokens else ""))
    print(f"  rubrics          {s['rubrics']}")
    points = s.get("unit_test_points")
    print(f"  unit tests       {s['unit_tests']}"
          + (f"  ({points['count']} worth {points['total']} points)"
             if points else ""))
    counted = s.get("checks") or {}
    if counted:
        print(f"  checks           {counted['total']} of {counted['floor']}"
              + ("" if counted["enough"] else "  (grading needs the floor)"))
        if counted.get("repeats"):
            print(f"                   {counted['distinct']} of them separate: "
                  f"{len(counted['repeats'])} only "
                  f"repeat{'s' if len(counted['repeats']) == 1 else ''} another line"
                  + ("" if counted.get("distinct_enough")
                     else f"  (delivery needs {counted['floor']} separate)"))
    labels = s.get("labels") or {}
    if labels.get("exists"):
        print(f"  labels           {labels['answered']} of {labels['of']} answered"
              + (f"  ({labels['to_fix']} to fix in {lb.LABELS})"
                 if labels["to_fix"] else ""))
    if s["packages"]:
        print(f"  extra packages   {s['packages']}")
    # The block list, printed whether or not anything is on it, and before the
    # first run stated as a question rather than a fact. It is the one thing on
    # this list that cannot be fixed after the fact: a run the model answered
    # off a web page is a run to throw away, and the remedy costs another one.
    # Named up to three and then counted, because a thirteen-domain list wraps
    # and stops being read.
    blocked = s["blocked_domains"]
    shown = ", ".join(blocked[:3])
    if len(blocked) > 3:
        shown += f" and {len(blocked) - 3} more"
    print(f"  blocked          {len(blocked)} site(s)"
          + (f"  {shown}" if blocked else ""))
    if s["run"] == "none":
        print("                   the model browses while it works. Block "
              "anything that")
        print("                   would state your answer outright -- the "
              "paper the data")
        print("                   came from, the database page for what you "
              "are asking")
        print("                   about:  /flc-block-domain example.com")
    print()
    costs = s.get("edit_costs") or []
    if costs:
        print("  changing one of these now costs:")
        for row in costs:
            print(f"    {row['file']:<26} {', '.join(row['cascade'])}")
        # The one thing this list must not become. It is here so a cost is
        # known before it is paid, not so it can be weighed against shipping
        # something known to be wrong -- and the pressure runs one way, since
        # the difficulty bar is a ceiling and a criterion the judge misread is
        # most often one the model passed.
        print("    A criterion the judge misread, a prompt that says the wrong")
        print("    thing: fix it, whatever it costs and whatever it does to the")
        print("    score. This is what an edit costs, not a reason to skip one.")
        print()
    print(f"  next: {s['next'] or 'nothing -- the task is packaged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
