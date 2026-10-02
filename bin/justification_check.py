#!/usr/bin/env python3
"""Does the justification hold up against the prompt and the answer?

`solution/underspecification_justification.md` says why the contributor's
ground truth is the only answer an expert could reach. This asks whether that
claim survives being read against the two documents it is about.

Two passes, and the first one needs no model. A file that is still the template,
or that has a heading with nothing under it, is not a justification yet and
there is nothing to review -- saying so costs a second and does not spend a
gateway call. What the model pass then asks is the rest: is it true, does it
contradict itself, the prompt or the ground truth, and is it vague.

    python3 bin/justification_check.py             # review and record
    python3 bin/justification_check.py --json
    python3 bin/justification_check.py --samples 1
    python3 bin/justification_check.py --task ~/flc/task

Nothing here writes into solution/underspecification_justification.md. The
justification is the contributor's account of why their own answer is forced,
and one an assistant composed is a model's opinion of a model's reading --
which is the defect the file exists to rule out.

Exit code 0 when it holds, 1 when a finding has to be answered, and 2 when
nothing was reviewed -- which is never the same thing as a justification that
was reviewed and found wanting.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import check_integrity as ci  # noqa: E402
import flc_state as st  # noqa: E402
import labels as lb  # noqa: E402
import statement_vote as sv  # noqa: E402
from prompt_taxonomy import (  # noqa: E402
    Refused, Unreachable, answered_by, call_models, cutoff_note,
)

MODEL_ENV = "FLC_JUSTIFICATION_MODEL"
STATE_KEY = "justification_check"

DEFAULT_SAMPLES = 3

# How many readings a finding has to appear in before it can refuse a
# delivery. One reading is a finding worth reading; a finding that would not
# survive being asked again is not one worth stopping a task for. The same
# number, for the same reason, as the rubric review.
REPRODUCTION = 2

MAX_TOKENS = 8000

# A ground truth may embed a figure as a data: URL. Do not add \n to the class:
# the pattern would span the joins and eat the prose on either side.
_B64_BLOB = re.compile(r"[A-Za-z0-9+/=]{2000,}")

HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)

# Past either of these a justification is refused for its length alone.
MAX_WORDS = 600
MAX_PARAGRAPHS = 5

# How long a justification usually needs to be at each level, as (paragraphs,
# words). Past it is reported and never refused.
LENGTH_GUIDE = {
    "l1 - minimal": (1, 120),
    "l2 - low": (1, 250),
    "l3 - moderate": (1, 250),
    "l4 - high": (3, 400),
    "l5 - full": (3, 400),
}

# Phrases that do not determine a ground truth on their own. Reported and never
# more: "it is standard practice, and SOP-DE-004 1.1 requires it" names a
# determiner, and whether the phrase is the whole argument is the model pass's
# reading.
AUTHORITY = re.compile(
    r"\b(?:standard practice|common practice|any (?:expert|practitioner|"
    r"competent \w+) would|every (?:expert|practitioner) would|"
    r"everyone (?:knows|in the field)|as everybody knows|"
    r"in my (?:experience|judgement|judgment|opinion|view)|"
    r"I (?:prefer|would|always|usually)|common sense|goes without saying|"
    r"obviously|self-evident|well[- ]known that)\b", re.I)


@dataclass(frozen=True)
class Category:
    """One defect: what it is, what it is not, and whether it stops a task."""
    key: str
    name: str
    blocking: bool
    definition: str
    boundary: str
    # False for what is read off the file and never asked of the model.
    model: bool = True


# The categories the justification is reviewed against. What is incorrect or
# contradictory blocks; what is loosely worded, generic or a judgement two
# careful readers disagree about reports. Every blocking remedy adds -- name
# the determiner, close the path, add the material, make the gap deliberate.
# The three with `model=False` are read off the file and never asked of the
# model. `SERIOUS` are reported first.
CATEGORIES: dict[str, Category] = {
    "no_determiner": Category(
        key="no_determiner",
        name="Underspecification Justification - No Determiner",
        blocking=True,
        definition=(
            "Nothing is named that forces the answer. What determines a "
            "ground truth is a published standard or protocol, a value or "
            "constraint in the material the task supplies, or a stated fact "
            "that eliminates the alternatives. An appeal to standard "
            "practice, to what any expert would know, or to the author's own "
            "preference is not one of those, however true it may be."
        ),
        boundary=(
            "A determiner does not have to be a document or a number. A "
            "stated fact about the material -- that the construct carries no "
            "origin of replication, that the gel cannot resolve below a "
            "certain size -- determines the answer if it eliminates the "
            "alternatives, and that is not this finding. The phrase "
            "'standard practice' appearing beside a named determiner is also "
            "not this finding: what is being asked is whether anything at all "
            "is pointed at, not whether the prose is free of the phrase."
        ),
    ),
    "path_left_open": Category(
        key="path_left_open",
        name="Underspecification Justification - Path Not Eliminated",
        blocking=True,
        definition=(
            "An alternative route an expert could plausibly take is named and "
            "not closed, or is obvious from the prompt and the material and "
            "is not addressed at all. If another path survives, two experts "
            "reach two answers and the ground truth is not objective."
        ),
        boundary=(
            "Only a path a competent practitioner would actually consider. A "
            "route that is careless, that contradicts material the task "
            "supplies, or that no one reading the prompt would take is not a "
            "surviving path and is not this finding -- do not invent an "
            "alternative in order to report it. Where the justification says "
            "no default is defensible and asking is the expected answer, the "
            "paths are meant to stay open and this finding does not apply: "
            "what it has to show there is that each candidate default fails, "
            "not that one survives."
        ),
    ),
    "contradicts_prompt": Category(
        key="contradicts_prompt",
        name="Underspecification Justification - Contradicts the Prompt",
        blocking=True,
        definition=(
            "The justification asserts something the prompt contradicts, or "
            "relies on the prompt having said something it does not say. The "
            "commonest shape is a justification that quietly treats the "
            "prompt as naming a method, a file or a threshold that it leaves "
            "out."
        ),
        boundary=(
            "The prompt is deliberately vague about the route, and a "
            "justification that supplies what the prompt leaves out is doing "
            "its job rather than contradicting it. This finding needs an "
            "actual conflict: quote the words of each that cannot both be "
            "true."
        ),
    ),
    "contradicts_ground_truth": Category(
        key="contradicts_ground_truth",
        name="Underspecification Justification - Contradicts the Ground Truth",
        blocking=True,
        definition=(
            "The justification and the recorded answer disagree. A determiner "
            "that would produce a different value, a path ruled out that the "
            "ground truth in fact took, a threshold stated one way here and "
            "another way there. Where the two agree, that is not yet the "
            "figure being right: check it against the files or recompute it, "
            "and where both are wrong, the justification is untrue and so is "
            "the recorded answer."
        ),
        boundary=(
            "Different wording for the same fact is not a contradiction, and "
            "neither is the justification being shorter than the ground truth "
            "or covering only part of it. Quote both sides."
        ),
    ),
    "self_contradictory": Category(
        key="self_contradictory",
        name="Underspecification Justification - Internally Inconsistent",
        blocking=True,
        definition=(
            "The justification disagrees with itself: a rule applied one way "
            "in one place and another way in another, a path "
            "described as closed by something the same document says does not "
            "apply, a determiner that would rule out the answer it is offered "
            "for."
        ),
        boundary=(
            "Two determiners that point the same way are not a "
            "contradiction, and neither is a caveat. Quote the two passages."
        ),
    ),
    "untrue": Category(
        key="untrue",
        name="Underspecification Justification - Not True",
        blocking=True,
        definition=(
            "A statement in the justification is wrong on the evidence of the "
            "task's material or of a check anyone can rerun: a file named that "
            "the task does not supply, a value the files or a recomputation "
            "give differently, a threshold or a clause stated another way, or "
            "a reason given for why a route fails or an answer holds that the "
            "data does not bear out, even where the conclusion stands. The "
            "recorded answer saying the same does not make a statement true."
        ),
        boundary=(
            "A claim about what a workspace file says is contradicts_material "
            "and not this. A claim about a document the task does not supply "
            "at all, which you cannot check, is not this finding either -- an "
            "external standard is a legitimate determiner and citing one is "
            "expected. That covers a citation you do not recognise, whatever "
            "its date: a reference published after your training data is one "
            "you have not seen, which is not evidence that it does not exist."
        ),
    ),
    "contradicts_material": Category(
        key="contradicts_material",
        name="Underspecification Justification - Contradicts the Files",
        blocking=False,
        definition=(
            "A statement in the justification that a workspace file shown to "
            "you contradicts: a value, a clause, a date, a sample or a fact "
            "that the file gives differently, or a figure attached to the "
            "wrong file or the wrong item."
        ),
        boundary=(
            "Only where the file's own words are in front of you. Copy the "
            "file's passage exactly into material_quote and name the file in "
            "file. A file cut short or not shown is not evidence either way, "
            "and a claim you cannot find in the passage shown is not this "
            "finding. Different wording for the same fact is not a "
            "contradiction."
        ),
    ),
    "generic": Category(
        key="generic",
        name="Underspecification Justification - Generic",
        blocking=False,
        definition=(
            "Text that could move unchanged onto another task of the same "
            "kind and still read true: it names nothing specific from this "
            "prompt, this material or this answer, and describes the kind of "
            "task rather than this one. Say in 'what' which thing in this "
            "task it never points at."
        ),
        boundary=(
            "One concrete statement of the gap or of what settles it -- a "
            "file, a value, a clause, a named fact that the material bears "
            "out -- and it is not this, however plain the rest of the text "
            "is. Text that is specific but loosely worded is vague. If "
            "nothing at all is pointed at as forcing the answer, that is "
            "no_determiner. The remedy is one added sentence naming what in "
            "this task's material settles it, keeping the rest."
        ),
    ),
    "vague": Category(
        key="vague",
        name="Underspecification Justification - Vague",
        blocking=False,
        definition=(
            "Something specific is named but too loosely to be checked: 'the "
            "protocol' with no protocol identified, 'the data show' with no "
            "file, 'the usual threshold' with no value. The justification "
            "points somewhere rather than at something."
        ),
        boundary=(
            "If nothing is pointed at at all, that is no_determiner, and text "
            "that could fit another task unchanged is generic; neither is "
            "this. If what is pointed at is identified but you would have "
            "liked more detail, that is a preference and not a finding. The "
            "remedy is one added sentence naming what is meant, keeping the "
            "rest; never ask for the text to be expanded throughout."
        ),
    ),
    "reads_generated": Category(
        key="reads_generated",
        name="Underspecification Justification - Reads as Generated",
        blocking=False,
        definition=(
            "The text reads like a filled-in form rather than a researcher "
            "explaining their answer: stock phrasing that would fit any task, "
            "commentary on the task's own design, difficulty or level instead "
            "of on the material, or a catalogue of every file and path when "
            "one or two settle the answer."
        ),
        boundary=(
            "Plain or terse writing is not this, and neither is technical "
            "vocabulary. Naming the one or two paths a careful expert would "
            "consider is what is asked for; only an exhaustive list of "
            "everything in the folder is this finding."
        ),
    ),
    "underspecification_not_real": Category(
        key="underspecification_not_real",
        name="Underspecification Justification - Gap Is Not Real",
        blocking=False,
        definition=(
            "The researcher marks the task underspecified -- the model is "
            "meant to ask -- but the material the task supplies, or a "
            "convention every expert in the field applies, settles the gap. "
            "A model that works it out is then right, and one that asks is "
            "only being cautious."
        ),
        boundary=(
            "Only where the task is marked underspecified. Quote the words "
            "that describe the gap, and say what settles it. A fact only the "
            "requester holds -- their intent, which of two conflicting "
            "sources governs for them -- is a real gap, and a gap whose "
            "branches lead to incompatible work rather than different values "
            "is too."
        ),
    ),
    "markdown": Category(
        key="markdown",
        name="Underspecification Justification - Markdown",
        blocking=True,
        definition="The justification uses markdown rather than plain prose.",
        boundary="",
        model=False,
    ),
    "too_long": Category(
        key="too_long",
        name="Underspecification Justification - Too Long",
        blocking=True,
        definition=(f"The justification runs past {MAX_WORDS} words or "
                    f"{MAX_PARAGRAPHS} paragraphs."),
        boundary="",
        model=False,
    ),
    "longer_than_needed": Category(
        key="longer_than_needed",
        name="Underspecification Justification - Longer Than the Level Needs",
        blocking=False,
        definition=("The justification is longer than its underspecification "
                    "level usually needs."),
        boundary="",
        model=False,
    ),
}

BLOCKING = tuple(k for k, cat in CATEGORIES.items() if cat.blocking)
SERIOUS = ("contradicts_material", "generic")
# Findings that say something in the justification is inaccurate. One of these
# stops a task only once the statement it rests on is confirmed by the vote.
INACCURACY = ("untrue", "contradicts_material", "contradicts_ground_truth",
              "contradicts_prompt", "self_contradictory")


# --- reading the file ---------------------------------------------------------


def strip_comments(text: str) -> str:
    return COMMENT_RE.sub("", text)


def length(text: str) -> tuple[int, int]:
    """(paragraphs, words) of the prose, comments excluded."""
    body = lb.prose(text)
    if not body:
        return 0, 0
    return len(body.split("\n\n")), len(body.split())


def written(text: str) -> bool:
    """Whether anything survives the template's own instructions.

    The template is one comment, and an older one was comments and two empty
    headings, so stripping comments and headings leaves nothing of either. This
    is what separates "not started" from "started and thin", and the two get
    different answers.
    """
    body = strip_comments(text)
    prose = [ln for ln in body.splitlines()
             if ln.strip() and not HEADING_RE.match(ln)]
    return bool(prose)


@dataclass
class Finding:
    """One defect, and what it was established from."""
    category: str
    what: str = ""
    quote: str = ""
    remedy: str = ""
    samples: int = 1
    # Established from the file itself rather than from a reading of it.
    structural: bool = False
    # For contradicts_material: the file's passage, and the file.
    material_quote: str = ""
    file: str = ""
    # The statement it rests on, and whether the vote confirmed it.
    statement: str = ""
    confirmed: bool | None = None

    @property
    def cat(self) -> Category:
        return CATEGORIES[self.category]

    @property
    def serious(self) -> bool:
        return self.category in SERIOUS or bool(
            self.statement and self.confirmed and not self.cat.blocking)

    @property
    def blocking(self) -> bool:
        if not self.cat.blocking:
            return False
        # A structural finding is not a reading, and asking again returns the
        # same fact: the file is untouched, or a heading has nothing under it.
        # Holding it to the reproduction threshold would mean inventing a
        # sample count for something nothing sampled, and the report would
        # then tell a contributor it was "seen in 2 of the readings" when no
        # reading was taken.
        if self.structural:
            return True
        if self.statement:
            return bool(self.confirmed)
        if self.category in INACCURACY:
            return False
        return self.samples >= REPRODUCTION

    def as_dict(self) -> dict:
        out = {"category": self.category, "name": self.cat.name,
               "blocking": self.blocking, "serious": self.serious,
               "what": self.what, "quote": self.quote, "remedy": self.remedy,
               "samples": self.samples, "structural": self.structural}
        if self.material_quote:
            out["material_quote"] = self.material_quote
            out["file"] = self.file
        if self.statement:
            out["statement"] = self.statement
            out["confirmed"] = self.confirmed
        return out


def structure(text: str | None, level: str | None = None) -> list[Finding]:
    """What can be answered without a model, and answered for free.

    Returned as findings in the same shape as the model's, so one report can
    carry both and the caller never has to know which pass produced a line.
    `level` is the task's underspecification level, where labels.md gives one.
    """
    if text is None:
        return [Finding("no_determiner",
                        what=(f"There is no {st.JUSTIFICATION}. Every task "
                              "needs it, underspecified or not: it says why "
                              "this answer is the only one an expert could "
                              "reach, and nothing has been written down yet."),
                        remedy=("Write it. Step 3 of the guides has what goes "
                                "in it, and the file itself carries the "
                                "instructions."),
                        structural=True)]
    if not written(text):
        return [Finding("no_determiner",
                        what=(f"{st.JUSTIFICATION} is still the "
                              "template: nothing has been written in it yet. "
                              "Every task needs it, underspecified or not: it "
                              "says why this answer is the only one an expert "
                              "could reach."),
                        remedy=("Replace the instructions in the file with "
                                "your justification, in plain prose, then run "
                                "this again."),
                        structural=True)]

    out: list[Finding] = []
    kinds = lb.markdown(text)
    if kinds:
        out.append(Finding(
            "markdown",
            what=("It uses " + lb.listing(kinds) + ". The justification is read "
                  "as plain prose, and markup makes it read as a form rather "
                  "than as your explanation."),
            remedy=("Rewrite it as plain paragraphs, with no headings, lists, "
                    "bold or backticks. Write file names as they are."),
            structural=True))
    paragraphs, words = length(text)
    if words > MAX_WORDS or paragraphs > MAX_PARAGRAPHS:
        out.append(Finding(
            "too_long",
            what=(f"It is {words} words in {paragraphs} paragraph"
                  f"{'' if paragraphs == 1 else 's'}; the most is {MAX_WORDS} "
                  f"words or {MAX_PARAGRAPHS} paragraphs."),
            remedy=("Keep what determines the answer and the one or two other "
                    "paths a careful expert would consider, and cut the rest. "
                    "Most justifications are one paragraph."),
            structural=True))
    elif level in LENGTH_GUIDE:
        most_paragraphs, most_words = LENGTH_GUIDE[level]
        if paragraphs > most_paragraphs or words > most_words:
            usual = ("one short paragraph" if most_words < 200 else
                     "one paragraph" if most_paragraphs == 1 else
                     f"up to {most_paragraphs} short paragraphs")
            out.append(Finding(
                "longer_than_needed",
                what=(f"It is {words} words in {paragraphs} paragraph"
                      f"{'' if paragraphs == 1 else 's'}, and a task at "
                      f'"{level}" usually needs {usual}.'),
                remedy=("Keep what determines the answer and what rules out "
                        "the paths a careful expert would consider, and cut "
                        "the rest."),
                structural=True))
    return out


def authority_phrases(text: str) -> list[str]:
    """The phrases that do not determine a ground truth on their own."""
    seen: list[str] = []
    for match in AUTHORITY.finditer(strip_comments(text or "")):
        phrase = match.group(0).strip()
        if phrase.lower() not in {s.lower() for s in seen}:
            seen.append(phrase)
    return seen


# --- the model pass -----------------------------------------------------------


METHOD_FILE = Path(__file__).resolve().parent / "review_spec" / "justification_method.md"


def _method() -> str:
    """The method for this review, as exported into review_spec/."""
    try:
        return METHOD_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def system_prompt() -> str:
    parts = [cutoff_note(), """
