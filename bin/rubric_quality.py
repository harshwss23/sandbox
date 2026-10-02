#!/usr/bin/env python3
"""Reviewing a rubric's criteria against defect categories, and turning the
findings into a verdict.

This module holds the parts that must give the same answer wherever they run:
the categories, read from review_spec/, the evidence a finding has to carry,
the exceptions that are decided by code rather than by the model, the
arithmetic for where a rubric fails, and the verdict. It reads no task files.
Callers supply the task's text and a way of reaching a model.

The review is six focused readings, one per group of categories, each seeing
the same task material, which is sent as one shared prefix so it can be
cached. No single finding refuses anything: a rubric is refused only when
findings seen in every one of three readings are too many, and then until it
is fixed.

`rubric_audit.py` uses it against delivered tasks; `rubric_check.py` uses it
inside the sandbox against the rubric being written.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from prompt_taxonomy import (  # noqa: F401
    Refused, Unreachable, call_http, call_models, cutoff_note, parse_object,
)
import statement_vote as sv

SPEC_DIR = Path(__file__).resolve().parent / "review_spec"

# Readings a counted finding is held to: one, and two more only when the first
# puts the rubric past the line. A finding has to be seen in REPRODUCTION of
# them -- every one -- to count.
DEFAULT_SAMPLES = 3
REPRODUCTION = 3

# A review of a group of categories is many findings rather than one verdict,
# and a reply cut off at the limit is measured as nothing at all.
MAX_TOKENS = 16000
# Reasoning before the reply, where the gateway takes it.
THINKING = 8000
WORKERS = 6

# A ground truth may embed a figure as a data: URL. Runs of encoded bytes are
# replaced before the request is built, so one image cannot spend the whole
# budget. Do not add \n to the character class: the pattern would span the
# joins and eat the prose on either side of the blob.
_B64_BLOB = re.compile(r'[A-Za-z0-9+/=]{2000,}')

SEVERITIES = ("major", "moderate", "minor", "note")
SEVERITY_RANK = {"major": 3, "moderate": 2, "minor": 1}

# Where a rubric fails, as whole-number percentages of the criteria written.
# Exclusive, and compared as whole counts against the limit times the
# denominator rather than in floating point. Never printed.
MAJOR_LIMIT = 10
MAJOR_MODERATE_LIMIT = 15
ANY_LIMIT = 20
CLEAN_MINOR_LIMIT = 5
# Uncovered escapes a rubric may carry, over every criterion, positive and
# negative together.
GENERALITY_LIMIT = 5

SPOT_CHECK_CAP = 5

# How much of the task goes into the shared prefix.
ANSWER_CHARS = 12_000
TRAJECTORY_CHARS = 24_000
MATERIAL_CHARS = 40_000


def _norm(text: str) -> str:
    """Fold case, dashes, quotes and whitespace so two spellings still match."""
    text = unicodedata.normalize("NFKD", text or "")
    for dash in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212":
        text = text.replace(dash, "-")
    for quote in "\u2018\u2019\u201c\u201d":
        text = text.replace(quote, "'")
    return " ".join(text.split()).lower()


def _load(name: str):
    try:
        text = (SPEC_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return None
    return json.loads(text) if name.endswith(".json") else text


_SPEC = {_norm(c["name"]): c for c in (_load("categories.json") or [])}
_EXCEPTIONS = _load("exceptions.json") or []
_GENERALITY = _load("generality.json") or {}
SPEC_SOURCE = _load("SOURCE.json") or {}


@dataclass(frozen=True)
class Category:
    """One defect category: which review reads it, what it is, what it is not."""
    key: str
    name: str
    group: str
    severity: str
    evidence: tuple[str, ...]
    definition: str
    boundary: str
    counts: str | None = "quality"
    one_of: tuple[str, ...] = ()
    lead: str = ""


def _spec(name: str, field_: str, fallback: str) -> str:
    entry = _SPEC.get(_norm(name))
    return (entry or {}).get(field_) or fallback


# The reviewing model's training ends before today, so a source it does not
# recognise is not evidence of anything.
HORIZON = ("This includes a criterion that cites a source you do not "
           "recognise or dates one later than anything you have seen; neither "
           "is evidence of anything.")


def _category(key, name, group, evidence, lead, fallback_def, fallback_bound="",
              counts="quality", one_of=(), extra=""):
    severity = (_SPEC.get(_norm(name)) or {}).get("severity") or {
        "Missing Criteria - Critical Requirements": "major",
        "Criteria Not Self Contained": "major",
        "Criteria Not Atomic - Major": "major",
        "Incorrect Criteria": "major",
        "Incorrect Weights - Minor": "minor",
    }.get(name, "moderate")
    boundary = _spec(name, "boundary", fallback_bound)
    if extra:
        boundary = f"{boundary} {extra}".strip()
    return Category(key=key, name=name, group=group, severity=severity,
                    evidence=tuple(evidence), one_of=tuple(one_of),
                    definition=_spec(name, "definition", fallback_def),
                    boundary=boundary, counts=counts, lead=lead)


CATEGORIES: dict[str, Category] = {c.key: c for c in (
    _category("missing_critical", "Missing Criteria - Critical Requirements",
              "coverage", (), "A requirement of the prompt no criterion checks, "
              "without which no good response is imaginable.",
              "Something the prompt asks for that no criterion checks.",
              one_of=("prompt_quote", "answer_quote")),
    _category("missing_noncritical", "Missing Criteria — Non-critical Requirements",
              "coverage", (), "The same, for a requirement a good response "
              "could do without.",
              "The same defect for a requirement that is not critical.",
              one_of=("prompt_quote", "answer_quote")),
    Category(key="too_many_spot_checks", name="Too Many Spot Checks",
             group="coverage", severity="note", evidence=(), counts=None,
             definition=(f"More than {SPOT_CHECK_CAP} criteria spot-checking "
                         "members of one group of similar outcomes."),
             boundary=("Not a defect in any one criterion, and never counted. "
                       "Report it once for the group.")),
    _category("not_self_contained", "Criteria Not Self Contained", "form",
              ("cannot_tell", "would_consult"),
              "A grader holding only this criterion and the response could not "
              "evaluate it.",
              "The criterion does not settle what counts as right."),
    _category("not_atomic_major", "Criteria Not Atomic - Major", "form",
              ("part_a", "part_b", "splitting_response"),
              "Bundles deliverables about different subjects.",
              "The criterion bundles deliverables."),
    _category("not_atomic_moderate", "Criteria Not Atomic - Moderate", "form",
              ("part_a", "part_b", "splitting_response"),
              "Bundles parts of the same deliverable or subject.",
              "The criterion bundles parts of one deliverable."),
    _category("subjective", "Subjective Criteria", "form", ("qualifier",),
              "Rests on a qualifier with no standard attached.",
              "The criterion is vague or immeasurable."),
    _category("double_negative", "Double Negative", "form", (),
              "A negative criterion penalising an absence.",
              "A negative criterion penalising the absence of something."),
    _category("ambiguous", "Dense or Ambiguous Phrasing", "form",
              ("reading_a", "reading_b", "dividing_response"),
              "Correct and measurable, and still two readings.",
              "The wording admits more than one reading."),
    _category("incorrect_criteria", "Incorrect Criteria", "truth_fit", ("statement",),
              "States something the task's material, or a check anyone can "
              "rerun, shows is wrong -- including where it repeats the "
              "author's answer.",
              "The criterion contains a factual error or misaligns with the prompt.",
              extra=HORIZON),
    _category("overfit", "Overfitting and Underfitting", "truth_fit",
              ("rejected_answer",), "Too rigid: rejects a valid answer.",
              "The criterion rejects a valid answer."),
    _category("underfit", "Overfitting and Underfitting", "truth_fit",
              ("accepted_answer",), "Too loose: accepts an invalid answer.",
              "The criterion accepts an invalid answer."),
    _category("overlapping", "Overlapping/Redundant Criteria", "redundancy",
              ("other_criterion", "shared_element"),
              "Two criteria assess the same element.",
              "Two criteria assess the same element."),
    _category("incorrect_weight_major", "Incorrect Weights - Major", "weights",
              ("bucket", "proposed_weight"),
              "Two levels from the bucket its content puts it in.",
              "The weight is two levels away from its bucket."),
    _category("incorrect_weight_minor", "Incorrect Weights - Minor", "weights",
              ("bucket", "proposed_weight"),
              "One level from its bucket.",
              "The weight is one level away from its bucket."),
    Category(key="hallucination_generality",
             name="Rubric Criteria - Hallucination Generality",
             group="generality", severity="major",
             evidence=("particular", "escape"), counts="generality",
             definition=(_GENERALITY.get("description") or
                         "A negative criterion a rerun making the same kind of "
                         "mistake with different particulars would escape."),
             boundary=_GENERALITY.get("note") or ""),
)}

# Category keys a model used before a rename, read as the current one.
ALIASES = {"not_atomic_minor": "not_atomic_moderate"}

# What a contributor is shown for each category, in place of its review name.
LABELS = {
    "missing_critical": "Something the rubric should check has no line",
    "missing_noncritical": "Something the rubric should check has no line",
    "too_many_spot_checks": "Too many lines check single items of one group",
    "not_self_contained": "A line needs something outside it to be graded",
    "not_atomic_major": "A line checks two things",
    "not_atomic_moderate": "A line checks two things",
    "subjective": "A line asks for a judgement, not a check",
    "double_negative": "A line penalises something being absent",
    "ambiguous": "A line reads two ways",
    "incorrect_criteria": "A line states something your files or a check show is wrong",
    "overfit": "A line turns down a right answer",
    "underfit": "A line accepts a wrong answer",
    "overlapping": "Two lines check the same thing",
    "incorrect_weight_major": "A weight is in the wrong bucket",
    "incorrect_weight_minor": "A weight is in the wrong bucket",
    "hallucination_generality": "A rerun could make the same mistake and not be caught",
}


def label(key: str) -> str:
    return LABELS.get(ALIASES.get(key, key), "A line needs another look")

GROUPS: dict[str, list[str]] = {}
for _key, _cat in CATEGORIES.items():
    GROUPS.setdefault(_cat.group, []).append(_key)
GROUP_ORDER = ("form", "coverage", "truth_fit", "redundancy", "weights", "generality")

WEIGHTS = (5, 3, 1, -1, -3, -5)

# A finding whose own text concedes the defect is not a finding. Matched
# against the claim alone, never against the evidence or the remedy, where an
# ordinary sentence can carry any of these words without hedging anything.
HEDGES = (
    "borderline", "arguably", "on balance", "debatable", "hypothetical",
    "could be seen as", "could be considered", "could be argued", "one might",
    "not strictly", "a reviewer could", "it is unclear whether", "somewhat of",
)


# Words a contributor is never shown, since nobody authoring a task is told
# how tasks are reviewed. A model's own finding text is passed through this.
_REVIEW_WORDS = ((re.compile(r"\bQC's\b"), "this project's"),
                 (re.compile(r"\bQC\b"), "this project"),
                 (re.compile(r"\b(?:the )?customer's\b", re.I), "the project's"),
                 (re.compile(r"\b(?:the )?customers?\b", re.I), "the project"),
                 (re.compile(r"\b(?:the )?eval's\b", re.I), "the project's"),
                 (re.compile(r"\b(?:the )?evals?\b", re.I), "the project"),
                 (re.compile(r"\b(?:auditors|reviewers)\b", re.I), "readers"),
                 (re.compile(r"\b(?:auditor|reviewer)\b", re.I), "reader"))


def contributor_text(text: str) -> str:
    for pattern, plain in _REVIEW_WORDS:
        text = pattern.sub(plain, text or "")
    return text


# --- the prompt ---------------------------------------------------------------


def shared_system() -> str:
    """What every reading is told, whichever categories it holds."""
    preamble = _load("preamble.md") or (
        "Work through every criterion in the rubric in order, one at a time, and "
        "reach a verdict on each against each category below. Report only a "
        "defect you can state without hedging.\n")
    return "\n".join([
        cutoff_note(), "",
        "You are reviewing the grading criteria a researcher wrote for one "
        "research task, against named defect categories. The task's material "
        "comes first and is the same for every category; the categories you "
        "are asked about, and the shape to reply in, follow it.", "",
        preamble.strip(), "",
        "Do not report a severity: each category carries its own. A remedy says "
        "what the author should change, as an instruction and never as a "
        "criterion line to paste: the author writes every criterion "
        "themselves.",
    ])


def _exceptions_for(name: str) -> list[str]:
    return [e["exception"] for e in _EXCEPTIONS
            if _norm(e["category"]) == _norm(name)]


FIELDS = {
    "prompt_quote": "the words of the prompt the requirement comes from, copied exactly",
    "answer_quote": "for a hallucination the run committed and no criterion covers: "
                    "the wrong claim, copied exactly from the run's answer",
    "cannot_tell": "what a grader holding only the criterion and the response could "
                   "not tell -- the subject, the target, or which alternatives count",
    "would_consult": "what they would have to consult to tell it",
    "limited_exception": "true where the limited exception applies",
    "covering": "with limited_exception: the criteria that capture the failure, "
                "each copied exactly",
    "part_a": "the first part, copied from the criterion",
    "part_b": "the second part, copied from the criterion",
    "splitting_response": "a response delivering one part and not the other",
    "qualifier": "the qualifier with no standard, copied exactly from the criterion",
    "reading_a": "the first reading",
    "reading_b": "the second reading",
    "dividing_response": "a correct response one reading accepts and the other rejects",
    "ground_truth_quote": "the words of the author's answer that settle it, copied exactly",
    "material_quote": "the words of the supplied material that settle it, copied exactly",
    "check": "the arithmetic, unit conversion or definition that shows the error",
    "rejected_answer": "a valid answer this criterion turns down",
    "accepted_answer": "an invalid answer this criterion lets through",
    "other_criterion": "the criterion it overlaps, copied exactly",
    "shared_element": "the element both criteria assess",
    "bucket": "the bucket that prices it, as +5, +3, +1, -1, -3 or -5",
    "proposed_weight": "the weight it should carry, as a number",
    "statement": "the id, in `statements`, of the statement this rests on",
}


def _reply_notes() -> str:
    return (' "notes": ["<a criterion a category says is not counted, and why; a doubt '
            'only the author can settle; a gap in the material>"]}')


def group_body(group: str, has_suite: bool = False) -> str:
    """The categories one reading holds, and the shape to reply in.

    Every reading accounts for every criterion, one row each, because a
    reading that returns only the findings it chose to report skims -- and a
    criterion nobody considered reads as clean. The exceptions the definitions
    carry are applied to the reply by code.
    """
    keys = GROUPS[group]
    lines = ["## The categories for this reading", ""]
    if group == "generality":
        cat = CATEGORIES["hallucination_generality"]
        lines += [f"### {cat.name}", "", cat.definition.strip(), ""]
        if cat.boundary:
            lines += ["Where it stops: " + cat.boundary.strip(), ""]
        lines += [(_GENERALITY.get("contract") or "").strip(), "",
                  "### What to return", "",
                  "One row per negative criterion, by its number in the list "
                  "above. Each escapable row is read as a "
                  "`hallucination_generality` finding. Reply with a single JSON "
                  "object and nothing else:", "",
                  '{"criteria_examined": <n>, "escape_verdicts": [{"criterion": '
                  '<its number>, "verdict": "clean|escapable|undecided", '
                  '"particular": "<escapable: the words of the criterion that name '
                  'the wrong values or claims it covers, copied exactly>", '
                  '"escape": "<escapable: what a rerun would write>", '
                  '"covered_by": <escapable: the number of the criterion that '
                  'penalises the escaping answer, or null>, "detail": "<why>"}],',
                  _reply_notes()]
        return "\n".join(lines)

    seen = set()
    for key in keys:
        cat = CATEGORIES[key]
        files_as = [k for k in keys if CATEGORIES[k].name == cat.name]
        if cat.name in seen:
            continue
        seen.add(cat.name)
        lines += [f"### {cat.name} ({cat.severity})", "", cat.definition.strip(), ""]
        if cat.boundary:
            lines += ["Where it stops: " + cat.boundary.strip(), ""]
        for k in files_as:
            c = CATEGORIES[k]
            need = list(c.evidence) + ([" or ".join(c.one_of)] if c.one_of else [])
            lines.append(f"File as `{k}`: {c.lead}"
                         + (f" Carries: {', '.join(need)}." if need else ""))
        lines.append("")
    if group == "form":
        lines += [(_load("naming.md") or "").strip(), ""]
    if group == "weights":
        lines += [(_load("weights.md") or "").strip(), ""]
    if group == "coverage" and has_suite:
        lines += ["This task also carries a unit-test suite, listed with the "
                  "material. A requirement the tests assert mechanically is "
                  "covered, unless a qualifier of the request cannot be "
                  "settled by a test.", ""]
    lines += ["### What to return", ""]

    if group == "weights":
        lines += [
            "Price every criterion, in order, by its number in the list above: "
            "the bucket its own content puts it in, read against the bucket "
            "definitions and not against the weight it carries, quoting the words "
            "of the bucket that put it there. Say whether the content puts it "
            "there clearly, or whether the placement is a judgement between two "
            "buckets. A clear placement that differs from the weight carried is a "
            "finding; a judgement call is not. The case the buckets do not price, "
            "a negative outweighed by the positives it guards, goes under "
            "`findings` with its arithmetic.", "",
            "Reply with a single JSON object and nothing else:", "",
            '{"criteria_examined": <n>,',
            ' "verdicts": [{"criterion": <its number>, "bucket": "<+5, +3, +1, -1, '
            '-3 or -5>", "clear": true or false, "why": "<one sentence, quoting '
            'the bucket>"}],',
            ' "findings": [{"category": "incorrect_weight_minor or incorrect_weight_major", '
            '"criterion": <its number>, "what": "<the arithmetic>", "remedy": "<...>", '
            '"bucket": "<...>", "proposed_weight": <n>}],',
            _reply_notes()]
        return "\n".join(lines)

    if group == "coverage":
        lines += [
            "Go down the prompt sentence by sentence and list every thing it asks "
            "for, with the numbers of the criteria (or the names of the tests) "
            "that check it in either direction; an empty list is a requirement "
            "nothing checks, and is read as a missing criterion. Then list every "
            "wrong claim the graded run's answer makes, with the criteria that "
            "penalise it; one nothing penalises is a missing criterion too.", "",
            "Reply with a single JSON object and nothing else:", "",
            '{"criteria_examined": <n>,',
            ' "requirements": [{"prompt_quote": "<the words of the prompt, copied '
            'exactly>", "critical": true or false, "covered_by": [<numbers>], '
            '"remedy": "<for one nothing covers: what to add>"}],',
            ' "annotations": [{"answer_quote": "<the wrong claim, copied exactly '
            'from the run\'s answer>", "covered_by": [<numbers>]}],',
            ' "findings": [{"category": "too_many_spot_checks", "what": "<the group '
            'and how many criteria sample it>"}],',
            _reply_notes()]
        return "\n".join(lines)

    used = sorted({f for k in keys for f in CATEGORIES[k].evidence + CATEGORIES[k].one_of}
                  | ({"limited_exception", "covering"} if group == "form" else set()))
    lines += [
        "One row for every criterion, in order, by its number in the list above: "
        "a criterion you clear is a row with \"verdict\": \"clean\", and one with "
        "two defects is two rows. Reply with a single JSON object and nothing "
        "else:", "",
        '{"criteria_examined": <n>,',
        ' "verdicts": [{"criterion": <its number>, "verdict": "clean or one of: '
        + ", ".join(k for k in keys) + '",',
        '   "what": "<the defect, stated without hedging>",',
        '   "remedy": "<what the author should change, as an instruction>",']
    lines += [f'   "{name}": "<{FIELDS[name]}>",' for name in used]
    lines += ["  }],"]
    if group == STATEMENT_GROUP:
        lines += [STATEMENTS_SHAPE]
    lines += [_reply_notes(), "",
              "A defect row carries only the fields its category calls for, and "
              "one missing its evidence is discarded unread, so quote rather than "
              "paraphrase: a quotation that is not in the text it claims to come "
              "from discards the finding. Criteria are referred to by number, "
              "including in other_criterion and covering."]
    if group == STATEMENT_GROUP:
        lines += ["", statements_body()]
    return "\n".join(lines)


# The reading that files a statement that something in the task is inaccurate.
STATEMENT_GROUP = "truth_fit"

STATEMENTS_SHAPE = (
    ' "statements": [{"id": "s1", "file": "<ground truth | justification | '
    'criterion <its number> | prompt | answer | a workspace path>", "quote": '
    '"<the words, copied exactly from where they are>", "reading": '
    '"inaccurate", "kind": "<' + " | ".join(sv.KINDS) + '>", "what_is_wrong": '
    '"<what is wrong with it, in a sentence>", "check": "<the check that '
    'settles it, with its numbers and the files it reads>", "confidence": '
    '"high", "bears_on": ["<criterion <its number> | justification | test '
    '<its name>>"]}, {"id": "s2", "file": "<...>", "quote": "<...>", '
    '"reading": "accurate"}],')


def statements_body() -> str:
    """What an inaccuracy is, and where it counts in this reading."""
    return "\n\n".join(p for p in [
        sv.contract_text(),
        sv.checks_text(),
        "Every inaccuracy goes in `statements`, and so do statements you checked "
        "closely and found accurate: list at least one of those, and up to as "
        "many as the inaccuracies you list. `file` says where the words are: "
        "the ground truth (the author's answer), the justification, a criterion "
        "by its number, the prompt, the run's answer, or a workspace file by its "
        "path.",
        "An incorrect_criteria row is an inaccuracy whatever else it is, so it "
        "names its statement in `statement`: the criterion's own words, or the "
        "author's answer's that the criterion repeats. Check the author's "
        "answer's own statements that a criterion, a unit test or the "
        "justification rests on as well: an inaccuracy there goes in "
        "`statements` with `bears_on` naming what rests on it, whether or not "
        "you file a row against a criterion. Each statement is checked again, "
        "independently, before anything rests on it.",
    ] if p)


def system_prompt(has_suite: bool = False) -> str:
    """The whole of what the reviewer is told, every reading together."""
    return "\n\n".join([shared_system()] + [group_body(g, has_suite)
                                             for g in GROUP_ORDER])


def _weight(value) -> str:
    try:
        return f"{int(value):+d}"
    except (TypeError, ValueError, OverflowError):
        return "?"


def build_request(criteria: list[dict], prompt: str, ground_truth: str,
                  workspace: list[str], tests: list[str] | None = None,
                  material: dict | None = None) -> str:
    """The task, laid out once and shared by every reading.

    `criteria` are dicts carrying at least `text` and `weight`, in the order
    they were written. `material` may carry the run's final `answer`, a
    `trajectory` digest, bounded `workspace_text`, and `fired`: which negative
    criteria the graded run was charged for, by criterion text.
    """
    material = material or {}
    fired = {_norm(k): v for k, v in (material.get("fired") or {}).items()}
    parts = ["## The criteria", ""]
    for index, crit in enumerate(criteria, 1):
        weight = crit.get("weight")
        tag = " [state]" if crit.get("kind") == "state change" else ""
        section = crit.get("section") or ""
        head = f"{index}. [{_weight(weight)}]{tag}"
        if section:
            head += f" (under {section})"
        note = ""
        key = _norm(crit.get("text", ""))
        if key in fired and isinstance(weight, (int, float)) and weight < 0:
            note = " -- fired against the graded run" if fired[key] else \
                   " -- did not fire against the graded run"
        parts.append(f"{head} {crit.get('text', '')}{note}")
    parts += ["", "## The prompt the task asks", "", prompt.strip() or "(empty)"]
    parts += ["", "## The author's own answer", "",
              _B64_BLOB.sub("[encoded image omitted]", ground_truth).strip()
              or "(none was written)"]
    justification = (material.get("justification") or "").strip()
    if justification:
        parts += ["", "## The author's justification of that answer", "",
                  _B64_BLOB.sub("[encoded image omitted]", justification)]
    parts += ["", "## The material the task supplies", ""]
    parts += [f"- {name}" for name in workspace] or ["(none)"]
    if tests:
        parts += ["", "## The unit tests", ""]
        parts += [f"- {name}" for name in tests]
    text = (material.get("workspace_text") or "").strip()
    if text:
        parts += ["", "## Extracts of the material", "",
                  _B64_BLOB.sub("[encoded data omitted]", text)[:MATERIAL_CHARS]]
    answer = (material.get("answer") or "").strip()
    parts += ["", "## The graded run's final answer", "",
              answer[:ANSWER_CHARS] if answer else "(no run has answered yet)"]
    steps = (material.get("trajectory") or "").strip()
    if steps:
        parts += ["", "## What the run did", "", steps[:TRAJECTORY_CHARS]]
    return "\n".join(parts)


def sender(model, key: str, base: str, shape: str, has_suite: bool = False,
           usage: list | None = None, thinking: int = THINKING,
           answered: dict | None = None):
    """A `send(request)` over HTTP. The shared material is sent as a cached prefix.

    `model` is one name, or a sequence to fall back through when one declines.
    `answered`, when given, receives the model that replied, by review group.
    """
    def send(request: dict) -> str:
        got: list[str] = []
        text = call_models(request["body"], model, key, base, shape, answered=got,
                           system=request["system"], max_tokens=MAX_TOKENS,
                           prefix=request["prefix"] + "\n\n", usage=usage,
                           thinking=thinking)
        if answered is not None and got:
            answered[request["group"]] = got[0]
        return text
    return send


# --- reading a reply ------------------------------------------------------------


@dataclass
class Finding:
    """One defect, and what it was established from."""
    category: str
    criterion: str = ""
    index: int | None = None
    what: str = ""
    remedy: str = ""
    evidence: dict = field(default_factory=dict)
    samples: int = 1
    exempt: str = ""
    from_run: bool | None = None
    covered: bool | None = None

    @property
    def cat(self) -> Category:
        return CATEGORIES[self.category]

    @property
    def severity(self) -> str:
        return self.cat.severity

    @property
    def group(self) -> str:
        return self.cat.group

    @property
    def ident(self) -> str:
        """What makes two readings' findings the same finding.

        The criterion and the review that raised it, not the exact category:
        the same point filed under a sibling category in a later reading is the
        same finding. A missing requirement is keyed to the prompt sentence it
        was quoted from, since the quoted span varies between readings.
        """
        if self.criterion:
            basis = f"{self.group}|{_norm(self.criterion)}"
        else:
            basis = (f"{self.group}|missing|"
                     + _norm(self.evidence.get("prompt_sentence")
                             or self.evidence.get("prompt_quote")
                             or self.evidence.get("answer_quote") or ""))
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    @property
    def key(self) -> str:
        return self.ident

    @property
    def counts_toward(self) -> str | None:
        """Which line this finding counts towards, if any."""
        if self.exempt:
            return None
        if self.cat.counts == "generality":
            return "generality" if (self.from_run and not self.covered) else None
        return self.cat.counts

    @property
    def reproduced(self) -> bool:
        return self.samples >= REPRODUCTION

    @property
    def blocking(self) -> bool:
        """Seen often enough, and of a kind, to count towards the fail line."""
        return self.reproduced and self.counts_toward is not None

    def as_dict(self) -> dict:
        return {"id": self.ident, "category": self.category, "name": self.cat.name,
                "label": label(self.category),
                "group": self.group, "severity": self.severity,
                "criterion": self.criterion, "index": self.index,
                "what": self.what, "remedy": self.remedy,
                "evidence": self.evidence, "samples": self.samples,
                "exempt": self.exempt, "from_run": self.from_run,
                "covered": self.covered, "counts_toward": self.counts_toward,
                "blocking": self.blocking}

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        key = ALIASES.get(data.get("category"), data.get("category"))
        return cls(category=key if key in CATEGORIES else "subjective",
                   criterion=data.get("criterion") or "", index=data.get("index"),
                   what=data.get("what") or "", remedy=data.get("remedy") or "",
                   evidence=dict(data.get("evidence") or {}),
                   samples=int(data.get("samples") or 1),
                   exempt=data.get("exempt") or "", from_run=data.get("from_run"),
                   covered=data.get("covered"))


RUBRIC_LINE = re.compile(r"^\s*[-*]?\s*\[[+-]?[135]\]\s*(?:\[[a-z-]+\]\s*)?",
                         re.IGNORECASE | re.MULTILINE)
_FIGURE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?!\d)")


def scrub(text: str) -> str:
    """A remedy with any finished criterion line taken out of it.

    The contributor writes every criterion, so a remedy says what to change and
    is not a line to paste. A weight tag is what makes a sentence a criterion
    rather than advice, so that is what comes off.
    """
    return " ".join(RUBRIC_LINE.sub("", text or "").split())


def _hedged(text: str) -> bool:
    lowered = _norm(text)
    return any(hedge in lowered for hedge in HEDGES)


def _bands_apart(carried, proposed) -> int | None:
    """How many bands apart two weights are, or None if either is off the scale.

    Answering None rather than raising keeps an off-scale weight a dropped
    finding instead of an exception out of the middle of a review.
    """
    if carried not in WEIGHTS or proposed not in WEIGHTS:
        return None
    return abs(WEIGHTS.index(carried) - WEIGHTS.index(proposed))


def _quoted(claim: str, source: str) -> bool:
    """Whether a quotation really is in the text it is attributed to.

    Long quotations are matched on their opening words: a model that copies a
    sentence and normalises a comma has still quoted it, while one that
    paraphrases has not.
    """
    want, have = _norm(claim), _norm(source)
    if not want:
        return False
    if want in have:
        return True
    words = want.split()
    return len(words) > 6 and " ".join(words[:6]) in have


_WORD = re.compile(r"[a-z0-9][a-z0-9_.-]{2,}")


def _named_in(part: str, text: str) -> bool:
    """Whether a part of a criterion, in the reviewer's own words, is recognisably in it.

    Quoted, or a third of its content words the criterion's own. A reading
    naming the two halves of a bundle often paraphrases them; a part with
    nothing in common with the criterion is not one of its parts.
    """
    if _quoted(part, text):
        return True
    have = set(_WORD.findall(_norm(text)))
    want = {w for w in _WORD.findall(_norm(part)) if w not in _STOP}
    return bool(want & have) and len(want & have) * 3 >= len(want)


_STOP = frozenset("the and that this with from for response states names reports "
                  "gives which what whether its their them they part".split())


def _figures(text: str) -> set[str]:
    return {m.group().replace(",", "") for m in _FIGURE.finditer(text or "")
            if len(m.group()) > 1 or "." in m.group()}


# A line that opens by naming a file checks that file, whether or not it was
# tagged [state].
_OPENS_WITH_FILE = re.compile(r"^\s*[\w./-]+\.[A-Za-z][A-Za-z0-9]{0,5}\b")

# The note an exempt Limited Exception finding carries.
LIMITED_EXEMPT = "supplementary, and another criterion covers it"
# A negative naming a class of wrong claims and giving examples of its members
# is self-contained: the examples show what puts a claim in the class.
EXAMPLES_EXEMPT = "it names a class of wrong claims and gives examples of it"
_GIVES_EXAMPLES = re.compile(r"\be\.g\.|\bfor example\b|\bsuch as\b", re.I)
PROVEN_EXEMPT = ("the negative fired against the graded run, so it is a proven "
                 "hallucination and not overlap")
UNCONFIRMED_EXEMPT = ("the statement it rests on was not confirmed by the "
                      "independent check, so it is recorded and not counted")


def _checks_a_file(crit: dict) -> bool:
    return crit.get("kind") == "state change" or bool(
        _OPENS_WITH_FILE.match(crit.get("text", "") or ""))


def _proven(pair: list[tuple[str, object]], fired: dict[str, bool]) -> bool:
    """Whether an opposite-polarity pair's negative fired against the graded run."""
    signs = {w > 0 for _, w in pair if isinstance(w, (int, float))}
    if signs != {True, False}:
        return False
    negative = next(t for t, w in pair if isinstance(w, (int, float)) and w < 0)
    return bool(fired.get(_norm(negative)))


