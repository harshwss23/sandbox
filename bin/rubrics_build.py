#!/usr/bin/env python3
"""Turn tests/rubrics.md into tests/rubrics.json, and check it while doing it.

The markdown is what a contributor writes; the JSON is what ships and what the
judge reads. Each delivered criterion carries three keys and no more --
`criteria`, `weight`, `type` -- so there is nothing in the file that can go
stale against the criterion text. The judge derives the rest from those.

Usage:
    rubrics_build.py             build and report
    rubrics_build.py --check     report only, write nothing
    rubrics_build.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_integrity as ci  # noqa: E402
import flc_state as st  # noqa: E402
import labels as lb  # noqa: E402

try:
    import rubric_quality as rq  # noqa: E402
except Exception:  # noqa: BLE001 -- every other finding here still runs
    rq = None

# The heading a contributor typed, lowercased, to the category it names. The
# several spellings of the middle one are all in use.
CATEGORIES = {
    "completion": "completion",
    "clarification": "clarification",
    "clarifications": "clarification",
    "non-hallucination": "non_hallucination",
    "non hallucination": "non_hallucination",
    "nonhallucination": "non_hallucination",
    "hallucination": "non_hallucination",
}

SECTIONS = "'Completion', 'Clarification' or 'Non-hallucination'"

# Every criterion ships with two labels, and neither is written out by hand.
#
# What it measures comes from the section it sits under, which the contributor
# already has to choose. Where it is checked defaults to the answer text; a
# criterion about what the model did to the workspace is marked with a tag on
# the line.
LABEL_COMPLETION = "task completion"
LABEL_CLARIFICATION = "clarification"
LABEL_HALLUCINATION = "hallucination"
LABEL_USER_FACING = "user facing"
LABEL_STATE_CHANGE = "state change"

# A file the prompt pinned the shape of, and a value exact enough to compare.
FILE_PATH = re.compile(
    r"\b[\w./-]+\.(?:json|jsonl|csv|tsv|txt|ya?ml|parquet|xlsx?)\b", re.I)
# Not preceded or followed by a word character, so the 2 in `run2.csv` and the
# 19 in `S19` are not values.
# Digits hyphenated onto a letter are part of an identifier, as in SOP-DE-004.
EXACT_VALUE = re.compile(
    r"(?<![\w.])(?<![A-Za-z]-)-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])")

CATEGORY_LABEL = {"completion": LABEL_COMPLETION,
                  "clarification": LABEL_CLARIFICATION,
                  "non_hallucination": LABEL_HALLUCINATION}

STATE_TAGS = {"state", "state-change", "statechange", "environment", "env"}
USER_TAGS = {"user-facing", "userfacing", "user", "answer"}

TAG_RE = re.compile(r"^\s*(?:\[(?P<tag>[+-]?[a-zA-Z0-9-]+)\]\s*)+")
ONE_TAG_RE = re.compile(r"\[(?P<tag>[+-]?[a-zA-Z0-9-]+)\]")

# The weight is the whole annotation: how much the line is worth, and -- by its
# sign -- whether the answer earns that by satisfying the line or by avoiding it.
WEIGHTS = (5, 3, 1, -1, -3, -5)
WEIGHT_RE = re.compile(r"^[+-]?\d+$")

# A word tag is read as its nearest weight.
LEGACY_TAGS = {"must": 5, "should": 1, "negative": None}
BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<body>.+?)\s*$")
HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*$")

# Phrases that make a criterion unjudgeable on its own. The judge sees one
# criterion at a time with no memory of the others, so a back-reference is
# guaranteed to be scored on a guess.
DANGLING = re.compile(
    r"\b(as (?:described |stated |mentioned )?above|as below|the correct (?:value|answer|gene|number)"
    r"|the expected (?:value|answer|result)|see above|previously mentioned|the aforementioned"
    r"|this value|that value|the same as)\b",
    re.IGNORECASE,
)
# --- atomicity -----------------------------------------------------------
# One criterion, one fact: a line checking two things scores zero when the
# answer got one of them right, which throws away the distinction the
# contributor was trying to draw.
#
# "and" on its own is a bad signal for this -- most of its uses inside a single
# fact are perfectly ordinary -- so the trigger is a second *predicate* or a
# second *value assignment*, and the ordinary uses are excluded outright.

# "between 0.4 and 0.6", "from 10 to 20". One value, expressed as a range.
RANGE = re.compile(r"\b(?:between|from|within|range of)\b[^,;]{0,50}?\b(?:and|to)\b", re.I)
# "the March file and not the January one". One fact, stated by contrast.
CONTRAST = re.compile(
    r"\band\s+(?:not\b|never\b|no\b|neither\b|without\b|(?:does|do|did|is|are|was|were)\s+not\b)",
    re.I)
# A second claim: "and reports", "and explains", "and also states".
#
# The gerunds of the verbs whose stem keeps its e -- stating, naming, noting --
# are spelled out, because the suffix group cannot build them from the stem and
# they are the forms the joining phrases below take.
CLAIM_VERB = (r"(?:report|state|identif|explain|includ|mention|give|note|describ|list|"
              r"provid|show|comput|calculat|cite|name|attribut|conclud|deriv|quot)"
              r"(?:s|es|ed|ing|ies)?"
              r"|(?:stating|naming|noting|giving|citing|listing)")
# What joins the two claims. A comma and "and" were the whole set, which left a
# semicolon and the phrases that mean "and" in more words entirely uncovered.
CLAIM_JOIN = (r"(?:\band\b|,|;|\bas well as\b|\bin addition to\b|"
              r"\balong with\b|\btogether with\b)")
SECOND_CLAIM = re.compile(
    rf"{CLAIM_JOIN}\s+(?:also\s+|then\s+)?(?:{CLAIM_VERB})\b", re.I)

# An item together with the property that identifies it -- "the Sh ble
# cassette conferring zeocin resistance" -- is one fact, and there is
# deliberately no guard here for it. None is needed: a restrictive modifier
# carries no second claim verb and no second value, so nothing above catches
# it, and an exclusion for a shape that is never caught is dead code that
# reads like protection.
#
# A guard was written and removed for that reason. What holds the shape
# instead is a check in the selftest, whose mutation is the edit somebody
# actually makes while sharpening this: putting "conferring" among the claim
# verbs. That splits one fact into two lines a response could satisfy without
# connecting them, and it is what a delivered criterion was flagged for.

# A value pinned to something: "as 3.87", "of 0.05", "is 1.2e-5". Two of them in
# one line is two facts. "which is 12" is excluded -- an aside about a value
# already given is not a second claim about it.
VALUE_FRAME = re.compile(
    r"(?<!which )(?<!that )\b(?:as|of|is|are|equals?|=|to be)\s+"
    r"(?:approximately\s+|about\s+|roughly\s+|~)?[-+]?\d", re.I)

# --- self-containment: no ordinals, no implicit sequence ----------------
# The judge sees one criterion with no memory of the others, so "the second
# recombination" asks it to know a build order the line never states. Naming
# the thing costs a few words and is gradeable on any run.
#
# An ordinal is perfectly self-contained when it indexes a position in
# something the line names -- "lists Pten in its first row" -- so the noun
# after it decides this, not the ordinal. Getting that backwards would flag
# criteria that are already right, which is the failure mode this whole family
# of lints has to avoid.
POSITIONAL = (r"row|rows|column|columns|line|lines|cell|cells|page|pages|"
              r"field|fields|entry|entries|item|items|element|elements|"
              r"paragraph|paragraphs|sentence|sentences|position|positions|"
              r"section|sections|table|tables|figure|figures|panel|panels|"
              r"lane|lanes|place|instance|instances|occurrence|occurrences")
ORDINAL = re.compile(
    rf"\b(?:the|its|a)\s+"
    rf"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    rf"1st|2nd|3rd|[4-9]th)\s+"
    rf"(?!(?:{POSITIONAL})\b)[a-z]", re.I)

# "the former", "the latter", "the previous step". These point outside the line
# with no noun to rescue them. "the other" is deliberately absent: a line that
# says "one allele ... and the other allele" establishes both ends itself.
SEQUENCE_REF = re.compile(
    r"\b(?:the\s+former|the\s+latter|the\s+previous|the\s+preceding|"
    r"the\s+subsequent|the\s+earlier\s+one|the\s+later\s+one|"
    r"the\s+one\s+before|the\s+one\s+after)\b", re.I)

# --- one phrasing for every line ----------------------------------------
# A line about what the answer says opens with "Response" and a verb. A line
# about what the agent did opens by naming its trajectory or the agent:
# "Trajectory shows ...", "The agent's trajectory shows ...", "The agent ...",
# "In its trajectory, the agent ...".
SUBJECT = re.compile(
    r"^(?:Response\s+\S"
    r"|(?:the\s+)?(?:agent(?:'|\u2019)s\s+)?trajectory\s+\S"
    r"|(?:the\s+)?agent\s+\S"
    r"|in\s+(?:its|the|the\s+agent(?:'|\u2019)s)\s+trajectory\b)", re.I)
# The subjects written instead, named so the finding can say which of the two
# mistakes this is: a different subject and a missing one need different
# rewrites.
OTHER_SUBJECT = re.compile(
    r"^(?:the\s+)?(?:answer|model|assistant|output|reply|solver|submission|"
    r"solution|it)\b", re.I)

# --- the failure class, not this run's output ----------------------------
# Two shapes of a hallucination criterion written to one run's output.

# A list of three or more items, each carrying a digit: "claims clones 5, 16,
# 27 and 28 were transformed". A list of plain words is not matched.
ENUMERATION = re.compile(
    r"\b[\w.-]*\d[\w.-]*(?:\s*,\s*[\w.-]*\d[\w.-]*){2,}", re.I)

# An enumeration defining an open class by exclusion -- "presents any clone
# other than 8, 18 and 22" -- which cancels the finding.
OPEN_CLASS = re.compile(
    r"\b(any|other than|outside|none of|not among|except|apart from|"
    r"rather than|instead of|beyond)\b", re.I)

# A quoted sentence, long enough that a quoted filename, column name or short
# identifier is not one.
QUOTED_SPAN = re.compile(r"[\"\u201c][^\"\u201d]{25,}[\"\u201d]")

# --- browsing is the route, not the check --------------------------------
# A positive line resting on what a web page said. The judge is shown the
# answer, the produced files and the transcript, never a web page. Negative
# lines are not checked: an invented source is a fabrication caught.
WEB_ADDRESS = re.compile(r"\bhttps?://|\bwww\.[a-z0-9-]+\.[a-z]{2,}", re.I)

# Compound nouns only: a bare "web" is part of a beam and "online" an in-line
# instrument in domains that ship.
WEB_SOURCE = re.compile(
    r"\b(?:web[\s-]?(?:search|searches|fetch|page|pages|site|sites)|website|"
    r"websites|webpage|webpages|search\s+engine|search\s+results|"
    r"internet\s+search|online\s+search)\b", re.I)

# A browsing verb with something web-shaped for it to act on; "Response
# searches the counts matrix" is ordinary work. The inflected forms of
# "google" carry their object; bare "Google" is a company a line may name.
WEB_ACT = re.compile(
    r"\bgoogl(?:es|ed|ing)\b|"
    r"\b(?:search(?:es|ed|ing)?|brows(?:e|es|ed|ing)|"
    r"look(?:s|ed|ing)?\s+up|consult(?:s|ed)?|visit(?:s|ed)?|"
    r"navigat(?:e|es|ed)\s+to)\b[^.]{0,40}?"
    r"\b(?:the\s+web|the\s+internet|online|google|a\s+search\s+engine)\b",
    re.I)

# Judgement calls dressed up as checks.
SUBJECTIVE = re.compile(
    r"\b(sensible|reasonable|appropriate|good|well[- ](?:written|structured|reasoned)"
    r"|high[- ]quality|thorough|clear(?:ly)? explains?|properly|correctly handles?"
    r"|adequate|sufficient|nicely|elegant)\b",
    re.IGNORECASE,
)


# A hedge on the value a line is graded on, in three shapes: a bound with a
# hedge on it, an exactness or a whole with a hedge on it, and "most" used as
# a count. A quoted span is a word the answer might use, which the line names
# rather than grades by.
HEDGED = (
    ("a hedged bound", re.compile(
        r"\b(?:no more than|no fewer than|no less than|at most|at least|more than|"
        r"fewer than|less than|up to|under|over|above|below|within)\s+"
        r"(?:about|approximately|roughly|around|nearly|almost|some)\b", re.I)),
    ("a hedged exactness", re.compile(
        r"\b(?:almost|nearly|roughly|approximately|virtually)\s+"
        r"(?:exactly|identical|all|every|none|the same)\b", re.I)),
    ("an unquantified most", re.compile(
        r"\b(?:that|whether|where|when|if|because)\s+most\s+"
        r"(?!(?:closely|likely|probably|often|recently)\b)|"
        r"\bmost of (?:the|its|their|those|these)\b", re.I)),
)
QUOTED = re.compile(r"(?<!\w)'[^']{1,60}'(?!\w)|\"[^\"]{1,200}\"|\u201c[^\u201d]{1,200}\u201d")

# The words a negative uses to turn a positive round.
NEGATING = re.compile(
    r"\b(?:does not|do not|did not|fails? to|omits?|other than|anything but|"
    r"incorrect(?:ly)?|wrong(?:ly)?|misstates?|instead of)\b", re.I)
# A negative that states a bound or a class rather than one value.
CLASS_WORDS = re.compile(
    r"\b(?:other than|any|anything|outside|below|above|less than|more than|"
    r"fewer than|greater than|except)\b", re.I)
# One wrong claim with where it was said to come from: the same claim, not two.
ATTRIBUTION = re.compile(
    r"\band (?:attributes|credits|cites|sources) (?:it|this|that|them|the figure|"
    r"the value|the claim)\b", re.I)
STOPWORDS = frozenset(
    "response the a an of to in on for and or as by with that this is are was "
    "its it from at be not does do states reports gives names says any other "
    "than which what when".split())


def _content(body: str) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9_.-]+", EXACT_VALUE.sub(" ", body.lower()))
    words = (w.rstrip(".-") for w in words)
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def _identifiers(words: set[str]) -> set[str]:
    """The words that carry a digit: sample, gene and file names."""
    return {w for w in words if any(ch.isdigit() for ch in w)}


def _values(body: str) -> set[str]:
    """The figures a line states, leaving out a named ratio such as 260/280."""
    body = re.sub(r"\d+(?:\.\d+)?/\d+(?:\.\d+)?", " ", body)
    return {m.group(0) for m in EXACT_VALUE.finditer(body)}


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def parse(text: str) -> tuple[list[dict], list[str]]:
    """Parse rubrics.md. Returns (rubrics, parse errors)."""
    rubrics: list[dict] = []
    errors: list[str] = []
    category: str | None = None
    counters: dict[str, int] = {}

    for lineno, raw in enumerate(strip_comments(text).splitlines(), start=1):
        if not raw.strip():
            continue

        heading = HEADING_RE.match(raw)
        if heading:
            key = heading.group("title").strip().lower()
            category = CATEGORIES.get(key)
            if category is None:
                errors.append(
                    f"line {lineno}: heading '{heading.group('title').strip()}' is not one of "
                    + SECTIONS
                )
            continue

        bullet = BULLET_RE.match(raw)
        if not bullet:
            errors.append(f"line {lineno}: not a heading and not a '- ' bullet: {raw.strip()[:60]!r}")
            continue

        if category is None:
            errors.append(f"line {lineno}: this criterion is not under a "
                          + SECTIONS + " heading")
            continue

        body = bullet.group("body")
        tags = set()
        prefix = TAG_RE.match(body)
        if prefix:
            tags = {m.group("tag").lower() for m in ONE_TAG_RE.finditer(prefix.group(0))}
            body = body[prefix.end():].strip()

        weight = None
        legacy = []
        unknown = []
        rejected = False
        where = set()
        for tag in sorted(tags):
            if WEIGHT_RE.match(tag):
                value = int(tag)
                if value not in WEIGHTS:
                    rejected = True
                    errors.append(
                        f"line {lineno}: weight [{tag}] is not allowed; use one of "
                        + ", ".join(f"[{w:+d}]".replace("+", "") for w in WEIGHTS))
                else:
                    weight = value
            elif tag in STATE_TAGS:
                where.add(LABEL_STATE_CHANGE)
            elif tag in USER_TAGS:
                where.add(LABEL_USER_FACING)
            elif tag in LEGACY_TAGS:
                legacy.append(tag)
            else:
                unknown.append(tag)

        if unknown:
            errors.append(f"line {lineno}: unknown tag(s) {sorted(unknown)}; "
                          "expected a weight such as [5], [3], [1], [-1], [-3] or [-5], "
                          "optionally followed by [state]")

        if len(where) > 1:
            errors.append(
                f"line {lineno}: this line is tagged as both [state] and [user-facing]. "
                "One criterion is checked in one place: the answer text, or the "
                "workspace. Split it into two lines if it is really both.")
            continue

        if weight is None and legacy:
            # must -> 5, should -> 1, and [negative] flips the sign.
            weight = max((LEGACY_TAGS[t] for t in legacy if LEGACY_TAGS[t]), default=5)
            if "negative" in legacy:
                weight = -weight

        if weight is None:
            # A weight that was written but rejected has already been reported;
            # saying "no weight" as well would send the contributor looking for
            # a second, different problem on the same line.
            if not rejected:
                errors.append(
                    f"line {lineno}: no weight. Start the line with how much it is worth: "
                    "[5], [3] or [1] for something the answer should do, "
                    "[-5], [-3] or [-1] for something it should not.")
            continue

        if not body:
            errors.append(f"line {lineno}: a weight but no criterion text")
            continue

        counters[category] = counters.get(category, 0) + 1

        # These three keys are the whole delivered file. The id, the category
        # and whether the line is a must-have are derived from them rather than
        # stored alongside them.
        rubrics.append({
            "criteria": body,
            "weight": weight,
            "type": [CATEGORY_LABEL[category],
                     where.pop() if where else LABEL_USER_FACING],
            "_id": hashlib.md5(body.encode("utf-8")).hexdigest(),
            "_category": category,
            "_body": body,
            "_line": lineno,
            "_legacy": legacy,
        })

    return rubrics, errors


def lint(rubrics: list[dict], phase: str = "finished",
         has_suite: bool = False, tests: int = 0,
         labels: dict | None = None, fired: set[str] | None = None,
         prompt: str = "") -> list[dict]:
    """The rules from rubrics.md, plus id collisions and the count.

    `phase` -- "none", "running" or "finished" -- is what separates the two
    halves of this step. Completion criteria come from the ground truth and are
    written while the solver runs; the non-hallucination criteria are written
    afterwards, against what the model actually claimed. Holding a half-written
    set to the finished standard would fail a contributor who is doing exactly
    the right thing.

    `has_suite` turns on the finding about values belonging in a test. Off
    where there is no suite to move them into, which is every task in the
    rubrics-only sandbox and any task that has run /flc-skip-tests -- there an
    exact-value criterion is the right thing and must stay it.

    `tests` is how many unit tests the task carries, which count towards the
    floor alongside the criteria. The floor is reported here and enforced at
    /flc-grade: a half-written set has to keep compiling while the run goes.

    `labels` is what labels.md answers, and the Clarification heading is held
    to its first answer. Not given, nothing here is about the labels.

    `fired` is the criteria the current grade charged the run for, and
    `prompt` the contributor's prompt; the mirror and pinned-figure findings
    stay silent where either shows the line is right.
    """
    fired = {" ".join(f.split()).lower() for f in (fired or set())}
    positives = [r for r in rubrics if r["weight"] > 0]
    run_finished = phase == "finished"
    findings: list[dict] = []

    def add(level: str, title: str, detail: str = "", fix: str = "") -> None:
        findings.append({"level": level, "title": title, "detail": detail, "fix": fix})

    if not rubrics:
        add("FAIL", "No rubrics found",
            "tests/rubrics.md has no '- ' criteria under a recognised heading.",
            "Write your criteria in tests/rubrics.md, then run this again.")
        return findings

    seen: dict[str, dict] = {}
    for r in rubrics:
        body, line = r["_body"], r["_line"]

        if r["_id"] in seen:
            add("FAIL", "Two identical criteria",
                f"line {line} repeats line {seen[r['_id']]['_line']}: {body[:70]!r}",
                "Delete one, or make them say different things.")
        seen[r["_id"]] = r

        # Rule 1 -- one fact per line. A negative naming one wrong claim with
        # the source it was credited to is one claim.
        if not (RANGE.search(body) or CONTRAST.search(body)
                or (r["weight"] < 0 and ATTRIBUTION.search(body))):
            second_claim = SECOND_CLAIM.search(body)
            if second_claim or len(VALUE_FRAME.findall(body)) >= 2:
                add("WARN", "This line looks like it checks two separate things",
                    f"line {line}: {body[:70]!r}",
                    "Split it into two. As one line, an answer that gets the "
                    "first part right and the second wrong scores zero, and you "
                    "lose the difference between them.")

        # Rule 2 -- judgeable alone.
        if DANGLING.search(body):
            add("FAIL", "This line refers to something outside itself",
                f"line {line}: {body[:70]!r}",
                "The judge sees this line and nothing else. Write the actual "
                "value in the line.")

        # Self-containment, the ordinal half. Applies to every section: the
        # judge reads one line at a time whatever heading it sat under.
        #
        # A WARN rather than a FAIL, unlike the back-references above. Those
        # phrases cannot be anything but a reference outside the line;
        # an ordinal can be part of a name the field just uses that way, and
        # the contributor knows whether theirs is.
        ordinal = ORDINAL.search(body)
        if ordinal:
            add("WARN", "This line uses an ordinal the judge cannot resolve",
                f"line {line}: {body[:70]!r}",
                f"{ordinal.group(0).strip()!r} asks the judge to know an order "
                "the line never states, and it is shown one criterion at a "
                "time with nothing else. Name the thing instead -- 'the "
                "hygromycin construct' rather than 'the second construct'. An "
                "ordinal that indexes a position in something the line names, "
                "like 'its first row', is fine and is not what this catches.")
        sequence = SEQUENCE_REF.search(body)
        if sequence:
            add("WARN", "This line points outside itself",
                f"line {line}: {body[:70]!r}",
                f"{sequence.group(0).strip()!r} has nothing to refer to: the "
                "judge sees this line alone. Name what is meant.")

        # One phrasing for every line: "Response" and a verb, or the agent's
        # trajectory for a line about what it did. Always a WARN. A [state]
        # line, and a line that opens by naming a file, take the file as their
        # subject.
        about_artifact = (LABEL_STATE_CHANGE in r["type"]
                          or FILE_PATH.match(body))
        if not about_artifact and not SUBJECT.match(body):
            other = OTHER_SUBJECT.match(body)
            add("WARN", "This line does not open with 'Response' or the agent",
                f"line {line}: {body[:70]!r}",
                ("Write it as 'Response " + body.split()[0].lower() + " ...', or "
                 "as 'The agent " + body.split()[0].lower() + " ...' if it is "
                 "about what the agent did. "
                 if not other else
                 f"Write {other.group(0).strip()!r} as 'Response' for what the "
                 "answer says, or as 'The agent' or 'Trajectory shows' for what "
                 "the agent did. ")
                + "Every criterion opens one of those ways, so that a rubric "
                "reads the same way from the first line to the last. A line "
                "about a file names the file instead.")

        # Rule 3 -- checkable, not an opinion.
        if SUBJECTIVE.search(body):
            add("WARN", "This line asks for a judgement, not a check",
                f"line {line}: {body[:70]!r}",
                "Replace the judgement with the observable fact you actually "
                "mean.")

        # Browsing is the route, not the check. Positive lines only: a negative
        # line about an invented source is a fabrication caught, and that is
        # the most valuable kind of criterion there is.
        if r["weight"] > 0:
            web = (WEB_ADDRESS.search(body) or WEB_SOURCE.search(body)
                   or WEB_ACT.search(body))
            if web:
                add("WARN", "This line credits the model for looking something up",
                    f"line {line}: {body[:70]!r}",
                    f"{web.group(0).strip()!r} asks about where the model went "
                    "rather than what it ended up with. The judge is shown the "
                    "answer, the files the model produced and the transcript, "
                    "and never a web page, so it cannot check what one said -- "
                    "and the same task is re-run against an agent that may have "
                    "no browser. Looking things up is part of the work and your "
                    "prompt can ask for it; the criterion states the fact that "
                    "came back. A negative line about a source the model "
                    "invented is a different thing and is not what this "
                    "catches.")

        # A negative under Clarification is allowed: asking and not asking are
        # two sides of one behaviour, and either sign describes it. What the
        # section cannot hold is a fabrication, which is the neighbouring
        # section's whole subject.
        if r["_category"] == "clarification" and r["weight"] < 0:
            add("WARN", "A negative criterion under Clarification",
                f"line {line}: {body[:70]!r}",
                "If this line describes something the model made up, it belongs "
                "under '## Non-hallucination'. If it describes a question it "
                "should have asked and did not, it is right where it is.")

        # Written to the failure class rather than to this run: the
        # non-hallucination half only, and always a WARN.
        if r["_category"] == "non_hallucination":
            if ENUMERATION.search(body) and not OPEN_CLASS.search(body):
                add("WARN", "This line lists what the run did, not the mistake",
                    f"line {line}: {body[:70]!r}",
                    "Another run of this task will not produce the same list. "
                    "State the class of "
                    "mistake and let the list define what is correct instead: "
                    "'presents any clone other than 8, 18 and 22 as a double "
                    "transformant' catches the same error on any run, where the "
                    "four this one named catches it on none.")
            if QUOTED_SPAN.search(body):
                add("WARN", "This line quotes a phrase from the answer",
                    f"line {line}: {body[:70]!r}",
                    "A criterion pinned to one wording scores nothing against a "
                    "model that made the same mistake in other words. Say what "
                    "was wrong about the claim rather than how this run "
                    "happened to word it.")

        # A hedge on the value the grade turns on leaves two graders free to
        # disagree about the same answer.
        for shape, pattern in HEDGED:
            hedge = pattern.search(QUOTED.sub(" ", body))
            if hedge:
                add("WARN", "This line hedges the value it is graded on",
                    f"line {line}: {body[:70]!r}",
                    f"{hedge.group(0).strip()!r} is {shape}: two graders holding "
                    "the same answer can read it either way. State the number, "
                    "or the tolerance you would accept.")
                break

        # A negative that is a positive turned round -- the same subject and
        # the same value, charged for departing from it -- measures one thing
        # twice. Silent where the negative names a wrong value of its own,
        # where it names identifiers the positive does not (a class by
        # exclusion over a set), and where the grade shows the run committed it.
        if r["weight"] < 0 and " ".join(body.split()).lower() not in fired \
                and NEGATING.search(body):
            mine = _content(body)
            for p in positives:
                theirs = _content(p["_body"])
                shared = mine & theirs
                if (_values(body) <= _values(p["_body"]) and len(shared) >= 3
                        and _identifiers(mine) <= _identifiers(theirs)
                        and len(shared) >= 0.6 * min(len(mine), len(theirs) or 1)):
                    add("WARN", "This negative restates a positive the other way round",
                        f"line {line}: {body[:70]!r} mirrors line {p['_line']}",
                        "Both lines score the same thing, so one mistake costs "
                        "twice. Let the positive require the right value, and "
                        "have the negative name the wrong route an answer takes "
                        "-- the stale file it reads, the rule it skips -- or "
                        "delete it.")
                    break

        # A negative pinned to a figure catches an answer that writes that
        # figure and nothing else. It needs a positive requiring the correct
        # value for the same thing, so that a different wrong figure still
        # costs the answer something.
        if r["weight"] < 0 and r["_category"] == "non_hallucination":
            pinned = {v for v in _values(body) if v not in (prompt or "")}
            if pinned and not CLASS_WORDS.search(body):
                mine = _content(body)
                covered = any(_values(p["_body"]) and len(mine & _content(p["_body"])) >= 2
                              for p in positives)
                if not covered:
                    add("WARN", "This negative names a figure no positive line covers",
                        f"line {line}: {body[:70]!r}",
                        f"A rerun that writes a different wrong figure than "
                        f"{', '.join(sorted(pinned))} walks past it. Keep this "
                        "line, and add a positive one requiring the correct value "
                        "for the same thing, so any other wrong figure still "
                        "costs the answer.")

        # Rule 4 -- not a restatement of the prompt.
        if len(body.split()) < 4:
            add("WARN", "This line is very short",
                f"line {line}: {body[:70]!r}",
                "Short criteria are usually restatements of the task rather "
                "than something checkable.")

        # Rule 6 -- an exact value in a produced file is an assertion.
        #
        # Both halves are required. A number alone would catch every criterion
        # about a figure the answer states in prose, which is correctly a
        # criterion: the model may write 1.2e-5 or 0.000012 and the judge reads
        # for the value where a text match gets one spelling. A named file
        # alone would catch "results.csv lists Pten in its first row", which
        # has no value in it to compare. What is being caught is the pair.
        if has_suite and EXACT_VALUE.search(body) and (
                FILE_PATH.search(body) or LABEL_STATE_CHANGE in r["type"]):
            add("WARN", "This line checks an exact value in a file",
                f"line {line}: {body[:70]!r}",
                "That is an automated check rather than a criterion. A judge "
                "call is being spent to have a language model eyeball a number "
                "that an assertion settles exactly. Move it into "
                "tests/verifier.py -- a test carries a weight on this same "
                "scale, so nothing is lost. Two kinds of line stay "
                "here: a number the answer states in prose, and one whose file "
                "position or format your prompt only gave as an example, since "
                "a check demanding one spelling would fail a model that chose "
                "another.")

    # Rule 7 -- the Clarification heading follows labels.md.
    clarifying = [r for r in rubrics if r["_category"] == "clarification"]
    underspecified = (labels or {}).get("underspecified_task")
    if labels is None:
        pass
    elif underspecified is None and not (run_finished or clarifying):
        # The labels wait for the first run, so the first sitting is not
        # reminded of them unless it has written the criteria they govern.
        pass
    elif underspecified is None:
        add("WARN", "labels.md does not say yet whether the task is underspecified",
            f"{len(clarifying)} Clarification criteri"
            f"{'on' if len(clarifying) == 1 else 'a'} so far, and nothing to "
            "hold them against.",
            f"Answer the first three headings in {lb.LABELS} (step 3), then "
            "run /flc-check-justification.")
    else:
        problem = lb.clarification(
            underspecified, sum(1 for r in clarifying if r["weight"] > 0),
            len(clarifying), run_finished)
        if problem:
            add("FAIL" if problem.blocking else "TODO",
                ("A Clarification criterion on a task marked not underspecified"
                 if underspecified == "no" else
                 "No criterion says the model raised the gap"),
                problem.what, problem.fix)

    # Rule 5 -- the non-hallucination half, and how much of it there has to be.
    #
    # Counted over the negative lines under the heading, the same count
    # /flc-grade reads. A positive line there is counted as completion.
    by_cat: dict[str, int] = {}
    for r in rubrics:
        by_cat[r["_category"]] = by_cat.get(r["_category"], 0) + 1
    catching = sum(1 for r in rubrics
                   if r["_category"] == "non_hallucination" and r["weight"] < 0)
    if not catching:
        if run_finished:
            add("FAIL", "No hallucination criteria",
                "Nothing under '## Non-hallucination' describes a mistake the "
                "answer or the trajectory should not make."
                + (f" {by_cat['non_hallucination']} positive line(s) sit there, "
                   "which measure what the answer got right."
                   if by_cat.get("non_hallucination") else " Every criterion is "
                   "under Completion."),
                f"Write {st.HALLUCINATION_FLOOR} lines at [-5], [-3] or [-1] "
                "for the ways this task leads a model wrong: a claim nothing "
                "supports, a file it never read, a step it skipped, sources it "
                "mixed up, a conflict it settled without saying so. They are "
                "the point of this project. Read what the model did with "
                "/flc-inspect.")
        elif phase == "running":
            add("TODO", "The non-hallucination criteria are still to come",
                "The solver run has not finished, so there is nothing to write "
                "them against yet.",
                "Finish your completion criteria now. When the run lands, run "
                "/flc-rubrics again and write these against what it claimed.")
        else:
            add("TODO", "The non-hallucination criteria are still to come",
                "They are written against what the model claims, and no run "
                "has been started yet.",
                "Start the run with /flc-run-solver, write your completion "
                "criteria while it goes, then come back to these.")
    elif catching < st.HALLUCINATION_FLOOR:
        short = st.HALLUCINATION_FLOOR - catching
        if run_finished:
            add("FAIL", f"{catching} of the {st.HALLUCINATION_FLOOR} "
                        "hallucination criteria needed",
                "Counted over the negative lines under '## Non-hallucination'. "
                "A positive line under that heading is a fine criterion and "
                "does not count here.",
                f"Write {short} more. They come from the run first -- a claim "
                "no file supports, a file cited for something it does not say, "
                "a check it says it ran and did not, a file it had to read and "
                "never opened, a conflict it settled without saying so. Up to "
                f"{st.ANTICIPATED_CAP} of the {st.HALLUCINATION_FLOOR} may "
                "instead be a wrong turn your material makes attractive that "
                "this run avoided, and a set where all of them fire is better "
                "than one where two do not.")
        else:
            add("TODO", f"{catching} non-hallucination criteria so far, of the "
                        f"{st.HALLUCINATION_FLOOR} needed",
                "A running count, not a problem yet: these are written against "
                "what the model claims.",
                "Come back to these when the run lands. /flc-inspect reads it "
                "and lists the claims worth checking.")

    # The floor on how many checks a task carries. Reported here and enforced
    # at /flc-grade, never failed here: the completion criteria are written
    # while the run goes, so a set that is short at this moment is a set being
    # written rather than a set that is wrong.
    total = len(rubrics) + tests
    if total < st.MIN_CHECKS:
        short = st.MIN_CHECKS - total
        counted = f"{len(rubrics)} criteria"
        if tests:
            counted += f" and {tests} unit tests"
        if run_finished:
            add("WARN", f"{total} checks of the {st.MIN_CHECKS} needed",
                f"{counted}. Grading refuses below {st.MIN_CHECKS}.",
                f"Add {short} more. Every ask in the prompt needs an outcome "
                "line of its own, and each way the run went wrong can be a "
                "hallucination criterion. A hard step that every correct route "
                "has to take can earn a line about the trajectory too -- never "
                "an easy one like opening a file. A line that checks nothing "
                "real is worse than none.")
        else:
            add("TODO", f"{total} checks so far, of the {st.MIN_CHECKS} needed",
                f"{counted}. This is a running count, not a problem yet.",
                "Keep going. Every ask in the prompt earns an outcome line, and "
                "the hallucination criteria come once the run lands.")

    # Nothing here counts the criteria for a ceiling. What is caught is two
    # lines measuring the same thing, which would score one mistake twice.

    if not any(abs(r["weight"]) == 5 for r in rubrics):
        add("FAIL", "Nothing is weighted [5]",
            "Every criterion is worth 3 or 1, so nothing can fail the answer.",
            "Give [5] to the criteria that carry the answer.")

    legacy = [r for r in rubrics if r.get("_legacy")]
    if legacy:
        add("WARN", "%d line(s) still use [must]/[should]/[negative]" % len(legacy),
            "Read as " + ", ".join(f"line {r['_line']} -> [{r['weight']}]" for r in legacy[:4]),
            "Weights replaced them: [5], [3], [1] for what the answer should do, "
            "and the same with a minus for what it should not.")

    # A rubric with no negative line anywhere.
    if run_finished and not any(r["weight"] < 0 for r in rubrics):
        add("WARN", "No negative criteria",
            "Every line describes something the answer should do.",
            "Add hallucination criteria: the ways a model goes wrong on this "
            "task, weighted [-5], [-3] or [-1]. Those are what catch a fluent "
            "wrong answer.")

    # Decided the way /flc-check-rubric decides them, so they are said here first.
    if rq is not None and rubrics:
        shaped = [{"text": r["criteria"], "weight": r["weight"], "kind": r["type"][1]}
                  for r in rubrics]
        for f in rq.carryovers(shaped):
            r = rubrics[f.index - 1]
            add("WARN", "This line weighs a file's copy of a value at [1]",
                f"line {r['_line']}: {r['_body'][:70]!r} checks a value a [5] "
                "line checks in the answer",
                "A copy is weighted like the value it copies: [5] where your "
                "prompt asks for the file, and never below [3].")
        for a, b in rq.containment_pairs(shaped):
            first, second = rubrics[a - 1], rubrics[b - 1]
            add("WARN", "This line may only repeat another",
                f"line {first['_line']}: {first['_body'][:60]!r} says nothing line "
                f"{second['_line']} does not",
                "If no answer could earn the other line without earning this one, "
                "it checks nothing the other does not: take it out, or fold it "
                "into the other. If it does check something more, say what in its "
                "own words.")

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", default=None)
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    ci.announce(root, "rubrics")
    source = root / "tests" / "rubrics.md"
    if not source.exists():
        raise SystemExit(f"no {source}")

    phase = st.run_state(root)
    tests = st._test_count(root)
    rubrics, errors = parse(source.read_text())
    findings = [{"level": "FAIL", "title": "rubrics.md could not be read", "detail": e,
                 "fix": "Fix that line and run this again."} for e in errors]
    # The labels decide whether Clarification criteria belong. has_suite reads
    # the disk, so a suite set aside by /flc-skip-tests counts as none.
    lb.ensure(root)
    import rubric_check  # noqa: PLC0415 -- it parses this module's rubrics.md
    charged = rubric_check.fired(root, st.load(root)) or {}
    findings += lint(rubrics, phase=phase,
                     has_suite=(root / "tests" / "verifier.py").exists(),
                     tests=tests,
                     labels=lb.read(root).values,
                     fired={text for text, hit in charged.items() if hit},
                     prompt=st.contributor_prompt(root))

    verdict = "FAIL" if any(f["level"] == "FAIL" for f in findings) else "PASS"
    by_cat: dict[str, int] = {}
    for r in rubrics:
        by_cat[r["_category"]] = by_cat.get(r["_category"], 0) + 1

    wrote = None
    if verdict == "PASS" and not args.check:
        payload = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rubrics]
        target = root / "tests" / "rubrics.json"
        target.write_text(json.dumps(payload, indent=2) + "\n")
        wrote = str(target)
        # The verifier timeout scales with the rubric count, so the manifest has
        # to be rewritten whenever that count changes.
        st.write_task_toml(root)
        # A half-written set compiles, so that the completion criteria can be
        # checked while the run is going, but the step is not done until the
        # non-hallucination criteria exist.
        if by_cat.get("non_hallucination"):
            st.mark_done(root, "rubrics")

    # Reported after the compile, because compiling is what moves the digest
    # the rubric review is pinned to: a criterion edited here leaves a recorded
    # verdict describing a set nobody is shipping.
    review_entry, review_current = rubric_check.recorded(st.load(root), root)
    if verdict == "PASS":
        if review_entry is None:
            findings.append({
                "level": "TODO", "title": "The criteria have not been reviewed yet",
                "detail": "Nothing has asked whether a criterion turns down a "
                          "right answer, reads two ways, or leaves something "
                          "the prompt asks for unchecked.",
                "fix": "Run /flc-check-rubric once these criteria are finished. "
                       "Delivery needs that check, taken on the criteria it "
                       "ships.",
            })
        elif not review_current:
            findings.append({
                "level": "WARN", "title": "The check on record is of earlier criteria",
                "detail": f"It read a different set and said {review_entry['verdict']}.",
                "fix": "Run /flc-check-rubric again when these are finished. "
                       "Delivery needs that check, taken on the criteria it "
                       "ships.",
            })

    # Counted from what was just parsed rather than through check_count(),
    # which reads the compiled rubrics.json -- absent or stale on a FAIL, and
    # this has to report the file in front of the contributor.
    report = {
        "verdict": verdict, "total": len(rubrics), "by_category": by_cat,
        "checks": {"rubrics": len(rubrics), "tests": tests,
                   "total": len(rubrics) + tests, "floor": st.MIN_CHECKS,
                   "enough": len(rubrics) + tests >= st.MIN_CHECKS},
        "findings": findings, "wrote": wrote, "run": phase,
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if verdict == "PASS" else 1

    print(f"  criteria: {len(rubrics)}"
          f"  (completion {by_cat.get('completion', 0)},"
          f" clarification {by_cat.get('clarification', 0)},"
          f" non-hallucination {by_cat.get('non_hallucination', 0)})")
    if tests:
        print(f"  checks:   {len(rubrics) + tests} of {st.MIN_CHECKS} needed"
              f"  ({len(rubrics)} criteria + {tests} unit tests)")
    else:
        print(f"  checks:   {len(rubrics)} of {st.MIN_CHECKS} needed")
    if rubrics:
        # The two totals are not one total. Positive weights are the marks
        # available and are what the score is divided by; negative ones are
        # deducted for tripping them and are not marks anybody can collect.
        # Adding them together produced a number that appears in no calculation.
        available = sum(r["weight"] for r in rubrics if r["weight"] > 0)
        penalties = -sum(r["weight"] for r in rubrics if r["weight"] < 0)
        spread = {w: sum(1 for r in rubrics if r["weight"] == w) for w in WEIGHTS}
        print("  points:   %d available, %d in penalties  (%s)" % (
            available, penalties,
            ", ".join(f"{n}x[{w}]" for w, n in spread.items() if n)))
    if phase != "finished":
        print("  the solver run has not landed: completion criteria now, "
              "non-hallucination\n            criteria once it has")
    print()
    for f in findings:
        print(f"  [{f['level']}] {f['title']}")
        if f["detail"]:
            print(f"         {f['detail']}")
        if f["fix"]:
            print(f"         -> {f['fix']}")
    if not findings:
        print("  nothing to fix.")
    print()
    if wrote:
        print(f"  wrote {wrote}")
    print(f"  {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
