#!/usr/bin/env python3
"""Run a task's verifier.py under pytest and record what passed.

Every function in verifier.py whose name starts with `test_` is a test, and a
raised exception is a failure. Each test carries the weight given to it in
tests/test_weights.json; a test that file does not mention is worth the default.

Writes /logs/verifier/unit_test_results.json, and copies the weights in beside
it so the score can be checked against what produced it. Always exits 0;
test.sh decides the overall outcome.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

VERIFIER_PATH = Path(os.environ.get("FLC_VERIFIER", "/tests/verifier.py"))
RESULTS_PATH = Path(os.environ.get("FLC_UNIT_RESULTS", "/logs/verifier/unit_test_results.json"))
WEIGHTS_PATH = Path(os.environ.get("FLC_TEST_WEIGHTS", str(VERIFIER_PATH.parent / "test_weights.json")))

DEFAULT_WEIGHT = 3

# pytest's own exit codes. 5 is "nothing was collected", which is the
# rubric-only task and not a failure; the rest are the suite not running.
PYTEST_OK, PYTEST_FAILED, PYTEST_INTERRUPTED = 0, 1, 2
PYTEST_INTERNAL, PYTEST_USAGE, PYTEST_NO_TESTS = 3, 4, 5


def _write(payload: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def _load_weights() -> dict:
    """{test name: weight}, or {} when there is no weights file to read."""
    try:
        data = json.loads(WEIGHTS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    weights = data.get("weights") if isinstance(data, dict) else None
    if not isinstance(weights, dict):
        return {}
    return {str(k): int(v) for k, v in weights.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _publish_weights() -> None:
    """Copy the weights in beside the results, where the score is read."""
    if not WEIGHTS_PATH.exists():
        return
    try:
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEIGHTS_PATH, RESULTS_PATH.parent / "test_weights.json")
    except OSError:
        pass


def _docstrings() -> dict:
    """{test name: first line of its docstring}, read straight off the source."""
    try:
        tree = ast.parse(VERIFIER_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return {}
    found = {}

    def visit(nodes) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    doc = (ast.get_docstring(node) or "").strip().splitlines()
                    found[node.name] = doc[0] if doc else ""
            elif isinstance(node, ast.ClassDef):
                visit(node.body)

    visit(tree.body)
    return found


def _legacy_checks() -> list:
    """Names of `check_` functions, the convention pytest does not collect."""
    try:
        tree = ast.parse(VERIFIER_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    return [n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("check_")]


def _is_assertion(message: str) -> bool:
    """Did this test fail an assert, as against raising something else?"""
    first = (message or "").strip().splitlines()
    if not first:
        return False
    head = first[0].strip()
    return head.startswith("AssertionError") or head.startswith("assert")


def _parse(xml_path: Path, weights: dict, docs: dict) -> list:
    """The junit XML pytest wrote, as our own per-test records."""
    tests = []
    root = ET.parse(str(xml_path)).getroot()
    suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
    for suite in suites:
        for case in suite.iter("testcase"):
            name = case.get("name") or "?"
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            crash = False
            if error is not None:
                status = "failed"
                message = (error.get("message") or "") + "\n" + (error.text or "")
                crash = True
            elif failure is not None:
                status = "failed"
                message = (failure.get("message") or "") + "\n" + (failure.text or "")
                crash = not _is_assertion(failure.get("message") or failure.text or "")
            elif skipped is not None:
                status = "skipped"
                message = skipped.get("message") or ""
            else:
                status, message = "passed", ""
            tests.append({
                "name": name,
                "status": status,
                "message": message.strip(),
                "description": docs.get(name, ""),
                "weight": int(weights.get(name, DEFAULT_WEIGHT)),
                "crash": crash,
            })
    tests.sort(key=lambda t: t["name"])
    return tests


def main() -> int:
    # No file, or a file with no tests in it, is a task graded by rubrics
    # alone, recorded as skipped rather than as a failure.
    if not VERIFIER_PATH.exists():
        print("  no verifier.py -- this task is graded by rubrics alone")
        _write({"status": "skipped", "reason": "no verifier.py", "total": 0,
                "passed": 0, "failed": 0, "tests": []})
        return 0

    _publish_weights()

    # No pytest is the suite not running, recorded as an error rather than
    # as a task with no suite.
    if importlib.util.find_spec("pytest") is None:
        print("  pytest is not installed -- the unit tests could not be run")
        _write({"status": "error", "reason": "pytest is not installed in this image",
                "total": 0, "passed": 0, "failed": 0, "tests": []})
        return 0

    weights, docs = _load_weights(), _docstrings()

    tmp = Path(tempfile.mkdtemp(prefix="flc-pytest-"))
    xml_path = tmp / "results.xml"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    # The verifier's own directory has to be importable so `import flc_testkit`
    # resolves, and is prepended rather than replacing anything already there.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(VERIFIER_PATH.parent)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(VERIFIER_PATH),
         "--junitxml", str(xml_path),
         "-p", "no:cacheprovider",
         "-o", "addopts=",
         "--rootdir", str(tmp),
         "-q", "--no-header", "-rN"],
        capture_output=True, text=True, env=env, cwd=str(tmp), check=False)

    output = (proc.stdout or "") + (proc.stderr or "")

    if proc.returncode == PYTEST_NO_TESTS:
        legacy = _legacy_checks()
        if legacy:
            # Functions named check_, which pytest does not collect: an error
            # rather than a task with no suite.
            print("  verifier.py defines check_ functions, which pytest does not run")
            _write({"status": "error",
                    "reason": "verifier.py uses the old check_ naming; pytest collects "
                              "only functions named test_",
                    "detail": ", ".join(sorted(legacy)),
                    "total": 0, "passed": 0, "failed": 0, "tests": []})
            return 0
        print("  verifier.py defines no test_ functions -- graded by rubrics alone")
        _write({"status": "skipped", "reason": "no test_ functions", "total": 0,
                "passed": 0, "failed": 0, "tests": []})
        return 0

    if proc.returncode not in (PYTEST_OK, PYTEST_FAILED) or not xml_path.exists():
        # Interrupted, an internal error, a bad invocation, or a collection
        # error: the suite did not run, which is not a score.
        print("  verifier.py could not be run by pytest:\n" + output[-1500:])
        _write({"status": "error",
                "reason": f"pytest exited {proc.returncode} without running the suite",
                "detail": output[-4000:], "total": 0, "passed": 0, "failed": 0,
                "tests": []})
        return 0

    try:
        tests = _parse(xml_path, weights, docs)
    except ET.ParseError as exc:
        print(f"  pytest's report could not be read: {exc}")
        _write({"status": "error", "reason": "pytest wrote an unreadable report",
                "detail": str(exc), "total": 0, "passed": 0, "failed": 0, "tests": []})
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not tests:
        print("  verifier.py defines no test_ functions -- graded by rubrics alone")
        _write({"status": "skipped", "reason": "no test_ functions", "total": 0,
                "passed": 0, "failed": 0, "tests": []})
        return 0

    for t in tests:
        if t["status"] == "passed":
            print(f"  PASS  [{t['weight']}]  {t['name']}")
        elif t["status"] == "skipped":
            print(f"  SKIP  [{t['weight']}]  {t['name']}")
        else:
            head = (t["message"].splitlines() or [""])[0]
            print(f"  FAIL  [{t['weight']}]  {t['name']}: {head}")

    passed = sum(1 for t in tests if t["status"] == "passed")
    points = sum(t["weight"] for t in tests if t["status"] == "passed")
    available = sum(t["weight"] for t in tests)
    _write({
        "status": "ran",
        "total": len(tests),
        "passed": passed,
        "failed": len(tests) - passed,
        "points": points,
        "available": available,
        "weights_source": "test_weights.json" if weights else "default",
        "tests": tests,
    })
    print(f"\n  unit tests: {passed}/{len(tests)} passed, "
          f"{points}/{available} points")
    return 0


if __name__ == "__main__":
    sys.exit(main())
