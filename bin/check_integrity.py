#!/usr/bin/env python3
"""Compare the sandbox's own machinery against the manifest the seed shipped.

    check_integrity.py                  report on every covered file
    check_integrity.py --json
    check_integrity.py --step grade     what that step would do about it
    check_integrity.py --quiet          record only, print nothing

bin/seed_manifest.json lists every shipped file and its sha256, written when
the seed was built. Anything that no longer matches is reported here.

Two tiers. The files covering the run, the model it is taken against and the
score refuse their own step; everything else records and lets the step run. Either way the evidence the
file produced is cleared, so the existing freshness checks demand it be taken
again.

A missing or unreadable manifest is unmeasured rather than clean: it reports
that nothing could be checked and blocks nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402

MANIFEST_NAME = "seed_manifest.json"
STATE_KEY = "integrity"
# The modified contents of crash-only files whose evidence has already been
# voided once, as [path, where, sha256].
VOIDED_KEY = "integrity_voided"
SCHEMA = "1"

# What the manifest covers, as tree-relative directories and suffixes. Written
# here rather than in make_seed.py so the tree carries its own account of what
# it is: the manifest is built by importing this file out of the tree being
# built, which is what stops the writer and the reader disagreeing.
COVERED_DIRS = (
    ("bin", (".py", ".sh")),
    ("bin/review_spec", (".json", ".md")),
    ("template_task/tests", (".py", ".sh")),
    ("skill", (".md",)),
)
# Single files the suffixes above do not reach.
COVERED_FILES = (
    "bin/solver_model.txt",
    "template_task/tests/system_prompt.txt",
    "template_task/tests/user_prompt_template.txt",
)

# Never covered, because a contributor owns them or we generate them. A file
# in here that were covered would report tampering on ordinary work, which is
# the one thing that would make this whole check worth switching off.
EXCLUDED = frozenset({
    "bin/profile.json",
    f"bin/{MANIFEST_NAME}",
    "template_task/tests/verifier.py",
    "template_task/tests/verifier.py.skipped",
})

# The score, the run and the model the run is taken against. A modification
# here has no legitimate reading -- nothing about authoring a task requires
# editing a judge or choosing a model -- so these refuse the step they belong
# to rather than only recording.
#
# bin/solver_answer.py is here because it decides which attempt of a job is the
# run: the transcript the judge is shown, the workspace it is shown beside it,
# and the results delivery reads. An edit there moves the score without
# touching anything that computes one.
BLOCKING = frozenset({
    "bin/run_solver.sh",
    "bin/run_guard.py",
    "bin/solver_model.txt",
    "bin/run_grader.py",
    "bin/solver_answer.py",
    "template_task/tests/judge.py",
    "template_task/tests/system_prompt.txt",
    "template_task/tests/user_prompt_template.txt",
    "template_task/tests/test.sh",
    "template_task/tests/snapshot_workspace.py",
    "template_task/tests/run_verifier.py",
    "template_task/tests/flc_testkit.py",
    "bin/test_weights.py",
})

# Which step each blocking file stops. A modified judge must not refuse
# /flc-check-inputs: the person is then blocked at a step that has nothing to
# do with the file, and the message reads as the sandbox being broken.
STEP_BLOCKERS = {
    "run_solver": ("bin/run_solver.sh", "bin/run_guard.py", "bin/solver_model.txt"),
    "grade": ("bin/run_grader.py",
              "bin/solver_answer.py",
              "template_task/tests/judge.py",
              "template_task/tests/system_prompt.txt",
              "template_task/tests/user_prompt_template.txt",
              "template_task/tests/test.sh",
              "template_task/tests/snapshot_workspace.py",
              "template_task/tests/run_verifier.py",
              "template_task/tests/flc_testkit.py",
              "bin/test_weights.py"),
    # Delivery asks about the whole manifest rather than one step's slice.
    "deliver": tuple(sorted(BLOCKING)),
}

# What each file's modification invalidates, and therefore which recorded
# evidence is cleared. Reused rather than reinvented: clearing a fingerprint
# makes fingerprint_drift() report every key under it as moved, which is the
# same path that catches an edited rubric, so nothing new has to learn to
# block.
#
# flc_state.py is deliberately absent. It computes the fingerprints, so an
# edit to it could fake any of them and no clearing done through it can be
# trusted -- and voiding everything on one helper edit would be the blanket
# block this design rejected. It is recorded, and downstream is what enforces.
VOIDS = {
    "bin/run_solver.sh": "run",
    "bin/run_guard.py": "run",
    "bin/solver_model.txt": "run",
    "bin/proxy_setup.sh": "run",
    "bin/run_grader.py": "grade",
    "bin/solver_answer.py": "grade",
    "template_task/tests/judge.py": "grade",
    "template_task/tests/system_prompt.txt": "grade",
    "template_task/tests/user_prompt_template.txt": "grade",
    "template_task/tests/test.sh": "grade",
    "template_task/tests/run_verifier.py": "grade",
    "bin/test_weights.py": "grade",
    "template_task/tests/flc_testkit.py": "grade",
    "template_task/tests/snapshot_workspace.py": "grade",
    "bin/check_inputs.py": "inputs",
    "bin/prompt_check.py": "prompt",
    "bin/prompt_taxonomy.py": "prompt",
    "bin/rubric_check.py": "rubric",
    "bin/rubric_quality.py": "rubric",
    "bin/justification_check.py": "justification",
    "bin/statement_vote.py": "checks",
    "bin/tool_session.py": "checks",
}
# The definitions the rubric review reads. Editing one changes what the review
# finds, so it voids the review the way editing the reviewer does.
VOIDS_UNDER = {"bin/review_spec/": "rubric"}


def voids(rel: str) -> str | None:
    if rel in VOIDS:
        return VOIDS[rel]
    return next((kind for prefix, kind in VOIDS_UNDER.items()
                 if rel.startswith(prefix)), None)

EVIDENCE_STEP = {
    "run": "/flc-run-solver, then /flc-grade",
    "grade": "/flc-grade",
    "inputs": "/flc-check-inputs",
    "prompt": "/flc-prompt-check",
    "rubric": "/flc-check-rubric",
    "justification": "/flc-check-justification",
    "checks": "/flc-check-justification and /flc-check-rubric",
}

# What an assistant may do about a sandbox file that stops a contributor. A
# repair must not move a score, change what ships or how the delivery is laid
# out, change what a gate decides, or block a later step. Anything named in
# neither set below is never repaired.
#
# Pages and the status report: they show what other files decided.
REPAIRABLE = frozenset({"bin/status.py", "bin/view_run.py", "bin/view_grade.py"})

# A task file the tooling writes for the contributor is never edited -- it is
# changed through the command that owns it, which keeps the state and the file
# it generates in step. Naming that command in the refusal is the difference
# between an assistant that can unblock a contributor and one that can only say
# no: the files below are written automatically, so a wrong entry is not
# something the contributor chose or can see coming, and the first thing it
# stops is the image build, which stops the run, the grade and the delivery at
# once.
TASK_FILE_COMMANDS = {
    "environment/.flc/packages.txt":
        "task_config.py add-package NAME [--apt|--r] / remove-package NAME [--apt|--r]",
    "environment/.flc/blocked_domains.txt":
        "task_config.py block-domain DOMAIN / unblock-domain DOMAIN",
    ".flc/state.json":
        "task_config.py show, and the subcommand that owns the setting",
}
# The checks, and the helpers whose output a check or the delivery reads. The
# fault that stops one running may be fixed; nothing it decides, keeps or
# records may change.
CRASH_ONLY = frozenset({
    "bin/check_inputs.py", "bin/prompt_check.py", "bin/prompt_taxonomy.py",
    "bin/rubric_check.py", "bin/rubric_quality.py", "bin/justification_check.py",
    "bin/review_run.py", "bin/check_grade.py", "bin/unpack_upload.py",
    "bin/detect_packages.py", "bin/statement_vote.py", "bin/tool_session.py",
    # The bundle is how a fault that stops the task is reported at all, so a
    # crash in it is the one crash that leaves a contributor with nothing.
    "bin/support_bundle.py",
})
CRASH_ONLY_UNDER = ("bin/review_spec/",)


def tree_relative(path: str, home: Path, task: Path | None = None) -> tuple[str, str]:
    """A path as the manifest names it, and where it lives: "tree", "task" or "outside"."""
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        return raw.as_posix(), "tree"
    raw = raw.resolve()
    task = (task or st.task_root()).resolve()
    if raw == task or task in raw.parents:
        return raw.relative_to(task).as_posix(), "task"
    home = home.resolve()
    if home in raw.parents:
        rel = raw.relative_to(home).as_posix()
        for src, dest in INSTALL_MOVES:
            if rel.startswith(dest):
                rel = src + rel[len(dest):]
        return rel, "tree"
    return raw.as_posix(), "outside"


def may_edit(path: str, home: Path | None = None, task: Path | None = None) -> dict:
    """Whether an assistant may repair this file, and on what terms.

    `verdict` is "yes", "crash-only" or "no". `then` names what has to happen
    straight after a crash-only repair.
    """
    rel, where = tree_relative(path, home or st.FLC_HOME, task)
    def no(why: str) -> dict:
        return {"path": rel, "verdict": "no", "why": why, "then": ""}
    if where == "outside":
        return no("it is not part of the sandbox's own tooling")
    if where == "task":
        why = ("it is in the task folder: the contributor's own files, files "
               "generated from them, or the task's copy of the grading files")
        owner = TASK_FILE_COMMANDS.get(rel)
        if owner:
            why += f". Do not edit it -- change it with: {owner}"
        return no(why)
    if rel in BLOCKING:
        return no("it is one of the files the run and the score are measured by")
    if voids(rel) in ("run", "grade"):
        return no("editing it voids the solver run or the grade")
    if rel.startswith("template_task/"):
        return no("it ships inside every task bundle")
    if rel.startswith(("skill/", "contributor_instructions/")):
        return no("it is the instructions the workflow follows, not a fault to fix")
    if rel in REPAIRABLE:
        return {"path": rel, "verdict": "yes", "then": "",
                "why": "it only shows what other files decided"}
    if rel in CRASH_ONLY or rel.startswith(CRASH_ONLY_UNDER):
        kind = voids(rel)
        return {"path": rel, "verdict": "crash-only",
                "why": ("fix only the fault that stops it running; never a "
                        "threshold, a category, or what it refuses, warns about, "
                        "keeps or records"),
                "then": (f"run {EVIDENCE_STEP[kind]} again straight away: the edit "
                         "clears its recorded result") if kind else
                        "run the same command again straight away"}
    return no("it decides a gate, shapes the delivery or its record, generates "
              "files the grade is pinned to, or is the integrity check itself")


def manifest_path(home: Path) -> Path:
    return home / "bin" / MANIFEST_NAME


def covered(tree: Path) -> list[str]:
    """Every tree-relative path the manifest should carry, sorted."""
    out = []
    for folder, suffixes in COVERED_DIRS:
        base = tree / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if path.suffix not in suffixes or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(tree).as_posix()
            if rel not in EXCLUDED:
                out.append(rel)
    for rel in COVERED_FILES:
        path = tree / rel
        if path.is_file() and not path.is_symlink():
            out.append(rel)
    return sorted(out)


def build(tree: Path) -> dict:
    """The manifest for a built tree: every covered path, by sha256."""
    return {
        "schema_version": SCHEMA,
        "files": {rel: st.sha256_file(tree / rel) for rel in covered(tree)},
    }


def load(home: Path) -> dict | None:
    """The shipped manifest, or None when there is nothing to compare against."""
    try:
        data = json.loads(manifest_path(home).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data.get("files"), dict) else None


def tier(rel: str) -> str:
    return "blocking" if rel in BLOCKING else "recorded"


# Where provisioning puts a bundle directory that is not installed under its
# own name. The manifest is keyed on the bundle's layout, because that is what
# make_seed.py can see; what a VM has is the installed layout.
INSTALL_MOVES = (("skill/", "flc_skill/"),)


def installed_path(rel: str, home: Path) -> Path:
    """Where a manifest entry actually lives once the seed is installed.

    flc_install_skills copies the bundle's skill/ to ~/flc/flc_skill/, so every
    command file and the skill's own SKILL.md were reported missing on every
    VM -- seventeen entries of noise in the audit record, which is where a real
    edit would have had to be noticed.
    """
    for src, dest in INSTALL_MOVES:
        if rel.startswith(src):
            moved = home / dest / rel[len(src):]
            if moved.exists():
                return moved
            # An unpacked bundle keeps the directory under its own name, and
            # is checked that way. Falling back only when the file is really
            # there keeps a genuinely absent one reported at the path a VM
            # would have.
            direct = home / rel
            return direct if direct.exists() else moved
    return home / rel


def _task_copy(rel: str, task: Path) -> Path | None:
    """Where a template file also lives once a task has been scaffolded.

    new_task.sh copies template_task/ wholesale, so the grading files exist
    twice and the task's copy is the one that runs: run_grader.py mounts
    <task>/tests at /tests. A manifest keyed only on the template path would
    miss an edit to the copy that counts.
    """
    prefix = "template_task/"
    return task / rel[len(prefix):] if rel.startswith(prefix) else None


def scan(home: Path, task: Path | None = None) -> dict:
    """Compare both copies of every covered file against the manifest."""
    data = load(home)
    if data is None:
        return {"measured": False,
                "why": f"no readable {MANIFEST_NAME} in {home / 'bin'}",
                "findings": []}

    findings = []
    for rel, expected in sorted(data["files"].items()):
        for where, path in (("tree", installed_path(rel, home)),
                            ("task", _task_copy(rel, task) if task else None)):
            if path is None:
                continue
            actual = st.sha256_file(path)
            # "" is both an unreadable file and an absent one. A task that has
            # not been scaffolded has no second copy, and that is not a finding.
            if actual == expected:
                continue
            if actual == "" and where == "task":
                continue
            findings.append({
                "path": rel, "where": where, "tier": tier(rel),
                "expected": expected, "actual": actual,
                "state": "missing" if actual == "" else "modified",
                "voids": voids(rel),
            })
    return {"measured": True, "why": "", "findings": findings}


def blocked(report: dict, step: str) -> list[dict]:
    """The findings that stop this step, which is never a tier 2 finding."""
    watched = set(STEP_BLOCKERS.get(step, ()))
    return [f for f in report["findings"] if f["path"] in watched]


def void(root: Path, report: dict) -> list[str]:
    """Clear the evidence the modified files produced. Returns what was cleared.

    Detection voids whether or not the edit came before the evidence, and that
    is deliberate: mtimes cannot date it, since a copy resets them and anyone
    editing a file can set them. Narrowing it would mean trusting the one
    thing already known to be untrustworthy.

    A check a crash may be repaired in (CRASH_ONLY) is voided once for each
    distinct content it is found with. Its verdict is then taken again under
    the repaired file and stands; voiding it on every later scan would leave a
    step nobody can pass. Any other file voids on every scan, as before.
    """
    if not any(f["voids"] for f in report["findings"]):
        return []
    try:
        state = st.load(root)
    except SystemExit:
        return []     # no task to void anything in
    seen = {tuple(k) for k in state.get(VOIDED_KEY) or [] if isinstance(k, list)}
    kinds = set()
    for f in report["findings"]:
        if not f["voids"]:
            continue
        once = f["path"] in CRASH_ONLY or f["path"].startswith(CRASH_ONLY_UNDER)
        key = (f["path"], f["where"], f["actual"])
        if once and key in seen:
            continue
        kinds.add(f["voids"])
        if once:
            seen.add(key)
    state[VOIDED_KEY] = sorted(list(k) for k in seen)
    cleared = []
    for kind in sorted(kinds):
        if kind == "run" and state.pop("run_fingerprint", None) is not None:
            cleared.append("run")
        elif kind == "grade" and state.pop("grade_fingerprint", None) is not None:
            cleared.append("grade")
        elif kind == "inputs":
            gone = state.pop("input_check", None) is not None
            if "check_inputs" in (state.get("steps_done") or []):
                state["steps_done"] = [s for s in state["steps_done"]
                                       if s != "check_inputs"]
                gone = True
            if gone:
                cleared.append("inputs")
        elif kind == "prompt" and state.pop("prompt_check", None) is not None:
            cleared.append("prompt")
        elif kind == "rubric" and state.pop("rubric_check", None) is not None:
            cleared.append("rubric")
        elif (kind == "justification"
              and state.pop("justification_check", None) is not None):
            cleared.append("justification")
        elif kind == "checks":
            for key, name in (("justification_check", "justification"),
                              ("rubric_check", "rubric")):
                if state.pop(key, None) is not None:
                    cleared.append(name)
    st.save(root, state)
    return cleared


def record(root: Path, report: dict, cleared: list[str]) -> dict:
    """Write what was found into the task state, so every later step sees it."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": ("UNMEASURED" if not report["measured"]
                    else "PASS" if not report["findings"] else "MODIFIED"),
        "why": report["why"],
        "findings": report["findings"],
        "evidence_cleared": cleared,
    }
    state = st.load(root)
    # Never narrows. A step that finds nothing after a file was put back must
    # not erase the record that it was modified -- the evidence stays void, and
    # the delivery record has to say why.
    previous = state.get(STATE_KEY) or {}
    if previous.get("verdict") == "MODIFIED":
        seen = {(f["path"], f["where"]) for f in entry["findings"]}
        entry["findings"] = entry["findings"] + [
            dict(f, state="restored") for f in previous.get("findings", [])
            if (f["path"], f["where"]) not in seen]
        entry["verdict"] = "MODIFIED"
        entry["evidence_cleared"] = sorted(
            set(cleared) | set(previous.get("evidence_cleared") or []))
    state[STATE_KEY] = entry
    st.save(root, state)
    return entry


