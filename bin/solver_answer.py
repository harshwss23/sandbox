#!/usr/bin/env python3
"""Print what the solver answered, so criteria can be written against it.

The non-hallucination criteria are the point of the task and they cannot be
invented in advance: nobody can predict which number a model will make up. They
are written by reading what it actually claimed. This prints exactly that -- the
agent's final message, the same text the judge will be shown -- and nothing
else. No verdict, no comparison against the ground truth: deciding which claims
are false is the contributor's job and is the work this step exists to do.

    python3 bin/solver_answer.py             # the last run
    python3 bin/solver_answer.py --job PATH  # a specific one
    python3 bin/solver_answer.py --files     # also list what it wrote
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402

WIDTH = 78


def find_job(root: Path, explicit: str | None) -> Path | None:
    """The run to read, preferring the one this task last started."""
    if explicit:
        return Path(explicit).resolve()
    recorded = st.load(root).get("last_job")
    if recorded and Path(recorded).is_dir():
        return Path(recorded)
    # Runs land in a jobs directory beside the task, not inside it.
    for jobs in (root / "jobs", root.parent / "jobs"):
        if jobs.is_dir():
            runs = [p for p in jobs.iterdir() if p.is_dir()]
            if runs:
                return max(runs, key=lambda p: p.stat().st_mtime)
    return None


def _trial_root(transcript: Path, job: Path) -> Path:
    """The attempt directory a transcript belongs to.

    Harbor 0.20.0 writes `<trial>/agent/trajectory.json` and the nested layout
    writes `<trial>/logs/agent/trajectory.json`; both resolve to `<trial>`. A
    trial handed in as the job resolves to the job itself.
    """
    current = transcript.parent
    while current.name in ("agent", "logs") and current != job:
        current = current.parent
    return current


def trials(job: Path) -> list[Path]:
    """Every attempt under a job, oldest first.

    An attempt is identified by its transcript, which is what makes it a run at
    all -- `flc_state.run_state()` reports a job with no transcript as never
    having run. Ordered by the transcript's own mtime rather than the
    directory's: grading later writes into the attempt and moves the directory's
    mtime, so the directory cannot say which attempt the agent finished last.
    Ties break on the path, so the order is total.
    """
    newest: dict[Path, float] = {}
    for transcript in job.rglob("*trajectory*.json"):
        try:
            when = transcript.stat().st_mtime
        except OSError:
            continue
        trial = _trial_root(transcript, job)
        newest[trial] = max(newest.get(trial, when), when)
    return sorted(newest, key=lambda p: (newest[p], str(p)))


def resolve_trial(job: Path) -> Path | None:
    """The one attempt every reader of this job must use: the last one.

    `harbor run --n-attempts N` writes N of them side by side, each with its own
    transcript and its own finished workspace. Every reader has to agree on
    which one is the run, or a grade is taken against one attempt's answer and
    another's files. This is the only place that choice is made.
    """
    found = trials(job)
    return found[-1] if found else None


def find_trajectory(job: Path) -> Path | None:
    trial = resolve_trial(job)
    if trial is None:
        return None
    found = sorted(trial.rglob("*trajectory*.json"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


# The shape of a trajectory depends on the agent that produced it. Two dialects
# are known to arrive: {"messages": [{"role": "assistant", "content": ...}]},
# and the ATIF form, whose records carry "source" and "message" instead.
_AGENT_MARKERS = {"assistant", "agent", "ai", "model"}
_SPEAKER_KEYS = ("role", "source", "sender", "author", "speaker")
_RECORD_LISTS = ("messages", "steps", "trajectory", "events", "history", "turns")
_TEXT_KEYS = ("content", "message", "text", "final_answer", "output", "response")
# A record written by a subagent the agent started, rather than by the agent.
_SUBAGENT_KEYS = ("is_sidechain", "isSidechain")
_STOP_KEYS = ("stop_reason", "finish_reason")
# Stop reasons after which the agent's turn continues into a tool call.
_TURN_GOES_ON = {"tool_use", "tool_calls", "function_call"}
# Placed between two replies when the answer is made of several.
REPLY_SEPARATOR = "\n\n---\n\n"


def _text_of(value) -> str:
    """The prose in a content field, whatever shape that field takes."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner
        return ""
    if isinstance(value, list):
        parts = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text", "output_text"):
                parts.append(_text_of(block))
        return "\n".join(p for p in parts if p.strip())
    return ""


