#!/usr/bin/env python3
"""Does anything in these grading criteria need fixing?

`/flc-rubrics` checks what can be checked from the words alone. This asks the
harder half, which needs the task in view: does every criterion accept every
right answer, does each one read one way, is anything the prompt asks for
going unchecked, and would a rerun that makes the same mistake with different
values walk past a negative criterion.

The categories, the exceptions and the line live in rubric_quality.py, and
their definitions in review_spec/. This reads tests/rubrics.md, prompt.md, the
ground truth, the workspace, and -- once there is one -- the run's answer. It
asks one reading per group of categories, and records the answer in the task
state, where /flc-deliver reads it without asking again.

    python3 bin/rubric_check.py             # review and record
    python3 bin/rubric_check.py --json
    python3 bin/rubric_check.py --force     # read again even if nothing moved

A review is taken again only when something it reads has changed; a grade
does not count, because which negatives fired is applied to the recorded
findings by code. Each finding is tagged new, or seen before when it was
already reported on the same unchanged criterion. Findings that stop delivery
stop it until they are fixed.

Nothing here writes into tests/rubrics.md. Every criterion is the
contributor's, including one whose wording follows obviously from a defect this
has just named.

Exit code 0 when the rubric clears, 1 when it is past the line, and 2 when
nothing was reviewed -- which is never the same thing as a rubric that was
reviewed and found wanting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import check_integrity as ci  # noqa: E402
import flc_state as st  # noqa: E402
import rubrics_build  # noqa: E402
import rubric_quality as rq  # noqa: E402

MODEL_ENV = "FLC_RUBRIC_MODEL"
STATE_KEY = "rubric_check"
SEEN_KEY = "rubric_seen"
# Written by seeds that allowed a finding to be disputed. Read only to show
# what an older task's state carries; nothing here writes it or acts on it.
DISPUTES_KEY = "rubric_disputes"
RUBRICS_JSON = "tests/rubrics.json"
TEST_WEIGHTS = "tests/test_weights.json"
FILE_CHARS = 4_000


def criteria(root: Path) -> tuple[list[dict], list[str]]:
    """The criteria as written, in the shape the classifier reads them.

    Parsed from tests/rubrics.md rather than the compiled rubrics.json, because
    the section a criterion sits under is part of what is being reviewed and
    the compiled file carries a label instead.
    """
    path = root / "tests" / "rubrics.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], [f"there is no {path}"]
    parsed, errors = rubrics_build.parse(text)
    return [{"text": r["criteria"], "weight": r["weight"],
             "section": r["_category"], "kind": r["type"][1]} for r in parsed], errors


def tests(root: Path) -> list[str]:
    """The suite's test names, where this task has a suite.

    Read off the compiled weights, which is the file the grader multiplies by,
    so a suite set aside by /flc-skip-tests contributes nothing. A tree with no
    unit-test path never has this file, which is why this module is identical
    in both of them.
    """
    try:
        data = json.loads((root / TEST_WEIGHTS).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    weights = data.get("weights") if isinstance(data, dict) else None
    return sorted(weights) if isinstance(weights, dict) else []


def digest(root: Path) -> str:
    """The compiled criteria this verdict was taken against."""
    return st.sha256_file(root / RUBRICS_JSON)


def ground_truth(root: Path) -> str:
    try:
        return (root / st.GROUND_TRUTH).read_text(encoding="utf-8")
    except OSError:
        return ""


def _job(state: dict) -> Path | None:
    for key in ("last_graded_job", "last_job"):
        value = state.get(key)
        if value and Path(value).is_dir():
            return Path(value)
    return None


def fired(root: Path, state: dict) -> dict[str, bool] | None:
    """Which negative criteria the grade charged the run for, while it is current."""
    job = state.get("last_graded_job")
    if not job or not Path(job).is_dir():
        return None
    if st.fingerprint_drift(state.get("grade_fingerprint"), st.fingerprint(root),
                            st.GRADE_ONLY_INPUTS):
        return None
    try:
        import grade_report as gr
        logs = gr.find_logs(Path(job))
        rows, _, _ = gr.load(logs) if logs else ([], {}, "")
    except Exception:
        return None
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            weight = int(row.get("weight", 0))
        except (TypeError, ValueError):
            continue
        if weight >= 0:
            continue
        score = row.get("score") if isinstance(row.get("score"), dict) else {}
        if str(score.get("score")) in ("0", "1"):
            out[str(row.get("title", "")).strip()] = str(score.get("score")) == "1"
    return out or None


def workspace_text(root: Path) -> str:
    """What the workspace files say, bounded per file and in total."""
    try:
        import review_run as rr
    except Exception:
        return ""
    ws = root / "environment" / "workspace"
    chunks, budget = [], rq.MATERIAL_CHARS
    for rel in st.workspace_files(root):
        if budget <= 0:
            break
        text = rr.file_text(ws / rel)
        if not text:
            continue
        piece = f"### {rel}\n{text[:min(FILE_CHARS, budget)]}"
        chunks.append(piece)
        budget -= len(piece)
    return "\n\n".join(chunks)


def justification(root: Path) -> str:
    try:
        return st.justification_file(root).read_text(encoding="utf-8")
    except OSError:
        return ""


def read_file(root: Path):
    """A reader of one workspace file whole, for holding a statement's words to it."""
    def read(rel: str) -> str:
        try:
            import review_run as rr
            return rr.file_text(root / "environment" / "workspace" / rel) or ""
        except Exception:
            return ""
    return read