def apply_fired(findings: list["Finding"], criteria: list[dict],
                fired: dict[str, bool] | None) -> list["Finding"]:
    """The recorded findings with the current grade applied to them.

    Whether a negative fired is the grade's to say, and the grade can be taken
    or retaken after the review. An overlap between a positive and a negative
    that fired is a proven hallucination and not overlap, so it stops
    counting; one whose negative no longer fires counts again. Nothing else is
    read again.
    """
    fired = {_norm(k): v for k, v in (fired or {}).items()}
    weights = {_norm(c.get("text", "")): c.get("weight") for c in criteria}
    for f in findings:
        other = f.evidence.get("other_criterion")
        if f.category != "overlapping" or not other or f.exempt not in ("", PROVEN_EXEMPT):
            continue
        pair = [(f.criterion, weights.get(_norm(f.criterion))),
                (other, weights.get(_norm(other)))]
        f.exempt = PROVEN_EXEMPT if _proven(pair, fired) else ""
    return findings


# --- decided from the lines themselves -------------------------------------------

_IDENTIFIER = re.compile(r"[A-Za-z0-9][\w./-]*[A-Za-z0-9]")
_ABOUT_TRAJECTORY = re.compile(
    r"^\s*(?:(?:the\s+)?(?:agent(?:'|\u2019)s\s+)?trajectory\b|(?:the\s+)?agent\b"
    r"|in\s+(?:its|the)\b[^.]*\btrajectory\b)", re.I)
