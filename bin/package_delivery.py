#!/usr/bin/env python3
"""Step 8: rebuild the task from scratch, verify it, and package it.

The live container is thrown away here. Everything is rebuilt from the files in
environment/ alone, which is all the bundle carries, so a task that only works
thanks to something typed into a running container fails at this step.

What it does, in order:

  1. check the recorded grade still belongs to what is being shipped
  2. rebuild the image with --no-cache from environment/ only
  3. run the shipped verifier inside it, short of the judge
  4. assemble delivery/bundle/ -- a plain Harbor task, nothing added
  5. copy the run artifacts to delivery/run/
  6. write delivery/validation.json and a readable summary

It does not grade. `/flc-grade` already ran the same verifier the bundle
carries and left the score in the run's own logs, so this reads that number
instead of buying a second one. What it checks instead is that the score still
belongs to this task: see `flc_state.GRADE_INPUTS`.

Usage:
    package_delivery.py [--task PATH] [--job PATH] [--keep-image] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_grade  # noqa: E402  -- for the recorded reading of the verdicts
import check_inputs  # noqa: E402  -- for the recorded workspace digest
import check_integrity as ci  # noqa: E402
import check_tests as ct  # noqa: E402
import context_report as cr  # noqa: E402
import flc_state as st
import grade_report as gr  # noqa: E402  -- the fired/quiet split, shared with /flc-grade
import materials_record  # noqa: E402
import model_check as mc  # noqa: E402  -- which model a run asked for, and the sandbox's own
import prompt_check  # noqa: E402  -- for the recorded difficulty verdict
import rubric_check  # noqa: E402  -- for the recorded rubric quality verdict
import restore_task  # noqa: E402  -- for the review-pass record
import run_guard as rg  # noqa: E402  -- the run history and the sealed answer
import review_run as rr  # noqa: E402  -- the answer-lookup verdict, shared with /flc-inspect
import justification_check as jc  # noqa: E402  -- the recorded justification verdict
import labels as lb  # noqa: E402  -- solution/labels.md, and the taxonomy delivery writes
import solver_answer as sa  # noqa: E402
import test_weights as tw  # noqa: E402

BIN = Path(__file__).resolve().parent

# The Harbor task itself. Everything else in the task folder -- the state file,
# the contributor's notes, the solution -- is working material and stays behind,
# by not being named here: only these are copied.
BUNDLE_FILES = ["task.toml", "instruction.md"]
BUNDLE_DIRS = ["environment", "tests"]
# Matched against the basename in every directory walked, so a name here is
# excluded at any depth. `.flc` must NOT be added: the task's own .flc/ is
# already left behind by not being copied, while environment/.flc/ holds the
# install and blocking helpers that the generated Dockerfile's first COPY names.
BUNDLE_EXCLUDE = {"prompt.md", "__pycache__", ".pytest_cache", ".DS_Store",
                  "verifier.py.skipped"}

# What stays in delivery/run. The rest is moved to delivery/run_removals,
# keeping its path. The transcript's own filename is added at packaging time.
RUN_KEEP = ["ctrf.json", "grading_summary.json", "final_workspace",
            "test_weights.json"]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def read_json(path: Path) -> dict:
    """The file as a dict, or {} if it is absent or unreadable.

    Every caller here treats "not there" and "not readable" the same way -- as
    a check that has not been passed -- and says so in its own words, which is
    more useful than a traceback naming a path the contributor did not choose.
    """
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def advisories(state: dict) -> list[dict]:
    """Steps that ran and failed at some point, whether or not they passed later.

    A step that failed and was then fixed leaves nothing here: mark_done clears
    it. What is left is a step still standing on a failure at packaging time.
    """
    return [dict(step=k, **v) for k, v in sorted((state.get("steps_failed") or {}).items())]


def earlier_deliveries(delivery: Path) -> list[dict]:
    """What previous deliveries of this task recorded, oldest first.

    Kept as a summary rather than the whole record: what a reviewer needs is
    that there was one, when, and what it scored, and carrying every field
    forward would grow without bound over repeated deliveries.
    """
    try:
        previous = json.loads((delivery / "validation.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []
    summary = {k: previous.get(k) for k in
               ("packaged_at", "seed_version", "verdict", "graded_job",
                "rubric_count", "context_added")}
    summary["reward"] = (previous.get("solver_reward") or {}).get("reward")
    summary["review_pass"] = bool(previous.get("review"))
    return (previous.get("previous_deliveries") or []) + [summary]


def statement_record(state: dict) -> list[dict]:
    """Every statement either check put to the vote, with its votes, by check."""
    out = []
    for key, name in ((rubric_check.STATE_KEY, "criteria check"),
                      (jc.STATE_KEY, "justification check")):
        entry = state.get(key)
        if not isinstance(entry, dict):
            continue
        for s in entry.get("statements") or []:
            if isinstance(s, dict) and s.get("flagged"):
                out.append(dict(s, check_name=name,
                                ballot=(entry.get("vote") or {}).get("version")))
    return out


def statements_markdown(validation: dict) -> list[str]:
    """The statements found inaccurate, what each voter said, and what counted."""
    rows = validation.get("statements") or []
    found = validation.get("answer_inaccuracies") or {}
    out = ["## Statements found inaccurate", ""]
    if not rows:
        out += ["No check filed a statement that something in the task is "
                "inaccurate.", ""]
        return out
    confirmed = sum(1 for s in rows if s.get("confirmed"))
    out.append(f"{len(rows)} statement(s) were put to the blind vote; "
               f"{confirmed} confirmed by all three voters. Only a confirmed one "
               "counts. The answer's verdict: "
               f"**{found.get('verdict', 'PASS')}**.")
    out.append("")
    for s in rows:
        state_ = "confirmed" if s.get("confirmed") else "not confirmed"
        out.append(f"- **{state_}** ({s.get('check_name')}, {s.get('kind') or 'statement'}) "
                   f"in {s.get('where') or s.get('file')}: \"{s.get('quote', '')}\"")
        out.append(f"  - what is wrong: {s.get('what_is_wrong', '')}")
        out.append(f"  - the check: {s.get('check', '')}")
        if s.get("bears_on"):
            out.append(f"  - graded material resting on it: {', '.join(s['bears_on'])}")
        for slot, vote in sorted((s.get("votes") or {}).items()):
            out.append(f"  - {slot} ({vote.get('model') or 'abstained'}): "
                       f"{vote.get('verdict', '?')} -- {str(vote.get('check', ''))[:200]}")
    out.append("")
    return out


def audit_markdown(validation: dict, state: dict) -> str:
    """The delivery record, as prose rather than as JSON.

    validation.json is the machine-readable half and nobody reads it by choice.
    This is the same content for a person: what was checked, what was waved
    through, and on whose written say-so. Without it the only account of why a
    task shipped with a known problem lives in a chat log that is already gone.
    """
    out = [f"# Delivery record: {validation['task_id']}", ""]
    out.append(f"Packaged {validation['packaged_at']} "
               f"from seed {validation.get('seed_version') or 'unknown'}.")
    out.append("")

    # Whether anyone delivered this task before, and whether this sandbox
    # authored it or was handed it. Placed first because it changes how
    # everything below is read: a second delivery's score is not a second
    # opinion on the first, it is a different task with the same name.
    history = validation.get("previous_deliveries") or []
    review = validation.get("review") or {}
    if history or review:
        out.append("## Provenance")
        out.append("")
        if review:
            came = ", ".join(sorted((review.get("restored_from") or {}).values()))
            out.append(f"This is a **review pass**. The task was authored "
                       f"elsewhere and moved into this sandbox on "
                       f"{review.get('at', 'an unrecorded date')}"
                       + (f" from `{came}`" if came else "") + ".")
            arrival = review.get("receipt") or {}
            broken = (arrival.get("missing") or []) + (arrival.get("mismatched") or [])
            if not arrival.get("checked"):
                out.append("It carried no receipt "
                           f"({arrival.get('why') or 'no reason recorded'}), so "
                           "nothing confirms these are the files the last "
                           "person delivered.")
            elif broken:
                out.append(f"**What arrived did not match the receipt it came "
                           f"with**: {len(broken)} file(s) missing or changed. "
                           f"Everything below describes the files as they were "
                           f"found, not as they were delivered.")
                for rel in broken:
                    out.append(f"  - `{rel}`")
            else:
                out.append("What arrived matched the receipt it came with, "
                           f"which the attempter left as `{arrival.get('verdict')}` "
                           f"on {arrival.get('at') or 'an unrecorded date'}.")
            out.append("")
        if history:
            out.append(f"Delivered {len(history)} time(s) before this one:")
            for prior in history:
                got = prior.get("reward")
                out.append(f"- {prior.get('packaged_at', 'unrecorded date')}: "
                           + (f"scored {got:.0%}" if isinstance(got, (int, float))
                              else "score unrecorded")
                           + f", {prior.get('rubric_count', '?')} criteria, "
                           f"seed {prior.get('seed_version') or 'unknown'}"
                           + (" (itself a review pass)"
                              if prior.get("review_pass") else ""))
            out.append("")
            out.append("Those records were overwritten by this delivery and "
                       "survive only as the lines above.")
        out.append("")

    scored = validation.get("solver_reward") or {}
    reward = scored.get("reward")
    out.append("## The measurement")
    out.append("")
    out.append(f"- Solver scored **{reward:.0%}**" if isinstance(reward, (int, float))
               else "- Solver score unavailable")
    # What that number is over, where it is read. A task with no suite writes no
    # unit_tests key at all, so this appears only where the score has two parts
    # -- and where it does, the headline is the two together and the rubric rate
    # on its own sits several points below it.
    units = scored.get("unit_tests")
    if isinstance(reward, (int, float)) and isinstance(units, (int, float)):
        out.append(f"  - over the criteria and the suite together: rubrics "
                   f"{scored.get('rubrics', 0):.0%}, unit tests {units:.0%}")
        ran = validation.get("unit_tests_scored")
        if isinstance(ran, dict):
            out.append(f"  - {ran.get('passed')} of {ran.get('total')} tests "
                       f"passed, {ran.get('points')} of {ran.get('of')} points")
    added = validation.get("context_added")
    if added is None:
        out.append("- Context could not be measured for this run")
    else:
        out.append(f"- Context the task put in front of the model: **{added:,}** "
                   f"tokens ({(validation.get('context_band') or '').replace('_', '-')})")
        out.append(f"  - peak {validation['context_peak']:,}, "
                   f"harness {validation['context_baseline']:,}, "
                   f"of which roughly {validation.get('context_from_files') or 0:,} "
                   f"came back from the workspace")
    out.append(f"- Graded run: `{validation['graded_job']}`")
    observed = validation.get("solver_model_observed") or []
    asked = validation.get("solver_model_requested") or "unrecorded"
    if validation.get("solver_model_check") == "mismatch":
        out.append(f"- **Answered by {', '.join(observed)}, not by the {asked} "
                   f"this run asked for.** The score above is that model's.")
    elif observed:
        out.append(f"- Answered by {', '.join(observed)}")
    else:
        out.append(f"- Model asked for: {asked} (the transcript names none)")
    difficulty = validation.get("prompt_check") or {}
    if difficulty.get("verdict") == "UNMEASURED":
        out.append("- The prompt's difficulty could not be checked before the "
                   f"run ({difficulty.get('why', 'no reason recorded')})")
    elif difficulty.get("verdict"):
        out.append(f"- Prompt read as **Level {difficulty.get('level')}** before "
                   f"the run ({difficulty['verdict']}"
                   + (f", by {difficulty['model']}" if difficulty.get("model") else "")
                   + "); a non-expert working out "
                   f"what it asks: {difficulty.get('comprehension') or 'not said'}, "
                   f"spotting a wrong answer: "
                   f"{difficulty.get('answer_check') or 'not said'}")
        kind = difficulty.get("hardness")
        described = prompt_check.taxonomy.HARDNESS.get(kind)
        if described:
            out.append(f"- What makes it hard: {described} (`{kind}`). Two "
                       f"prompts can share a level for different reasons; this "
                       f"is which one.")
    quality = validation.get("rubric_check") or {}
    if quality.get("verdict") == "UNMEASURED":
        out.append("- The criteria check could not run "
                   f"({quality.get('why', 'no reason recorded')})")
    elif quality.get("verdict"):
        findings = [f for f in quality.get("findings") or [] if not f.get("exempt")]
        noted = [f for f in quality.get("findings") or [] if f.get("exempt")]
        unread = quality.get("unmeasured_groups") or []
        out.append(f"- The criteria were checked{' in part' if unread else ''}: "
                   f"nothing stopped delivery; {len(findings)} finding(s) were "
                   f"shown as worth fixing and {len(noted)} noted and not counted"
                   + (f"; read by {quality['model']}" if quality.get("model") else ""))
        if unread:
            why = quality.get("unmeasured_why") or {}
            out.append("  - **Not read:** " + "; ".join(
                f"{group} ({why.get(group, 'no reason recorded')})" for group in unread)
                + ". Those categories were not checked at all.")
        for finding in quality.get("findings") or []:
            criterion = " ".join(str(finding.get("criterion") or "").split())
            named = f': "{criterion}"' if criterion else ""
            name = finding.get("label") or finding.get("name")
            status = (f" (noted, not counted: {finding['exempt']})"
                      if finding.get("exempt") else "")
            out.append(f"  - {finding.get('severity')} -- {name}{named} -- "
                       f"{finding.get('what', '')}{status}")
    standing = validation.get("rubric_line") or {}
    if standing:
        out.append("- Findings seen in every reading, with the grade applied: "
                   f"{standing.get('major', 0)} major, "
                   f"{standing.get('moderate', 0)} moderate, "
                   f"{standing.get('minor', 0)} minor, "
                   f"{standing.get('escapes', 0)} uncovered escapes")
    for ident, dispute in sorted((validation.get("disputes") or {}).items()):
        out.append(f"- **Disputed under an earlier seed**: {dispute.get('name')} on "
                   f"\"{' '.join(str(dispute.get('criterion') or '').split())}\""
                   " (no longer changes what counts)")
        out.append(f"  - the finding: {dispute.get('what', '')}")
        out.append(f"  - the contributor: {dispute.get('reason', '')}")
        out.append(f"  - the re-check ruled {str(dispute.get('ruling')).replace('_', ' ')}: "
                   f"{dispute.get('why', '')}")
    flips = (validation.get("grade_sensitivity") or {}).get("flips") or []
    if flips:
        out.append(f"- {len(flips)} criterion(s) would put the score at the bar "
                   "or over it if the judge misread that one alone:")
        for flip in flips[:6]:
            out.append(f"  - [{flip['weight']:+d}] {flip['criterion']} "
                       f"(would score {flip['reward_if_reversed']:.0%})")
    fixed = validation.get("score_if_fixed") or {}
    if isinstance(fixed.get("reward"), (int, float)) \
            and fixed["reward"] >= fixed.get("bar", 1.0):
        out.append("- **The score rests on defects the criteria check counted.** With "
                   f"{len(fixed.get('reweighted') or {})} weight(s) moved to their "
                   f"bucket and {len(fixed.get('left_out') or [])} repeated line(s) "
                   f"left out, this run would score {fixed['reward']:.0%}, which is "
                   "not under the bar.")
    out.append(f"- {validation['rubric_count']} rubric criteria, "
               f"unit tests {validation['unit_tests']}")
    by_kind = validation.get("rubric_by_category") or {}
    if by_kind:
        # Named rather than totalled: what a task completes, what it asks
        # about, and what it must not invent are three different measurements.
        out.append("- Those criteria are "
                   + ", ".join(f"{n} {kind}" for kind, n
                               in sorted(by_kind.items(), key=lambda kv: -kv[1])))
    counted = validation.get("check_count") or {}
    if counted:
        out.append(f"- {counted['total']} checks in all against a floor of "
                   f"{counted['floor']} ({counted['rubrics']} criteria, "
                   f"{counted['tests']} unit tests)"
                   + (f", {counted['distinct']} of them separate: "
                      f"{len(counted['repeats'])} only "
                      f"repeat{'s' if len(counted['repeats']) == 1 else ''} another line"
                      if counted.get("repeats") else ""))
        for text in counted.get("repeats") or []:
            out.append(f"  - repeats another line: {text}")
    weights = validation.get("test_weights")
    if weights:
        spread = {}
        for value in weights["weights"].values():
            spread[value] = spread.get(value, 0) + 1
        counted = ", ".join(f"{spread[w]} at [{w}]" for w in sorted(spread, reverse=True))
        out.append(f"- The {weights['count']} unit tests are worth "
                   f"{weights['total']} points between them ({counted}), on the "
                   f"same total as the rubric's. The weights are the "
                   f"contributor's and are listed in "
                   f"`authoring/test_weights.md`.")
    seal = validation.get("answer_moved") or {}
    if seal.get("recorded") and seal.get("moved"):
        out.append("- **The answer was changed after the graded run started.** "
                   f"{', '.join(seal['moved'])} no longer say what they said "
                   "before the model saw the task, so the criteria may have "
                   "been fitted to what came back. Not a failure and nothing "
                   "was blocked on it; it is here to be looked at.")
        corrected = [s for s in validation.get("statements") or []
                     if s.get("file") == "ground truth" and s.get("confirmed")]
        if corrected:
            out.append(f"  - The change follows {len(corrected)} statement(s) in the "
                       "answer that a check found inaccurate and three independent "
                       "voters confirmed, listed under *Statements found "
                       "inaccurate*: correcting them is what the checks asked for.")
        for name in seal["moved"]:
            for when, text in (("before the run", (seal.get("before") or {}).get(name)),
                               ("now", (seal.get("after") or {}).get(name))):
                out.append(f"  - {name}, {when}:")
                out.append("    > " + (text or "(nothing written)")
                           .replace("\n", "\n    > "))
    elif seal.get("recorded"):
        out.append("- The answer has not moved since the graded run started"
                   + ("; the rest of the ground truth was finished afterwards"
                      if seal.get("other_sections_moved") else ""))
    elif validation.get("ground_truth_moved"):
        out.append("- **The ground truth was rewritten after the run.** The "
                   "answer this task is graded against is not the one that was "
                   "written down before the model saw it, so the criteria may "
                   "have been fitted to what came back. Not a failure and "
                   "nothing was blocked on it; it is here to be looked at.")
    elif validation.get("ground_truth_pinned"):
        out.append("- The ground truth has not moved since the run started")
    else:
        out.append("- Nothing recorded what the ground truth said when the run "
                   "started, so whether it moved cannot be answered")
    if validation.get("judge_model"):
        out.append(f"- Graded by {validation['judge_model']}")
    refused = validation.get("rubric_refused") or []
    if refused:
        out.append(f"- **{len(refused)} criterion(s) were dropped**, "
                   f"{validation.get('rubric_coverage_lost', 0.0):.0%} of the "
                   "rubric by weight. The judge's safety filter declined to grade "
                   "them, so they were left out of the bundle rather than shipped "
                   "ungraded. They remain in the authoring copy:")
        for text in refused:
            out.append(f"  > {text}")
    if validation.get("hallucination_criteria") is not None:
        quiet = validation.get("hallucination_quiet") or 0
        out.append(f"- {validation['hallucination_criteria']} hallucination "
                   f"criteria, and this run committed "
                   f"{validation.get('hallucination_fired', 0)} of the failures "
                   f"they describe")
        if quiet:
            out.append(f"  - {quiet} describe a failure this run did not commit, "
                       f"within the allowance of {st.ANTICIPATED_CAP}. Those "
                       "catch something only if another model takes the wrong "
                       "turn this one avoided:")
            for text in validation.get("hallucination_quiet_criteria") or []:
                out.append(f"    > {text}")
    out.append("")

    # Every run started on this task, not only the graded one: how many there
    # were is part of how the score came about.
    runs = validation.get("run_history") or []
    if runs:
        graded = Path(str(validation.get("graded_job") or "")).name
        counted = sum(1 for r in runs if r.get("counted"))
        out.append("## Solver runs")
        out.append("")
        out.append(f"{len(runs)} run(s) started, {counted} counted against the "
                   f"limit of {validation.get('run_limit', rg.RUN_LIMIT)}.")
        out.append("")
        for entry in runs:
            line = (f"- `{entry['job']}` {entry.get('started') or 'unrecorded'}: "
                    + ("counted" if entry.get("counted")
                       else f"not counted ({entry.get('why') or 'no reason'})"))
            if isinstance(entry.get("tokens"), int):
                line += f", {entry['tokens']:,} tokens"
            if entry["job"] == graded:
                line += " -- **the graded run**"
            out.append(line)
            confirmed = entry.get("confirmed_rerun") or {}
            if confirmed:
                out.append(f"  - started as a near-identical rerun of "
                           f"`{confirmed.get('matches')}`, confirmed by the "
                           "contributor")
            if entry.get("limit_reason"):
                out.append("  - past the limit, with the reason:")
                out.append(f"    > {entry['limit_reason']}")
        for pair in validation.get("run_laundering") or []:
            out.append(f"- **The sealed answer changed between `{pair['from']}` "
                       f"and `{pair['to']}`**, whose files were the same and "
                       f"whose prompts differ by {pair['words']} word(s). Worth "
                       "reading both runs against the answer each was sealed "
                       "with.")
        out.append("")

    # What the model was given, split the way the contributor described it.
    # Counts only: the per-file listing is materials.md, which also carries the
    # ground truth's own account of the distractors and where the two disagree.
    mat = validation.get("materials_record") or {}
    out.append("## The material")
    out.append("")
    if not mat:
        out.append("No record of which files carry the answer.")
    else:
        out.append(f"Of the workspace, {mat.get('required', 0)} file(s) were "
                   f"marked as carrying the answer and "
                   f"{mat.get('distractors', 0)} as there to be ruled out. "
                   f"That is the contributor's description of their own "
                   f"design, recorded before the answer was written, and "
                   f"nothing in the score depends on it.")
        if not mat.get("ground_truth_section"):
            out.append("")
            out.append("The ground truth names no distractors, so there is "
                       "only the one account of them.")
        out.append("")
        out.append("`authoring/materials.md` lists every file, reproduces "
                   "what the ground truth says about the distractors, and "
                   "notes where the two accounts differ.")
    out.append("")

    # The labels as answered, and what the justification check left open.
    labels = validation.get("labels") or {}
    out.append("## The labels")
    out.append("")
    if not labels:
        out.append("No labels were recorded for this task.")
    else:
        out.append(f"- Underspecified: **{labels.get('underspecified_task') or 'not answered'}**, "
                   f"level {labels.get('underspecification_level') or 'not answered'}")
        out.append(f"- Needs browsing: {labels.get('browsing_required') or 'not answered'}")
        out.append("- What went wrong: "
                   + (", ".join(labels.get("model_failure_category") or [])
                      or "not answered"))
        if labels.get("model_failure_justification"):
            out.append(f"  > {labels['model_failure_justification']}")
        out.append("- `authoring/taxonomy.json` carries these with the "
                   "underspecification justification, as the taxonomy step "
                   "takes them")
    for note in validation.get("label_notes") or []:
        out.append(f"- Noted, not blocking: {note.get('what', '')}")
    just = validation.get("justification_check") or {}
    if just.get("verdict") == "UNMEASURED":
        out.append("- The justification could not be checked "
                   f"({just.get('why', 'no reason recorded')})")
    elif just.get("verdict"):
        still = just.get("open") or []
        out.append(f"- The justification was checked ({just['verdict']}): "
                   f"{len(just.get('findings') or [])} finding(s), "
                   f"{len(still)} left open"
                   + (f"; read by {just['model']}" if just.get("model") else ""))
        if just.get("short"):
            out.append(f"  - **Read in part:** {just['short']}")
        for finding in sorted(still, key=lambda f: not f.get("serious")):
            out.append(f"  - {'**Serious:** ' if finding.get('serious') else ''}"
                       f"{finding.get('name')} -- {finding.get('what', '')}")
            if finding.get("material_quote"):
                out.append(f"    - the justification: \"{finding.get('quote', '')}\"")
                out.append(f"    - {finding.get('file') or 'the file'}: "
                           f"\"{finding['material_quote']}\"")
    out.append("")
    out += statements_markdown(validation)

    # Who checked the judge, and what they disputed. The verdict each flagged
    # criterion carried is here because it is the thing that distinguishes a
    # real misreading from a rubric reworded to get under the difficulty bar,
    # and that judgement belongs to whoever reads this rather than to the
    # command that wrote it.
    review = validation.get("grade_review")
    out.append("## The judge's verdicts")
    out.append("")
    if validation.get("grade_review_stale"):
        out.append("The verdicts were checked, but against an earlier grade "
                   "than the one delivered here. Nothing has read the judge's "
                   "reasoning on this grade.")
    elif not review:
        out.append("Not checked. Nothing has asked whether the judge read each "
                   "criterion the way it was meant, so the score rests on the "
                   "judge's reading of the wording alone.")
    else:
        flagged = [f for f in review.get("flagged") or [] if isinstance(f, dict)]
        out.append(f"Checked on {review.get('at', 'an unrecorded date')}: "
                   f"{review.get('confirmed', 0)} criterion(s) confirmed as read "
                   f"correctly, {len(flagged)} flagged.")
        if flagged:
            out.append("")
            out.append("These were flagged as misjudged and are still in the "
                       "rubric as they were graded. The verdict each carried "
                       "when it was flagged is given first:")
            for entry in flagged:
                out.append(f"  > [{entry.get('verdict', '?')}] "
                           f"[{entry.get('case', '?')}] "
                           f"{entry.get('criterion', '')}")
    out.append("")

    # Before the checks list, because a task graded by machinery that is not
    # ours is a different question from any of the checks below and a reader
    # deciding whether to trust the score needs it before they read one.
    integrity = validation.get("integrity") or {}
    findings = integrity.get("findings") or []
    out.append("## The sandbox's own files")
    out.append("")
    if not integrity:
        out.append("Not checked. This seed carries no manifest of what it "
                   "shipped, so nothing here can say whether the machinery "
                   "that produced the score is ours.")
    elif integrity.get("verdict") == "UNMEASURED":
        out.append("Could not be checked: "
                   + (integrity.get("why") or "no reason recorded") + ".")
    elif not findings:
        out.append("Every shipped file matches the seed manifest, so the run "
                   "and the score were produced by the machinery we sent.")
    else:
        outstanding = [f for f in findings if f.get("state") != "restored"]
        out.append(f"**{len(findings)} file(s) differ from the seed manifest**, "
                   + ("and are still modified." if outstanding else
                      "and have since been put back. A score produced on a "
                      "changed copy is still that copy's, which is why this is "
                      "recorded after the fact."))
        out.append("")
        for f in findings:
            out.append(f"- `{f['path']}` ({f.get('where', '?')} copy, "
                       f"{f.get('tier', '?')}, {f.get('state', '?')})")
            out.append(f"  - shipped `{(f.get('expected') or '')[:16]}`, "
                       f"found `{(f.get('actual') or 'absent')[:16]}`")
        cleared = integrity.get("evidence_cleared") or []
        if cleared:
            out.append("")
            out.append("Evidence cleared as a result: " + ", ".join(cleared) + ".")
    out.append("")

    out.append("## Checks")
    out.append("")
    for check in validation["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        out.append(f"- [{mark}] {check['check']}")
        if check.get("detail"):
            for line in check["detail"].strip().splitlines():
                out.append(f"  > {line}")
    out.append("")

    removed = validation.get("run_removed") or []
    if removed:
        out.append("## Set aside")
        out.append("")
        out.append("`run/` holds the transcript, the score and the finished "
                   "workspace. These were moved to `run_removals/`, which is "
                   "kept but is not part of what the run is read from.")
        out.append("")
        for path in removed:
            out.append(f"- `run/{path}`")
        out.append("")

    overrides = validation.get("overrides") or []
    out.append("## Overrides")
    out.append("")
    if not overrides:
        out.append("None. Every check was passed rather than acknowledged.")
    else:
        out.append("A check below was acknowledged rather than fixed. The reason "
                   "is the contributor's own, recorded when they went past it.")
        out.append("")
        for entry in overrides:
            out.append(f"- **{entry['check']}** at {entry['at']} "
                       f"(during {entry.get('step', 'unknown')})")
            out.append(f"  > {entry['reason']}")
    out.append("")

    faults = validation.get("technical_issues") or []
    out.append("## Faults in the sandbox's own tooling")
    out.append("")
    if not faults:
        out.append("None recorded.")
    else:
        out.append("Recorded as they happened, by the checks themselves or by "
                   "the assistant. None of them is a finding about the task.")
        out.append("")
        for entry in faults:
            out.append(f"- {entry.get('at', '?')} `{entry.get('kind', '?')}`"
                       + (f" in `{entry['command']}`" if entry.get("command") else "")
                       + f": {' '.join(str(entry.get('detail', '')).split())[:300]}")
            repair = entry.get("repair") or {}
            if repair:
                out.append(f"  - repaired `{repair.get('file', '?')}`: "
                           f"{repair.get('what', '')}")
    out.append("")

    notes = validation.get("advisories") or []
    if notes:
        out.append("## Steps that failed along the way")
        out.append("")
        for entry in notes:
            out.append(f"- `{entry['step']}` failed at {entry['at']} "
                       f"on: {entry['check']}")
            if entry.get("detail"):
                out.append(f"  > {entry['detail'].strip().splitlines()[0]}")
        out.append("")

    return "\n".join(out) + "\n"


def criteria_scored(results: Path) -> set[str] | None:
    """The criterion texts the judge actually returned a verdict on.

    None when the file cannot be read, which is not the same as an empty set:
    the first means there is nothing to compare and the check stands aside, the
    second means a grade that scored nothing.

    `title` is the key judge.py writes; the others are dialects a differently
    built results file may carry, and `score.rubric_statement` is the judge's
    own copy of the same text.
    """
    try:
        data = json.loads(results.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    rows = data.get("rubric_scores") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None
    out = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = row.get("score")
        text = (row.get("title") or row.get("criteria") or row.get("criterion")
                or row.get("text")
                or (score.get("rubric_statement") if isinstance(score, dict) else None))
        if isinstance(text, str) and text.strip():
            out.add(text.strip())
    return out


def criteria_refused(results: Path) -> list[dict]:
    """The criteria the judge declined to grade, with their weights.

    Kept apart from `criteria_scored`, which reads the criterion text off every
    row whether or not a verdict came back with it. Both readings are wanted:
    one asks which criteria the grade covers, this one asks which it does not.
    """
    return [row for row in _rows(results)
            if row.get("unmeasured") == "judge_refused"]


def criteria_no_score(results: Path) -> list[dict]:
    """The criteria the judge answered, but never in a form that is a verdict.

    Not a refusal: nothing declined to read these, and there is nothing wrong
    with their wording that a reviewer could see. They are apart from
    `criteria_refused` because the repair differs -- a refused criterion is
    dropped from the bundle, and one of these is not, since shipping a smaller
    rubric would be fixing the wrong thing.
    """
    return [row for row in _rows(results)
            if not _graded(row) and row.get("unmeasured") != "judge_refused"]


def _rows(results: Path) -> list[dict]:
    """The per-criterion rows, in either shape the results file comes in."""
    try:
        data = json.loads(results.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("rubric_scores") if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def coverage_lost(results: Path) -> float:
    """The share of the rubric's weight that went ungraded, for any reason.

    A refusal and a reply that never became a verdict cost the same coverage,
    so both count here. Only the remedy differs, and that is decided where this
    is read rather than in the arithmetic.
    """
    rows = _rows(results)
    total = sum(abs(int(r.get("weight", 5))) for r in rows)
    lost = sum(abs(int(r.get("weight", 5))) for r in rows if not _graded(r))
    return lost / total if total else 0.0


def _graded(row: dict) -> bool:
    """Whether a verdict came back for this criterion at all."""
    score = row.get("score")
    return isinstance(score, dict) and str(score.get("score")) in ("0", "1")


def rubrics_without(rubrics_json: Path, dropped: set[str]) -> list[dict]:
    """The rubric with the criteria the judge would not grade removed."""
    return [r for r in json.loads(rubrics_json.read_text())
            if str(r.get("criteria", "")).strip() not in dropped]


def criteria_shipped(rubrics_json: Path) -> set[str]:
    try:
        rows = json.loads(rubrics_json.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    return {r["criteria"].strip() for r in rows
            if isinstance(r, dict) and isinstance(r.get("criteria"), str)}


def negatives_shipped(rubrics_json: Path, dropped: set[str]) -> int:
    """How many of the bundle's criteria are hallucination criteria.

    Counted off the delivered label, falling back to the weight's sign where a
    criterion carries none, which is how grade_report.kind() places one. A
    negative under Clarification is not one of these: choosing silently
    fabricates nothing.
    """
    out = 0
    for row in rubrics_without(rubrics_json, dropped):
        if not isinstance(row, dict) or int(row.get("weight", 5)) >= 0:
            continue
        labels = row.get("type") or []
        first = labels[0] if labels and isinstance(labels[0], str) else ""
        if first in ("", "hallucination"):
            out += 1
    return out


def clarification_shipped(rubrics_json: Path, dropped: set[str]) -> tuple[int, int]:
    """The bundle's Clarification criteria: how many are positive, and in all."""
    positive = total = 0
    for row in rubrics_without(rubrics_json, dropped):
        labels = row.get("type") or []
        if labels and labels[0] == "clarification":
            total += 1
            positive += int(row.get("weight", 5)) > 0
    return positive, total


