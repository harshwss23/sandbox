#!/usr/bin/env python3
"""Step 6 gate: do the unit tests run, and do they actually test anything?

There is no gold solution to check the tests against -- writing one is not part
of a contributor's job here -- so this cannot confirm that a passing test means
a correct answer. What it can confirm is the other half, which is where nearly
all broken verifiers land:

  - verifier.py imports, and every test_ function runs without crashing.
    A typo or a missing import makes a test that can never pass, and the run it
    ruins is a bad place to find that out.

  - the tests fail on an unsolved workspace. They are run against the task's own
    inputs with nothing solved, in the real task image. A check that passes
    there is measuring something the model never had to do, and would pass for a
    model that did nothing at all.

  - the tests are the contributor's and not the template's worked examples.
    Those examples pass both checks above -- they run, and they fail on an
    unsolved workspace, since the task they describe is imaginary. A Harbor
    probe run shipped them by accident and lost 60% of its reward to assertions
    about a file its prompt never mentioned.

  - no test is parametrized. One test is one named thing carrying one weight,
    and a parametrized one is several under names that move whenever the list
    of cases is edited.

It also refreshes tests/test_weights.md against the suite and compiles it, so
a new test always has a weight and the weights always name tests that exist.

Usage:
    check_tests.py [--task PATH] [--json] [--keep-image] [--weights-only]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402
import test_weights as tw  # noqa: E402

BIN = Path(__file__).resolve().parent
MARKER = "---FLC-RESULTS---"

# The worked examples template_task/tests/verifier.py ships with, and the files
# of the imaginary task they are written against. Both halves are required to
# call one a leftover: the names alone would fail a contributor who happens to
# want a test called test_prediction_file_exists, which is an ordinary enough
# thing to want.
TEMPLATE_CHECKS = frozenset({
    "test_prediction_file_exists",
    "test_evidence_has_required_fields",
    "test_it_consulted_the_manifest",
    "test_reported_median_matches_the_data",
})
TEMPLATE_FIXTURES = ("analysis/prediction.txt", "analysis/evidence.json",
                     "data/metadata.csv", "data/ko_counts.json")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def template_examples(verifier: Path) -> list[str]:
    """Which of the template's examples are still here, unadapted.

    A check counts as a leftover when it carries a template name *and* still
    reads one of the template's files. Renaming it, or pointing it at the
    contributor's own material, clears it -- either one means somebody looked
    at it, which is the whole thing being asked for.

    An unreadable or unparseable file is nobody's leftover; the syntax check
    reports that, and reporting it twice would only obscure it.
    """
    try:
        source = verifier.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []
    found = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in TEMPLATE_CHECKS:
            continue
        body = ast.get_source_segment(source, node) or ""
        if any(fixture in body for fixture in TEMPLATE_FIXTURES):
            found.append(node.name)
    return found


def untouched(verifier: Path) -> bool:
    """Is this still the template, byte for byte?

    The name check above asks whether the examples were adapted, and clears as
    soon as one of them is renamed. This asks the blunter question and catches
    a suite nobody opened at all, which the template was written to pass.
    """
    template = BIN.parent / "template_task" / "tests" / "verifier.py"
    return (template.exists() and verifier.exists()
            and st.sha256_file(template) == st.sha256_file(verifier))


# A path in a test either names something the task has or names nothing. There
# is no third case, and no judgement involved, which is what makes this worth
# blocking on where "is this a good test" would not be.
_PATH_LITERAL = re.compile(r"^[\w./-]+\.[A-Za-z0-9]{1,8}$")


def unrelated_paths(verifier: Path, root: Path) -> list[str]:
    """File paths a test reads that this task has never heard of.

    Checked against three places, and a literal has to miss all of them: the
    workspace as it stands, the manifest of what was uploaded, and the prompt
    -- which covers a test asserting the model *creates* a file, since a task
    that wants one has to have asked for it.

    Directories and bare names are ignored. This looks for the case where a
    suite was written against a different task's material, and that always
    shows up as a path with an extension.
    """
    try:
        tree = ast.parse(verifier.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []

    known = set(st.workspace_files(root))
    manifest = root / "tests" / "inputs_manifest.json"
    if manifest.exists():
        try:
            known |= set(json.loads(manifest.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    prompt = ""
    for name in ("prompt.md", "instruction.md"):
        path = root / name
        if path.exists():
            prompt += path.read_text(errors="replace")

    unknown = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        literal = node.value.strip().lstrip("./")
        if not literal or not _PATH_LITERAL.match(literal):
            continue
        if literal in known or literal in prompt:
            continue
        if any(k == literal or k.endswith("/" + literal) for k in known):
            continue
        if literal not in unknown:
            unknown.append(literal)
    return unknown


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--keep-image", action="store_true")
    ap.add_argument("--weights-only", action="store_true",
                    help="refresh and check the weights without running anything")
    args = ap.parse_args()

    root = st.task_root(args.task)
    state = st.load(root)
    findings: list[dict] = []

    def add(level: str, title: str, detail: str = "", fix: str = "") -> None:
        findings.append({"level": level, "title": title, "detail": detail, "fix": fix})

    set_aside = root / "tests" / "verifier.py.skipped"

    if state.get("unit_tests") == "skipped":
        print("This task is graded by rubrics alone -- nothing to check.")
        if set_aside.exists():
            print("Its suite is set aside as tests/verifier.py.skipped, where nothing "
                  "runs it.")
        print("Run /flc-enable-tests if you want to write unit tests after all.")
        return 0

    verifier = root / "tests" / "verifier.py"
    if not verifier.exists():
        add("FAIL", "There is no tests/verifier.py",
            "A suite set aside by /flc-skip-tests is at tests/verifier.py.skipped."
            if set_aside.exists() else "",
            "Run /flc-enable-tests to bring it back."
            if set_aside.exists() else
            "Write your checks there, or run /flc-skip-tests to grade by rubrics alone.")

    # A syntax error is worth catching before spending a build on it.
    if verifier.exists():
        syntax = run([sys.executable, "-m", "py_compile", str(verifier)])
        if syntax.returncode != 0:
            add("FAIL", "verifier.py has a syntax error",
                syntax.stderr.strip()[:600],
                "Fix the line named above.")

        for item in tw.parametrized(verifier):
            add("FAIL", f"{item['name']} is a parametrized test",
                f"It is generated by {item['detail']}, so it is not one test but "
                "several, under names that change whenever you edit the list of "
                "cases. A weight is set per test name, so those weights could "
                "never stay in step with the suite.",
                "Write the cases out as separate tests, each named for what it "
                "checks. If that feels repetitive, they are usually several "
                "different facts sharing one name.")

        if untouched(verifier):
            add("FAIL", "tests/verifier.py has not been touched",
                "It is still the template, byte for byte. Every check in it is "
                "about an example task, so they would run against your material "
                "and fail, and the model would lose those points for work it was "
                "never asked to do.",
                "Open tests/verifier.py and write checks about your own task, or "
                "run /flc-skip-tests to grade by rubrics alone.")
        else:
            leftovers = template_examples(verifier)
            if leftovers:
                add("FAIL", "These are still the template's example tests",
                    ", ".join(leftovers) + ".\nThey check a task nobody wrote: a "
                    "prediction file, an evidence file and a manifest that belong "
                    "to the example, not to your material. They would run against "
                    "your task and fail, and the model would lose those points for "
                    "work it was never asked to do.",
                    "Delete them and write your own, or run /flc-skip-tests to "
                    "grade by rubrics alone.")

            stray = unrelated_paths(verifier, root)
            if stray:
                add("FAIL", "These tests read files this task does not have",
                    ", ".join(stray[:6]) + ".\nNone of them is in "
                    "environment/workspace/, and none is named in your prompt. A "
                    "check that reads a file nobody has can only fail.",
                    "Point each check at your own material, or -- if the model is "
                    "meant to create the file -- say so in prompt.md, since it "
                    "cannot produce something it was never asked for.")

    # Free, and it has to happen before anything is scored: a test with no
    # weight would otherwise be worth the default without anyone deciding that.
    # Skipped when a check above already failed, so a suite that is about to be
    # rewritten does not have its weights churned first.
    if not any(f["level"] == "FAIL" for f in findings) and verifier.exists():
        weights = tw.refresh(root)
        for problem in weights["problems"]:
            add("FAIL", "tests/test_weights.md has a line that cannot be read",
                problem,
                "Each line is `- [5] test_name`, and the weights are [5], [3] "
                "and [1].")
        if not weights["problems"]:
            compiled = tw.build(root)
            if weights["added"]:
                add("PASS", f"{len(weights['added'])} test(s) added to "
                            "tests/test_weights.md",
                    ", ".join(weights["added"]) + f".\nEach is worth "
                    f"[{tw.DEFAULT}] until you say otherwise.",
                    "Open tests/test_weights.md and set the weight of anything "
                    "the default does not fit.")
            if weights["stale"]:
                add("PASS", "Dropped weights for tests that no longer exist",
                    ", ".join(weights["stale"]) + ".")
            add("PASS", f"{len(compiled['weights'])} tests worth "
                        f"{compiled['total']} points",
                "Those points count towards the model's score as the rubric "
                "criteria do.")

    if any(f["level"] == "FAIL" for f in findings):
        return report(findings, None, args.json, root)

    if args.weights_only:
        return report(findings, None, args.json, root, mark_done=False)

    print("Building the task image (a few minutes the first time)...")
    build = run(["bash", str(BIN / "build_image.sh"), str(root), "--quiet"])
    if build.returncode != 0:
        add("FAIL", "The task image did not build",
            build.stderr.strip()[-1500:],
            "If a package is missing, run /flc-add-package <name>.")
        return report(findings, None, args.json, root)
    tag = build.stdout.strip().splitlines()[-1]

    print("Running your tests against the unsolved task...")
    # The image already carries the inputs at /workspace, so this is exactly the
    # state the model starts in: nothing solved, nothing written.
    proc = run([
        "docker", "run", "--rm",
        "-v", f"{root / 'tests'}:/tests:ro",
        "-e", "FLC_UNIT_RESULTS=/tmp/unit_test_results.json",
        "-e", "FLC_TEST_WEIGHTS=/tests/test_weights.json",
        tag,
        "bash", "-lc",
        f"python3 /tests/run_verifier.py; echo '{MARKER}'; cat /tmp/unit_test_results.json",
    ])

    # The marker separates the human-readable log from the machine-readable
    # results, so neither has to be parsed out of the other.
    results = None
    if MARKER in proc.stdout:
        try:
            results = json.loads(proc.stdout.split(MARKER, 1)[1])
        except json.JSONDecodeError:
            results = None

    if results is None:
        add("FAIL", "The tests could not be run at all",
            (proc.stdout + proc.stderr).strip()[-1500:],
            "The output above is what the container printed.")
        return report(findings, None, args.json, root)

    if results.get("status") == "error":
        add("FAIL", "The tests could not be run",
            (results.get("reason", "") + "\n"
             + results.get("detail", ""))[-1200:],
            "Usually a typo in an import, or a package the image does not have "
            "(add it with /flc-add-package <name>).")
        return report(findings, results, args.json, root)

    if results.get("status") == "skipped":
        add("FAIL", "verifier.py defines no tests",
            "No functions whose name starts with test_.",
            "Name each test test_something. Or run /flc-skip-tests to grade by "
            "rubrics alone.")
        return report(findings, results, args.json, root)

    tests = results.get("tests", [])
    crashed = [t for t in tests if t["status"] == "failed" and t.get("crash")]
    passed_unsolved = [t for t in tests if t["status"] == "passed"]

    for t in crashed:
        add("FAIL", f"{t['name']} crashes instead of failing",
            (t.get("message") or "").strip()[-800:],
            "A test that raises can never pass. Use the flc_testkit helpers to "
            "read files -- they give a clear message when a file is missing.")

    if len(passed_unsolved) == len(tests) and tests:
        add("FAIL", "Every test passes before the task has been solved",
            f"all {len(tests)} of them.",
            "These tests would pass for a model that did nothing. Check something "
            "the model has to produce.")
    else:
        for t in passed_unsolved:
            add("WARN", f"{t['name']} already passes on the unsolved task", "",
                "It is not measuring the model's work. Intentional only if it is "
                "guarding an input file.")

    real_failures = [t for t in tests if t["status"] == "failed" and t not in crashed]
    if real_failures:
        add("PASS", f"{len(real_failures)} of {len(tests)} tests fail on the unsolved task",
            "Which is what should happen -- they are waiting on the model's work.")

    if not args.keep_image:
        run(["docker", "image", "rm", "-f", tag])

    return report(findings, results, args.json, root)


def report(findings: list[dict], results, as_json: bool, root: Path,
           mark_done: bool = True) -> int:
    verdict = "FAIL" if any(f["level"] == "FAIL" for f in findings) else "PASS"
    if as_json:
        print(json.dumps({"verdict": verdict, "findings": findings, "results": results}, indent=2))
        return 0 if verdict == "PASS" else 1

    print()
    for f in findings:
        print(f"  [{f['level']}] {f['title']}")
        if f["detail"]:
            for line in f["detail"].splitlines():
                print(f"         {line}")
        if f["fix"]:
            print(f"         -> {f['fix']}")
    # The suite and the criteria are counted together against one floor, so
    # this says where the task stands overall rather than only how the tests
    # did -- a contributor writing tests should not have to go elsewhere to
    # find out whether they are enough.
    counted = st.check_count(root)
    print(f"  checks:   {counted['total']} of {counted['floor']} needed"
          f"  ({counted['rubrics']} criteria + {counted['tests']} unit tests)")
    if not counted["enough"]:
        print(f"            grading refuses below {counted['floor']}; add "
              "checks in either place.")
    print()
    print(f"  {verdict}")
    if verdict == "PASS" and mark_done:
        state = st.load(root)
        state["unit_tests"] = "written"
        st.save(root, state)
        st.mark_done(root, "check_tests")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