# At most this many candidate pairs go to the redundancy reading.
PAIRS_ASKED = 12


def _marks(text: str) -> set[str]:
    """The identifiers and figures a criterion names."""
    words = {w.lower() for w in _IDENTIFIER.findall(text or "")
             if any(ch.isdigit() for ch in w) and any(ch.isalpha() for ch in w)}
    return words | _figures(text)


def _stem(word: str) -> str:
    word = word.rstrip(".-")
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _wording(text: str) -> set[str]:
    """A criterion's content words, plurals folded and figures left out."""
    return {_stem(w) for w in _WORD.findall(_norm(text))
            if w.rstrip(".-") not in _STOP and len(w.rstrip(".-")) > 2
            and not any(ch.isdigit() for ch in w)}


def carryovers(criteria: list[dict]) -> list[Finding]:
    """A [1] line about a file whose figures a [5] line about the answer checks.

    A file's copy of a value is weighted like the value it copies, never below
    [3]. Decided from the lines alone, so each counts without further readings.
    """
    answers = [c for c in criteria
               if c.get("weight") == 5 and not _checks_a_file(c)]
    out = []
    for index, crit in enumerate(criteria, 1):
        figures = _figures(crit.get("text", ""))
        if crit.get("weight") != 1 or not figures or not _checks_a_file(crit):
            continue
        source = next((a for a in answers
                       if figures <= _figures(a.get("text", ""))), None)
        if source is None:
            continue
        out.append(Finding(
            category="incorrect_weight_major", criterion=crit.get("text", ""),
            index=index, samples=REPRODUCTION,
            what=("It checks a file's copy of a value that a [5] line checks in the "
                  "answer, and a copy is weighted like the value it copies."),
            remedy="Weight it [5] where the prompt asks for the file, and never below [3].",
            evidence={"bucket": "+5", "proposed_weight": 3, "accepted_weights": [3, 5],
                      "carries": source.get("text", ""), "decided_by": "code"}))
    return out