def _records_of(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in _RECORD_LISTS:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _is_agent(record: dict) -> bool:
    for key in _SPEAKER_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.strip().lower() in _AGENT_MARKERS:
            return True
    return False


def _fields(record: dict) -> tuple:
    extra = record.get("extra")
    return (record, extra) if isinstance(extra, dict) else (record,)


def _is_subagent(record: dict) -> bool:
    return any(holder.get(key) is True
               for holder in _fields(record) for key in _SUBAGENT_KEYS)


def _stop_reason(record: dict) -> str | None:
    for holder in _fields(record):
        for key in _STOP_KEYS:
            if isinstance(holder.get(key), str):
                return holder[key]
    return None


def _said(record: dict) -> str:
    for key in _TEXT_KEYS:
        if key in record:
            text = _text_of(record[key]).strip()
            if text:
                return text
    return ""


def reply_records(data) -> list[dict]:
    """The records holding what the agent said at the end of each of its turns.

    A reply is a message of the agent's own, not a subagent's, whose stop
    reason ends the turn. The last message the agent wrote is always the last
    reply, including in a transcript that records no stop reasons.
    """
    spoken = [r for r in _records_of(data)
              if isinstance(r, dict) and _is_agent(r) and not _is_subagent(r)
              and _said(r)]
    if not spoken:
        return []
    ended = [r for r in spoken[:-1]
             if _stop_reason(r) is not None and _stop_reason(r) not in _TURN_GOES_ON]
    return ended + [spoken[-1]]


def replies(data) -> list[str]:
    """What the agent said at the end of each of its turns, in order."""
    return [_said(r) for r in reply_records(data)]


def final_message(trajectory: Path) -> str:
    """The agent's answer: its replies, joined by REPLY_SEPARATOR.

    Kept in step with judge._final_message: what is printed here has to be the
    text the judge will grade, or criteria get written against something the
    judge never sees.
    """
    try:
        data = json.loads(trajectory.read_text(errors="replace"))
    except Exception:
        return ""
    return REPLY_SEPARATOR.join(replies(data))


def finished_workspace(job: Path) -> Path | None:
    """The workspace as the model left it, if the run kept one at all.

    Harbor does not bring it back, and no `task.toml` key changes that on 0.20.0
    -- a 1.4 manifest declaring `artifacts` and `environment_mode = "shared"`
    returned an identical job tree with no workspace in it. What is here instead
    is `tests/snapshot_workspace.py`, which the verifier runs while /workspace is
    still mounted and which writes the produced files into the verifier's log
    directory, and that directory is collected.

    None means no copy came back, which is not the same as a model that wrote
    nothing. "Cannot tell" against "did not happen": reporting the first as the
    second is what turns a script the model really wrote into a fabricated file.

    Only the attempt `resolve_trial()` chose is searched. A sibling attempt's
    workspace is another run's files: pairing it with this run's transcript
    reads as a model that wrote something it never wrote, and is graded as one.
    So an attempt that kept no workspace is None -- never a neighbour's.
    """
    trial = resolve_trial(job)
    if trial is None:
        return None
    for pattern in ("logs/workspace", "workspace"):
        for candidate in sorted(trial.rglob(pattern)):
            if candidate.is_dir():
                return candidate
    return None


def written_files(job: Path, root: Path) -> list[str] | None:
    """Files in the finished workspace that were not uploaded inputs.

    None means the run collected no workspace, so nothing can be said about
    what the model wrote. An empty list means it collected one and the model
    added nothing to it.
    """
    workspace = finished_workspace(job)
    if workspace is None:
        return None
    manifest = root / "tests" / "inputs_manifest.json"
    # Flat, {relative path: sha256}, as flc_state writes it and the judge reads
    # it. This read it as {"files": {...}} and so saw an empty set of inputs,
    # which made every uploaded file look like something the model produced --
    # the same false accusation as the uncollected workspace, from the other
    # direction.
    try:
        given = json.loads(manifest.read_text())
        given = given if isinstance(given, dict) else {}
    except Exception:
        given = {}
    out: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(workspace))
        digest = given.get(rel)
        if digest and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        if rel in given and not digest:
            continue
        out.append(rel)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="a job directory (default: the last run)")
    ap.add_argument("--task", help="the task folder")
    ap.add_argument("--files", action="store_true",
                    help="also list the files the model left behind")
    args = ap.parse_args()

    root = st.task_root(args.task)
    job = find_job(root, args.job)
    if not job or not job.is_dir():
        print("No solver run found. Start one with /flc-run-solver.", file=sys.stderr)
        return 2

    trajectory = find_trajectory(job)
    if not trajectory:
        print(f"No transcript in {job}.\n"
              "If the run is still going, wait for it to finish:\n"
              "  bash bin/run_solver.sh --status", file=sys.stderr)
        return 2

    answer = final_message(trajectory)
    if not answer:
        print(f"The transcript at {trajectory} has no final message from the "
              "agent.\nThe run may have been killed before it answered.",
              file=sys.stderr)
        return 2

    print("=" * WIDTH)
    print("WHAT THE SOLVER ANSWERED")
    print("=" * WIDTH)
    print()
    print(answer)
    print()
    print("=" * WIDTH)

    if args.files:
        produced = written_files(job, root)
        print("FILES IT LEFT BEHIND")
        if produced is None:
            print("  (this run collected no workspace, so what it wrote cannot")
            print("   be listed -- do not read this as 'it wrote nothing')")
        elif produced:
            for name in produced:
                print(f"  {name}")
        else:
            print("  (none -- it answered without writing anything)")
        print("=" * WIDTH)

    print(f"full transcript: {trajectory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