You review one short document: a researcher's written justification for why
their own recorded answer to a research task is the only answer an expert
could reach.

You are shown the justification, the prompt the task asks, the researcher's
recorded answer, the names of the files the task supplies, and what those
files say, cut short where they are long. Where you can run Python, the files
are there whole, and you can read and recompute from them. A file you cannot
see is not evidence either way. Never report something as wrong merely because
you cannot confirm it. The recorded answer is one of the documents you check,
not proof: a statement is not accurate because the recorded answer says the
same.

You are not judging whether the answer is correct, whether the task is
interesting, or whether the writing is good. You are judging whether the
justification holds together: whether it names something that actually forces
the answer, whether it closes the other routes, and whether it contradicts
itself, the prompt or the recorded answer.

Two things to hold on to, because they are where this review goes wrong.

The prompt is *meant* to leave things out. That is the design of these tasks,
and a justification supplying what the prompt omits is doing its job. A gap
between them is only a finding when the two make claims that cannot both be
true.

Some tasks are built so that no default is defensible and the expected answer
is for the model to ask. The researcher's labels say whether this is one: it
is marked underspecified, at level l5 - full. There, the alternatives are
supposed to stay open, and the justification's job is to show that every
candidate default fails. Do not report a surviving path against a
justification that is doing that. At any other level the task is meant to
have one answer, and a surviving path is a finding.

