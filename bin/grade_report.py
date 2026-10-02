#!/usr/bin/env python3
"""Print the result of a graded run: every rubric, pass or fail, and why.

This is the whole of the grading. There are no unit tests and nothing here
inspects the transcript -- a criterion passed or it did not, and the judge said
why in its own words. That reasoning is reproduced verbatim rather than
summarised.

    python3 bin/grade_report.py              # the most recent run
    python3 bin/grade_report.py --job PATH   # a specific one
    python3 bin/grade_report.py --json       # the same thing, machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402
import solver_answer as sa  # noqa: E402

WIDTH = 78


def find_logs(job: Path) -> Path | None:
    """The verifier's log directory inside a finished job.

    Newest wins. A job can hold more than one -- the deferred pass Harbor runs
    with the agent leaves a directory behind, and grading later writes into the
    run's own -- and the results a person asked for are the later ones.

    Searched inside the attempt `solver_answer.resolve_trial()` chose, so the
    score reported is the score of the run whose answer was read. A sibling
    attempt's results are a different run's marks.
    """
    scope = sa.resolve_trial(job) or job
    candidates = list(scope.rglob("verifier/evaluation_results.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime).parent


def statuses(job: Path) -> set[str]:
    """Every verifier pass's own account of itself, in the chosen attempt.

    Scoped the way `find_logs()` is: pooled across attempts, one attempt's
    deferred authoring pass reports another attempt's grade as deferred.
    """
    seen: set[str] = set()
    scope = sa.resolve_trial(job) or job
    for summary in scope.rglob("verifier/grading_summary.json"):
        try:
            seen.add(str(json.loads(summary.read_text()).get("status")))
        except (OSError, json.JSONDecodeError):
            pass
    return seen


def deferred(job: Path) -> bool:
    """Whether the only verifier pass in this job was the one that declined."""
    return "deferred" in statuses(job)


def latest_job(root: Path) -> Path | None:
    """The run to report on, preferring the one this task last started.

    Runs land in a jobs directory beside the task rather than inside it. The
    path recorded in the state is authoritative; the scan below is the fallback
    for a job started by hand.
    """
    recorded = st.load(root).get("last_job")
    if recorded and Path(recorded).is_dir():
        return Path(recorded)
    for jobs in (root / "jobs", root.parent / "jobs"):
        if jobs.is_dir():
            runs = [p for p in jobs.iterdir() if p.is_dir()]
            if runs:
                return max(runs, key=lambda p: p.stat().st_mtime)
    return None


def load(logs: Path) -> tuple[list, dict, str]:
    """The per-criterion results, the reward, and any reason nothing was graded.

    The judge writes an object with the criteria under `rubric_scores`, and a
    bare list is accepted too for results produced before that was so.
    """
    payload = json.loads((logs / "evaluation_results.json").read_text())
    if isinstance(payload, dict):
        results = payload.get("rubric_scores") or []
        reason = str(payload.get("reason") or "")
    else:
        results = payload
        reason = ""
    reward_path = logs / "reward.json"
    reward = json.loads(reward_path.read_text()) if reward_path.exists() else {}
    return results, reward, reason


def verdict(entry: dict) -> tuple[str, str]:
    """PASS, FAIL or UNSCORED, with the judge's reasoning.

    The judge is always asked the same thing -- is this statement true of this
    answer -- so its yes is a pass on a positive criterion and a failure on a
    negative one, where the statement describes what the answer was supposed to
    avoid. Reading the raw score here without the weight's sign would print
    every avoided hallucination as a failure.
    """
    score = entry.get("score")
    if not isinstance(score, dict):
        return "UNSCORED", "the judge returned nothing usable for this criterion"
    justification = (score.get("justification") or "").strip()
    negative = int(entry.get("weight", 5)) < 0
    raw = str(score.get("score"))
    if raw not in ("0", "1"):
        return "UNSCORED", justification or "the judge returned no score"
    said_true = raw == "1"
    return ("PASS" if said_true != negative else "FAIL"), justification


# What each first label is called where a person reads it.
KIND_NAMES = {"task completion": "completion",
              "clarification": "clarification",
              "hallucination": "non-hallucination"}


def kind(entry: dict) -> str:
    """Which section a graded criterion came from.

    Off the label the criterion shipped with, and from the weight's sign only
    when there is none -- a result taken before the label was carried through
    reads exactly as it always did.
    """
    labels = entry.get("type") or []
    first = labels[0] if labels and isinstance(labels[0], str) else ""
    if first in KIND_NAMES:
        return KIND_NAMES[first]
    return "non-hallucination" if int(entry.get("weight", 5)) < 0 else "completion"


def fired_split(results: list) -> tuple[list[dict], list[dict]]:
    """The negative hallucination criteria this run committed, and the rest.

    One reader for the note printed here and the refusal /flc-deliver makes, so
    the two cannot disagree about verdicts neither of them changed.

    A criterion the judge never scored is in neither list. An absent verdict is
    not evidence that the run avoided the failure the criterion describes.
    """
    fired, quiet = [], []
    for entry in results:
        if int(entry.get("weight", 5)) >= 0 or kind(entry) != "non-hallucination":
            continue
        state = verdict(entry)[0]
        if state == "FAIL":
            fired.append(entry)
        elif state == "PASS":
            quiet.append(entry)
    return fired, quiet


def sensitivity(results: list, reward: dict, bar: float,
                combined: dict | None = None) -> dict:
    """Which single penalty, reversed, would put the score at the bar or over it.

    A judge that was wrong about one criterion moves the score by that
    criterion's weight, and a score just under the bar is one misreading away
    from over it. Reported and never blocking: the remedy is to check the
    judge's reading of those criteria, not to change them.
    """
    earned = of = 0
    penalised = []
    for entry in results:
        try:
            weight = int(entry.get("weight", 5))
        except (TypeError, ValueError):
            continue
        state = verdict(entry)[0]
        if state == "UNSCORED":
            continue
        if weight > 0:
            of += weight
            if state == "PASS":
                earned += weight
            else:
                penalised.append(entry)
        elif state == "FAIL":
            earned += weight
            penalised.append(entry)
    if isinstance(combined, dict) and isinstance(combined.get("of"), (int, float)) \
            and combined.get("of"):
        earned, of = combined.get("score", earned), combined["of"]
    current = reward.get("reward") if isinstance(reward, dict) else None
    flips = []
    for entry in penalised if of else []:
        gained = max(0, earned + abs(int(entry.get("weight", 5)))) / of
        if gained >= bar:
            flips.append({"criterion": str(entry.get("title", "")).strip(),
                          "weight": int(entry.get("weight", 5)),
                          "reward_if_reversed": round(gained, 4)})
    flips.sort(key=lambda f: -f["reward_if_reversed"])
    return {"reward": current, "bar": bar, "flips": flips}


def with_fixes(results: list, weights: dict[str, int], dropped: set[str],
               combined: dict | None = None) -> float | None:
    """The score as it would be with these lines reweighted and these taken out.

    Lines are matched by their text. The unit tests' share, where there is one,
    is carried over unchanged.
    """
    def tally(fix: bool) -> tuple[int, int]:
        earned = of = 0
        for entry in results:
            try:
                weight = int(entry.get("weight", 5))
            except (TypeError, ValueError):
                continue
            text = " ".join(str(entry.get("title", "")).split())
            if fix:
                if text in dropped:
                    continue
                weight = weights.get(text, weight)
            state = verdict(entry)[0]
            if state == "UNSCORED":
                continue
            if weight > 0:
                of += weight
                earned += weight if state == "PASS" else 0
            elif state == "FAIL":
                earned += weight
        return earned, of

    before, after = tally(False), tally(True)
    earned, of = after
    if isinstance(combined, dict) and isinstance(combined.get("of"), (int, float)) \
            and isinstance(combined.get("score"), (int, float)):
        earned += combined["score"] - before[0]
        of += combined["of"] - before[1]
    return round(max(0, earned) / of, 4) if of > 0 else None


GRADES_KEY = "grades"


def grade_record(job: Path, results: list, reward: dict) -> dict:
    """One grade, as the task's history keeps it: the run, the score, each line."""
    from datetime import datetime, timezone
    lines = []
    for entry in results:
        try:
            weight = int(entry.get("weight", 5))
        except (TypeError, ValueError):
            continue
        lines.append({"text": " ".join(str(entry.get("title", "")).split()),
                      "weight": weight, "verdict": verdict(entry)[0]})
    return {"job": job.name,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reward": reward.get("reward") if isinstance(reward, dict) else None,
            "bar": st.MAX_SOLVER_REWARD, "criteria": lines}