def describe(finding: dict) -> str:
    copy = ("the task's copy of " if finding["where"] == "task" else "")
    verb = {"missing": "is missing", "modified": "has been modified",
            "restored": "was modified earlier in this task"}[finding["state"]]
    return f"{copy}{finding['path']} {verb}"


def refusal(findings: list[dict]) -> str:
    """What to print when a blocking file stops a step."""
    lines = ["This step cannot run: one of the sandbox's own scripts was changed.", ""]
    for f in findings:
        lines.append(f"  - {describe(f)}")
    lines += [
        "",
        "Nothing you wrote is affected, and none of your work is lost. Put the "
        "originals",
        "back with /flc-restore-tools and run this step again. If that does not "
        "work, it is",
        "a technical issue on our side: please reach out to the project team.",
    ]
    return "\n".join(lines)


def check(root: Path, home: Path, step: str = "") -> tuple[dict, list[dict]]:
    """Scan, void what it invalidates, record it, and return what blocks `step`.

    Only the live scan can block: a file already put back stops nothing. The
    recorded entry is the wider history and is carried on the report, because
    a screen saying PASS beside a state saying MODIFIED would be two of our
    own readers disagreeing about the same tree.
    """
    report = scan(home, root)
    cleared = void(root, report) if report["findings"] else []
    try:
        report["recorded"] = record(root, report, cleared)
    except SystemExit:
        report["recorded"] = None   # no task state yet, not this check's problem
    return report, blocked(report, step) if step else []