Report only defects that fall into one of the categories below. For each one,
quote the words out of the justification that carry the defect. A finding with
nothing quoted from the justification is not a finding; leave it out.
"""]
    method = _method()
    if method:
        parts.append("""
THE METHOD A DELIVERED JUSTIFICATION IS REVIEWED WITH

Apply it as far as you can. Where you can run Python, take a route on the
files as the method says. Without it, a claim that could only be settled by
trying a route on the files is not decided here: it is not a finding either
way. Reconciling every figure against the recorded answer and the files is
always possible, and is the first thing to do. Report in the shape asked for
below, not in the one the method names: a claim the method would record as
false is a finding here, resting on a statement.

""" + method)
    contract = sv.contract_text()
    if contract:
        parts.append("""

""" + contract + "\n\n" + sv.checks_text() + """

A finding that the justification is untrue, or that it contradicts the files,
the prompt, the recorded answer or itself, is an inaccuracy, so it names the
statement it rests on in `statement`. List in `statements` every inaccuracy
you find, and at least one statement you checked closely and found accurate.
Check the recorded answer's own statements that the justification repeats or
rests on as well: an inaccuracy there goes in `statements`, in the ground
truth, with `bears_on` naming the justification. Each statement is checked
again, independently, before anything rests on it.
""")
    parts.append("""
