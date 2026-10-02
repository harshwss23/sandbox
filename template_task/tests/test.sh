#!/usr/bin/env bash
set -uo pipefail

LOGS="${FLC_LOGS:-/logs/verifier}"
TESTS="${FLC_TESTS:-/tests}"
mkdir -p "$LOGS"

export FLC_LOGS TESTS
export FLC_EVAL_RESULTS="$LOGS/evaluation_results.json"
export FLC_VERIFIER="$TESTS/verifier.py"
export FLC_UNIT_RESULTS="$LOGS/unit_test_results.json"

rm -f "$LOGS/unit_test_results.json" "$LOGS/evaluation_results.json"

# Written failing before any grading runs, so a grader that does not finish
# leaves a scored-zero run rather than no result at all.
cat > "$LOGS/reward.json" <<'JSON'
{
  "rubrics": 0.0,
  "reward": 0.0
}
JSON

cat > "$LOGS/ctrf.json" <<'JSON'
{
  "results": {
    "tool": { "name": "flc-verifier" },
    "summary": { "tests": 0, "passed": 0, "failed": 0, "pending": 0, "skipped": 0, "other": 1 },
    "tests": [
      { "name": "grading", "status": "other", "duration": 0,
        "message": "the grader did not produce a report" }
    ]
  }
}
JSON

cat > "$LOGS/grading_summary.json" <<'JSON'
{ "status": "incomplete", "reason": "the grader did not finish" }
JSON

echo "=============================================================="
echo " FLC verifier"
echo "=============================================================="
echo

echo "-- produced files --------------------------------------------"
python3 "$TESTS/snapshot_workspace.py"
echo

# Deferral needs the exact string 1, so an unexpanded variable grades as normal.
if [ "${FLC_GRADE_NOW:-}" != "1" ] && [ "${FLC_DEFER_GRADING:-}" = "1" ]; then
    cat > "$LOGS/grading_summary.json" <<'JSON'
{
  "status": "deferred",
  "reason": "an authoring run: the criteria are written from this run, so grading happens later, at /flc-grade"
}
JSON
    echo "  Grading deferred -- this is an authoring run."
    echo
    echo "  The non-hallucination criteria come from what this run claimed, so"
    echo "  there is nothing worth grading against yet. Write them, then grade:"
    echo
    echo "    /flc-rubrics    then    /flc-grade"
    echo
    echo "  The zeroed reward.json beside this note is the crash-safe default,"
    echo "  not a score. Nothing was measured."
    echo "=============================================================="
    exit 0
fi

echo "-- rubrics ---------------------------------------------------"
if command -v uv >/dev/null 2>&1; then
    uv run "$TESTS/judge.py"
else
    PYTHON="$(command -v python3)"
    "$PYTHON" -c "import openai" 2>/dev/null \
      || "$PYTHON" -m pip install openai -q --break-system-packages --index-url https://pypi.org/simple/
    "$PYTHON" "$TESTS/judge.py"
fi
judge_status=$?
echo

echo "-- unit tests ------------------------------------------------"
python3 "$TESTS/run_verifier.py"
echo

echo "-- result ----------------------------------------------------"
python3 - "$LOGS" "$judge_status" <<'PY'
import json, os, sys

logs, judge_status = sys.argv[1], int(sys.argv[2])


def load(name, default):
    try:
        with open(os.path.join(logs, name)) as f:
            return json.load(f)
    except Exception:
        return default


rubrics = load("evaluation_results.json", None)
units = load("unit_test_results.json", {"status": "skipped", "total": 0, "passed": 0, "tests": []})

reward = {}
ctrf_tests = []
summary = {"unit_tests": units.get("status", "skipped")}
rubric_max = rubric_score = 0

if judge_status == 3:
    print("  the judge endpoint could not be reached -- nothing was graded")
    print("  this is a verifier network fault, not a result about the model")
    summary["rubrics"] = "unreachable"
    summary["status"] = "error"
    summary["reason"] = "the grader could not reach the judge endpoint"
    reward = {"rubrics": 0.0, "reward": 0.0}
    ctrf_tests.append({"name": "rubrics", "status": "other", "duration": 0,
                       "message": "the judge endpoint could not be reached"})
elif rubrics is None:
    print("  the rubric judge produced no results -- scoring 0")
    summary["rubrics"] = "error"
    summary["status"] = "incomplete"
    reward = {"rubrics": 0.0, "reward": 0.0}
    ctrf_tests.append({"name": "rubrics", "status": "other", "duration": 0,
                       "message": f"judge exited {judge_status} without writing results"})