def containment_pairs(criteria: list[dict]) -> list[tuple[int, int]]:
    """Pairs of same-sign criteria about the same thing, where every identifier,
    figure and content word of the first is in the second. By number, the most
    specific first.

    A line about the answer and a line about a file carrying its value are never
    a pair: that is a carryover, weighed rather than overlapping. Nor are a line
    about the answer and one about the trajectory.
    """
    marks = [_marks(c.get("text", "")) for c in criteria]
    words = [_wording(c.get("text", "")) for c in criteria]
    about = [bool(_ABOUT_TRAJECTORY.match(c.get("text", "") or "")) for c in criteria]
    found = []
    for i, a in enumerate(criteria):
        for j, b in enumerate(criteria):
            wa, wb = a.get("weight"), b.get("weight")
            if (i == j or not marks[i] or not words[i]
                    or not isinstance(wa, (int, float))
                    or not isinstance(wb, (int, float)) or (wa > 0) != (wb > 0)
                    or _checks_a_file(a) != _checks_a_file(b) or about[i] != about[j]
                    or not marks[i] <= marks[j]
                    or (marks[i] == marks[j] and j < i)
                    or not words[i] <= words[j]):
                continue
            found.append((i + 1, j + 1))
    found.sort(key=lambda p: (-len(marks[p[0] - 1]), p))
    return found[:PAIRS_ASKED]