THE CATEGORIES
""")
    for cat in CATEGORIES.values():
        if cat.model:
            parts.append(f"\n- {cat.key}: {cat.definition}\n  Not this: {cat.boundary}")
    parts.append("""

Reply with a single JSON object and nothing else, in this shape:

{
  "reading": "two or three sentences on what the justification claims forces \
the answer, and what it rules out",
  "findings": [
    {
      "category": "one of the keys above",
      "what": "one sentence saying what the defect is",
      "quote": "the words out of the justification that carry it",
      "remedy": "what the author would add or change, in one sentence",
      "material_quote": "contradicts_material only: the file's passage, \
copied exactly",
      "file": "contradicts_material only: the file it is in",
      "statement": "for an inaccuracy: the id, in statements, of the statement \
it rests on"
    }
  ],
  "statements": [
    {"id": "s1", "file": "justification | ground truth | prompt | a workspace \
path", "quote": "the words, copied exactly from where they are", "reading": \
"inaccurate", "kind": "KINDS", "what_is_wrong": "what is wrong with it, in a \
sentence", "check": "the check that settles it, with its numbers and the files \
it reads", "confidence": "high", "bears_on": ["justification"]},
    {"id": "s2", "file": "...", "quote": "...", "reading": "accurate"}
  ]
}