else:
    summary["rubrics"] = "graded"
    block = rubrics.get("overall") or {}
    rubric_max = block.get("max_reward", 0) or 0
    rubric_score = block.get("agent_score", 0) or 0
    reward["rubrics"] = round(block.get("rate", 0.0), 4)
    if rubrics.get("judge_model"):
        summary["judge_model"] = rubrics["judge_model"]
    summary["rubrics_detail"] = {
        "passed": block.get("passed", 0),
        "scored": block.get("scored", 0),
        "unscored": block.get("unscored", 0),
        "refused": block.get("refused", 0),
        "coverage_lost": block.get("coverage_lost", 0.0),
        "max_reward": block.get("max_reward", 0),
        "agent_score": block.get("agent_score", 0),
        "rate": round(block.get("rate", 0.0), 4),
        "count_rate": round(block.get("count_rate", 0.0), 4),
    }
    if block.get("refused"):
        print(f"  the judge declined to grade {block['refused']} criterion(s), "
              f"{block.get('coverage_lost', 0.0):.0%} of the rubric by weight")
        print("  those criteria were not scored, and the reward beside this is "
              "over the rest")
    for row in rubrics.get("rubric_scores", []):
        score = row.get("score") or {}
        value = str(score.get("score"))
        # A negative criterion states a mistake, so on those the judge saying
        # yes is the criterion failing.
        if value in ("0", "1"):
            said_true = value == "1"
            earned = said_true if int(row.get("weight", 5)) >= 0 else not said_true
            status = "passed" if earned else "failed"
        else:
            status = "other"
        ctrf_tests.append({
            "name": row.get("title", row.get("id", "rubric")),
            "status": status,
            "duration": 0,
            "message": (score.get("justification") or "")[:2000],
        })

# Each unit test is worth the weight it was given and earns it by passing, on
# the same total as the rubric points. A test with no recorded weight is worth
# DEFAULT_TEST_WEIGHT. A task with no suite carries no unit_tests key.
DEFAULT_TEST_WEIGHT = 3


def test_weight(t):
    value = t.get("weight")
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else DEFAULT_TEST_WEIGHT


graded = summary.get("rubrics") == "graded"
unit_status = units.get("status", "skipped")

if unit_status == "error":
    print("  verifier.py could not be run -- nothing was scored")
    reward = {"rubrics": reward.get("rubrics", 0.0), "unit_tests": 0.0, "reward": 0.0}
    summary["unit_tests"] = "error"
    summary["status"] = "error"
    summary["reason"] = units.get("reason", "verifier.py could not be run")
    ctrf_tests.append({"name": "verifier.py", "status": "other", "duration": 0,
                       "message": units.get("reason", "verifier.py could not be run")})
elif unit_status == "ran":
    rows = units.get("tests") or []
    total, passed = units.get("total", 0), units.get("passed", 0)
    if rows:
        unit_max = sum(test_weight(t) for t in rows)
        unit_score = sum(test_weight(t) for t in rows if t.get("status") == "passed")
    else:
        # Counts without the tests they came from: every test at the default.
        unit_max = DEFAULT_TEST_WEIGHT * total
        unit_score = DEFAULT_TEST_WEIGHT * passed
    reward["unit_tests"] = round(unit_score / unit_max, 4) if unit_max else 0.0
    summary["unit_tests"] = {"passed": passed, "total": total,
                             "points": unit_score, "of": unit_max,
                             "weights": units.get("weights_source", "default")}
    for t in rows:
        ctrf_tests.append({
            "name": f"{t['name']} [{test_weight(t)}]",
            "status": "passed" if t["status"] == "passed" else "failed",
            "duration": 0,
            "message": (t.get("message") or "")[:2000],
        })
    if graded:
        total_max = rubric_max + unit_max
        reward["reward"] = round(max(0.0, (rubric_score + unit_score) / total_max), 4) \
            if total_max else 0.0
        summary["combined"] = {"score": rubric_score + unit_score, "of": total_max}
elif graded:
    reward["reward"] = reward.get("rubrics", 0.0)
summary.setdefault("status", "graded")
summary["reward"] = reward["reward"]

with open(os.path.join(logs, "reward.json"), "w") as f:
    json.dump(reward, f, indent=2, sort_keys=True)
    f.write("\n")

counts = {"passed": 0, "failed": 0, "other": 0}
for t in ctrf_tests:
    counts[t["status"] if t["status"] in counts else "other"] += 1
with open(os.path.join(logs, "ctrf.json"), "w") as f:
    json.dump({"results": {
        "tool": {"name": "flc-verifier"},
        "summary": {"tests": len(ctrf_tests), "passed": counts["passed"],
                    "failed": counts["failed"], "pending": 0, "skipped": 0,
                    "other": counts["other"]},
        "tests": ctrf_tests,
    }}, f, indent=2)
    f.write("\n")

with open(os.path.join(logs, "grading_summary.json"), "w") as f:
    json.dump(summary, f, indent=2, sort_keys=True)
    f.write("\n")

for key in sorted(reward):
    print(f"  {key:<20} {reward[key]}")
if units.get("status") == "skipped":
    print("  (no unit tests -- this task is graded by rubrics alone)")

sys.exit(0 if reward["reward"] == 1.0 else 1)
PY
status=$?

echo
echo "=============================================================="
exit "$status"