def _pairs_text(criteria: list[dict], pairs: list[tuple[int, int]]) -> str:
    if not pairs:
        return ""
    return "\n".join([
        "## Pairs to rule on", "",
        "Every identifier and figure in the first criterion of each pair below is "
        "also in the second. For each pair, add to the reply a `pairs` list with a "
        "row giving a response that would earn the second criterion and not the "
        "first. Where no such response exists, the first repeats the second: file "
        "it as an `overlapping` row with the second as other_criterion.", "",
        *(f"- {a} and {b}" for a, b in pairs), "",
        'Each row: {"first": <number>, "second": <number>, "response": "<a response '
        'earning the second and not the first>"}.'])


def _separated(parsed: dict, criteria: list[dict]) -> set[tuple[str, str]]:
    """The pairs a reading separated: first and second by their text."""
    out = set()
    for row in parsed.get("pairs") or []:
        if not isinstance(row, dict) or not str(row.get("response") or "").strip():
            continue
        try:
            a, b = int(row.get("first")), int(row.get("second"))
        except (TypeError, ValueError, OverflowError):
            continue
        if 1 <= a <= len(criteria) and 1 <= b <= len(criteria):
            out.add((_norm(criteria[a - 1].get("text", "")),
                     _norm(criteria[b - 1].get("text", ""))))
    return out


def repeats(findings: list[Finding], reproduced_only: bool = True) -> list[str]:
    """The criteria that only repeat another line, by their text.

    From overlap findings that count, and never both lines of a pair: the line
    that is repeated still counts.
    """
    gone: set[str] = set()
    out = []
    use = sorted((f for f in findings
                  if f.category == "overlapping" and f.criterion and not f.exempt
                  and f.evidence.get("other_criterion")
                  and (f.reproduced or not reproduced_only)),
                 key=lambda f: (f.index is None, f.index or 0, f.ident))
    for f in use:
        mine, other = _norm(f.criterion), _norm(f.evidence["other_criterion"])
        if mine in gone or other in gone or mine == other:
            continue
        gone.add(mine)
        out.append(f.criterion)
    return out


def _sentence_of(quote: str, text: str) -> str:
    """The sentence of `text` a quotation was taken from."""
    want = _norm(quote)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if want and want[:60] in _norm(sentence):
            return sentence.strip()
    return quote


RESOLVE_MIN_CHARS = 15


def _resolve(text: str, lookup: dict) -> tuple[int, dict] | None:
    """The criterion a reply names, by its text or a fragment of it long enough to mean it."""
    found = lookup.get(_norm(text))
    if found is None and len(_norm(text)) >= RESOLVE_MIN_CHARS:
        for norm_text, pair in lookup.items():
            if _norm(text) in norm_text or norm_text in _norm(text):
                return pair
    return found


def _by_number(value, criteria: list[dict]):
    """A criterion given by its number in the list, as its text; anything else as it is."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        n = int(value)
        if 1 <= n <= len(criteria):
            return criteria[n - 1].get("text", "")
        return ""
    return value


def _numbered(values, criteria: list[dict]) -> list[str]:
    values = values if isinstance(values, list) else ([values] if values not in (None, "") else [])
    return [t for t in (_by_number(v, criteria) for v in values) if isinstance(t, str) and t]


def _rows(parsed: dict, criteria: list[dict]) -> list[dict]:
    """The per-criterion rows of a reply, as findings: defects, prices, and gaps.

    A clean row is no finding. A weight row whose bucket is the weight the
    criterion carries is none either. A requirement or a claim of the run's
    that nothing covers is a missing criterion.
    """
    out = []
    for row in parsed.get("verdicts") or []:
        if not isinstance(row, dict):
            continue
        text = _by_number(row.get("criterion"), criteria)
        if "bucket" in row and not row.get("verdict"):
            try:
                bucket = int(float(str(row["bucket"]).replace("+", "")))
            except (ValueError, OverflowError):
                continue
            carried = next((c.get("weight") for c in criteria if c.get("text") == text), None)
            if carried == bucket or row.get("clear") is False \
                    or str(row.get("clear")).lower() == "false":
                continue
            out.append({"category": "incorrect_weight_minor", "criterion": text,
                        "what": row.get("why") or f"its content puts it at {bucket:+d}",
                        "remedy": row.get("remedy") or f"weigh it at {bucket:+d}",
                        "bucket": row.get("why") or f"{bucket:+d}",
                        "proposed_weight": bucket})
            continue
        verdict = str(row.get("verdict", "")).strip()
        if not verdict or verdict.lower() == "clean":
            continue
        raw = dict(row, category=verdict, criterion=text)
        if "other_criterion" in raw:
            raw["other_criterion"] = _by_number(raw["other_criterion"], criteria)
        if "covering" in raw:
            raw["covering"] = _numbered(raw["covering"], criteria)
        out.append(raw)
    for row in parsed.get("requirements") or []:
        if not isinstance(row, dict):
            continue
        covered = row.get("covered_by") or []
        covered = covered if isinstance(covered, list) else [covered]
        # A test name covers it as well as a criterion number does.
        if _numbered(covered, criteria) or any(
                isinstance(v, str) and v.strip() and not v.strip().isdigit() for v in covered):
            continue
        quote = str(row.get("prompt_quote") or "").strip()
        out.append({"category": "missing_critical" if row.get("critical") else "missing_noncritical",
                    "criterion": "", "prompt_quote": quote,
                    "what": f"No criterion checks what the prompt asks here: {quote}",
                    "remedy": row.get("remedy") or "add a criterion that checks it"})
    for row in parsed.get("annotations") or []:
        if not isinstance(row, dict) or _numbered(row.get("covered_by"), criteria):
            continue
        quote = str(row.get("answer_quote") or "").strip()
        out.append({"category": "missing_critical", "criterion": "", "answer_quote": quote,
                    "what": f"The run's answer claims this and no criterion penalises "
                            f"it: {quote}",
                    "remedy": "add a negative criterion describing that mistake"})
    return out


def _escape_rows(parsed: dict, criteria: list[dict] | None = None
                 ) -> tuple[list[dict], list[str]]:
    """The generality reading's per-negative rulings, as findings and notes."""
    rows, notes = [], []
    criteria = criteria or []
    for row in parsed.get("escape_verdicts") or []:
        if not isinstance(row, dict):
            continue
        verdict = str(row.get("verdict", "")).strip().lower()
        covering = row.get("covered_by")
        if covering not in (None, "", "null"):
            covering = _by_number(covering, criteria)
        if verdict == "escapable":
            rows.append({"category": "hallucination_generality",
                         "criterion": _by_number(row.get("criterion", ""), criteria),
                         "what": row.get("detail") or
                                 f"a rerun could write: {row.get('escape', '')}",
                         "remedy": row.get("remedy") or
                                   "describe the failure rather than one run's values",
                         "particular": row.get("particular"),
                         "escape": row.get("escape"),
                         "covered_by": covering})
        elif verdict == "undecided":
            notes.append(f"undecided: {row.get('criterion', '')} -- {row.get('detail', '')}")
    return rows, notes