def proposed_weights(state: dict) -> dict[str, set[int]]:
    """Every weight a criteria-check finding has named for a line, by its text."""
    out: dict[str, set[int]] = {}
    for info in (state.get("rubric_seen") or {}).values():
        if not isinstance(info, dict) or "proposed_weight" not in info:
            continue
        named = set()
        for value in [info["proposed_weight"], *(info.get("accepted_weights") or [])]:
            try:
                named.add(int(float(str(value).replace("+", ""))))
            except (ValueError, OverflowError):
                continue
        text = " ".join(str(info.get("criterion", "")).split())
        out.setdefault(text, set()).update(named)
    return out


def weights_only_drop(history: list, current: dict, bar: float,
                      proposed: dict | None = None) -> dict | None:
    """An earlier grade of the same run at or over the bar, and this one under it,
    with nothing changed between them but weights.

    `proposed` maps a line's text to the weights a criteria-check finding named
    for it; a line moved to exactly one of those does not count as moved.
    Returns the earlier grade and the lines whose weights moved, or None.
    """
    score = current.get("reward")
    if not isinstance(score, (int, float)) or score >= bar:
        return None
    now = {c["text"]: c["weight"] for c in current.get("criteria") or []}
    for earlier in reversed(history or []):
        if earlier is current or earlier.get("job") != current.get("job"):
            continue
        before_score = earlier.get("reward")
        if not isinstance(before_score, (int, float)) or before_score < bar:
            continue
        before = {c["text"]: c["weight"] for c in earlier.get("criteria") or []}
        if set(before) != set(now):
            continue
        moved = [{"text": text, "before": before[text], "after": now[text]}
                 for text in now if before[text] != now[text]
                 and now[text] not in (proposed or {}).get(text, ())]
        if moved:
            return {"earlier": earlier, "moved": moved}
    return None