def criteria_by_category(rubrics_json: Path) -> dict:
    """How many shipped criteria of each kind, off the first delivered label.

    A count per kind rather than a total, because each kind answers a
    different question about the task and a reviewer reading the record cannot
    get them back out of one number. Counted off whatever labels are present
    rather than against a list, so a section added to the compiler is recorded
    without this needing to know about it.
    """
    try:
        rows = json.loads(rubrics_json.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        labels = row.get("type") or []
        kind = labels[0] if labels and isinstance(labels[0], str) else "unlabelled"
        out[kind] = out.get(kind, 0) + 1
    return out


def run_history(root: Path, state: dict) -> list[dict]:
    """Every run started on this task, as the delivery record carries them."""
    out = []
    for entry in rg.runs(root, state):
        out.append({"job": entry["job"], "started": entry.get("started"),
                    "counted": entry["counted"], "why": entry["why"],
                    "model": entry.get("model"),
                    "tokens": (entry.get("tokens") or {}).get("total"),
                    "sealed_sha256": entry.get("sealed_sha256"),
                    "confirmed_rerun": entry.get("confirmed_rerun"),
                    "limit_reason": entry.get("limit_reason")})
    return out


def model_record(state: dict, job: Path, transcript: Path | None) -> dict:
    """The model fields of the delivery record, about the delivered run.

    Read from the job's own record and its own transcript, not from the
    last-run fields, which a run started after the grade rewrites.
    """
    asked = mc.requested(state, job) or {}
    observed = mc.observed_models(transcript) if transcript else []
    return {
        "solver_model_requested": asked.get("model"),
        "solver_model_configured": (mc.configured() or {}).get("model"),
        "solver_model_observed": observed,
        "solver_model_check": mc.verdict(asked.get("model"), observed),
        "solver_agent": asked.get("agent"),
    }


def is_trial(path: Path) -> bool:
    """Whether a directory is a Harbor trial: it holds the run's output.

    The test is for `agent/` or `verifier/` themselves, not for a directory
    named `logs`. A real 0.20.0 job has `<trial>/artifacts/logs/`, which under
    the looser test looked exactly like a nested-layout trial and was picked
    whenever its mtime happened to be the later one -- resolving to a directory
    with no transcript in it, which is the empty-answer 0.0 this file already
    guards against everywhere else.
    """
    inner = path / "logs" if (path / "logs").is_dir() else path
    return (inner / "agent").is_dir() or (inner / "verifier").is_dir()


def find_run(job_dir: Path) -> Path | None:
    """The most recent trial directory under a Harbor job.

    A trial is identified by holding the agent's or the verifier's output,
    however deep that sits -- see `trial_logs()` for why that varies.

    `solver_answer.resolve_trial()` is asked first, so the trial packaged here
    is the one whose transcript and workspace every other reader resolves. The
    scan below runs only when no transcript exists anywhere in the job, which is
    a run that produced none rather than a choice between attempts.
    """
    chosen = sa.resolve_trial(job_dir)
    if chosen is not None:
        return chosen
    # A trial directory handed in directly is that trial. rglob starts below
    # `job_dir`, so without this the one thing that is certainly a trial is the
    # one thing that could never be chosen.
    if is_trial(job_dir):
        return job_dir
    # `logs` itself is never the trial. Under the nested layout it holds both
    # `agent/` and `verifier/` and so matches the same test its parent does,
    # and picking it would name the run "logs" everywhere a run is named.
    candidates = [p for p in job_dir.rglob("*")
                  if p.is_dir() and p.name != "logs" and is_trial(p)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def trial_logs(trial: Path) -> Path:
    """Where `agent/` and `verifier/` live inside a trial.

    Harbor 0.20.0 writes them straight into the trial directory. Something
    else, or an earlier version, nests them under `logs/`. This looked for the
    nested form only, so on a real run the agent mount was silently skipped and
    the judge graded an empty answer -- every criterion failing, a reward of
    0.0, and nothing about it distinguishable from a model that got everything
    wrong. Which is the worst way for this to break, so it checks for both.
    """
    return trial / "logs" if (trial / "logs").is_dir() else trial


def trajectory_file(agent_logs: Path) -> Path | None:
    """The transcript inside a trial's agent log directory.

    Harbor 0.20.0 writes `trajectory.json`. Delivery packages whatever this
    resolves rather than looking the names up a second time, so a run accepted
    here is a run whose transcript ships. `agent.log` is not among the names --
    it is a log of the run rather than the record of what the agent said, and no
    answer can be read out of it.
    """
    for name in ("trajectory.json", "trajectory.jsonl"):
        if (agent_logs / name).is_file():
            return agent_logs / name
    return None


def prune_bundle_tests(bundle_tests: Path, skipped: bool) -> None:
    """Remove from the copied tests/ what grading the bundle does not read.

    The source Markdown is working material; the .json compiled from it is what
    the judge and the test runner read. A skipped suite leaves neither the
    verifier nor its weights, rather than an empty stub.
    """
    leaving = ["rubrics.md", "test_weights.md"]
    if skipped:
        leaving += ["verifier.py", "test_weights.json"]
    for name in leaving:
        (bundle_tests / name).unlink(missing_ok=True)


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(*BUNDLE_EXCLUDE),
        dirs_exist_ok=True,
    )


def copy_sources(env: Path) -> list[str]:
    """Paths inside environment/ that the Dockerfile's COPY lines name."""
    dockerfile = env / "Dockerfile"
    if not dockerfile.exists():
        return []
    sources = []
    for line in re.findall(r"^COPY\s+(.+)$", dockerfile.read_text(), re.M):
        parts = [p for p in line.split() if not p.startswith("--")]
        sources += [s.rstrip("/") for s in parts[:-1]]   # the last is the destination
    return sources


def missing_copy_sources(env: Path) -> list[str]:
    """COPY sources the bundle's Dockerfile names but does not contain.

    The clean rebuild proves the task directory builds; this proves the same of
    the directory that is actually shipped. A file excluded on its way into the
    bundle is invisible until somebody else runs docker build.
    """
    if not (env / "Dockerfile").exists():
        return ["Dockerfile"]
    return [s for s in copy_sources(env) if not (env / s).exists()]


def set_aside(tree: Path, keep: list[str], removals: Path) -> list[str]:
    """Move every file in tree that no keep path covers into removals/.

    A keep entry is a path relative to tree and covers the file itself or, for a
    directory, everything under it. Directories left empty are removed. Returns
    the paths that were moved, relative to tree.
    """
    prefixes = [tuple(k.strip("/").split("/")) for k in keep]
    moved = []
    for src in sorted(p for p in tree.rglob("*") if p.is_file()):
        rel = src.relative_to(tree).parts
        if any(rel[:len(prefix)] == prefix for prefix in prefixes):
            continue
        dst = removals.joinpath(*rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append("/".join(rel))
    for directory in sorted((p for p in tree.rglob("*") if p.is_dir()),
                            key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return moved


def unit_weights(root: Path) -> dict:
    """What each unit test is worth, as tests/test_weights.json records it.

    None when there is no suite or nothing was compiled, which is not the same
    as a suite whose tests are all worth nothing.
    """
    weights = tw.compiled(root)
    if not weights:
        return None
    return {"total": sum(weights.values()), "count": len(weights),
            "weights": dict(sorted(weights.items()))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--job", default=None, help="the Harbor job directory to take the run from")
    ap.add_argument("--keep-image", action="store_true")
    ap.add_argument("--json", action="store_true")
    # Only the checks that can fail when the measurement fails, never one about
    # the task itself.
    ap.add_argument("--acknowledge", choices=["context_unmeasured"], default=None,
                    help="go past a check that could not be evaluated, with a reason")
    ap.add_argument("--reason", default="")
    args = ap.parse_args()

    root = st.task_root(args.task)
    if args.acknowledge:
        try:
            st.record_override(root, args.acknowledge, args.reason, "deliver")
        except ValueError as exc:
            print(f"  {exc}", file=sys.stderr)
            return 2
        print(f"  recorded: {args.acknowledge} acknowledged.")
    state = st.load(root)
    checks: list[dict] = []
    started = time.time()

    def record(name: str, ok: bool, detail: str = "") -> bool:
        # `detail` is what to do about the check having failed, so it is only
        # kept when it did. Recorded against a check that passed it reads as a
        # contradiction, in the one file a reviewer reads instead of watching
        # this run.
        checks.append({"check": name, "passed": bool(ok),
                       "detail": detail if not ok else ""})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if detail and not ok:
            for line in detail.strip().splitlines()[-20:]:
                print(f"         {line}")
        return ok

    # Everything generated is rewritten first, so a stale task.toml or
    # Dockerfile cannot be what gets delivered.
    st.regenerate(root)

    print("Checking the task is complete...")

    # The whole manifest rather than one step's slice, and here rather than in
    # a gate somewhere later, because this is the last moment the answer can
    # be written into a record that travels with the task.
    integrity, integrity_stops = ci.check(root, st.FLC_HOME, "deliver")
    integrity_entry = integrity.get("recorded") or {}
    integrity_history = integrity_entry.get("findings", integrity["findings"])
    if not integrity["measured"]:
        # An older seed carries no manifest, and our own failure to write one
        # must not read as a finding about somebody's task.
        record("the sandbox's own files could not be checked (recorded, not "
               "blocking)", True)
    elif integrity_stops:
        record("the grading machinery is the one the seed shipped", False,
               "\n".join("  - " + ci.describe(f) for f in integrity_stops)
               + "\n\nThe score would be one this copy produced rather than one "
                 "the seed's did.\nPut the originals back with "
                 "/flc-restore-tools, then grade again.")
    elif integrity_history:
        # Not blocking, and named so the row itself says what happened: a
        # passing check called "the machinery is the seed's" would be a lie in
        # the one file a reviewer reads instead of watching this run.
        record("part of the sandbox was modified (recorded, not blocking)", True)
    else:
        record("the sandbox's own files are the ones the seed shipped", True)

    record("the prompt is written", bool(st.contributor_prompt(root)))
    rubrics_json = root / "tests" / "rubrics.json"
    record("rubrics are built", rubrics_json.exists(),
           "Run /flc-rubrics first." if not rubrics_json.exists() else "")

    # Asked again here rather than left to the grade. /flc-grade refuses below
    # the floor, but a criterion can be deleted afterwards, and doing so is
    # rubric drift that the grade freshness check reports as a stale score
    # rather than as a rubric that is now too small.
    counted = st.check_count(root)
    short = f"{counted['rubrics']} criteria"
    if counted["tests"]:
        short += f" and {counted['tests']} unit tests"
    record(f"the task carries at least {counted['floor']} checks",
           counted["enough"],
           f"{short} -- {counted['total']} in all.\n"
           "A score over this few says where the answer landed and not how it "
           "got there.\nAdd checks for the steps the answer depended on, then "
           "grade again:\n/flc-rubrics, then /flc-grade.")
    separate = rubric_check.distinct(root, state)
    if separate["repeats"] and counted["enough"]:
        n = len(separate["repeats"])
        record(f"at least {separate['floor']} separate checks",
               separate["distinct_enough"],
               f"Your rubric has {separate['rubrics']} lines"
               + (f" and {separate['tests']} unit tests" if separate["tests"] else "")
               + f", but {n} only repeat{'s' if n == 1 else ''} what another line "
               f"checks, so {separate['distinct']} count:\n"
               + "\n".join(f'  "{t}"' for t in separate["repeats"])
               + "\nAdd a line for something your prompt asks that no line covers "
               "yet, a hallucination criterion from the run, or a hard trajectory "
               "line.")

    # A suite is graded when tests/verifier.py is on disk: test.sh exports
    # FLC_VERIFIER="$TESTS/verifier.py" and run_verifier.py decides on that path
    # existing, and nothing in that chain reads the state. So the file decides
    # what happens and the flag says what was meant, and the two have to agree.
    # An absence either way counts as skipped, so nothing here can ship or check
    # a suite the contributor said to do without.
    verifier = root / "tests" / "verifier.py"
    meant_to_skip = state.get("unit_tests") == "skipped"
    skipped = meant_to_skip or not verifier.exists()

    # The steps that have to have run before delivery. Each one is the only
    # thing that asks its question, so these gate rather than warn.
    done = set(state.get("steps_done") or [])
    failed = state.get("steps_failed") or {}
    mandatory = [("check_inputs", "/flc-check-inputs")]
    if not skipped:
        # A task grading by rubrics alone has no suite for this step to run.
        mandatory.append(("check_tests", "/flc-check-tests"))
    for step, command in mandatory:
        note = failed.get(step)
        record(f"{command} has been run and passed", step in done,
               (f"{command} ran at {note['at']} and failed on: {note['check']}.\n"
                f"{note.get('detail', '')}\n"
                f"Fix what it reported and run it again."
                if note else
                f"{command} has never been run, so nothing has checked what it "
                f"checks.\nRun it now."))

    # Passing it is not enough, for the reason the prompt check below is asked
    # a second time: the workspace can be edited afterwards, and the run and
    # grade can then be taken again so that every other freshness check is
    # satisfied while this one is not. Regenerate() above has already refreshed
    # the manifest this compares.
    if "check_inputs" in done:
        inputs_entry, inputs_current = check_inputs.recorded(root, state)
        if inputs_entry is None:
            record("the workspace being delivered is the one that was checked",
                   False,
                   "/flc-check-inputs passed, but the record does not say which "
                   "workspace it\nlooked at, so nothing can tell whether the "
                   "material has changed since.\nRun /flc-check-inputs.")
        elif not inputs_current:
            record("the workspace being delivered is the one that was checked",
                   False,
                   f"environment/workspace/ has changed since /flc-check-inputs "
                   f"passed at\n{inputs_entry['at']}. The bundle would ship "
                   f"material nothing has\nlooked at. Run /flc-check-inputs.")
        else:
            record("the workspace being delivered is the one that was checked",
                   True)

    # The difficulty verdict, against the prompt actually being shipped.
    # /flc-check-inputs asks the same question, and passing it is not enough:
    # the prompt can be edited afterwards, and if the solver is run and graded
    # again every other freshness check is satisfied while this one is not.
    prompt_entry, prompt_current = prompt_check.recorded(
        state, st.contributor_prompt(root))
    if prompt_entry is None:
        record("the prompt was checked for difficulty", False,
               "/flc-prompt-check has never been run, so nothing has asked "
               "whether\nsomeone outside this field could work out what the "
               "prompt is asking.\nRun /flc-prompt-check.")
    elif not prompt_current:
        record("the prompt being delivered is the one that was checked", False,
               f"The recorded verdict was {prompt_entry['verdict']}, taken "
               "against an earlier\nversion of prompt.md. The bundle would ship "
               "a prompt nothing has\nchecked. Run /flc-prompt-check.")
    elif prompt_entry["verdict"] == "FAIL":
        record("the prompt clears the difficulty bar", False,
               f"{prompt_entry.get('why', '')}\n"
               "Edit prompt.md so answering it takes someone in this field, run\n"
               "/flc-prompt-check again, and rerun the solver against the new "
               "prompt.")
    elif prompt_entry["verdict"] == "UNMEASURED":
        # Not a gate. The score below is the measurement this predicts, and it
        # is already in hand by the time delivery runs, so demanding a written
        # excuse for a failed predictor would be asking for the wrong thing.
        record("the prompt's difficulty could not be checked (recorded, not "
               "blocking)", True)
    else:
        record(f"the prompt clears the difficulty bar "
               f"({prompt_entry['verdict']}, Level {prompt_entry.get('level')})",
               True)

    if skipped:
        # Two ways to reach this and they are different mistakes. A suite still
        # under its own name would be graded and shipped against a decision to
        # do without it; a suite nowhere at all, with nothing saying that was
        # meant, is a task that lost its tests.
        record("the suite that was skipped is out of the graded path",
               not verifier.exists(),
               "tests/verifier.py is on disk while this task is marked as graded "
               "by rubrics\nalone. What runs the tests looks at that file and "
               "nothing else, so it would be\ngraded and shipped with the task "
               "-- on a task that asked for no suite, that\nmeans the template's "
               "own examples failing against files nobody wrote.\n"
               "Run /flc-skip-tests to set it aside, or /flc-enable-tests and "
               "then\n/flc-check-tests if it should count after all. Either way "
               "/flc-grade again,\nbecause the score moves.")
        record("grading by rubrics alone was a decision", meant_to_skip,
               "There is no tests/verifier.py, so nothing would be graded from a "
               "suite, and\nnothing recorded that as a choice. Run "
               "/flc-skip-tests to grade by rubrics\nalone, or write the suite "
               "and run /flc-check-tests.")
        if (root / "tests" / "verifier.py.skipped").exists():
            print("  (unit tests are skipped -- the suite set aside as "
                  "verifier.py.skipped will be left out)")
    else:
        # The state's own account of itself, which the file's existence does not
        # give: a template copied into place exists and is written by nobody.
        record("the unit tests have been written, not left unwritten",
               state.get("unit_tests") != "unwritten",
               "tests/verifier.py has never been written. Write it, or run "
               "/flc-skip-tests\nto grade by rubrics alone -- an unwritten suite "
               "ships as scored criteria nobody wrote.")
        # Repeated from /flc-check-tests, which can be passed and the file
        # edited afterwards. These tests ship and are graded on every run.
        record("the unit tests are not still the template", not ct.untouched(verifier),
               "tests/verifier.py is the template, byte for byte. Every check in "
               "it is about\nan example task, so each one would fail here and cost "
               "the model points for\nwork nobody asked for. Write your own, or run "
               "/flc-skip-tests.")
        leftovers = ct.template_examples(verifier)
        record("the unit tests are yours, not the template's examples",
               not leftovers,
               "still defined: " + ", ".join(leftovers) + ".\nThey check a "
               "prediction file, an evidence file and a manifest belonging to the "
               "example task in the template, so every run of this bundle would "
               "lose those points to work nobody asked for. Delete them, or run "
               "/flc-skip-tests." if leftovers else "")
        # Also repeated from /flc-check-tests. A parametrized test is several
        # tests under names that move, and the weight that scores each one is
        # set per name.
        generated = [item["name"] for item in tw.parametrized(verifier)]
        record("no unit test is parametrized",
               not generated,
               "parametrized: " + ", ".join(generated) + ".\nEach is several "
               "tests under names that change whenever the list of cases is "
               "edited,\nand a weight is set per name. Write the cases out as "
               "separate tests." if generated else "")
        # The weights are compiled from tests/test_weights.md, and a stale
        # compile would score the run against numbers nobody can see.
        wanted = tw.intended(root)
        record("the weights being shipped are the ones in tests/test_weights.md",
               wanted is None or wanted == tw.compiled(root),
               "tests/test_weights.md has been edited since the weights were "
               "compiled, so\nthe score is against numbers that are no longer "
               "written down. Run\n/flc-check-tests --weights-only, then "
               "/flc-grade." if wanted is not None else "")
        stray = ct.unrelated_paths(verifier, root)
        record("the unit tests read files this task has",
               not stray,
               "tests/verifier.py reads " + ", ".join(stray[:6]) + ".\nNone of "
               "them is in environment/workspace/ and none is named in prompt.md, "
               "so\nthose checks can only fail. Point them at your own material, "
               "or ask for\nthe file in prompt.md if the model is meant to write "
               "it." if stray else "")

    if not all(c["passed"] for c in checks):
        return finish(root, checks, None, args.json, started)

    # --- 1. the grade ---------------------------------------------------------
    #
    # Every check in this section is free, so they come before the rebuild: a
    # rubric edited after grading should cost a second to find out about, not
    # five minutes of docker build first.
    graded_job = state.get("last_graded_job")
    if args.job:
        job = Path(args.job).resolve()
        if graded_job and Path(graded_job).resolve() != job:
            record("the run being delivered is the one that was graded", False,
                   f"{job}\nhas not been graded -- the score on record belongs to "
                   f"{graded_job}.\nGrade this one first:  /flc-grade --job {job}")
            return finish(root, checks, None, args.json, started)
    else:
        job = Path(graded_job) if graded_job else None

    if not record("the run has been graded",
                  bool(graded_job) and job is not None and job.exists(),
                  "No graded run. The score is taken here rather than measured, so\n"
                  "there has to be one: run /flc-grade."):
        return finish(root, checks, None, args.json, started)

    trial = find_run(job)
    if trial is None:
        record("there is a solver run to deliver", False,
               f"No finished run inside {job}.")
        return finish(root, checks, None, args.json, started)

    # Each attempt of a multi-attempt job is a separate trial carrying its own
    # transcript, its own finished workspace and its own verifier results. The
    # delivery ships one transcript and one workspace and reports one score, so
    # a job holding several is refused rather than resolved: which attempt the
    # grade belongs to is not recorded anywhere, and a reviewer reading the
    # shipped run cannot tell that a choice was made.
    attempts = sa.trials(job)
    if len(attempts) > 1:
        record("the run being delivered is a single attempt", False,
               f"{job} holds {len(attempts)} attempts "
               f"({', '.join(p.name for p in attempts)}).\n"
               "Each is a different run, with its own answer and its own files, "
               "and this\n"
               "delivery ships one of each. Nothing on record says which "
               "attempt the score\n"
               "was taken from.\n"
               "  Run the solver again as a single attempt, then grade it:\n"
               "    /flc-run-solver\n"
               "    /flc-grade\n"
               "No criterion has to change, and nothing you wrote is affected.")
        return finish(root, checks, None, args.json, started)
    record(f"found the solver run ({trial.name})", True)

    # run_solver.sh takes --model and --agent over bin/solver_model.txt for one
    # run, and a score is a score of whatever the run asked for.
    asked = mc.requested(state, job)
    setup = mc.configured()
    if asked is None or setup is None:
        record("which model the run was started with is not recorded "
               "(recorded, not blocking)", True)
    else:
        differs = mc.overridden(asked, setup)
        said = "".join(f"  {key}: the run asked for {asked[key]}, and this "
                       f"sandbox is set up for {setup[key]}\n" for key in differs)
        if not record("the run used the model this sandbox is set up for",
                      not differs,
                      f"{said}"
                      "A run started with --model or --agent is for comparing, "
                      "and its score\nbelongs to what it asked for, not to the "
                      "model this task is measured\nagainst. Run the solver "
                      "again without them, read the new run, then\ngrade it:\n"
                      "    /flc-run-solver, then /flc-inspect, then /flc-grade\n"
                      "Your prompt, files and ground truth stand. The "
                      "hallucination criteria\nwere written from the other run, so "
                      "check them against the new one."):
            return finish(root, checks, None, args.json, started)

    trial_out = trial_logs(trial)
    agent_logs = trial_out / "agent"
    verifier_dir = trial_out / "verifier"

    # Whether there is a score at all is read from the summary's status rather
    # than from the number: a deferred run and an unreachable gateway both
    # leave a zeroed reward.json.
    summary = read_json(verifier_dir / "grading_summary.json")
    status = summary.get("status")
    if not record("the run was graded, not deferred", status == "graded",
                  {"deferred": "This run has not been scored yet: the run itself "
                               "scores nothing.\nRun /flc-grade.",
                   "error": "The last grade did not finish: "
                            + str(summary.get("reason") or "no reason recorded")
                            + ".\nNothing was measured, so there is no result to "
                              "deliver. Run /flc-grade again.",
                   None: "No grading summary in the run's logs. Run /flc-grade."
                   }.get(status, f"The last grade reported status {status!r}. "
                                 "Run /flc-grade again.")):
        return finish(root, checks, None, args.json, started)

    reward = read_json(verifier_dir / "reward.json")
    if not record("the grade produced a score", bool(reward),
                  f"No readable reward.json in {verifier_dir}. Run /flc-grade."):
        return finish(root, checks, None, args.json, started)

    # Does that score still describe this task? Two questions with two
    # different answers, so they are asked separately: the rubric is allowed to
    # move after the run and not after the grade, while the prompt and the
    # material are not allowed to move after either.
    current = st.fingerprint(root)

    def what(keys: list[str]) -> str:
        return ", ".join(st.drift_names(root, keys) or keys)

    seen = st.fingerprint_drift(state.get("run_fingerprint"), current, st.RUN_INPUTS)
    if not record("the model was shown the task being delivered", not seen,
                  what(seen) + " changed after the solver ran.\n"
                  "The bundle would ship one task and the evidence for it would be a\n"
                  "run of another. Run /flc-run-solver again, then /flc-grade."
                  if seen else ""):
        return finish(root, checks, reward, args.json, started)

    judged = st.fingerprint_drift(state.get("grade_fingerprint"), current,
                                  st.GRADE_ONLY_INPUTS)
    if judged == ["unit_tests"] and skipped:
        judged_detail = ("The unit tests were set aside after the grade, so the "
                         "score on record still\ncounts them. Run /flc-grade again "
                         "to score this task by its rubric alone.")
    else:
        judged_detail = (what(judged) + " changed after the "
                         "grade.\nThe score on record is of the earlier criteria. "
                         "Run /flc-grade again\nto score the ones being delivered.")
    if not record("the score is of the rubric being shipped", not judged,
                  judged_detail if judged else ""):
        return finish(root, checks, reward, args.json, started)

    # The score's own parts against what the bundle carries. Every route into a
    # disagreement found so far also moves a digest above, so this asks the
    # question of the evidence rather than of the files: a reward carrying
    # points for a suite the bundle does not carry is a number over a rubric
    # nobody can re-take, and it is the number the difficulty bar read.
    units = summary.get("unit_tests")
    scored_tests = (units.get("total") or 0) if isinstance(units, dict) else 0
    if not record("the score counts only tests that are being shipped",
                  not (scored_tests and skipped),
                  f"The score on record counts {scored_tests} unit tests and no "
                  "suite is being shipped:\nthere is no tests/verifier.py, so the "
                  "task is graded on the rubric alone.\nThose points are part "
                  "of the score the difficulty bar was checked against.\n"
                  "Run /flc-grade to score this task the way it will be graded."
                  if scored_tests and skipped else ""):
        return finish(root, checks, reward, args.json, started)

    # The rubric's own quality, against the criteria actually being shipped.
    # Same four outcomes as the difficulty verdict, and for the same reason: the
    # criteria can move after the check passed, and a verdict taken against an
    # earlier set describes a rubric nobody is shipping.
    #
    # It sits after the grade freshness checks rather than beside the difficulty
    # one because a criterion edit moves the score and this review together, and
    # of the two the score is what has to be retaken. A contributor told only
    # that the review is stale would run /flc-check-rubric, deliver again, and
    # find the grade waiting.
    # Why the recorded answer is the only one an expert could reach. Asked
    # before the rubric review rather than after, because the two repairs are
    # different sizes: a rubric finding is a line to reword, and this one can
    # be the task needing material or a level. A contributor told to fix both
    # at once should hear the larger one first.
    #
    # No --acknowledge. Every remedy adds -- name the determiner, close the
    # path, add the material, make the gap deliberate -- so acting on a
    # finding that turns out to be wrong cannot damage a task that was
    # already sound.
    just_entry, just_current = jc.recorded(state, root)
    just_name = st.justification_file(root).relative_to(root).as_posix()
    if just_entry is None:
        record("the ground truth was shown to be the only defensible answer",
               False,
               "/flc-check-justification has never been run, so nothing has "
               f"asked whether\n{just_name} names what forces your answer, "
               "or whether\nanother path an expert could take is still open. "
               "Run /flc-check-justification.")
        return finish(root, checks, reward, args.json, started)
    if not just_current:
        if just_entry.get("justification_sha256") != jc.digest(root):
            against = f"an earlier\nversion of {just_name}"
        elif jc.labels_moved(just_entry, root):
            against = (f"different answers under the first three headings "
                       f"of\n{lb.LABELS}, which the justification is read against")
        else:
            against = ("an earlier version of your files, which the "
                       "justification is\nread against")
        record("the justification being delivered is the one that was checked",
               False,
               f"The recorded verdict was {just_entry['verdict']}, taken "
               f"against {against}. Run /flc-check-justification.")
        return finish(root, checks, reward, args.json, started)
    just_blocking = just_entry.get("blocking") or []
    if just_blocking:
        named = "\n".join(f"  - {f.get('name')}: {f.get('what', '')}"
                          for f in just_blocking[:6])
        record("the justification carries no defect that has to be answered",
               False,
               f"{len(just_blocking)} finding(s) were found again on a second "
               "reading:\n" + named
               + "\nNone of them asks you to weaken your answer. Name the "
                 "determiner, close the\npath, add the material that closes "
                 "it, or make the gap deliberate so that\nstating the "
                 "assumption or asking is the expected answer. Then run\n"
                 "/flc-check-justification again.")
        return finish(root, checks, reward, args.json, started)
    if just_entry["verdict"] == "UNMEASURED":
        record("the justification could not be checked (recorded, not "
               "blocking)", True)
    else:
        record(f"the ground truth was shown to be the only defensible answer "
               f"({just_entry['verdict']}, "
               f"{len(just_entry.get('findings') or [])} finding(s) reported)",
               True)
        just_open = sorted(just_entry.get("open") or [],
                           key=lambda f: not f.get("serious"))
        if just_open:
            print(f"         {len(just_open)} still open in {just_name}, each a "
                  "common issue in this project:")
            for finding in just_open[:4]:
                print(f"           - {'serious: ' if finding.get('serious') else ''}"
                      f"{finding.get('name')}: "
                      f"{str(finding.get('what', ''))[:90]}")
            print("         Fix them unless a finding is wrong, then "
                  "/flc-check-justification.")

    # The criteria, as /flc-check-rubric recorded them. Read, never asked again:
    # the record holds while nothing it read has moved, and the grade is
    # applied to it by code. Findings that stop delivery stop it until fixed.
    state = st.load(root)
    rubric_entry = state.get(rubric_check.STATE_KEY) or {}
    if not rubric_entry.get("verdict"):
        record("the criteria have been checked", False,
               "/flc-check-rubric has not been run on these criteria.\n"
               "Run /flc-check-rubric, then deliver again.")
        return finish(root, checks, reward, args.json, started)
    if not rubric_check.current(state, root):
        record("the criteria were checked after their last change", False,
               "Something /flc-check-rubric reads changed after it last ran: the "
               "criteria, the prompt,\nthe ground truth, the files or the run.\n"
               "Run /flc-check-rubric, then deliver again.")
        return finish(root, checks, reward, args.json, started)
    rubric_standing = rubric_check.standing(root, state, rubric_entry)
    rubric_listed = rubric_check.items(state, rubric_entry, root)
    rubric_stop = rubric_check.stopping(state, rubric_entry, root)
    if rubric_entry.get("verdict") == "UNMEASURED":
        record("the criteria could not be checked (recorded, not blocking)", True)
    elif rubric_stop:
        named = "\n".join(
            f"  {n}. {i['label']}"
            + (f'\n     "{i["criterion"][:110]}"' if i["criterion"] else "")
            for n, i in enumerate(rubric_stop[:10], 1))
        record("nothing in the criteria stops delivery", False,
               f"{len(rubric_stop)} finding{'' if len(rubric_stop) == 1 else 's'} "
               f"in your criteria stop delivery:\n{named}\n"
               "/flc-check-rubric explains each one and how to fix it. Fix them in\n"
               "tests/rubrics.md, run /flc-rubrics, /flc-check-rubric and "
               "/flc-grade,\nthen deliver again.")
        return finish(root, checks, reward, args.json, started)
    elif rubric_entry.get("unmeasured_groups"):
        record("nothing in the criteria stops delivery (checked in part: "
               f"{', '.join(rubric_entry['unmeasured_groups'])} could not be read; "
               f"recorded, not blocking; {len(rubric_listed)} finding(s) worth "
               "fixing)", True)
    else:
        record(f"nothing in the criteria stops delivery "
               f"({len(rubric_listed)} finding(s) worth fixing)", True)

    # The answer itself, where a check found a statement in it inaccurate and
    # three independent readings confirmed it. Only a statement graded
    # material repeats stops delivery; one nothing graded uses is recorded.
    answer_found = rubric_check.answer_inaccuracies(root, state)
    if answer_found["verdict"] == "FAIL":
        named = "\n".join(
            f"  - \"{s.get('quote', '')[:110]}\"\n    {s.get('what_is_wrong', '')[:160]}"
            f"\n    repeated by: {', '.join(s.get('bears_on') or [])}"
            for s in answer_found["resting"][:6])
        record("the answer holds nothing a check shows is wrong that graded "
               "material repeats", False,
               f"Your answer states something a check shows is wrong, and graded "
               f"material repeats it:\n{named}\nFix it in {st.GROUND_TRUTH} and in "
               "everything that repeats it. Correcting the answer after the run is\n"
               "expected here and is recorded with the task. Then run "
               "/flc-check-justification,\n/flc-check-rubric and /flc-grade, and "
               "deliver again.")
        return finish(root, checks, reward, args.json, started)
    record("the answer holds nothing a check shows is wrong that graded material "
           "repeats" + (f" ({len(answer_found['unresting'])} recorded that nothing "
                        "graded repeats)" if answer_found["unresting"] else ""), True)

    # A criterion the judge did not grade is not a criterion that failed, and
    # the reward is computed over the rest -- so a rubric can quietly shrink
    # between the grade and the bundle without any number looking wrong. There
    # are two ways that happens and they are repaired differently, so they are
    # asked separately.
    results_file = verifier_dir / "evaluation_results.json"
    lost = coverage_lost(results_file)

    # First: a criterion the judge answered but never with a verdict. Not a
    # refusal -- nothing declined to read it, and there is nothing about the
    # wording a reviewer would call wrong -- so it is not dropped from the
    # bundle, which would repair the rubric instead of the criterion.
    #
    # It blocks at any weight, unlike a refusal, because an unparseable reply
    # has already been given the whole retry ladder. A row that arrives here
    # failed every attempt, so it is not a flake a rerun clears by chance.
    # There is no override, for the reason a refused criterion has none: the
    # wording is the contributor's to change. It is asked before the refusal
    # check so that the coverage figure there is refusals alone.
    no_score = criteria_no_score(results_file)
    if no_score:
        first = "; ".join(str(r.get("title", ""))[:70] for r in no_score[:3])
        if not record("every criterion came back with a verdict", False,
                      f"{len(no_score)} criterion(s) were never graded, "
                      f"{lost:.0%} of the rubric by weight:\n  {first}\n"
                      "The judge replied but never in the yes-or-no form the "
                      "criterion asks\nfor, through every retry, so the score "
                      "above is over the rest of the\nrubric rather than over "
                      "your task.\n"
                      "Grading again is worth one attempt. If it comes back the "
                      "same, the\ncriterion is most likely not a yes-or-no "
                      "question about the answer --\nreword it in "
                      "tests/rubrics.md to state one checkable fact, then "
                      "/flc-grade."):
            return finish(root, checks, reward, args.json, started)

    # Then the refusals. Under the limit the criteria are dropped from the
    # bundle, which is honest: what ships is then exactly what was graded. At
    # or above it there is too little of the rubric left to call the score a
    # measurement of the task.
    refused = criteria_refused(results_file)
    dropped_criteria = set()
    if refused:
        first = "; ".join(str(r.get("title", ""))[:70] for r in refused[:3])
        if not record("the judge graded enough of the rubric to deliver",
                      lost < st.REFUSAL_COVERAGE_LIMIT,
                      f"The judge declined to grade {len(refused)} criterion(s), "
                      f"{lost:.0%} of the rubric by weight,\nwhich is over the "
                      f"{st.REFUSAL_COVERAGE_LIMIT:.0%} limit:\n  {first}\n"
                      "Its safety filter refused the wording rather than judging "
                      "it, so the score\ncovers only part of the task. Reword "
                      "those criteria in tests/rubrics.md to\nsay the same thing "
                      "differently, then /flc-grade. The filter is not\n"
                      "consistent, so grading again is worth one attempt first."):
            return finish(root, checks, reward, args.json, started)
        dropped_criteria = {str(r.get("title", "")).strip() for r in refused}
        record(f"{len(refused)} ungraded criterion(s) dropped from the bundle",
               True, "")

    # The criteria the judge actually scored, against the criteria in the file
    # being shipped. The fingerprints above compare digests, so an unrelated
    # regenerate() clears them while leaving this wrong; this compares the
    # criteria themselves and cannot be cleared by rewriting a file.
    graded_criteria = criteria_scored(results_file)
    if graded_criteria is not None:
        graded_criteria -= dropped_criteria
    shipped_criteria = criteria_shipped(rubrics_json) - dropped_criteria
    if graded_criteria is not None:
        only_shipped = sorted(shipped_criteria - graded_criteria)
        only_graded = sorted(graded_criteria - shipped_criteria)
        if not record("every criterion being shipped is one that was graded",
                      not only_shipped and not only_graded,
                      ("not graded, but in the bundle: "
                       + "; ".join(c[:70] for c in only_shipped[:4]) + "\n"
                       if only_shipped else "")
                      + ("graded, but not in the bundle: "
                         + "; ".join(c[:70] for c in only_graded[:4]) + "\n"
                         if only_graded else "")
                      + "The score on record is of a different set of criteria than "
                        "the one\nbeing delivered. Edit tests/rubrics.md if it is "
                        "wrong, then /flc-grade."):
            return finish(root, checks, reward, args.json, started)

    # How many hallucination criteria the rubric carries, counted over the
    # bundle rather than over tests/rubrics.md. /flc-rubrics enforces the floor
    # when the rubric compiles and cannot see this: dropping a refused criterion
    # takes the bundle's count under it without moving a single digest.
    shipped_negatives = negatives_shipped(rubrics_json, dropped_criteria)
    if shipped_negatives < st.HALLUCINATION_FLOOR:
        detail = (f"{shipped_negatives} of the {st.HALLUCINATION_FLOOR} needed "
                  "are in the bundle.\n")
        if refused:
            detail += (f"{len(refused)} were dropped because the judge would not "
                       "grade them, which is\nwhat took the count under. Reword "
                       "those in tests/rubrics.md to say the same\nthing "
                       "differently, then /flc-grade.")
        else:
            detail += ("Write the rest in tests/rubrics.md under "
                       "## Non-hallucination, then\n/flc-grade.")
        if not record(f"the bundle carries {st.HALLUCINATION_FLOOR} "
                      "hallucination criteria", False, detail):
            return finish(root, checks, reward, args.json, started)

    # Then how many of them this run actually provoked. A negative criterion the
    # judge did not charge the model for describes a failure this task did not
    # compel, and a rubric made mostly of those measures what one model happened
    # to avoid rather than what the material does to a model.
    #
    # Only the criteria that were graded and are being shipped, and read through
    # the same split /flc-grade prints, which has already said this once.
    graded_rows = [r for r in _rows(results_file)
                   if str(r.get("title", "")).strip() not in dropped_criteria]
    fired, quiet = gr.fired_split(graded_rows)
    if len(quiet) > st.ANTICIPATED_CAP:
        first = "; ".join(str(r.get("title", ""))[:70] for r in quiet[:3])
        if not record(f"at most {st.ANTICIPATED_CAP} criteria describe a failure "
                      "the run did not commit",
                      False,
                      f"{len(quiet)} of your {len(fired) + len(quiet)} "
                      "non-hallucination criteria describe a failure\nthis run "
                      f"did not commit, and the allowance is {st.ANTICIPATED_CAP}:"
                      f"\n  {first}\n"
                      "The judge never charged the model for those, so they are "
                      "wrong turns your\ntask did not compel rather than ones it "
                      "recorded.\n"
                      "Only a line firing or going brings this count down, and "
                      "neither repair\nweakens a criterion that is right. Run the "
                      "solver again against material that\npulls harder towards "
                      "the wrong turns these lines describe, so that they fire,\n"
                      "or drop one you cannot point at in the answer. Then "
                      "/flc-grade."):
            return finish(root, checks, reward, args.json, started)

    # Whether anyone checked that the judge read each criterion the way it was
    # meant. Recorded and never blocking: a contributor who disagrees with
    # nothing has nothing to act on, and refusing here would strand a good task
    # on a step with no remedy. What was flagged travels into the record with
    # the verdict it was flagged under, because a task that could not clear the
    # difficulty bar and flagged only the criteria the model passed is a
    # different thing from one that found a real misreading.
    review, review_current = check_grade.recorded(state, results_file)
    flagged = [f for f in (review or {}).get("flagged") or []
               if isinstance(f, dict)]
    if review and review_current and not flagged:
        record(f"the verdicts were checked ({review.get('confirmed', 0)} "
               "confirmed)", True)
    elif review and review_current:
        record(f"{len(flagged)} criterion(s) were flagged as misjudged and not "
               "yet fixed (recorded, not blocking)", True)
        for entry in flagged[:4]:
            print(f"         [{entry.get('verdict', '?')}] "
                  f"{str(entry.get('criterion', ''))[:66]}")
        print("         /flc-check-grade names the remedy for each.")
    elif review:
        record("the verdicts were checked against an earlier grade, not this "
               "one (recorded, not blocking)", True)
    else:
        record("the verdicts have not been checked (recorded, not blocking)",
               True)
        print("         Nothing has asked whether the judge read each criterion "
              "the way\n         you meant it. /flc-check-grade does that.")

    # What the task put in front of the model, measured from the run itself and
    # checked before the difficulty bar.
    #
    # Unmeasurable is kept apart from thin: the first can be acknowledged in
    # writing, the second cannot.
    context = cr.measure(job)
    added = context["context_added"]
    if added is None:
        if not record("the run's context could be measured",
                      bool(st.overridden(state, "context_unmeasured")),
                      f"{context['why']}\n"
                      "This is a gap in the measurement rather than a fault in the "
                      "task.\nIf the task is right anyway, record why:\n"
                      '  /flc-deliver --acknowledge context_unmeasured --reason "..."'):
            return finish(root, checks, reward, args.json, started)
    elif not record(f"the task put {st.CONTEXT_ADDED_FLOOR:,} tokens or more in "
                    f"front of the model ({added:,})",
                    added >= st.CONTEXT_ADDED_FLOOR,
                    cr.summary(context)):
        return finish(root, checks, reward, args.json, started)

    # The difficulty bar, a gate on delivery rather than a warning.
    score = reward.get("reward")
    score = float(score) if isinstance(score, (int, float)) else 1.0
    if not record(f"the model scored below {st.MAX_SOLVER_REWARD:.0%} ({score:.0%})",
                  score < st.MAX_SOLVER_REWARD,
                  f"The solver scored {score:.0%}. A task it can already pass measures "
                  "nothing, so this one is not deliverable as it stands. Make it harder "
                  "-- bury the answer deeper, add material that has to be ruled out, or "
                  "ask for something the obvious shortcut does not give -- then rerun "
                  "the solver and grade it again."):
        return finish(root, checks, reward, args.json, started)

    drop = gr.weights_only_for(st.load(root), job)
    if not record("the score did not come under the bar through weights alone",
                  drop is None,
                  gr.weights_only_text(drop, score) if drop else ""):
        return finish(root, checks, reward, args.json, started)

    # The run's transcript, refused rather than skipped when it is missing.
    transcript = trajectory_file(agent_logs)
    if not record("the run's transcript is there", transcript is not None,
                  f"No trajectory under {agent_logs}.\n"
                  "There is a run here, but not the record of what the agent said,\n"
                  "so the delivery would carry no evidence of what the model did.\n"
                  "Rerun the solver, or pass --job for the run you meant."):
        return finish(root, checks, reward, args.json, started)

    # The answer read off a web page rather than worked out from the files.
    # Asked here and not only at /flc-inspect, because /flc-inspect can be
    # skipped and this is the one finding that decides whether a run is worth
    # delivering at all. The same function answers both, so the step that
    # reports it and the step that refuses on it cannot disagree.
    #
    # No --acknowledge, and none is wanted. The refusal is about this run and
    # never about the task: the remedy is /flc-block-domain and another run,
    # which loses none of the contributor's work, so a false positive costs a
    # run rather than a task. That is the same cost as a task that scored too
    # high, which is already a normal part of the job.
    try:
        lookups, requests = rr.run_lookups(root, job, transcript)
        unchecked = ""
    except Exception as exc:  # noqa: BLE001
        lookups, requests = [], None
        unchecked = type(exc).__name__
    if unchecked:
        record("whether the model looked the answer up could not be checked: "
               f"the sandbox's own check failed with {unchecked} (recorded, not "
               "blocking)", True)
    elif lookups:
        values = ", ".join(sorted({h["value"] for h in lookups}, key=float))
        hosts = sorted({h for hit in lookups for h in hit["hosts"]})
        where = ", ".join(hosts) or "the web"
        if not record("the model worked the answer out rather than looking it up",
                      False,
                      f"{values} came back from {where}, and your ground truth "
                      f"gives it as the answer.\n"
                      "It is in none of your files, in nothing the model "
                      "produced, and in the\noutput of nothing else it ran, so "
                      "this run did not derive it.\n\n"
                      "Nothing you have written is at fault and none of it is "
                      "lost. Block the site\nand run the solver again:\n"
                      + "".join(f"  /flc-block-domain {h}\n"
                                for h in (hosts or ["the-site.com"]))
                      + "  /flc-run-solver"):
            return finish(root, checks, reward, args.json, started)
    else:
        record("the model worked the answer out rather than looking it up", True)

    # The labels, held to each other, to the ground truth and to the rubric
    # being shipped. Asked again here because either can move after the steps
    # that checked them.
    label_findings = lb.check(root, "post", requests)
    positive, clarifying = clarification_shipped(rubrics_json, dropped_criteria)
    clash = lb.clarification(lb.read(root).get("underspecified_task"),
                             positive, clarifying, True)
    if clash:
        label_findings.append(clash)
    label_blocking = lb.blocking(label_findings)
    if not record(f"the labels in {lb.LABELS} read cleanly and agree",
                  not label_blocking,
                  "\n".join(f"  - {lb.HEADING.get(f.field, lb.LABELS)}: {f.what}"
                            + (f"\n    {f.fix}" if f.fix else "")
                            for f in label_blocking)
                  + f"\nFix them in {lb.LABELS}. /flc-check-justification checks "
                    "the first three and\n/flc-check-grade the last two; then "
                    "/flc-deliver again."):
        return finish(root, checks, reward, args.json, started)
    label_notes = [f for f in label_findings if not f.blocking]
    for finding in label_notes:
        print(f"         noted: {finding.what}")

    # Which single criterion, read the other way by the judge, would put the
    # score at the bar. Shown and recorded; the remedy is /flc-check-grade.
    sensitivity = gr.sensitivity(_rows(results_file), reward, st.MAX_SOLVER_REWARD,
                                 summary.get("combined"))
    if sensitivity["flips"]:
        print("         noted: if the judge misread any one of these, the score "
              "would reach the bar:")
        for flip in sensitivity["flips"][:4]:
            print(f'           [{flip["weight"]:+d}] "{flip["criterion"][:100]}" '
                  f"-> {flip['reward_if_reversed']:.0%}")
        print("         /flc-check-grade is where to check it.")

    # The score with the counted weight findings and repeated lines put right.
    fix_weights, fix_repeats = rubric_check.fixes(root, st.load(root))
    if_fixed = (gr.with_fixes(_rows(results_file), fix_weights, fix_repeats,
                              summary.get("combined"))
                if fix_weights or fix_repeats else None)
    if if_fixed is not None and if_fixed >= st.MAX_SOLVER_REWARD:
        print(f"         noted: with the weights and repeated lines the criteria check "
              f"found put right, this run would score {if_fixed:.0%}, which is not "
              "under the bar.")

    # The workspace as the model left it: the copy the verifier kept when the
    # run finished, since Harbor does not gather the directory itself.
    final_workspace = sa.finished_workspace(job)

    # --- 2. clean rebuild ----------------------------------------------------
    print("\nRebuilding the image from scratch, ignoring every cached layer.")
    print("This is the real test of whether the task is self-contained. Several minutes.")
    build_started = time.time()
    build = run(["bash", str(BIN / "build_image.sh"), str(root), "--no-cache", "--quiet",
                 "--tag", "flc-delivery-check"])
    build_secs = round(time.time() - build_started, 1)
    if not record(f"the image builds from environment/ alone ({build_secs}s)",
                  build.returncode == 0, build.stderr[-2000:]):
        return finish(root, checks, reward, args.json, started)
    tag = build.stdout.strip().splitlines()[-1]

    # --- 3. the shipped verifier runs in the shipped image -------------------
    #
    # Not a second grade. test.sh takes its deferral path, which writes the
    # crash-safe results, takes the snapshot and stops before the judge, so
    # this answers whether the tests/ being shipped run inside the image being
    # shipped. Run with `--network none`, which that path does not need.
    print("\nRunning the shipped verifier in it, short of the judge...")
    smoke_logs = root / ".flc" / "delivery_logs"
    if smoke_logs.exists():
        shutil.rmtree(smoke_logs)
    smoke_logs.mkdir(parents=True)

    mounts = ["-v", f"{root / 'tests'}:/tests:ro", "-v", f"{smoke_logs}:/logs/verifier"]
    if agent_logs.exists():
        mounts += ["-v", f"{agent_logs}:/logs/agent:ro"]
    if final_workspace is not None:
        mounts += ["-v", f"{final_workspace}:/workspace:ro"]

    smoke_started = time.time()
    smoke = run(["docker", "run", "--rm", "--network", "none", *mounts,
                 "-e", "FLC_DEFER_GRADING=1", tag, "bash", "/tests/test.sh"])
    smoke_secs = round(time.time() - smoke_started, 1)
    (smoke_logs / "verifier_stdout.txt").write_text(smoke.stdout + smoke.stderr)
    smoke_ok = (smoke.returncode == 0
                and read_json(smoke_logs / "grading_summary.json").get("status")
                == "deferred")

    if not args.keep_image:
        run(["docker", "image", "rm", "-f", tag])

    if not record(f"the shipped verifier runs in that image ({smoke_secs}s)",
                  smoke_ok,
                  (smoke.stdout[-2000:] + smoke.stderr[-1000:]).strip()
                  + "\n\ntests/test.sh did not complete inside the rebuilt image. "
                    "This file runs in\nexactly this image wherever the task "
                    "goes next, so it has to work\nbefore it ships."):
        return finish(root, checks, reward, args.json, started)

    if not all(c["passed"] for c in checks):
        return finish(root, checks, reward, args.json, started)

    # --- 4. the bundle -------------------------------------------------------
    print("\nPackaging...")
    delivery = root / "delivery"
    # Read before the directory goes. A re-delivery overwrites validation.json
    # and AUDIT.md in place, so without this nothing afterwards records that
    # the task was delivered once already, what it scored then, or that a
    # second person touched it -- which is the whole of what a review pass is.
    history = earlier_deliveries(delivery)
    if delivery.exists():
        shutil.rmtree(delivery)
    bundle = delivery / "bundle"
    bundle.mkdir(parents=True)

    for name in BUNDLE_FILES:
        shutil.copy2(root / name, bundle / name)
    for name in BUNDLE_DIRS:
        copy_tree(root / name, bundle / name)

    prune_bundle_tests(bundle / "tests", skipped)

    # A criterion the judge would not grade does not ship. Filtering the copy
    # rather than the task's own file leaves the graded digest intact, so this
    # cannot trip the drift checks above, and tests/rubrics.md still carries the
    # criterion for whoever reworks it.
    if dropped_criteria:
        (bundle / "tests" / "rubrics.json").write_text(
            json.dumps(rubrics_without(rubrics_json, dropped_criteria), indent=2) + "\n")

    absent = missing_copy_sources(bundle / "environment")
    if not record("the bundle holds every file its Dockerfile copies",
                  not absent,
                  "missing from the bundle: " + ", ".join(absent) if absent else ""):
        return finish(root, checks, reward, args.json, started)

    # Everything above checked the task directory. The bundle is a filtered copy
    # of it, and an exclusion rule acts on names rather than on the paths it was
    # written for, so the Dockerfile's COPY sources are checked again where they
    # end up.
    # Compared as criteria rather than as digests, since a dropped criterion is
    # a deliberate difference and a digest cannot tell it from an accidental one.
    bundle_criteria = criteria_shipped(bundle / "tests" / "rubrics.json")
    if not record("the rubric in the bundle is the rubric that was graded",
                  bundle_criteria == criteria_shipped(rubrics_json) - dropped_criteria,
                  "tests/rubrics.json differs between the task and the bundle by "
                  "more than\nthe criteria the judge would not grade. Something is "
                  "filtering or rewriting\nit on the way in, so the bundle would be "
                  "graded against criteria nobody\nscored."):
        return finish(root, checks, reward, args.json, started)

    # --- 5. the run ----------------------------------------------------------
    #
    # The graded run's own results, copied rather than regenerated: what
    # /flc-grade left behind, and what the checks above were made against.
    run_out = delivery / "run"
    run_out.mkdir(parents=True)
    for name in ("verifier_stdout.txt", "reward.json", "ctrf.json",
                 "evaluation_results.json", "grading_summary.json",
                 "unit_test_results.json", "test_weights.json"):
        src = verifier_dir / name
        if src.exists():
            shutil.copy2(src, run_out / name)
    shutil.copy2(transcript, run_out / transcript.name)
    for candidate in ("answer.txt", "agent.log"):
        src = agent_logs / candidate
        if src.exists():
            shutil.copy2(src, run_out / candidate)
    if final_workspace is not None:
        copy_tree(final_workspace, run_out / "final_workspace")

    run_removed = set_aside(run_out, RUN_KEEP + [transcript.name],
                            delivery / "run_removals")

    # --- 6. the authoring material -------------------------------------------
    #
    # Everything the bundle leaves out: the sources the generated files came
    # from, and the answer the task was built around. This is what review,
    # quality checks and linters run against later.
    #
    # Kept inside delivery/, so one captured path carries the deliverable and
    # the means to review it, without re-capturing the workspace that is
    # already in the bundle.
    authoring = delivery / "authoring"
    authoring.mkdir(parents=True)
    for name, src in {**st.authoring_sources(root),
                      "state.json": root / ".flc" / "state.json"}.items():
        if src.exists():
            shutil.copy2(src, authoring / name)

    # Which files carry the answer and which are there to be ruled out. The
    # split was already in validation.json as two lists; a reviewer deciding
    # whether to trust the task was reading neither.
    materials = materials_record.write(root, authoring / "materials.md", state)

    # The labels in the shape the taxonomy step takes, held by digest from here
    # until collection.
    taxonomy = lb.taxonomy_text(root)
    (authoring / "taxonomy.json").write_text(taxonomy, encoding="utf-8")

    # --- 7. validation -------------------------------------------------------
    validation = {
        "customer_deliverable": "bundle",
        "internal_only": ["authoring", "run", "run_removals"],
        "run_removed": run_removed,
        "task_id": state["task_id"],
        "domain": state.get("domain"),
        "seed_version": state.get("seed_version"),
        "packaged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "clean_rebuild_seconds": build_secs,
        "verifier_smoke_seconds": smoke_secs,
        # Which run the score is from, when it was taken, and the digests it
        # was taken against -- so the number in solver_reward can be tied to a
        # version of the task by anyone reading this downstream, without
        # trusting that it was measured at packaging time. It was not; it is
        # the grade, checked to still apply.
        "graded_job": str(job),
        "graded_at": state.get("graded_at"),
        # A score is a score of whatever model answered, which is not always
        # the one that was asked for.
        **model_record(state, job, transcript),
        "grade_inputs": current,
        "context_peak": context["context_peak"],
        "context_baseline": context["context_baseline"],
        "context_added": context["context_added"],
        "context_from_files": context["context_from_files"],
        "context_band": context["context_band"],
        "material_estimate": state.get("material_estimate"),
        # How hard the prompt read before any model ran, against the prompt
        # being shipped. The score above is the measurement; this is what was
        # predicted of the prompt on its own.
        "prompt_check": state.get(prompt_check.STATE_KEY),
        "rubric_check": dict(rubric_entry, findings=rubric_check.settled(
            root, state, rubric_entry)),
        "justification_check": state.get(jc.STATE_KEY),
        # Statements found inaccurate and put to the blind vote, from both
        # checks, and what the confirmed ones in the answer come to.
        "answer_inaccuracies": rubric_check.answer_inaccuracies(root, state),
        "statements": statement_record(state),
        "labels": lb.taxonomy(root),
        "labels_sha256": st.sha256_file(lb.path(root)),
        "taxonomy_sha256": st.sha256_file(authoring / "taxonomy.json"),
        "label_notes": [f.as_dict() for f in label_notes],
        # Whether the sandbox's own machinery is what we shipped. Recorded as
        # digests so a validator can compare against the manifest held in the
        # repository, where nobody being reviewed can reach it.
        "integrity": integrity_entry or None,
        # Every earlier delivery of this task, so a reviewer's re-delivery
        # adds to the record rather than replacing it.
        "previous_deliveries": history,
        # The answer as it stood when the run started, and whether it has
        # moved since. Recorded rather than checked: a ground truth that was
        # wrong has to be corrected, and blocking would push a contributor
        # towards leaving it wrong.
        "ground_truth_sha256": st.ground_truth_digest(root),
        "ground_truth_pinned": state.get("ground_truth_sha256"),
        "ground_truth_moved": bool(
            state.get("ground_truth_sha256")
            and state["ground_truth_sha256"] != st.ground_truth_digest(root)),
        # The sealed sections -- the answer, how it is derivable, what the
        # model cannot know -- at the graded run's start, against now. The
        # whole-file digest above moves whenever the rest of the ground truth
        # is finished, which the workflow expects after a first run.
        "answer_moved": rg.seal_report(root, state, job),
        "run_history": run_history(root, state),
        "run_laundering": rg.laundering(rg.runs(root, state)),
        "run_limit": rg.RUN_LIMIT,
        # Where the criteria stand with the grade applied, and the review the
        # delivery read, so a review taken again afterwards is visible. An
        # older task's disputes are carried as they were recorded.
        "rubric_line": rubric_standing,
        "rubric_review_inputs": rubric_entry.get("inputs_sha256"),
        "disputes": state.get(rubric_check.DISPUTES_KEY) or {},
        "grade_sensitivity": sensitivity,
        "score_if_fixed": ({"reward": if_fixed, "bar": st.MAX_SOLVER_REWARD,
                            "reweighted": fix_weights, "left_out": sorted(fix_repeats)}
                           if if_fixed is not None else None),
        # Set by /flc-restore when the task was handed to this sandbox rather
        # than authored in it. What makes a second delivery legible as a
        # review rather than as somebody's own second attempt.
        "review": state.get(restore_task.STATE_KEY),
        "required_files": state.get("required_files", []),
        "distractor_files": state.get("distractor_files", []),
        "materials_record": materials,
        "rubric_count": len(bundle_criteria),
        "rubric_by_category": criteria_by_category(bundle / "tests" / "rubrics.json"),
        "check_count": rubric_check.distinct(root),
        "judge_model": summary.get("judge_model"),
        # Criteria the judge's safety filter would not grade. They are in
        # tests/rubrics.md and in the authoring copy, and in no shipped rubric.
        "rubric_refused": sorted(dropped_criteria),
        "rubric_coverage_lost": round(lost, 4),
        # The hallucination criteria, and how many of them this run
        # provoked. A reviewer deciding whether to trust the task cannot get
        # these back out of the score.
        "hallucination_criteria": shipped_negatives,
        "hallucination_fired": len(fired),
        "hallucination_quiet": len(quiet),
        "hallucination_quiet_criteria": sorted(str(r.get("title", "")).strip()
                                               for r in quiet),
        # Whether the judge's reading of each criterion was checked, and what
        # was disputed. Not a gate here; this is what a reviewer reads.
        "grade_review": (review if review_current else None),
        "grade_review_stale": bool(review and not review_current),
        "unit_tests": "skipped" if skipped else "included",
        # What the graded run counted, beside what is being shipped. The two are
        # checked against each other above; recording both is what lets a
        # reader downstream see the score's composition without the run.
        "unit_tests_scored": units,
        # What each test was worth. A weight changes the score without changing
        # a line of the suite, so the numbers travel with the delivery rather
        # than only the pass count.
        "test_weights": None if skipped else unit_weights(root),
        "solver_reward": reward,
        "checks": checks,
        # What the commands warned about and what was waved through anyway. A
        # chat session ends and takes its findings with it; these are what is
        # left for whoever reviews the task afterwards.
        "advisories": advisories(state),
        "technical_issues": st.issues(root),
        "overrides": [dict(check=k, **v)
                      for k, v in sorted((state.get("overrides") or {}).items())],
        "verdict": "PASS",
    }
    (delivery / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    (delivery / "AUDIT.md").write_text(audit_markdown(validation, state))

    return finish(root, checks, reward, args.json, started, delivery)


def finish(root: Path, checks: list[dict], reward, as_json: bool, started: float,
           delivery: Path | None = None) -> int:
    ok = all(c["passed"] for c in checks)
    elapsed = round(time.time() - started, 1)

    if as_json:
        print(json.dumps({"verdict": "PASS" if ok else "FAIL", "checks": checks,
                          "reward": reward, "seconds": elapsed,
                          "delivery": str(delivery) if delivery else None}, indent=2))
        return 0 if ok else 1

    print()
    if not ok:
        print(f"  FAIL -- the task was not packaged ({elapsed}s)")
        print("  Fix what is marked FAIL above and run /flc-deliver again.")
        return 1

    st.mark_done(root, "deliver")
    print(f"  PASS -- packaged in {elapsed}s")
    print()
    print(f"  {delivery}/")
    print("    bundle/          the task, ready to run")
    print("    run/             what the solver did and how it scored")
    print("    run_removals/    the rest of the run's files, kept for reference")
    print("    validation.json  the checks above, as a record")
    if reward:
        print()
        print("  The solver scored:")
        for k in sorted(reward):
            print(f"    {k:<20} {reward[k]}")
        # No "this looks too easy" note here: packaging is only reached once the
        # difficulty check above has passed, so by this point the score is
        # already known to be under the bar.
    return 0


if __name__ == "__main__":
    sys.exit(main())