def read_findings(parsed: dict, criteria: list[dict], prompt: str,
                  ground_truth: str, material: dict | None = None,
                  statements: dict[str, "sv.Statement"] | None = None
                  ) -> tuple[list[Finding], int, list[str]]:
    """The findings in one reply that clear the evidence bar, and what was dropped.

    Everything is checked here rather than asked for nicely: an unknown
    category, a criterion that is not in the rubric, a quotation that is not in
    the text it claims to come from, a hedged claim, or a missing evidence field
    all discard the finding. The exceptions that can be decided from the
    material are decided here too, whatever the model concluded. The model is
    the instrument being guarded against.
    """
    material = material or {}
    answer = material.get("answer") or ""
    workspace_text = material.get("workspace_text") or ""
    fired = {_norm(k): v for k, v in (material.get("fired") or {}).items()}
    lookup = {_norm(c.get("text", "")): (i, c) for i, c in enumerate(criteria, 1)}
    raws = [dict(r, criterion=_by_number(r.get("criterion"), criteria))
            for r in parsed.get("findings") or [] if isinstance(r, dict)]
    extra, _ = _escape_rows(parsed, criteria)
    raws += extra + _rows(parsed, criteria)
    kept, dropped = [], []
    for raw in raws:
        key = _norm(str(raw.get("category", ""))).replace(" ", "_").replace("-", "_")
        key = ALIASES.get(key, key)
        cat = CATEGORIES.get(key)
        if cat is None:
            dropped.append(f"unknown category {raw.get('category')!r}")
            continue
        what = str(raw.get("what", "")).strip()
        if not what:
            dropped.append(f"{cat.key}: no defect was stated")
            continue
        if _hedged(what):
            dropped.append(f"{cat.key}: the claim hedges, so it is not a finding")
            continue

        text = str(raw.get("criterion", "")).strip()
        index, crit = None, {}
        if text:
            found = _resolve(text, lookup)
            if found is None:
                dropped.append(f"{cat.key}: no such criterion is in the rubric")
                continue
            index, crit = found
            text = crit.get("text", "")
        elif not cat.key.startswith("missing") and cat.key != "too_many_spot_checks":
            dropped.append(f"{cat.key}: named no criterion")
            continue
        weight = crit.get("weight")

        evidence, missing = {}, []
        for name in cat.evidence:
            value = raw.get(name)
            value = str(value).strip() if value is not None else ""
            if not value:
                missing.append(name)
                continue
            evidence[name] = value
        if cat.one_of:
            chosen = {n: str(raw[n]).strip() for n in cat.one_of
                      if raw.get(n) is not None and str(raw[n]).strip()}
            if not chosen:
                missing.append(" or ".join(cat.one_of))
            evidence.update(chosen)
        if missing:
            dropped.append(f"{cat.key}: no {', '.join(missing)}")
            continue

        finding = Finding(category=cat.key, criterion=text, index=index,
                          what=contributor_text(what),
                          remedy=contributor_text(scrub(str(raw.get("remedy", "")))),
                          evidence=evidence)

        if "prompt_quote" in evidence:
            if not _quoted(evidence["prompt_quote"], prompt):
                if "answer_quote" not in evidence:
                    dropped.append(f"{cat.key}: its quotation is not in the prompt")
                    continue
                evidence.pop("prompt_quote")
            else:
                evidence["prompt_sentence"] = _sentence_of(evidence["prompt_quote"], prompt)
        if "answer_quote" in evidence and "prompt_quote" not in evidence:
            # A hallucination the run committed. An anticipated trap the run
            # never fell for is not a missing criterion.
            if not answer or not _quoted(evidence["answer_quote"], answer):
                dropped.append(f"{cat.key}: the claim it quotes is not in the run's answer")
                continue
        if "ground_truth_quote" in evidence and not _quoted(evidence["ground_truth_quote"], ground_truth):
            evidence.pop("ground_truth_quote")
            if not ({"material_quote", "check"} & set(evidence)):
                dropped.append(f"{cat.key}: its quotation is not in the answer")
                continue
        if "material_quote" in evidence and not _quoted(evidence["material_quote"], workspace_text):
            evidence.pop("material_quote")
            if not ({"ground_truth_quote", "check"} & set(evidence)):
                dropped.append(f"{cat.key}: its quotation is not in the material")
                continue
        if "qualifier" in evidence and not _quoted(evidence["qualifier"], text):
            dropped.append(f"{cat.key}: the qualifier it names is not in the criterion")
            continue
        for part in ("part_a", "part_b"):
            if part in evidence and not _named_in(evidence[part], text):
                dropped.append(f"{cat.key}: {part} is not in the criterion")
                break
        else:
            part = None
        if part:
            continue

        if cat.key == "double_negative" and not (isinstance(weight, (int, float)) and weight < 0):
            dropped.append(f"{cat.key}: only a negative criterion can be one")
            continue

        if "statement" in evidence:
            held = (statements or {}).get(evidence["statement"])
            if held is None or not held.flagged:
                dropped.append(f"{cat.key}: the statement it names is not one the "
                               "reading settled with a check")
                continue
            evidence.update(statement=held.ident, statement_quote=held.quote,
                            statement_where=held.where(), check=held.check)

        if "other_criterion" in evidence:
            evidence["other_criterion"] = _by_number(evidence["other_criterion"], criteria)
            other = _resolve(evidence["other_criterion"], lookup)
            if other is None or other[0] == index:
                dropped.append(f"{cat.key}: the criterion it overlaps is not in the rubric")
                continue
            evidence["other_criterion"] = other[1].get("text", "")
            if cat.key == "overlapping" and _checks_a_file(crit) != _checks_a_file(other[1]):
                dropped.append(f"{cat.key}: a value carried into a file is not "
                               "overlap; only the copy's weight is judged")
                continue
            pair = [(text, weight), (other[1].get("text", ""), other[1].get("weight"))]
            if cat.key == "overlapping" and _proven(pair, fired):
                finding.exempt = PROVEN_EXEMPT

        if cat.key == "hallucination_generality":
            if not _quoted(evidence["particular"], text):
                dropped.append(f"{cat.key}: its quotation is not in the criterion")
                continue
            if not (isinstance(weight, (int, float)) and weight < 0):
                dropped.append(f"{cat.key}: the criterion it names is not a negative one")
                continue
            named = _figures(evidence["particular"])
            finding.from_run = bool(answer) and (
                (bool(named) and named <= _figures(answer))
                or _quoted(evidence["particular"], answer))
            covering = raw.get("covered_by")
            covering = str(covering).strip() if covering not in (None, "null") else ""
            if covering:
                resolved = _resolve(covering, lookup)
                if resolved is not None and resolved[0] != index:
                    evidence["covered_by"] = resolved[1].get("text", "")
                    finding.covered = True
                else:
                    finding.covered = False
            else:
                finding.covered = False
            if not finding.from_run:
                finding.exempt = ("its wrong values were not taken from the run, "
                                  "so it is reported and not counted")
            elif finding.covered:
                finding.exempt = "another criterion catches what it misses"

        if "proposed_weight" in evidence:
            try:
                proposed = int(float(evidence["proposed_weight"]))
            except (ValueError, OverflowError):
                dropped.append(f"{cat.key}: the weight it proposes is not a number")
                continue
            if proposed not in WEIGHTS:
                dropped.append(f"{cat.key}: {proposed} is not one of the six weights")
                continue
            evidence["proposed_weight"] = proposed
            distance = _bands_apart(weight, proposed)
            if distance is not None:
                if distance == 0:
                    dropped.append(f"{cat.key}: the weight it proposes is the one it has")
                    continue
                # The severity is the distance, whichever half filed it.
                finding.category = ("incorrect_weight_major" if distance > 1
                                    else "incorrect_weight_minor")
                if distance == 1 and weight == 3 and proposed == 5:
                    shared = _figures(text) & set().union(*(
                        _figures(c.get("text", "")) for i, c in enumerate(criteria, 1)
                        if c.get("weight") == 5 and i != index))
                    if shared:
                        dropped.append(f"{cat.key}: a carryover of a value a +5 "
                                       "criterion already checks")
                        continue

        if cat.key == "not_self_contained" and str(raw.get("limited_exception", "")).lower() in ("true", "yes", "1"):
            covering = _numbered(raw.get("covering") or [], criteria)
            resolved = [_resolve(str(c), lookup) for c in covering]
            if resolved and all(r is not None and r[0] != index
                                and isinstance(r[1].get("weight"), (int, float))
                                and r[1]["weight"] > 0 for r in resolved) and weight != 5:
                evidence["covering"] = [r[1].get("text", "") for r in resolved]
                finding.exempt = LIMITED_EXEMPT
        if (cat.key == "not_self_contained" and not finding.exempt
                and isinstance(weight, (int, float)) and weight < 0
                and _GIVES_EXAMPLES.search(text)):
            finding.exempt = EXAMPLES_EXEMPT

        kept.append(finding)

    # The Limited Exception holds only while every covering criterion is
    # itself self-contained.
    unsettled = {_norm(f.criterion) for f in kept
                 if f.category == "not_self_contained" and not f.exempt}
    for f in kept:
        if f.exempt == LIMITED_EXEMPT and any(
                _norm(c) in unsettled for c in f.evidence.get("covering", [])):
            f.exempt = ""

    examined = parsed.get("criteria_examined")
    try:
        examined = int(examined)
    except (TypeError, ValueError):
        examined = 0
    return kept, examined, dropped