def weights_only_text(drop: dict, score: float) -> str:
    """What the weights-only drop says, at /flc-grade and at delivery alike."""
    earlier = drop["earlier"]
    lines = "\n".join(f"  [{m['before']}] -> [{m['after']}]  {m['text']}"
                      for m in drop["moved"])
    return (f"An earlier grade of this same run scored {earlier['reward']:.0%}, which is "
            f"not under the {st.MAX_SOLVER_REWARD:.0%} bar. This one scores {score:.0%}, "
            "and nothing has changed between them except the weights of these lines:\n"
            f"{lines}\n"
            "A task the model can already pass does not become deliverable by weighing "
            "what it got right for less. Put those weights back and make the task "
            "harder instead, then run the solver again. A weight moved to exactly the "
            "one /flc-check-rubric named for that line does not count here.")


def weights_only_for(state: dict, job: Path) -> dict | None:
    """The weights-only drop for this job's latest grade, if there is one."""
    history = state.get(GRADES_KEY) or []
    current = next((g for g in reversed(history) if g.get("job") == job.name), None)
    if current is None:
        return None
    return weights_only_drop(history, current, st.MAX_SOLVER_REWARD,
                             proposed_weights(state))


def environment_warning(job: Path) -> None:
    """Say so, before the results, if the run was fighting its environment.

    Printed before the results rather than after. Failed criteria look
    identical whether the model got the answer wrong or never got the tool it
    needed.
    """
    try:
        import detect_packages
    except Exception:
        return
    transcript = sa.find_trajectory(job)
    if transcript is None:
        return
    stuck = detect_packages.blocked(transcript.read_text(errors="replace"))
    if not stuck:
        return
    print()
    print("!" * WIDTH)
    print("The solver could not get something it went looking for:")
    for note in stuck:
        print(f"  - {note}")
    print()
    print("Read the failures below with that in mind. A criterion failed because")
    print("the model lacked a tool is not the model getting the answer wrong, and")
    print("this task probably needs the package added and a rerun:")
    print("  python3 bin/detect_packages.py --add")
    print("!" * WIDTH)


