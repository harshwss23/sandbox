#!/usr/bin/env python3
"""How much context the task put in front of the model, measured from the run.

    python3 context_report.py                 # the last run
    python3 context_report.py --job <dir>
    python3 context_report.py --json

A task is meant to give the model a lot to hold at once. The number that says
whether it did cannot be taken from the files: a spreadsheet of a million cells
reaches the model as the few hundred rows an agent chose to print, and a folder
of prose reaches it whole. So it is measured after the run, from what the model
was actually holding.

Three readings come out of one run, and they answer different questions:

  peak      the most the model held at once, harness and all
  baseline  what the harness cost before the task -- system prompt, tool
            schemas, and the rest of what the agent brings with it
  added     peak - baseline: everything this task caused, including the
            agent's own reasoning and the code it wrote

`added` is the one that decides anything. Peak is not comparable between
agents -- the harness here costs 26k and a leaner one costs a fraction of that
-- so peak alone would rate the same task differently depending on what ran it.
A fixed allowance goes back on top for reporting, so the published figure still
reads like a context size.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402
from grade_report import latest_job  # noqa: E402
from solver_answer import find_trajectory, resolve_trial  # noqa: E402

# Prompt sizes are reported per call. A turn's context is everything the model
# was given for it, whether that arrived fresh, was written to cache, or was
# read back from it -- the three are a billing distinction, not a size one.
_PROMPT_KEYS = ("input_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens")

CHARS_PER_TOKEN = 4


def session_records(job: Path) -> list[dict]:
    """Every record in the agent's own session log, oldest first.

    Harbor's trajectory.json is not the source here. It carries the turns as
    prose -- on the run this was built against, 19 messages and not one tool
    call or result -- which is enough to grade an answer and not enough to say
    what the model was holding. The session log beside it carries the per-call
    token usage and the tool results, so both readings come from there.

    Nothing about the format is Claude Code's: one JSON object per line, with
    usage or content under `message`.
    """
    records: list[tuple[str, dict]] = []
    # The attempt every other reader resolved. Pooled across attempts, the peak
    # is whichever attempt held the most, and the baseline the smallest first
    # call of any of them -- a figure belonging to no single run.
    scope = resolve_trial(job) or job
    for path in sorted(scope.rglob("*.jsonl")):
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append((str(record.get("timestamp") or ""), record))
    # A run can leave more than one log and rglob sorts by path, so order by
    # the recorded time.
    records.sort(key=lambda pair: pair[0])
    return [record for _, record in records]


def turn_sizes(records: list[dict]) -> list[int]:
    """The prompt size of every model call in the run, in order."""
    sizes = []
    for record in records:
        usage = (record.get("message") or {}).get("usage")
        if not isinstance(usage, dict):
            usage = record.get("usage")
        if not isinstance(usage, dict):
            continue
        total = sum(usage.get(k) or 0 for k in _PROMPT_KEYS)
        if total > 0:
            sizes.append(total)
    return sizes


_USAGE_KEYS = _PROMPT_KEYS + ("output_tokens",)


def usage_totals(records: list[dict]) -> dict | None:
    """Every token the run's model calls used, by kind, and in all.

    A call split over several log records carries the same usage on each, so
    a message id seen before is not counted again. None when the log carries
    no usage at all.
    """
    totals = dict.fromkeys(_USAGE_KEYS, 0)
    seen: set[str] = set()
    found = False
    for record in records:
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else record.get("usage")
        if not isinstance(usage, dict):
            continue
        ident = str(message.get("id") or "")
        if ident:
            if ident in seen:
                continue
            seen.add(ident)
        found = True
        for key in _USAGE_KEYS:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                totals[key] += int(value)
    if not found:
        return None
    totals["total"] = sum(totals[k] for k in _USAGE_KEYS)
    return totals


def harbor_peak(job: Path) -> int | None:
    """A second reading of the peak, from Harbor's own totals.

    Every token that enters the prompt gets written to the cache once, so the
    cache-creation total over a run equals the largest prompt it ever built --
    as long as nothing was evicted or compacted along the way. On the run this
    was built against it agrees with the session log to within two tokens.

    It cannot replace the session log: there is no per-call figure here, and so
    no baseline to subtract. Read as a cross-check, the two disagreeing means
    the conversation was compacted, and peak is then no longer the high-water
    mark of a single prompt.
    """
    trajectory = find_trajectory(job)
    if not trajectory:
        return None
    try:
        data = json.loads(trajectory.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    extra = (data.get("final_metrics") or {}).get("extra") or {}
    value = extra.get("total_cache_creation_input_tokens")
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def file_tokens(records: list[dict]) -> int | None:
    """Roughly how much of the context came back from the contributor's files.

    Advisory, and an estimate: it counts characters in tool results and divides.
    Nothing is gated on it. It separates "32k of context, 3k of it the
    contributor's material" from "32k of context, 28k of it their material".

    Only what came *back* to the agent is counted, never what the agent said,
    which is the rule review_run.py follows: the answer quotes the files, and
    counting the whole transcript would count them twice.
    """
    total = 0
    seen = False
    for record in records:
        content = (record.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            seen = True
            body = block.get("content")
            total += len(body if isinstance(body, str) else json.dumps(body))
    return total // CHARS_PER_TOKEN if seen else None


def band(reported: int) -> str:
    if reported < 32_000:
        return "under_32k"
    if reported < 64_000:
        return "32k_64k"
    return "over_64k"


def measure(job: Path) -> dict:
    """Every reading for one run, or a stated reason there is none.

    `context_added` is None when the run cannot be measured, which is not the
    same as a run that measured low. A truncated transcript, an agent that
    reports no usage, a run that died early: each means the measurement failed,
    and none says anything about the contributor's material. Everything
    downstream keeps the two apart -- a thin task and an unmeasurable one have
    different remedies.
    """
    records = session_records(job)
    sizes = turn_sizes(records)
    cross = harbor_peak(job)
    if len(sizes) < 2:
        return {
            "context_peak": None,
            "context_baseline": None,
            "context_added": None,
            "context_reported": None,
            "context_from_files": file_tokens(records),
            "context_band": None,
            "harness_allowance": st.HARNESS_ALLOWANCE,
            "peak_crosscheck": cross,
            "measured": False,
            "why": ("the run's per-call token usage could not be read -- no "
                    "session log with usage totals was found under "
                    f"{job}"),
        }

    peak = max(sizes)
    baseline = sizes[0]
    added = peak - baseline
    reported = added + st.HARNESS_ALLOWANCE
    note = None
    if cross and abs(cross - peak) > max(1000, peak // 20):
        note = (f"Harbor's cache-creation total ({cross:,}) disagrees with the "
                f"peak read from the session log ({peak:,}), which usually "
                f"means the conversation was compacted during the run.")
    return {
        "context_peak": peak,
        "context_baseline": baseline,
        "context_added": added,
        "context_reported": reported,
        "context_from_files": file_tokens(records),
        "context_band": band(reported),
        "harness_allowance": st.HARNESS_ALLOWANCE,
        "peak_crosscheck": cross,
        "measured": True,
        "why": note,
    }


def record(root: Path, job: Path) -> dict:
    """Measure the run and keep the readings in the task's state.

    The token totals go into the run's own record, so what each run cost can
    be read after later ones.
    """
    report = measure(job)
    tokens = usage_totals(session_records(job))
    state = st.load(root)
    for key in ("context_peak", "context_baseline", "context_added",
                "context_reported", "context_from_files", "context_band"):
        state[key] = report[key]
    runs = state.get("runs") if isinstance(state.get("runs"), dict) else {}
    entry = runs.get(job.name)
    if isinstance(entry, dict):
        entry["tokens"] = tokens
    st.save(root, state)
    return report


def summary(report: dict) -> str:
    """What to print after a run, and what /flc-grade repeats when it refuses."""
    if not report["measured"]:
        return ("Context could not be measured for this run.\n"
                f"  {report['why']}\n"
                "This is a gap in the measurement, not a judgement on the task.")
    added = report["context_added"]
    lines = [
        f"Context this task put in front of the model: {added:,} tokens"
        f"  ({report['context_band'].replace('_', '-')})",
        f"  peak {report['context_peak']:,}, "
        f"harness {report['context_baseline']:,}",
    ]
    if report["context_from_files"] is not None:
        lines.append(f"  of which roughly {report['context_from_files']:,} "
                     f"came back from your files")
    if added < st.CONTEXT_ADDED_FLOOR:
        short = st.CONTEXT_ADDED_FLOOR - added
        lines.append("")
        lines.append(f"  This is {short:,} short of the {st.CONTEXT_ADDED_FLOOR:,} "
                     f"a task needs.")
        lines.append("  Add material to environment/workspace/ that the question "
                     "cannot be answered without,")
        lines.append("  or widen prompt.md so the work has to cover more of what "
                     "is already there, then")
        lines.append("  run /flc-run-solver again.")
    if report["why"]:
        lines.append("")
        lines.append(f"  {report['why']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=None)
    parser.add_argument("--job", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--record", action="store_true",
                        help="write the readings into the task state")
    args = parser.parse_args()

    root = st.task_root(args.task)
    job = Path(args.job) if args.job else latest_job(root)
    if not job or not job.is_dir():
        print("No solver run found. Run /flc-run-solver first.", file=sys.stderr)
        return 1

    report = record(root, job) if args.record else measure(job)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