# --- the line -------------------------------------------------------------------


def line(findings: list[Finding], criteria_written: int, *,
         reproduced_only: bool = True) -> dict:
    """Where the rubric stands against the line a rubric fails at.

    The denominator is the criteria written, a criterion with several findings
    counts once at its worst severity, each missing requirement is its own
    unit, and the limits are exclusive. Uncovered escapes taken from the run
    count against their own limit, over every criterion. The reason names
    counts and never a limit.
    """
    n = int(criteria_written or 0)
    use = [f for f in findings if f.counts_toward
           and (f.reproduced or not reproduced_only)]
    worst, missing, escapes = {}, [], {}
    for f in use:
        if f.counts_toward == "generality":
            escapes[_norm(f.criterion)] = f
            continue
        if f.severity not in SEVERITY_RANK:
            continue
        if not f.criterion:
            missing.append(f)
            continue
        prior = worst.get(_norm(f.criterion))
        if prior is None or SEVERITY_RANK[f.severity] > SEVERITY_RANK[prior.severity]:
            worst[_norm(f.criterion)] = f
    units = list(worst.values()) + missing
    majors = sum(1 for u in units if u.severity == "major")
    moderates = sum(1 for u in units if u.severity == "moderate")
    general = len(escapes)
    out = {"criteria_written": n, "major": majors, "moderate": moderates,
           "minor": len(units) - majors - moderates, "units": len(units),
           "escapes": general, "counted": [u.ident for u in units]
           + [e.ident for e in escapes.values()]}
    if not n:
        out.update(over=False, quality_over=False, generality_over=False,
                   reason="the number of criteria written is unknown", to_clear=0)
        return out

    def over(maj: int, mod: int, total: int, esc: int) -> list[str]:
        why = []
        if maj * 100 > MAJOR_LIMIT * n:
            why.append(f"{maj} of {n} criteria carry a major issue")
        if (maj + mod) * 100 > MAJOR_MODERATE_LIMIT * n:
            why.append(f"{maj + mod} of {n} carry a major or moderate issue")
        if total * 100 > ANY_LIMIT * n:
            why.append(f"{total} of {n} carry an issue of any severity")
        if esc * 100 > GENERALITY_LIMIT * n:
            why.append(f"{esc} of {n} negative criteria can be walked around by a "
                       f"rerun, with nothing else catching it")
        return why

    reasons = over(majors, moderates, len(units), general)
    out["quality_over"] = bool(over(majors, moderates, len(units), 0))
    out["generality_over"] = general * 100 > GENERALITY_LIMIT * n
    # The fewest counted findings whose repair brings the rubric under, taking
    # the worst first since each major lowers all three quality counts.
    order = sorted(units, key=lambda u: -SEVERITY_RANK.get(u.severity, 0))
    maj, mod, total, cleared = majors, moderates, len(units), 0
    for u in order:
        if not over(maj, mod, total, 0):
            break
        maj -= u.severity == "major"
        mod -= u.severity == "moderate"
        total -= 1
        cleared += 1
    esc_allowed = (GENERALITY_LIMIT * n) // 100
    cleared += max(0, general - esc_allowed)
    out.update(over=bool(reasons), reason="; ".join(reasons), to_clear=cleared)
    return out


def score(findings: list[Finding], criteria_written: int) -> tuple[str, dict]:
    """Where the rubric stands on every finding this review made.

    Beside the verdict and deciding nothing: it counts findings seen in a
    single reading as well.
    """
    reading = line(findings, criteria_written, reproduced_only=False)
    detail = {"affected": reading["units"], "criteria_written": criteria_written,
              "major": reading["major"], "moderate": reading["moderate"],
              "minor": reading["minor"], "escapes": reading["escapes"]}
    if not criteria_written:
        detail["why"] = "the number of criteria written is unknown"
        return "UNMEASURED", detail
    n = int(criteria_written)
    detail.update(pct_major=round(reading["major"] / n, 4),
                  pct_major_moderate=round((reading["major"] + reading["moderate"]) / n, 4),
                  pct_any=round(reading["units"] / n, 4))
    if reading["over"]:
        detail["reason"] = reading["reason"]
        return "FAIL", detail
    if not reading["major"] and not reading["moderate"] and \
            reading["minor"] * 100 < CLEAN_MINOR_LIMIT * n and not reading["escapes"]:
        detail["reason"] = "no major or moderate issue, and few minor ones"
        return "CLEAN", detail
    detail["reason"] = (f"{reading['major']} major, {reading['moderate']} moderate, "
                        f"{reading['minor']} minor: not enough to refuse, and not clean")
    return "ISSUE", detail


@dataclass
class Report:
    """What the readings came to."""
    findings: list[Finding] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    criteria_written: int = 0
    criteria_examined: int = 0
    samples: int = 0
    verdict: str = "UNMEASURED"
    why: str = ""
    review: str = "UNMEASURED"
    review_detail: dict = field(default_factory=dict)
    line: dict = field(default_factory=dict)
    model: str = ""
    unmeasured_groups: list[str] = field(default_factory=list)
    unmeasured_why: dict = field(default_factory=dict)
    answered_by: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    statements: list = field(default_factory=list)
    vote: dict = field(default_factory=dict)
    sessions: dict = field(default_factory=dict)

    @property
    def blocking(self) -> list[Finding]:
        """The counted findings, when they put the rubric past the line."""
        if not self.line.get("over"):
            return []
        counted = set(self.line.get("counted") or [])
        return [f for f in self.findings if f.ident in counted]

    @property
    def clears(self) -> bool:
        return self.verdict in ("PASS", "WARN")

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "why": self.why, "model": self.model,
                "samples": self.samples,
                "criteria_written": self.criteria_written,
                "criteria_examined": self.criteria_examined,
                "review": self.review, "review_detail": dict(self.review_detail),
                "line": dict(self.line), "blocking": len(self.blocking),
                "findings": [f.as_dict() for f in self.findings],
                "notes": list(self.notes),
                "unmeasured_groups": list(self.unmeasured_groups),
                "unmeasured_why": dict(self.unmeasured_why),
                "answered_by": dict(self.answered_by),
                "usage": dict(self.usage), "dropped": self.dropped,
                "statements": [s.as_dict() for s in self.statements],
                "vote": dict(self.vote), "sessions": dict(self.sessions),
                "consistency": sv.consistency(self.statements)}


def judge(report: Report) -> Report:
    """The verdict the findings come to together.

    Only findings seen in every reading count, and they refuse only when there
    are too many of them, until the rubric is fixed. Everything else is
    reported and holds nothing up. A rubric some group could not read is never
    PASS: those categories were not checked, so nothing was established about
    them.
    """
    report.line = line(report.findings, report.criteria_written)
    if report.line.get("over"):
        report.verdict = "FAIL"
        k = len(report.line.get("counted") or [])
        report.why = (f"{k} finding{'' if k == 1 else 's'} seen in every reading "
                      f"stop delivery until fixed")
    elif report.unmeasured_groups:
        report.verdict = "WARN"
        count = len(report.findings)
        report.why = (f"read in part: {', '.join(report.unmeasured_groups)} could "
                      "not be read, so those categories were not checked"
                      + (f"; {count} finding{'' if count == 1 else 's'} from the rest"
                         if count else ""))
    elif report.findings:
        report.verdict = "WARN"
        report.why = (f"{len(report.findings)} finding"
                      f"{'' if len(report.findings) == 1 else 's'} worth reading, "
                      "none of which stops the task")
    else:
        report.verdict = "PASS"
        report.why = "no defect was established in any criterion"
    return report


def _request(group: str, prefix: str, has_suite: bool, only: list[str] | None = None,
             pairs: str = "") -> dict:
    body = group_body(group, has_suite)
    if only:
        body += ("\n\n## Consider only these criteria\n\n"
                 + "\n".join(f"- {text}" for text in only))
    if pairs and group == "redundancy":
        body += "\n\n" + pairs
    return {"group": group, "system": shared_system(), "prefix": prefix, "body": body}


