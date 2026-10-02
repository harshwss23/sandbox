#!/usr/bin/env python3
"""Record which model answered a run, and whether it is the one that was asked for.

Reads the model recorded on the agent's turns in the finished transcript and
writes it to the task state as `solver_model_observed`, with the comparison as
`solver_model_check`. Agents differ on whether they keep the provider prefix,
so names are compared on the part after the last `/`.

A run whose transcript records no model at all is recorded as unknown rather
than as a mismatch: nothing was measured, which is not the same as something
disagreeing.

`--quiet` records without printing, and is how the workflow calls it. The model
is not set from inside the sandbox, so what this finds is for the delivery
record and for whoever reads it afterwards.

    python3 bin/model_check.py             # the last run
    python3 bin/model_check.py --job PATH  # a specific one
    python3 bin/model_check.py --quiet     # record, say nothing
    python3 bin/model_check.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402
import solver_answer as sa  # noqa: E402

MODEL_KEYS = ("model_name", "model")
SETTINGS = ("model", "agent")


def normalise(name: str) -> str:
    """A model name without its provider prefix, for comparison."""
    return name.strip().rsplit("/", 1)[-1].lower()


def configured(bin_dir: Path = BIN_DIR) -> dict | None:
    """The model and agent bin/solver_model.txt sets, read as run_solver.sh reads them.

    None when the file is missing or names no model.
    """
    try:
        text = (bin_dir / "solver_model.txt").read_text()
    except OSError:
        return None
    found = {}
    for key in SETTINGS:
        line = re.search(rf"^[ \t]*{key}[ \t]*=[ \t]*(.*)$", text, re.M)
        if line and line.group(1).strip():
            found[key] = line.group(1).strip()
    return found if "model" in found else None


def requested(state: dict, job: Path | str | None) -> dict | None:
    """The model and agent a given run was started with, or None if nothing says.

    Read from the record run_solver.sh keeps per job. A run from before that
    record existed falls back on the last-run fields, and only when it is the
    last run, since those are rewritten by every run started after it.
    """
    if job is None:
        return None
    name = Path(job).name
    entry = (state.get("runs") or {}).get(name)
    if isinstance(entry, dict) and entry.get("model"):
        return {key: entry.get(key) for key in SETTINGS}
    last = state.get("last_job")
    if last and Path(last).name == name and state.get("solver_model"):
        return {"model": state.get("solver_model"), "agent": state.get("solver_agent")}
    return None


def overridden(asked: dict, setup: dict) -> list[str]:
    """Which of the model and agent a run asked for differ from the sandbox's.

    Compared whole, provider prefix included: a run that asked for another
    provider's model is another model. A setting either side does not record
    is not compared.
    """
    return [key for key in SETTINGS
            if asked.get(key) and setup.get(key)
            and asked[key].strip() != setup[key].strip()]


def observed_models(trajectory: Path) -> list[str]:
    """Every distinct model named on a record in the transcript, in order.

    `model_name` is taken from any record; the plainer `model` only from a
    record the agent spoke on, since that name is common enough to appear in a
    tool result or in the task's own material.
    """
    try:
        data = json.loads(trajectory.read_text())
    except Exception:
        return []
    seen: list[str] = []
    for record in sa._records_of(data):
        if not isinstance(record, dict):
            continue
        for key in MODEL_KEYS:
            if key == "model" and not sa._is_agent(record):
                continue
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                if value.strip() not in seen:
                    seen.append(value.strip())
                break
    return seen


def verdict(requested: str | None, observed: list[str]) -> str:
    """`match`, `mismatch`, or `unknown` when either side is missing."""
    if not requested or not observed:
        return "unknown"
    wanted = normalise(requested)
    return "match" if all(normalise(o) == wanted for o in observed) else "mismatch"


def check(root: Path, job: Path | None) -> dict:
    state = st.load(root)
    asked = (requested(state, job) or {}).get("model")
    result = {"requested": asked, "observed": [], "verdict": "unknown",
              "why": "", "job": str(job) if job else None}
    if job is None:
        result["why"] = "no run to read"
        return result
    trajectory = sa.find_trajectory(job)
    if trajectory is None:
        result["why"] = f"no transcript in {job}"
        return result
    result["trajectory"] = str(trajectory)
    result["observed"] = observed_models(trajectory)
    result["verdict"] = verdict(asked, result["observed"])
    if result["verdict"] == "unknown":
        result["why"] = ("the run did not record which model it asked for"
                         if not asked else
                         "the transcript names no model on any turn")
    return result


def record(root: Path, result: dict) -> None:
    state = st.load(root)
    state["solver_model_observed"] = result["observed"]
    state["solver_model_check"] = result["verdict"]
    st.save(root, state)


def report(result: dict) -> None:
    observed = ", ".join(result["observed"]) or "not recorded"
    if result["verdict"] == "match":
        print(f"The run was answered by {observed}, which is what it asked for.")
    elif result["verdict"] == "unknown":
        print(f"Which model answered this run could not be read: {result['why']}.")
    else:
        print("This run was not answered by the model it asked for.")
        print(f"  asked for: {result['requested']}")
        print(f"  answered:  {observed}")
        print()
        print("  The model comes from the sandbox rather than from")
        print("  bin/solver_model.txt alone, so a run can succeed against a")
        print("  different model than the one configured. The score, the")
        print("  transcript and every criterion written from it belong to the")
        print("  model that answered. It is in the delivery record either way.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root()
    job = sa.find_job(root, args.job)
    result = check(root, job)
    record(root, result)
    if args.json:
        print(json.dumps(result, indent=2))
    elif not args.quiet:
        report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