def repaired(root: Path) -> set[str]:
    """Files a recorded repair covers, where the repair was one that is allowed."""
    try:
        entries = st.issues(root)
    except Exception:
        return set()
    return {e["repair"]["file"] for e in entries
            if isinstance(e.get("repair"), dict) and e["repair"].get("file")
            and e["repair"].get("allowed") in ("yes", "crash-only")}


def announce(root: Path, step: str, home: Path | None = None) -> dict:
    """The check every step runs first. Exits the step when a tier 1 file moved.

    Called at the top of an entry point rather than inside a gate somewhere
    later, so the person is told about the file in front of them at the moment
    they are standing there. A tier 2 finding is one line and the step carries
    on: our own defects are the likeliest cause of an edited script, and a
    contributor cannot be stranded on one.
    """
    report, stops = check(root, home or st.FLC_HOME, step)
    if stops:
        print()
        print(refusal(stops))
        raise SystemExit(1)
    entry = report.get("recorded") or {}
    fixed = repaired(root)
    live = [f for f in report["findings"]
            if f["state"] != "restored" and f["path"] not in fixed]
    cleared = entry.get("evidence_cleared") or []
    if not live and cleared:
        print("  What the repaired script produced has to be taken again: "
              + "; ".join(EVIDENCE_STEP[k] for k in cleared))
        print()
    if live:
        names = ", ".join(sorted({f["path"] for f in live}))
        print(f"  Note: {names} differs from what the seed shipped. This step "
              f"will run.")
        print("  It is recorded, and /flc-restore-tools puts the original back.")
        if cleared:
            print("  What it produced has to be taken again: "
                  + "; ".join(EVIDENCE_STEP[k] for k in cleared))
        print()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--home", default=None)
    ap.add_argument("--step", default="",
                    help="report what this step would refuse: "
                         + ", ".join(sorted(STEP_BLOCKERS)))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="record and say nothing, for use inside another step")
    ap.add_argument("--may-edit", metavar="PATH", default=None,
                    help="whether a sandbox file may be repaired, and on what terms")
    args = ap.parse_args()

    root = st.task_root(args.task)
    home = Path(args.home).resolve() if args.home else st.FLC_HOME

    if args.may_edit:
        answer = may_edit(args.may_edit, home, root)
        if args.json:
            print(json.dumps(answer, indent=2))
        else:
            print(f"  {answer['verdict']}: {answer['path']} -- {answer['why']}")
            if answer["then"]:
                print(f"  then: {answer['then']}")
        return 0 if answer["verdict"] != "no" else 1
    report, stops = check(root, home, args.step)

    # Read back rather than reprinted from the scan. A file put back is not a
    # tree that was never modified, and the difference is what the delivery
    # record has to carry.
    entry = report.get("recorded") or {}
    history = entry.get("findings", report["findings"])
    outstanding = [f for f in history if f["state"] != "restored"]

    if args.json:
        print(json.dumps({**report, "blocked": stops}, indent=2))
    elif not args.quiet:
        if not report["measured"]:
            # The same tri-state as written_files() and model_check.py. An
            # older seed carries no manifest, and reporting that as tampering
            # would be a confident false accusation.
            print(f"  UNMEASURED -- {report['why']}")
            print("  Nothing is blocked by this. It is our check that could "
                  "not be taken,")
            print("  not a finding about your task.")
        elif not history:
            print("  PASS -- every shipped file is the one the seed put there.")
        else:
            print(f"  {'MODIFIED' if outstanding else 'RESTORED'}\n")
            for f in history:
                print(f"  [{f['tier']}] {describe(f)}")
            print()
            kinds = sorted({f["voids"] for f in history if f["voids"]})
            if kinds:
                print("  What has to be done again: "
                      + "; ".join(EVIDENCE_STEP[k] for k in kinds))
            if outstanding:
                print("  Put the originals back with /flc-restore-tools.")
            else:
                print("  Every file is back as the seed shipped it. This is "
                      "recorded and travels")
                print("  with the delivery, because a score taken on a changed "
                      "copy is still that")
                print("  copy's -- putting the file back does not un-produce it.")

    if stops and not args.json:
        print()
        print(refusal(stops))
    return 1 if stops else 0


if __name__ == "__main__":
    sys.exit(main())
