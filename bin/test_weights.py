#!/usr/bin/env python3
"""What each unit test is worth.

tests/test_weights.md is a generated list with one line per test, which the
contributor edits by changing a number. This discovers the tests in
tests/verifier.py, refreshes that list without disturbing weights already set,
and compiles it to tests/test_weights.json, which is what run_verifier.py reads.

Parametrized tests are refused. One test is one named thing carrying one
weight, and a parametrized one is several under names that move whenever the
list of cases is edited -- so a weights file could never stay in step with it.

Usage:
    test_weights.py [--task PATH] [--json] [--check]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402

WEIGHTS = st.TEST_WEIGHTS
DEFAULT = st.DEFAULT_TEST_WEIGHT

ENTRY_RE = re.compile(r"^-\s*\[\s*(-?\d+)\s*\]\s*([A-Za-z_]\w*)\s*(?:#.*)?$")

HEADER = """<!--
What each of your unit tests is worth. Generated from tests/verifier.py --
/flc-check-tests adds a line for every new test at [3], and never changes a
number you have set.

You edit the numbers. Nothing else on these lines is yours: the name comes from
the test and the note after the # is its first docstring line, both rewritten
each time this is refreshed.

    5   the test that would let a wrong answer through unnoticed
        a value that has to be right, a file the model must not have altered,
        something private or excluded that must not appear

    3   the test that says the work was done
        a file exists, has the right structure, the right keys, the right
        number of rows, the right order

    1   the test that tidies
        a filename spelling, a header or column format, a file that parses, a
        size or length bound, no leftover scratch files

Those three are the only weights. Read what the test asserts rather than what
it is called, weight anything your prompt asked for explicitly at 5, and when
you cannot decide between two, take the higher.