def with_decided(report: Report, criteria: list[dict]) -> Report:
    """A review nothing answered, with what the lines themselves decide."""
    report.findings = carryovers(criteria)
    report.line = line(report.findings, report.criteria_written)
    if report.line.get("over"):
        report.verdict = "FAIL"
        report.why = (f"{len(report.line.get('counted') or [])} findings decided "
                      f"from the lines themselves stop delivery until fixed; "
                      f"nothing else was read: {report.why}")
    return report


def _lost_why(exc: Exception) -> str:
    """Why a group's reading was lost, in the words the record keeps."""
    if isinstance(exc, Refused):
        return f"refused: {exc}"
    if isinstance(exc, Unreachable):
        return f"unreachable: {exc}"
    return f"unreadable reply: {exc}"


def _ask(send, requests: list[dict], workers: int) -> list[tuple[dict, str | Exception]]:
    def one(req):
        try:
            return req, send(req)
        except Exception as exc:  # noqa: BLE001 -- a reading lost is reported
            return req, exc
    if workers <= 1 or len(requests) <= 1:
        return [one(r) for r in requests]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, requests))


def apply_statements(findings: list[Finding], statements: list["sv.Statement"]) -> None:
    """An Incorrect Criteria finding counts only while its statement is confirmed."""
    confirmed = {s.ident for s in statements if s.confirmed}
    for f in findings:
        if f.category != "incorrect_criteria" or f.exempt not in ("", UNCONFIRMED_EXEMPT):
            continue
        f.exempt = "" if f.evidence.get("statement") in confirmed else UNCONFIRMED_EXEMPT


def statement_texts(prompt: str, ground_truth: str, material: dict | None) -> dict:
    """The texts a statement's words are held to, by where it says they are."""
    material = material or {}
    return {sv.GROUND_TRUTH: ground_truth, sv.JUSTIFICATION: material.get("justification") or "",
            sv.PROMPT: prompt, sv.ANSWER: material.get("answer") or "",
            "workspace": material.get("workspace_text") or ""}


def collect(criteria: list[dict], prompt: str, ground_truth: str,
            workspace: list[str], send, samples: int = DEFAULT_SAMPLES,
            tests: list[str] | None = None, model: str = "",
            material: dict | None = None, workers: int = WORKERS,
            usage: list | None = None, floor: int | None = None,
            session=None, vote=None, read_file=None) -> Report:
    """One reading per group of categories, and confirmation where it counts.

    Every group is read once. Only when that reading puts the rubric past the
    line are the groups with counted findings read again, up to `samples`
    readings in all, about the counted criteria alone -- so a rubric under the
    line costs nothing more. Overlap findings are confirmed the same way when,
    with `floor` given, the lines they repeat would leave fewer than `floor`
    checks. What the lines themselves decide counts without readings. A
    reading that could not be taken is reported, never scored around. Returns
    UNMEASURED when nothing answered, which is never the same as a rubric that
    was reviewed and found wanting.

    `session(request)`, where given, reads the truth-fit group in place of
    `send`, with the task's files to run Python on. `vote(statements)` puts
    that reading's flagged statements to the blind vote and returns its
    record; without it nothing is confirmed, so no Incorrect Criteria finding
    counts. `read_file(path)` reads a workspace file whole, to hold a
    statement's words to it.
    """
    report = Report(criteria_written=len(criteria), model=model)
    if not criteria:
        report.why = "the rubric has no criteria in it"
        return report
    has_suite = bool(tests)
    prefix = build_request(criteria, prompt, ground_truth, workspace, tests, material)
    candidates = containment_pairs(criteria)
    texts = statement_texts(prompt, ground_truth, material)
    found_statements: list[list[sv.Statement]] = []

    def dispatch(req: dict) -> str:
        if session is not None and req["group"] == STATEMENT_GROUP:
            return session(req)
        return send(req)

    def pairs_for(only: list[str] | None) -> str:
        if not only:
            return _pairs_text(criteria, candidates)
        wanted = {_norm(t) for t in only}
        return _pairs_text(criteria, [p for p in candidates
                                      if _norm(criteria[p[0] - 1].get("text", "")) in wanted])

    def parse(pairs):
        found, lost = {}, []
        for req, reply in pairs:
            if isinstance(reply, Exception):
                lost.append(f"{req['group']}: {reply}")
                report.unmeasured_why[req["group"]] = _lost_why(reply)
                continue
            try:
                parsed = parse_object(reply)
            except ValueError as exc:
                lost.append(f"{req['group']}: {exc}")
                report.unmeasured_why[req["group"]] = _lost_why(exc)
                continue
            by_id = {}
            if req["group"] == STATEMENT_GROUP:
                held, why = sv.read_statements(parsed, "rubric review", texts, criteria,
                                               tests, workspace, read_file)
                report.dropped.extend(why)
                found_statements.append(held)
                idents = sv.ids(parsed, held)
                by_id = {rid: next(s for s in held if s.ident == ident)
                         for rid, ident in idents.items()}
            kept, seen, dropped = read_findings(parsed, criteria, prompt,
                                                ground_truth, material, by_id)
            if req["group"] == "redundancy":
                apart = _separated(parsed, criteria)
                for f in [f for f in kept if f.category == "overlapping" and (
                        _norm(f.criterion),
                        _norm(f.evidence.get("other_criterion") or "")) in apart]:
                    kept.remove(f)
                    dropped.append("overlapping: the same reading gave a response "
                                   "earning one of the pair and not the other")
            _, undecided = _escape_rows(parsed, criteria)
            report.notes.extend(contributor_text(str(n)) for n in
                                (parsed.get("notes") or []) + undecided if n)
            report.dropped.extend(dropped)
            report.criteria_examined = max(report.criteria_examined, seen)
            found[req["group"]] = kept
        return found, lost

    first, lost = parse(_ask(dispatch, [_request(g, prefix, has_suite, pairs=pairs_for(None))
                                        for g in GROUP_ORDER], workers))
    if lost:
        # A filter that fires inconsistently and a passing network fault both
        # usually clear on a second asking, so each lost group is asked once more.
        retry = [l.split(":", 1)[0] for l in lost]
        again, lost = parse(_ask(dispatch, [_request(g, prefix, has_suite, pairs=pairs_for(None))
                                            for g in retry], workers))
        first.update(again)
        for group in again:
            report.unmeasured_why.pop(group, None)
    if not first:
        report.why = "; ".join(lost) or "nothing answered"
        return with_decided(report, criteria)
    report.unmeasured_groups = sorted(l.split(":", 1)[0] for l in lost)
    merged: dict[str, Finding] = {}
    for group in GROUP_ORDER:
        for f in first.get(group, []):
            merged.setdefault(f.ident, f)
    for f in carryovers(criteria):
        merged[f.ident] = f
    report.samples = 1

    report.statements = sv.merge(*found_statements)
    if vote is not None and any(s.flagged for s in report.statements):
        try:
            report.vote = vote(report.statements) or {}
        except Exception as exc:  # noqa: BLE001 -- a vote that could not be taken confirms nothing
            report.vote = {"asked": False, "why": f"{type(exc).__name__}: {exc}"}
    apply_statements(list(merged.values()), report.statements)

    provisional = line(list(merged.values()), len(criteria), reproduced_only=False)
    overlaps = {f.ident for f in merged.values()
                if _norm(f.criterion) in {_norm(t) for t in repeats(
                    list(merged.values()), reproduced_only=False)}
                and f.category == "overlapping"}
    under = (floor is not None and overlaps
             and len(criteria) + len(tests or []) - len(overlaps) < floor)
    if (provisional["over"] or under) and samples > 1:
        counted = (set(provisional["counted"]) if provisional["over"] else set()) \
            | (overlaps if under else set())
        by_group: dict[str, list[str]] = {}
        for f in merged.values():
            if f.evidence.get("decided_by"):
                continue
            if f.ident in counted and f.criterion:
                by_group.setdefault(f.group, []).append(f.criterion)
            elif f.ident in counted:
                by_group.setdefault(f.group, [])
        for _ in range(samples - 1):
            asked = [_request(g, prefix, has_suite, only or None, pairs_for(only))
                     for g, only in by_group.items()]
            again, _lost = parse(_ask(dispatch, asked, workers))
            report.samples += 1
            for group, kept in again.items():
                seen = set()
                for f in kept:
                    if f.ident in merged and f.ident in counted and f.ident not in seen:
                        merged[f.ident].samples += 1
                        seen.add(f.ident)

    report.findings = list(merged.values())
    report.review, report.review_detail = score(report.findings, len(criteria))
    judge(report)
    if lost:
        report.why += f" (not read: {'; '.join(lost)})"
    if usage:
        total: dict[str, int] = {}
        for entry in usage:
            for k, v in (entry or {}).items():
                total[k] = total.get(k, 0) + int(v)
        total["calls"] = len(usage)
        report.usage = total
    return report