def material(root: Path, state: dict | None = None) -> dict:
    """What the review sees beyond the criteria, the prompt and the ground truth."""
    state = state if state is not None else st.load(root)
    out: dict = {"answer": "", "trajectory": "", "workspace_text": "", "fired": None,
                 "justification": justification(root)}
    try:
        import review_run as rr
        import solver_answer as sa
    except Exception:
        return out
    out["workspace_text"] = workspace_text(root)
    job = _job(state)
    transcript = sa.find_trajectory(job) if job else None
    if transcript is not None:
        out["answer"] = sa.final_message(transcript)
        calls = []
        for number, step in enumerate(rr.steps(transcript), 1):
            for tool in step.get("tools") or []:
                name, arg = tool[0], tool[1]
                calls.append(f"- step {number}: {name} {' '.join(str(arg).split())[:200]}")
        came_back = rr.observed_text(transcript, job)
        half = rq.TRAJECTORY_CHARS // 2
        out["trajectory"] = ("\n".join(calls)[:half] + "\n\n### What came back, in part\n\n"
                             + came_back[:half])
    out["fired"] = fired(root, state)
    return out


def inputs_digest(root: Path, found: dict | None = None,
                  state: dict | None = None) -> str:
    """Everything a review reads, as one digest: unchanged means nothing to read again.

    Which negatives fired is left out. A grade taken after the review is
    applied to the recorded findings by code (standing()), so grading does not
    make a review stale.
    """
    state = state if state is not None else st.load(root)
    found = found if found is not None else material(root, state)
    blob = json.dumps({"rubrics": digest(root),
                       "prompt": st.contributor_prompt(root),
                       "ground_truth": st.ground_truth_digest(root),
                       "justification": st.justification_digest(root),
                       "workspace": st.sha256_file(root / st.GRADE_INPUTS["workspace"]),
                       "answer": found.get("answer") or "",
                       "spec": rq.SPEC_SOURCE.get("files")}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def review(root: Path, samples: int, model: str | None = None) -> tuple[rq.Report, dict]:
    """Review this task's rubric against the model on this machine."""
    written, errors = criteria(root)
    state = st.load(root)
    found = material(root, state)
    if errors:
        report = rq.Report(criteria_written=len(written))
        report.why = ("tests/rubrics.md does not compile yet, so there is "
                      "nothing settled to review: " + errors[0])
        return report, found
    creds = st.gateway()
    if not creds:
        report = rq.Report(criteria_written=len(written))
        report.why = "no gateway credentials were found on this machine"
        return rq.with_decided(report, written), found
    key, base = creds
    models = st.check_models(model, MODEL_ENV)
    usage: list = []
    answered: dict = {}
    shape = st.gateway_shape()
    send = rq.sender(models, key, base, shape, bool(tests(root)), usage,
                     answered=answered)
    import tool_session  # noqa: PLC0415
    tools = tool_session.Tools(root, _job(state), key, base, shape, usage)

    def session(req: dict) -> str:
        got: list[str] = []
        text = tools.reading(req["body"], models, system=req["system"],
                             prefix=req["prefix"], max_tokens=rq.MAX_TOKENS,
                             thinking=rq.THINKING, answered=got)
        if got:
            answered[req["group"]] = got[0]
        return text

    prompt, truth = st.contributor_prompt(root), ground_truth(root)
    voters_see = rq.build_request(written, prompt, truth, st.workspace_files(root),
                                  tests(root), dict(found, fired=None))

    def vote(statements: list) -> dict:
        return tools.vote(statements, voters_see, str(state.get("task_id") or ""))

    report = rq.collect(written, prompt, truth,
                        st.workspace_files(root), send, samples=samples,
                        tests=tests(root), model=models[0], material=found,
                        usage=usage, floor=st.MIN_CHECKS, session=session,
                        vote=vote, read_file=read_file(root))
    report.answered_by = dict(answered)
    report.model = rq_models(answered) or models[0]
    report.sessions = tools.summary()
    if tools.faults:
        st.record_issue(root, "check_partial", "rubric review read without tools: "
                        + "; ".join(tools.faults), "rubric_check.py")
    return report, found


def rq_models(answered: dict) -> str:
    """The models that read the rubric, by group when more than one did."""
    names = sorted(set(answered.values()))
    if len(names) <= 1:
        return names[0] if names else ""
    return "; ".join(f"{name} ({', '.join(sorted(g for g, m in answered.items() if m == name))})"
                     for name in names)


def record(root: Path, report: rq.Report, found: dict | None = None) -> dict:
    """Write the verdict into the task state and return what was written.

    Each finding is tagged new, or seen before when the same finding was
    reported on the same unchanged criterion by an earlier review.
    """
    state = st.load(root)
    seen = state.get(SEEN_KEY) if isinstance(state.get(SEEN_KEY), dict) else {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    findings = []
    for f in report.findings:
        entry = f.as_dict()
        entry["seen_before"] = f.ident in seen
        findings.append(entry)
        info = seen.setdefault(f.ident, {"first_at": now, "category": f.category})
        # The weight a weights finding proposed, kept after the line moves to it
        # and a later check stops raising it.
        if f.group == "weights" and f.evidence.get("proposed_weight") not in (None, ""):
            info["criterion"] = f.criterion
            info["proposed_weight"] = f.evidence.get("proposed_weight")
            if f.evidence.get("accepted_weights"):
                info["accepted_weights"] = list(f.evidence["accepted_weights"])
    entry = {
        "at": now,
        "verdict": report.verdict,
        "why": report.why,
        "review": report.review,
        "review_reason": report.review_detail.get("reason", ""),
        "line": report.line,
        "criteria_written": report.criteria_written,
        "criteria_examined": report.criteria_examined,
        "samples": report.samples,
        "model": report.model,
        "blocking": [f.as_dict() for f in report.blocking],
        "findings": findings,
        "notes": report.notes,
        "unmeasured_groups": report.unmeasured_groups,
        "unmeasured_why": report.unmeasured_why,
        "answered_by": report.answered_by,
        "usage": report.usage,
        "statements": [s.as_dict() for s in report.statements],
        "vote": report.vote,
        "consistency": rq.sv.consistency(report.statements),
        "sessions": report.sessions,
        "spec_commit": rq.SPEC_SOURCE.get("commit"),
        "rubrics_sha256": digest(root),
        "inputs_sha256": inputs_digest(root, found, state),
    }
    state[STATE_KEY] = entry
    state[SEEN_KEY] = seen
    st.save(root, state)
    if report.verdict == "UNMEASURED":
        st.record_issue(root, "check_unmeasured", f"rubric review: {report.why}",
                        "rubric_check.py")
    elif report.unmeasured_groups:
        st.record_issue(root, "check_partial", "rubric review read in part: " + "; ".join(
            f"{g}: {report.unmeasured_why.get(g, '')}" for g in report.unmeasured_groups),
            "rubric_check.py")
    return entry


def recorded(state: dict, root: Path) -> tuple[dict | None, bool]:
    """The recorded verdict, and whether it was taken against these criteria."""
    entry = state.get(STATE_KEY)
    if not isinstance(entry, dict) or not entry.get("verdict"):
        return None, False
    # An absent rubrics.json digests to "", which would match a record that
    # also carries "" and read as current. There is no review of a rubric that
    # does not compile.
    now = digest(root)
    return entry, bool(now) and entry.get("rubrics_sha256") == now


def current(state: dict, root: Path) -> bool:
    """Whether nothing the recorded review read has moved since it was taken.

    What delivery asks. A review some group could not read is still current:
    what it read is what the criteria were held to.
    """
    entry = state.get(STATE_KEY)
    return (isinstance(entry, dict) and bool(entry.get("verdict"))
            and bool(entry.get("inputs_sha256"))
            and entry["inputs_sha256"] == inputs_digest(root, state=state))


def fresh(state: dict, root: Path) -> bool:
    """Whether /flc-check-rubric can show the recorded review instead of reading again.

    A review some group could not read is never reused: those categories were
    not checked, so the next asking reads them.
    """
    entry = state.get(STATE_KEY)
    return (current(state, root) and entry.get("verdict") != "UNMEASURED"
            and not entry.get("unmeasured_groups"))


def ensure(root: Path, samples: int = rq.DEFAULT_SAMPLES, model: str | None = None,
           force: bool = False) -> tuple[dict, bool]:
    """The current review: the recorded one if nothing moved, otherwise a new one."""
    state = st.load(root)
    if not force and fresh(state, root):
        return state[STATE_KEY], False
    report, found = review(root, samples, model)
    return record(root, report, found), True


def findings_of(entry: dict | None) -> list[rq.Finding]:
    return [rq.Finding.from_dict(f) for f in (entry or {}).get("findings") or []
            if isinstance(f, dict)]


def settled(root: Path, state: dict, entry: dict | None) -> list[dict]:
    """The recorded findings, with the current grade applied.

    Whether a negative fired is the grade's to say, and an overlap with a
    negative that fired is not overlap. That is applied here by code on every
    reading of the record; nothing is read again.
    """
    raw = [f for f in (entry or {}).get("findings") or [] if isinstance(f, dict)]
    if not raw:
        return []
    written, _ = criteria(root)
    applied = rq.apply_fired([rq.Finding.from_dict(f) for f in raw], written,
                             fired(root, state))
    return [dict(f, exempt=g.exempt) for f, g in zip(raw, applied)]


def standing(root: Path, state: dict, entry: dict | None) -> dict:
    """The line as it stands now, with the current grade applied."""
    if not entry:
        return {"over": False, "counted": [], "to_clear": 0}
    findings = [rq.Finding.from_dict(f) for f in settled(root, state, entry)]
    return rq.line(findings, int(entry.get("criteria_written") or 0))


def _counted(root: Path, state: dict) -> list[rq.Finding]:
    """The recorded findings that count, grade applied, on lines still as reviewed."""
    entry = state.get(STATE_KEY)
    if not isinstance(entry, dict):
        return []
    written = {rq._norm(c["text"]) for c in criteria(root)[0]}
    out = []
    for f in (rq.Finding.from_dict(d) for d in settled(root, state, entry)):
        other = f.evidence.get("other_criterion")
        if (f.reproduced and f.counts_toward is not None and f.criterion
                and rq._norm(f.criterion) in written
                and (not other or rq._norm(other) in written)):
            out.append(f)
    return out


def distinct(root: Path, state: dict | None = None) -> dict:
    """The task's checks, with a line that only repeats another left out.

    From overlap findings seen in every reading of the recorded check, with the
    current grade applied, while both lines of the pair are still written as
    they were checked. The line that is repeated still counts.
    """
    state = state if state is not None else st.load(root)
    counted = st.check_count(root)
    gone = rq.repeats(_counted(root, state), reproduced_only=False)
    left = counted["total"] - len(gone)
    return dict(counted, distinct=left, repeats=gone,
                distinct_enough=left >= counted["floor"])


def fixes(root: Path, state: dict | None = None) -> tuple[dict[str, int], set[str]]:
    """The counted weight findings' weights, and the counted repeats, by line text."""
    state = state if state is not None else st.load(root)
    found = _counted(root, state)
    weights = {}
    for f in found:
        if f.group == "weights" and not f.exempt:
            try:
                weights[" ".join(f.criterion.split())] = int(f.evidence["proposed_weight"])
            except (KeyError, TypeError, ValueError):
                continue
    return weights, {" ".join(t.split()) for t in rq.repeats(found, reproduced_only=False)}


def items(state: dict, entry: dict | None, root: Path | None = None) -> list[dict]:
    """Every finding the review made, numbered in criterion order.

    `counted` marks a finding seen in every reading that counts towards the
    line; it stops delivery only while the rubric is past the line. A finding
    the category itself does not count is left out and shown as a note.
    """
    root = root or Path(".")
    now = standing(root, state, entry) if entry else {}
    counted = set(now.get("counted") or [])
    out = []
    rubric = [f for f in settled(root, state, entry) if not f.get("exempt")]
    rubric.sort(key=lambda f: (f.get("index") is None, f.get("index") or 0,
                               f.get("id") or ""))
    for f in rubric:
        ident = f.get("id") or ""
        out.append({"id": ident, "category": f.get("category"),
                    "label": f.get("label") or rq.label(str(f.get("category"))),
                    "name": f.get("name"), "criterion": f.get("criterion") or "",
                    "what": rq.contributor_text(f.get("what") or ""),
                    "remedy": rq.contributor_text(f.get("remedy") or ""),
                    "seen_before": bool(f.get("seen_before")),
                    "counted": ident in counted})
    for number, item in enumerate(out, 1):
        item["number"] = number
    return out


def stopping(state: dict, entry: dict | None, root: Path | None = None) -> list[dict]:
    """The findings that stop delivery: counted ones, while the rubric is past the line."""
    if not entry or not standing(root or Path("."), state, entry).get("over"):
        return []
    return [i for i in items(state, entry, root) if i["counted"]]


def _wrap(text: str, indent: str = "  ") -> str:
    return textwrap.fill(" ".join((text or "").split()), width=84,
                         initial_indent=indent, subsequent_indent=indent)


def _show_item(item: dict, mark: str) -> None:
    print(f"  {item['number']}. {item['label']} -- {mark}")
    if item["criterion"]:
        print(_wrap(f'"{item["criterion"]}"', "     "))
    print(_wrap(item["what"], "     "))
    if item["remedy"]:
        print(_wrap(f"to fix: {item['remedy']}", "     "))
    print()


RECORDS = (STATE_KEY, "justification_check")


def answer_inaccuracies(root: Path, state: dict, only: str | None = None) -> dict:
    """Confirmed inaccuracies in the author's answer, from the checks' records.

    A statement no longer in the ground truth has been fixed and is left out.
    FAIL where a criterion, a test or the justification repeats one, WARN
    where nothing graded does, PASS otherwise.
    """
    rows = []
    for key in ([only] if only else RECORDS):
        entry = state.get(key)
        if isinstance(entry, dict):
            rows += [s for s in entry.get("statements") or [] if isinstance(s, dict)]
    return rq.sv.consistency(rows, ground_truth(root))


def show_answer(found: dict) -> None:
    """A confirmed inaccuracy in the author's answer, told as something to fix."""
    resting, unresting = found.get("resting") or [], found.get("unresting") or []
    if not resting and not unresting:
        return
    if resting:
        print(f"  MUST FIX  your answer states something a check shows is wrong, "
              f"and graded material repeats it")
        print()
        print(_wrap("Three independent readings each found it wrong. Fix it in "
                    f"{st.GROUND_TRUTH} and in everything that repeats it, then "
                    "run the checks again. Your answer was set down before the "
                    "run, and correcting it now is expected; the change is "
                    "recorded with the task."))
        print()
    for s in resting + unresting:
        mark = "must fix" if s in resting else "fix, though nothing graded repeats it"
        print(_wrap(f"In your answer -- {mark}:", "  "))
        print(_wrap(f"\"{s.get('quote', '')}\"", "     "))
        print(_wrap(f"what is wrong: {s.get('what_is_wrong', '')}", "     "))
        print(_wrap(f"the check: {s.get('check', '')}", "     "))
        if s.get("bears_on"):
            print(_wrap(f"repeated by: {', '.join(s['bears_on'])}", "     "))
        print()


def show(entry: dict, state: dict, root: Path | None = None) -> None:
    """The review, presented once: what stops delivery, then what is worth fixing."""
    print()
    print("Does anything in these criteria need fixing?")
    print()
    if entry.get("verdict") == "UNMEASURED":
        print("  NOT MEASURED")
        print()
        print(_wrap(f"Nothing was reviewed: {entry.get('why', '')}"))
        print()
        print(_wrap("This is our check failing, not your rubric. It does not "
                    "stop you: delivery lets a rubric through when this could "
                    "not measure it, and says so."))
        print()
        return
    show_answer(answer_inaccuracies(root or Path("."), state, only=STATE_KEY))
    listed = items(state, entry, root)
    stop = stopping(state, entry, root)
    stop_ids = {i["id"] for i in stop}
    rest = [i for i in listed if i["id"] not in stop_ids]
    new = [i for i in rest if not i["seen_before"]]
    old = [i for i in rest if i["seen_before"]]
    partial = entry.get("unmeasured_groups") or []
    if stop:
        print(f"  MUST FIX  {len(stop)} finding{'' if len(stop) == 1 else 's'} "
              "stop delivery")
        print()
        print(_wrap("Each was found every time your criteria were read. Delivery "
                    "is refused until they are fixed. Fix them in "
                    "tests/rubrics.md, run /flc-rubrics and /flc-check-rubric "
                    "again, then /flc-grade before you deliver. Nothing here asks "
                    "you to weaken a criterion: each fix says it more plainly."))
        print()
        for item in stop:
            _show_item(item, "must fix")
        if new:
            print("  Worth fixing too -- these do not stop delivery:")
            print()
    else:
        head = ("NOTHING STOPS DELIVERY" if listed
                else "NOTHING TO FIX" if partial else "CLEAR")
        found = (f"{len(listed)} finding{'' if len(listed) == 1 else 's'} worth fixing"
                 if listed else "nothing found")
        print(f"  {head}  {entry.get('criteria_written')} criteria, {found}")
        if partial:
            print(_wrap(f"(read in part: {', '.join(partial)} could not be read "
                        "this time; recorded for the project team)", "  "))
        print()
        if listed:
            text = ("None of these stops delivery on its own. Each is a common "
                    "issue in this project: fix it unless the finding is wrong.")
            if entry.get("review") == "FAIL":
                text += (" If every finding here is right, this rubric would be "
                         "refused at delivery.")
            print(_wrap(text))
            print()
    for item in new:
        _show_item(item, "fix unless it is wrong")
    if old:
        print("  Seen before, on criteria that have not changed:")
        for item in old:
            print(_wrap(f"{item['number']}. {item['label']}: "
                        f"\"{item['criterion'][:70]}\"", "    "))
        print()
    exempt = [f for f in settled(root or Path("."), state, entry)
              if f.get("exempt") and f.get("exempt") != rq.UNCONFIRMED_EXEMPT]
    if exempt:
        print(f"  {len(exempt)} more noted and not counted:")
        for f in exempt[:6]:
            name = f.get("label") or rq.label(str(f.get("category")))
            print(_wrap(f"- {name}: {rq.contributor_text(f.get('exempt'))}", "    "))
        print()
    for note in (entry.get("notes") or [])[:6]:
        print(_wrap(f"note: {note}", "  "))
    if entry.get("model"):
        print(_wrap(f"read by {entry['model']}", "  "))
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--samples", type=int, default=rq.DEFAULT_SAMPLES)
    ap.add_argument("--model", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    if args.samples < 1:
        print("--samples must be at least 1", file=sys.stderr)
        return 2

    ci.announce(root, "rubric_check")

    entry, taken = ensure(root, args.samples, args.model, args.force)
    state = st.load(root)
    if args.json:
        print(json.dumps(entry, indent=2))
    else:
        if not taken:
            print(_wrap("Nothing this review reads has changed, so this is the "
                        "review already taken. Reading it again would cost budget "
                        "and most likely say the same."))
        show(entry, state, root)

    if entry.get("verdict") == "UNMEASURED":
        return 2
    if answer_inaccuracies(root, state, only=STATE_KEY)["verdict"] == "FAIL":
        return 1
    return 1 if stopping(state, entry, root) else 0


if __name__ == "__main__":
    sys.exit(main())