A test's points count towards the model's score exactly as a rubric criterion's
do, so this is the same scale as tests/rubrics.md. Four tests at 3 outweigh one
at 5: write the checks that matter rather than a long tail of easy ones.
-->
"""


def discover(verifier: Path) -> list:
    """Every test in the file, in source order.

    Functions named test_* at the top level and inside Test* classes, which is
    what pytest collects.
    """
    try:
        tree = ast.parse(verifier.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    found = []

    def visit(nodes) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    doc = (ast.get_docstring(node) or "").strip().splitlines()
                    found.append({"name": node.name,
                                  "doc": doc[0].strip() if doc else "",
                                  "line": node.lineno})
            elif isinstance(node, ast.ClassDef):
                visit(node.body)

    visit(tree.body)
    found.sort(key=lambda e: e["line"])
    return found


def _decorator_name(node: ast.AST) -> str:
    """The dotted name of a decorator, without its call arguments."""
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def parametrized(verifier: Path) -> list:
    """Every parametrized test in the file, and how it is parametrized.

    The three ways pytest generates tests from one function. Each is an
    unambiguous pytest API, so this cannot report something that is not one.
    """
    try:
        tree = ast.parse(verifier.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "pytest_generate_tests":
                found.append({"name": node.name, "kind": "pytest_generate_tests",
                              "detail": "generates tests from a hook"})
                continue
            for dec in node.decorator_list:
                name = _decorator_name(dec)
                if name.split(".")[-1] == "parametrize":
                    found.append({"name": node.name, "kind": "parametrize",
                                  "detail": f"@{name}"})
                elif (name.split(".")[-1] == "fixture" and isinstance(dec, ast.Call)
                        and any(kw.arg == "params" for kw in dec.keywords)):
                    found.append({"name": node.name, "kind": "fixture_params",
                                  "detail": f"@{name}(params=...)"})
    found.sort(key=lambda e: e["name"])
    return found


def parse(text: str) -> tuple:
    """({name: weight}, [problems]) read off the markdown."""
    weights, problems = {}, []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("- ["):
            continue
        match = ENTRY_RE.match(line)
        if not match:
            problems.append(f"line {number}: cannot read {line!r}")
            continue
        value, name = int(match.group(1)), match.group(2)
        if value not in WEIGHTS:
            problems.append(
                f"line {number}: {name} is [{value}], and the weights are "
                + ", ".join(f"[{w}]" for w in WEIGHTS))
            continue
        if name in weights:
            problems.append(f"line {number}: {name} is listed twice")
            continue
        weights[name] = value
    return weights, problems


def _header_of(text: str) -> str:
    """The instruction block at the top, kept as the contributor found it."""
    end = text.find("-->")
    return text[:end + 3] + "\n" if text.lstrip().startswith("<!--") and end != -1 else HEADER


def render(header: str, entries: list, weights: dict) -> str:
    lines = [header.rstrip("\n"), ""]
    for entry in entries:
        weight = weights.get(entry["name"], DEFAULT)
        line = f"- [{weight}] {entry['name']}"
        if entry["doc"]:
            line += f"  # {entry['doc']}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def refresh(root: Path) -> dict:
    """Bring tests/test_weights.md into step with tests/verifier.py.

    Weights already set are kept, a test with no line gets one at the default,
    and a line whose test is gone is dropped and reported.
    """
    verifier = root / "tests" / "verifier.py"
    path = root / "tests" / "test_weights.md"
    entries = discover(verifier)

    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    weights, problems = parse(existing)

    names = {e["name"] for e in entries}
    added = [e["name"] for e in entries if e["name"] not in weights]
    stale = sorted(n for n in weights if n not in names)

    text = render(_header_of(existing) if existing else HEADER, entries, weights)
    changed = text != existing
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    return {"entries": entries, "added": added, "stale": stale,
            "problems": problems, "changed": changed, "path": path}


def intended(root: Path) -> dict:
    """{name: weight} the suite and the markdown currently imply.

    None when the task has no tests, which is not the same as a suite whose
    tests are all worth nothing.
    """
    names = [e["name"] for e in discover(root / "tests" / "verifier.py")]
    if not names:
        return None
    md = root / "tests" / "test_weights.md"
    weights, _ = parse(md.read_text(encoding="utf-8", errors="replace")) \
        if md.exists() else ({}, [])
    return {n: weights.get(n, DEFAULT) for n in names}


def compiled(root: Path) -> dict:
    """{name: weight} as tests/test_weights.json records it, or None."""
    try:
        data = json.loads((root / "tests" / "test_weights.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    weights = data.get("weights")
    if not isinstance(weights, dict):
        return None
    return {str(k): int(v) for k, v in weights.items()}


def build(root: Path) -> dict:
    """Compile tests/test_weights.md to tests/test_weights.json."""
    md = root / "tests" / "test_weights.md"
    out = root / "tests" / "test_weights.json"
    _, problems = parse(md.read_text(encoding="utf-8", errors="replace")) \
        if md.exists() else ({}, [])
    weights = intended(root)
    if weights:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"default": DEFAULT, "total": sum(weights.values()), "weights": weights},
            indent=2, sort_keys=True) + "\n")
    else:
        weights = {}
        out.unlink(missing_ok=True)
    return {"weights": weights, "total": sum(weights.values()), "problems": problems,
            "path": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="report without rewriting anything")
    args = ap.parse_args()

    root = st.task_root(args.task)
    verifier = root / "tests" / "verifier.py"
    if not verifier.exists():
        print("No tests/verifier.py -- this task is graded by rubrics alone.")
        return 0

    banned = parametrized(verifier)
    if args.check:
        state = refresh_preview(root)
    else:
        state = refresh(root)
    compiled = build(root) if not args.check else {"weights": {}, "total": 0,
                                                   "problems": []}

    problems = state["problems"] + banned
    if args.json:
        print(json.dumps({
            "tests": [e["name"] for e in state["entries"]],
            "added": state["added"], "stale": state["stale"],
            "problems": state["problems"], "parametrized": banned,
            "weights": compiled["weights"], "total": compiled["total"],
        }, indent=2))
        return 1 if problems else 0

    for entry in state["entries"]:
        weight = compiled["weights"].get(entry["name"], DEFAULT)
        print(f"  [{weight}]  {entry['name']}")
    if state["added"]:
        print(f"\n  added at [{DEFAULT}]: " + ", ".join(state["added"]))
    if state["stale"]:
        print("\n  dropped, no longer in verifier.py: " + ", ".join(state["stale"]))
    for problem in state["problems"]:
        print(f"\n  {problem}")
    for item in banned:
        print(f"\n  {item['name']} is parametrized ({item['detail']}) -- not allowed")
    if state["entries"]:
        print(f"\n  {len(state['entries'])} tests, {compiled['total']} points")
    return 1 if problems else 0


def refresh_preview(root: Path) -> dict:
    """What refresh() would do, without writing anything."""
    verifier = root / "tests" / "verifier.py"
    path = root / "tests" / "test_weights.md"
    entries = discover(verifier)
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    weights, problems = parse(existing)
    names = {e["name"] for e in entries}
    return {"entries": entries,
            "added": [e["name"] for e in entries if e["name"] not in weights],
            "stale": sorted(n for n in weights if n not in names),
            "problems": problems, "changed": False, "path": path}


if __name__ == "__main__":
    sys.exit(main())