An empty findings list is the right answer for a justification that holds.
Do not manufacture a finding to appear thorough, and do not report the same
defect twice under two categories -- pick the one that fits best.
""".replace('"KINDS"', '"' + " | ".join(sv.KINDS) + '"'))
    return "".join(parts)


def sender(model, key: str, base: str, shape: str, answered: list | None = None,
           tools=None):
    """A `send(request)` over HTTP, carrying this module's own question.

    `model` is one name, or a sequence to fall back through when one declines.
    With `tools`, each reading can run Python on the task's files.
    """
    system = system_prompt()

    def send(request: str) -> str:
        if tools is not None:
            return tools.reading(request, model, system=system, answered=answered,
                                 max_tokens=MAX_TOKENS)
        return call_models(request, model, key, base, shape, answered=answered,
                           system=system, max_tokens=MAX_TOKENS)

    return send


def cast_vote(tools, statements: list, prefix: str, seed_basis: str) -> dict:
    """Put the flagged statements to the blind vote."""
    return tools.vote(statements, prefix, seed_basis)


def build_request(justification: str, prompt: str, ground_truth: str,
                  workspace: list[str], labels: dict | None = None,
                  material: str = "") -> str:
    def clean(text: str) -> str:
        return _B64_BLOB.sub("[encoded image omitted]", text or "").strip()

    labels = labels or {}
    parts = ["## The researcher's labels", "",
             "- underspecified: "
             + (labels.get("underspecified_task") or "(not answered)"),
             "- level: "
             + (labels.get("underspecification_level") or "(not answered)")]
    parts += ["", "## The justification", "", clean(justification) or "(empty)"]
    parts += ["", "## The prompt the task asks", "", clean(prompt) or "(empty)"]
    parts += ["", "## The researcher's recorded answer", "",
              clean(ground_truth) or "(none was written)"]
    parts += ["", "## The material the task supplies", ""]
    parts += [f"- {name}" for name in workspace] or ["(none)"]
    parts += ["", "## What the files say, cut short where they are long", "",
              clean(material) or "(no file could be read as text)"]
    return "\n".join(parts)


def parse_reply(text: str) -> dict:
    """The reply as an object, however the model wrapped it."""
    body = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise Unreachable("the reply carried no JSON object")
    try:
        parsed = json.loads(body[start:end + 1])
    except json.JSONDecodeError as exc:
        raise Unreachable(f"the reply was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise Unreachable("the reply was not an object")
    return parsed


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def read_findings(parsed: dict, justification: str,
                  material: str = "", statements: dict | None = None) -> list[Finding]:
    """The findings from one reading, with the unusable ones dropped.

    A finding has to name a category this module knows and quote the
    justification it is about, and the quote has to be in it. A contradiction
    with the files has to quote the file as well, and that passage has to be
    in what the files say. `statements` maps the reading's statement ids to
    the statements it settled; a finding naming one carries it.
    """
    out: list[Finding] = []
    body = _norm(justification)
    shown = _norm(material)
    for raw in parsed.get("findings") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("category", "")).strip()
        if key not in CATEGORIES or not CATEGORIES[key].model:
            continue
        quote = str(raw.get("quote", "")).strip().strip('"“”')
        what = str(raw.get("what", "")).strip()
        if not what:
            continue
        # The structural findings above are the only ones allowed to carry no
        # quote, because they are about an absence.
        if not quote or _norm(quote) not in body:
            continue
        passage = str(raw.get("material_quote", "") or "").strip().strip('"“”')
        if key == "contradicts_material" and (not passage or _norm(passage) not in shown):
            continue
        held = (statements or {}).get(str(raw.get("statement") or "").strip())
        out.append(Finding(key, what=what, quote=quote,
                           remedy=str(raw.get("remedy", "")).strip(),
                           material_quote=passage if key == "contradicts_material" else "",
                           file=(str(raw.get("file", "") or "").strip()
                                 if key == "contradicts_material" else ""),
                           statement=held.ident if held is not None and held.flagged else ""))
    return out


def reproduce(batches: list[list[Finding]]) -> list[Finding]:
    """One list, with a finding's sample count set to how often it was seen.

    Matched on category and quote rather than on wording: the same defect
    described twice in two sentences is one defect, and the quote is the part
    that does not drift between readings.
    """
    merged: dict[tuple[str, str], Finding] = {}
    for batch in batches:
        seen_here: set[tuple[str, str]] = set()
        for finding in batch:
            ident = (finding.category, _norm(finding.quote))
            if ident in seen_here:
                continue  # one reading counts once
            seen_here.add(ident)
            if ident in merged:
                merged[ident].samples += 1
                merged[ident].statement = merged[ident].statement or finding.statement
            else:
                merged[ident] = finding
    return sorted(merged.values(),
                  key=lambda f: (not f.serious, not f.blocking, -f.samples, f.category))


# --- the verdict --------------------------------------------------------------


@dataclass
class Report:
    verdict: str = "UNMEASURED"
    why: str = ""
    reading: str = ""
    findings: list[Finding] = field(default_factory=list)
    samples: int = 0
    model: str = ""
    phrases: list[str] = field(default_factory=list)
    # What labels.md needs before the justification can be read against it.
    labels: list = field(default_factory=list)
    # Set when too few readings answered for any finding to be confirmed.
    short: str = ""
    statements: list = field(default_factory=list)
    vote: dict = field(default_factory=dict)
    sessions: dict = field(default_factory=dict)
    # Findings resting on a statement the vote did not confirm. Recorded, never shown.
    unconfirmed: list = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    @property
    def open(self) -> list[Finding]:
        return [f for f in self.findings if not f.blocking]

    @property
    def serious(self) -> list[Finding]:
        return [f for f in self.findings if f.serious]

    @property
    def clears(self) -> bool:
        return self.verdict in ("PASS", "UNMEASURED")


def score(report: Report) -> Report:
    """FAIL on a blocking finding seen in REPRODUCTION readings, WARN on the rest.

    A blocking category seen once and not again is reported rather than
    enforced.
    """
    if report.blocking:
        report.verdict = "FAIL"
        unwritten = [f for f in report.blocking if f.structural]
        read = [f for f in report.blocking if not f.structural]
        said = []
        if unwritten:
            count = len(unwritten)
            said.append(f"{count} thing{'' if count == 1 else 's'} still to "
                        "be written before there is a justification to review")
        if read:
            count = len(read)
            said.append(f"{count} finding{'' if count == 1 else 's'} that "
                        "would stop it being read as an objective ground "
                        "truth, "
                        + ("found" if count == 1 else "each found")
                        + " again on another, independent reading")
        report.why = "This has " + ", and ".join(said) + "."
    elif report.findings:
        report.verdict = "WARN"
        count = len(report.findings)
        report.why = (
            f"{count} thing{'' if count == 1 else 's'} to fix before you go "
            "on. This check does not stop the task, but each is a common "
            "issue in this project and a reason a task fails, so fix "
            f"{'it' if count == 1 else 'each one'} unless the finding is "
            "wrong.")
    else:
        report.verdict = "PASS"
        report.why = ("The justification names what forces the answer and what "
                      "rules out the other paths, and nothing in it contradicts "
                      "the prompt, the recorded answer or the files.")
    return report


def justification_text(root: Path) -> str | None:
    try:
        return st.justification_file(root).read_text(encoding="utf-8")
    except OSError:
        return None


def ground_truth(root: Path) -> str:
    try:
        return (root / st.GROUND_TRUTH).read_text(encoding="utf-8")
    except OSError:
        return ""


def digest(root: Path) -> str:
    """The justification this verdict was taken against."""
    return st.justification_digest(root)


def review(root: Path, samples: int, model: str | None = None) -> Report:
    text = justification_text(root)
    label_findings = lb.check(root, "pre")
    values = lb.read(root).values
    structural = structure(text, values.get("underspecification_level"))
    report = Report(findings=structural, labels=label_findings)
    if lb.blocking(label_findings):
        # The justification is read against the labels, so they come first.
        report.verdict = "FAIL"
        report.why = (f"{lb.LABELS} has to be fixed before the justification "
                      "can be read against it.")
        return report
    if any(f.blocking for f in structural):
        # Nothing was written, or the form has to change first. There is no
        # reading to take, and spending a gateway call to be told so would be
        # slower and no more true.
        return score(report)

    report.phrases = authority_phrases(text or "")
    creds = st.gateway()
    if not creds:
        report.why = "no gateway credentials were found on this machine"
        return report
    key, base = creds
    models = st.check_models(model, MODEL_ENV)
    answered: list[str] = []
    shape = st.gateway_shape()
    import rubric_check  # noqa: PLC0415 -- the same bounded file text the rubric review reads
    import tool_session  # noqa: PLC0415
    state = st.load(root)
    tools = tool_session.Tools(root, rubric_check._job(state), key, base, shape)
    send = sender(models, key, base, shape, answered, tools=tools)
    material = rubric_check.workspace_text(root)
    prompt, truth = st.contributor_prompt(root), ground_truth(root)
    files = st.workspace_files(root)
    request = build_request(text or "", prompt, truth, files, values, material)
    texts = {sv.GROUND_TRUTH: truth, sv.JUSTIFICATION: text or "", sv.PROMPT: prompt,
             sv.ANSWER: "", "workspace": material}
    held: list[list] = []

    batches: list[list[Finding]] = []
    readings: list[str] = []
    last = ""
    # A reading lost to a refusal or an unreadable reply is asked for again, up
    # to REPRODUCTION more times, so a filter that fires inconsistently does
    # not leave too few readings to confirm on. A gateway that does not answer
    # gets no extra attempts.
    tried = 0
    while len(batches) < samples and tried < samples + min(samples, REPRODUCTION):
        tried += 1
        try:
            reply = send(request)
        except Refused as exc:
            last = str(exc)
            continue
        except Unreachable as exc:
            last = str(exc)
            if tried >= samples:
                break
            continue
        try:
            parsed = parse_reply(reply)
        except Unreachable as exc:
            last = str(exc)
            continue
        found, _dropped = sv.read_statements(parsed, "justification check", texts, [],
                                             [], files, rubric_check.read_file(root))
        held.append(found)
        by_id = {rid: next(s for s in found if s.ident == ident)
                 for rid, ident in sv.ids(parsed, found).items()}
        batches.append(read_findings(parsed, text or "", material, by_id))
        reading = str(parsed.get("reading", "")).strip()
        if reading:
            readings.append(reading)
    report.model = answered_by(answered) or models[0]
    if not batches:
        report.why = last or "the model did not answer"
        return report

    report.samples = len(batches)
    report.reading = readings[0] if readings else ""
    read = reproduce(batches)
    if values.get("underspecified_task") != "yes":
        read = [f for f in read if f.category != "underspecification_not_real"]
    report.statements = sv.merge(*held)
    if any(s.flagged for s in report.statements):
        try:
            report.vote = cast_vote(tools, report.statements, request,
                                    str(state.get("task_id") or "")) or {}
        except Exception as exc:  # noqa: BLE001 -- a vote that could not be taken confirms nothing
            report.vote = {"asked": False, "why": f"{type(exc).__name__}: {exc}"}
    confirmed = {s.ident for s in report.statements if s.confirmed}
    for f in read:
        if f.statement:
            f.confirmed = f.statement in confirmed
    report.unconfirmed = [f for f in read if f.statement and not f.confirmed]
    read = [f for f in read if not (f.statement and not f.confirmed)]
    report.findings = structural + read
    report.sessions = tools.summary()
    if tools.faults:
        st.record_issue(root, "check_partial", "justification check read without "
                        "tools: " + "; ".join(tools.faults), "justification_check.py")
    score(report)
    if report.samples < min(samples, REPRODUCTION) and report.verdict != "FAIL":
        report.short = (f"only {report.samples} of {samples} readings answered, so "
                        "no finding could be confirmed on a second reading")
        report.why = f"{report.why} ({report.short})"
    return report


def record(root: Path, report: Report) -> dict:
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": report.verdict,
        "why": report.why,
        "reading": report.reading,
        "samples": report.samples,
        "model": report.model,
        "authority_phrases": report.phrases,
        "blocking": [f.as_dict() for f in report.blocking],
        "open": [f.as_dict() for f in report.open],
        "findings": [f.as_dict() for f in report.findings],
        "justification_sha256": digest(root),
        "labels_sha256": lb.pre_digest(root),
        "workspace_sha256": files_digest(root),
        "statements": [s.as_dict() for s in report.statements],
        "vote": report.vote,
        "consistency": sv.consistency(report.statements),
        "unconfirmed": [f.as_dict() for f in report.unconfirmed],
        "sessions": report.sessions,
    }
    if report.short:
        entry["short"] = report.short
    state = st.load(root)
    state[STATE_KEY] = entry
    st.save(root, state)
    if report.verdict == "UNMEASURED" and not report.findings:
        st.record_issue(root, "check_unmeasured", f"justification check: {report.why}",
                        "justification_check.py")
    elif report.short:
        st.record_issue(root, "check_partial", f"justification check: {report.short}",
                        "justification_check.py")
    return entry


def recorded(state: dict, root: Path) -> tuple[dict | None, bool]:
    """The recorded verdict, and whether it was taken against this file, these
    labels and these workspace files."""
    entry = state.get(STATE_KEY)
    if not isinstance(entry, dict) or not entry.get("verdict"):
        return None, False
    # An absent file digests to "", which would match a record carrying "" and
    # read as current. There is no review of a justification that is not there.
    now = digest(root)
    return entry, (bool(now) and entry.get("justification_sha256") == now
                   and not labels_moved(entry, root) and not files_moved(entry, root))


def labels_moved(entry: dict, root: Path) -> bool:
    """Whether the first three labels differ from the ones the verdict read."""
    return entry.get("labels_sha256") != lb.pre_digest(root)


def files_digest(root: Path) -> str:
    """The workspace files as they stand, through a freshly written manifest."""
    st.write_inputs_manifest(root)
    return st.sha256_file(root / st.GRADE_INPUTS["workspace"])


def files_moved(entry: dict, root: Path) -> bool:
    """Whether the workspace files differ from the ones the verdict read."""
    return entry.get("workspace_sha256") != files_digest(root)


# --- what the contributor sees ------------------------------------------------


def _wrap(text: str, indent: str = "  ") -> str:
    return textwrap.fill(" ".join((text or "").split()), width=84,
                         initial_indent=indent, subsequent_indent=indent)


def _one(finding: Finding, number: int) -> None:
    mark = ("must be fixed" if finding.blocking
            else "fix this unless the finding is wrong")
    print(f"  {number}. {finding.cat.name} -- {mark}")
    if finding.quote:
        print(_wrap(f'you wrote: "{finding.quote}"' if finding.material_quote
                    else f'"{finding.quote}"', "     "))
    if finding.material_quote:
        where = f" ({finding.file})" if finding.file else ""
        print(_wrap(f'the file says{where}: "{finding.material_quote}"', "     "))
    print(_wrap(finding.what, "     "))
    if finding.remedy:
        print(_wrap(f"to fix: {finding.remedy}", "     "))
    # No guard on `structural` here, and one was written before it came out.
    # A structural finding is never reproduced -- `reproduce()` only ever sees
    # the model's batches -- so its count is always 1 and this line cannot
    # reach it. What stops the false "seen in 2 of the readings" is that the
    # finding no longer carries a count it did not earn, which is the fix
    # rather than hiding the symptom here.
    if finding.samples > 1:
        print(f"     seen in {finding.samples} of the readings")
    print()


def _open(findings: list[Finding], start: int = 1) -> None:
    if not findings:
        return
    print("  Fix this before you go on:")
    print()
    for number, finding in enumerate(findings, start):
        _one(finding, number)
    print(_wrap("These do not stop the task. Each is a common issue in this "
                "project and a reason a task fails, so fix it unless the "
                "finding is wrong -- and if it is wrong, say why."))
    print()


def report(result: Report) -> None:
    if result.labels:
        lb.report(result.labels, "pre")
        if lb.blocking(result.labels):
            print(_wrap(f"Fix {lb.LABELS} first: the justification is read "
                        "against the answers in it. Nothing else was checked, "
                        "and nothing was recorded."))
            print()
            return
    print()
    print("Is this ground truth objective, on the strength of what you wrote?")
    print()
    if result.verdict == "UNMEASURED":
        print("  NOT MEASURED")
        print()
        print(_wrap(f"Nothing was reviewed: {result.why}"))
        print()
        print(_wrap("This is our check failing, not your justification. It "
                    "does not stop you: delivery lets a task through when "
                    "this could not measure it, and says so."))
        print()
        _open(result.open)
        return

    print(f"  {result.verdict}  {len(result.findings)} finding"
          f"{'' if len(result.findings) == 1 else 's'}"
          + (f", {result.samples} reading"
             f"{'' if result.samples == 1 else 's'}" if result.samples else ""))
    print()
    print(_wrap(result.why))
    print()
    if result.reading:
        print(_wrap("Read as: " + result.reading))
        print()
    import rubric_check  # noqa: PLC0415 -- one way of telling a contributor about their answer
    rubric_check.show_answer(sv.consistency(result.statements))

    serious = result.serious
    if serious:
        print("  Check these against your files first:")
        print()
    for number, finding in enumerate(serious, 1):
        _one(finding, number)
    if result.blocking:
        print("  Must be fixed:")
        print()
    for number, finding in enumerate(result.blocking, len(serious) + 1):
        _one(finding, number)
    _open([f for f in result.open if not f.serious],
          len(serious) + len(result.blocking) + 1)

    if result.phrases:
        named = ", ".join(f'"{p}"' for p in result.phrases[:4])
        print(_wrap(f"You use {named}. None of those determines a ground "
                    "truth on its own -- if the sentence also names the "
                    "standard, the file or the fact, it is fine, and if it "
                    "does not, that is the sentence to rewrite."))
        print()

    if result.verdict == "FAIL":
        print(_wrap("Nothing here asks you to weaken your answer. Every "
                    "remedy adds something: name the determiner, close the "
                    "path, add the material that closes it, or make the gap "
                    "deliberate so that stating the assumption or asking is "
                    "the expected answer."))
        print()
        print(_wrap("A path that cannot be closed means the task has more "
                    "than one answer, and that is cheaper to find now than "
                    f"after a run. Fix it in {st.JUSTIFICATION}, or in the "
                    "task, then run this again."))
    else:
        print(_wrap("Run this again if you change your prompt, your answer "
                    "or your material, since all three are what it was read "
                    "against."))
    if result.model:
        print()
        print(_wrap(f"read by {result.model}"))
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    ap.add_argument("--model", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    if args.samples < 1:
        print("--samples must be at least 1", file=sys.stderr)
        return 2

    ci.announce(root, "justification_check")

    result = review(root, args.samples, args.model)
    if lb.blocking(result.labels):
        if args.json:
            print(json.dumps({"labels": [f.as_dict() for f in result.labels]},
                             indent=2))
        else:
            report(result)
        return 1
    entry = record(root, result)

    if args.json:
        print(json.dumps(entry, indent=2))
    else:
        report(result)

    if result.verdict == "UNMEASURED":
        return 2
    if sv.consistency(result.statements)["verdict"] == "FAIL":
        return 1
    return 0 if result.clears else 1


if __name__ == "__main__":
    sys.exit(main())