def report(results: list, reward: dict, reason: str = "") -> int:
    passed = [e for e in results if verdict(e)[0] == "PASS"]
    failed = [e for e in results if verdict(e)[0] == "FAIL"]
    unscored = [e for e in results if verdict(e)[0] == "UNSCORED"]
    scored = len(passed) + len(failed)

    if results:
        print()
        print("CRITERIA")
        print("-" * WIDTH)
        for entry in results:
            mark, why = verdict(entry)
            weight = int(entry.get("weight", 5))
            note = "  (should not have happened)" if weight < 0 else ""
            print(f"\n  {mark:<8} [{weight:+d}]  {entry.get('title', '(untitled)')}{note}")
            if why:
                for line in textwrap.wrap(why, WIDTH - 12):
                    print(f"           {line}")

    print()
    print("=" * WIDTH)
    if reason:
        # Nothing reached the judge, which is not a task the model failed.
        print("NOTHING WAS GRADED. This is not a result about the model:")
        for line in textwrap.wrap(reason, WIDTH - 2):
            print(f"  {line}")
        print()
        print("The run itself may have been fine. This is a technical issue on")
        print("our side: do not rewrite the task around it.")
        print("=" * WIDTH)
    if scored:
        # The positive criteria are the marks available; a negative criterion
        # the model tripped subtracts its weight. Same arithmetic as
        # judge._aggregate, kept here so the report can be read on its own.
        max_reward = sum(int(e.get("weight", 5)) for e in passed + failed
                         if int(e.get("weight", 5)) > 0)
        earned = sum(int(e.get("weight", 5)) for e in passed
                     if int(e.get("weight", 5)) > 0)
        lost = sum(abs(int(e.get("weight", 5))) for e in failed
                   if int(e.get("weight", 5)) < 0)
        print(f"held {len(passed)} of {scored} criteria")
        if max_reward:
            print(f"scored {earned - lost} of {max_reward} points"
                  + (f"  ({earned} earned, {lost} lost to negative criteria)"
                     if lost else ""))
        else:
            print("nothing at stake: this task has no positive criteria")
    else:
        print("nothing was scored")

    # The negative criteria, split by whether this run committed the failure
    # each one describes. A negative that did not fire is a failure the task
    # anticipated rather than one it recorded.
    #
    # The count itself is enforced at /flc-rubrics, which can see it. What is
    # only visible here is how many of them this run provoked, and /flc-deliver
    # refuses over the allowance on the same split this note prints.
    fired, quiet = fired_split(results)
    negatives = fired + quiet
    if negatives:
        print(f"non-hallucination criteria: {len(negatives)} written, "
              f"{len(fired)} fired, {len(quiet)} did not")
        if len(quiet) > st.ANTICIPATED_CAP:
            print()
            print(f"More than {st.ANTICIPATED_CAP} of them describe a failure "
                  "this run did not commit.")
            print(f"{st.ANTICIPATED_CAP} is the allowance, and a set where "
                  "every one of them fired is")
            print("better: a failure nobody was seen to commit is by "
                  "construction not one your")
            print("setup compelled, so those lines carry less than they look "
                  "like they do.")
            print("Delivery refuses over the allowance, so this is worth "
                  "settling now rather")
            print("than at /flc-deliver. Two repairs, and neither is "
                  "weakening a criterion")
            print("that is right: read the run again for mistakes no "
                  "criterion covers yet and")
            print("write those (/flc-inspect), or run the solver again "
                  "against material that")
            print("pulls harder towards the wrong turns these lines "
                  "describe. Drop one only")
            print("if you cannot point at it in the answer.")

    if unscored:
        print(f"{len(unscored)} criterion/criteria could not be scored by the judge")
    no_score = [e for e in results if e.get("unmeasured") == "judge_no_score"]
    if no_score:
        print()
        print(f"{len(no_score)} criterion/criteria were never graded. The judge "
              "answered, but never")
        print("in the yes-or-no form the criterion asks for, through every "
              "retry -- so the")
        print("score above is over the rest of the rubric rather than over your "
              "task, and")
        print("/flc-deliver will refuse it.")
        for entry in no_score:
            print(f"  - {entry.get('title', '')}")
        print()
        print("Grading again is worth one attempt. If it comes back the same, "
              "the criterion")
        print("is most likely not a yes-or-no question about the answer; reword "
              "it to state")
        print("one checkable fact.")
    refused = [e for e in results if e.get("unmeasured") == "judge_refused"]
    if refused:
        print()
        print(f"{len(refused)} criterion/criteria were not graded because the judge "
              "declined to")
        print("read them. Its safety filter refused the wording, which is about the")
        print("words rather than about your task, and the score above is over the rest.")
        for entry in refused:
            print(f"  - {entry.get('title', '')}")
        print()
        print("The filter is not consistent, so /flc-grade again is worth one try.")
        print("If it declines again, reword the criterion to say the same thing")
        print("differently -- naming the same fact in plainer terms is usually enough.")
    if reward:
        score = reward.get("reward")
        # The two rates the score is made of, printed only where a suite
        # scored: a task with no unit tests writes no unit_tests key.
        rubrics, units = reward.get("rubrics"), reward.get("unit_tests")
        both = all(isinstance(p, (int, float)) for p in (rubrics, units))
        print(f"score: {score}   ("
              + ("the criteria and the automated checks together" if both
                 else "the agent's points over the maximum") + ")")
        if both:
            print(f"       criteria {rubrics}   automated checks {units}")
        if isinstance(score, (int, float)):
            bar = st.MAX_SOLVER_REWARD
            if score >= bar:
                print()
                print(f"This is at or above {bar:.0%}, so the task is too easy to deliver.")
                print("The model is not failing here, and a task it passes measures")
                print("nothing. Make it harder before /flc-deliver: bury the answer")
                print("deeper, add material that has to be ruled out, or ask for")
                print("something the shortcut does not give.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="a job directory (default: the most recent)")
    ap.add_argument("--task", help="the task folder")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    root = st.task_root(args.task)
    job = Path(args.job).resolve() if args.job else latest_job(root)
    if not job or not job.is_dir():
        print("no solver run found. Run /flc-run-solver first.", file=sys.stderr)
        return 2

    logs = find_logs(job)
    if not logs:
        if "error" in statuses(job):
            # Says nothing about the model, so it must not be read as a zero.
            print("nothing was graded: the grader could not reach the judge "
                  "endpoint.\n\n"
                  "This is a verifier network fault, not a result about the "
                  "model. The\nverifier runs in its own container, so a gateway "
                  "on the host's loopback\naddress is not reachable from it. "
                  "Grading on request goes through the\nhost network and is the "
                  "way round it:\n\n"
                  "    python3 ~/flc/bin/run_grader.py\n\n"
                  "See the verifier's output in the run's logs for the endpoint "
                  "it tried.", file=sys.stderr)
            return 2
        if deferred(job):
            print("this run has not been graded yet.\n\n"
                  "That is the normal state after a solver run: the "
                  "hallucination\ncriteria are written from the run, "
                  "so grading waits for\nthem. Write them with /flc-rubrics, "
                  "then grade:\n\n"
                  "    python3 ~/flc/bin/run_grader.py", file=sys.stderr)
            return 2
        print(f"no grading results in {job}.\n"
              "The run may have failed before grading, or been killed. "
              "Check the run's output.", file=sys.stderr)
        return 2

    results, reward, reason = load(logs)

    if args.as_json:
        print(json.dumps({
            "job": str(job),
            "reward": reward,
            "not_graded": reason,
            "criteria": [
                {"id": e.get("id"), "title": e.get("title"),
                 "weight": e.get("weight", 5),
                 "result": verdict(e)[0], "reason": verdict(e)[1]}
                for e in results
            ],
        }, indent=2))
        return 0

    print(f"Graded run: {os.path.basename(job)}")
    environment_warning(job)
    return report(results, reward, reason)


if __name__ == "__main__":
    sys.exit(main())
