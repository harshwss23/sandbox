#!/usr/bin/env python3
"""Read solution/labels.md: the task's labels, as the contributor wrote them.

    python3 bin/labels.py                # the first three, and anything else answered
    python3 bin/labels.py --stage post   # all five, once the run has been graded
    python3 bin/labels.py --json         # the taxonomy delivery writes

Each answer sits under its heading in one of the spellings the template lists.
Capitals, surrounding space and trailing punctuation are ignored; anything else
is reported with its line and the spellings accepted, and never guessed at.

Nothing here writes into labels.md, except to create it from the template when
a task has none.

Exit code 0 when nothing has to change, 1 when something does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402

LABELS = "solution/labels.md"

YES_NO = ("yes", "no")
LEVELS = ("l1 - minimal", "l2 - low", "l3 - moderate", "l4 - high", "l5 - full")
FULL = "l5 - full"
CATEGORIES = ("grounding", "synthesis", "correctness_reasoning", "exploration",
              "conflict_resolution")
MAX_FAILURE_SENTENCES = 3

# (key, heading, kind). The heading is what the contributor sees; the key is
# what the taxonomy carries.
FIELDS = (
    ("underspecified_task", "Is your task underspecified?", "yes_no"),
    ("underspecification_level", "Underspecification level", "level"),
    ("browsing_required", "Does your task require browsing?", "yes_no"),
    ("model_failure_category", "Model failure category", "categories"),
    ("model_failure_justification", "Model failure justification", "prose"),
)
PRE = ("underspecified_task", "underspecification_level", "browsing_required")
POST = ("model_failure_category", "model_failure_justification")
HEADING = {key: heading for key, heading, _ in FIELDS}
KIND = {key: kind for key, _, kind in FIELDS}

TAXONOMY_KEYS = ("model_failure_category", "model_failure_justification",
                 "underspecified_task", "underspecification_level",
                 "underspecification_justification", "browsing_required")

HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TRAILING = ".,;:!"
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

# Markdown in prose that is meant to be pasted into a form field as plain text.
MARKDOWN = (
    ("a heading", re.compile(r"^\s*#{1,6}\s+\S", re.M)),
    ("a bullet list", re.compile(r"^\s*[-*+]\s+\S", re.M)),
    ("a numbered list", re.compile(r"^\s*\d{1,2}[.)]\s+\S", re.M)),
    ("bold or italic", re.compile(
        r"\*\*[^*\n]+\*\*|__[^_\n]+__"
        r"|(?<![\w*])\*[^*\s][^*\n]*\*(?![\w*])"
        r"|(?<![\w_])_[^_\s][^_\n]*_(?![\w_])")),
    ("backticks", re.compile(r"`")),
    ("a table", re.compile(r"^\s*\|.*\|\s*$", re.M)),
    ("a link in markdown form", re.compile(r"\[[^\]\n]+\]\([^)\n]+\)")),
    ("a quote block", re.compile(r"^\s*>\s", re.M)),
    ("a horizontal rule", re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.M)),
)

# Words ending in a full stop that do not end a sentence.
ABBREVIATIONS = {
    "e.g", "i.e", "etc", "vs", "al", "fig", "figs", "eq", "eqs", "no", "nos",
    "approx", "ca", "cf", "dr", "mr", "mrs", "ms", "prof", "st", "sp", "spp",
    "vol", "p", "pp", "ref", "refs", "sec", "resp", "var",
}
# A "What the model cannot know" section that only says there is nothing.
NOTHING_RE = re.compile(
    r"^\W*(?:(?:nothing|none|n/?a|not applicable)\b|-+\s*$)", re.I)
NOTHING_WORDS = 12

_BOUNDARY = re.compile(r"[.!?]+[\"')\]]*\s+(?=[A-Z0-9\"'(\[])")


def strip_comments(text: str) -> str:
    return COMMENT_RE.sub("", text or "")


def markdown(text: str) -> list[str]:
    """Which kinds of markdown the text carries, comments excluded."""
    body = strip_comments(text)
    return [name for name, pattern in MARKDOWN if pattern.search(body)]


def listing(items: list[str]) -> str:
    """"a", "a and b", "a, b and c"."""
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def prose(text: str) -> str:
    """Comments out, each paragraph's lines joined, paragraphs kept apart."""
    paragraphs, current = [], []
    for line in strip_comments(text).splitlines():
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def sentences(text: str) -> int:
    """How many sentences the prose holds, abbreviations and initials aside."""
    body = " ".join(prose(text).split())
    if not body:
        return 0
    count = 1
    for match in _BOUNDARY.finditer(body):
        before = body[:match.start()].rsplit(None, 1)
        word = before[-1].lstrip("(\"'[").lower() if before else ""
        if word in ABBREVIATIONS or re.fullmatch(r"[a-z]", word):
            continue
        count += 1
    return count


# --- reading the file ---------------------------------------------------------


def _norm_heading(title: str) -> str:
    return " ".join(title.lower().rstrip("?: ").split())


_KNOWN = {_norm_heading(heading): key for key, heading, _ in FIELDS}


def _norm_value(raw: str) -> str:
    value = raw.strip().rstrip(TRAILING).strip().lower()
    for dash in DASHES:
        value = value.replace(dash, "-")
    return " ".join(value.split())


def _level(raw: str) -> str | None:
    value = _norm_value(raw)
    match = re.fullmatch(r"(?:l|level)\s*([1-5])\s*-\s*([a-z]+)", value)
    if not match:
        return None
    canonical = f"l{match.group(1)} - {match.group(2)}"
    return canonical if canonical in LEVELS else None


def _category(raw: str) -> str | None:
    value = _norm_value(raw)
    value = re.sub(r"\s*/\s*|\s+", "_", value)
    return value if value in CATEGORIES else None


@dataclass
class Finding:
    field: str
    what: str
    fix: str = ""
    line: int | None = None
    blocking: bool = True

    @property
    def level(self) -> str:
        return "FAIL" if self.blocking else "WARN"

    def as_dict(self) -> dict:
        return {"field": self.field, "level": self.level, "line": self.line,
                "what": self.what, "fix": self.fix}


@dataclass
class Labels:
    exists: bool = False
    values: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    problems: list[Finding] = field(default_factory=list)

    def get(self, key: str):
        return self.values.get(key)


def path(root: Path) -> Path:
    return root / LABELS


def ensure(root: Path) -> Path:
    """labels.md, created from the template when the task has none."""
    target = path(root)
    if target.exists():
        return target
    template = st.FLC_HOME / "template_task" / LABELS
    target.parent.mkdir(parents=True, exist_ok=True)
    if template.is_file():
        shutil.copy2(template, target)
    else:
        target.write_text("".join(f"## {heading}\n\n\n" for _, heading, _ in FIELDS))
    return target


def parse(text: str) -> Labels:
    """The answers in `text`, and every place it could not be read."""
    out = Labels(exists=True)
    lines: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    seen: set[str] = set()
    body = COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for number, line in enumerate(body.splitlines(), 1):
        heading = HEADING_RE.match(line)
        if heading:
            key = _KNOWN.get(_norm_heading(heading.group("title")))
            if key is None:
                out.problems.append(Finding(
                    "file", f'"{heading.group("title")}" is not one of the '
                    "headings in labels.md, so nothing under it is read.",
                    fix="Keep only the five headings the template has, and "
                        "put each answer under its own.", line=number))
                current = "_unknown"
            elif key in seen:
                out.problems.append(Finding(
                    key, f'"{HEADING[key]}" appears more than once.',
                    fix="Keep one, with the answer under it.", line=number))
                current = "_unknown"
            else:
                seen.add(key)
                current = key
                lines.setdefault(key, [])
            continue
        if not line.strip():
            continue
        if current is None:
            out.problems.append(Finding(
                "file", f'"{line.strip()[:60]}" sits above the first heading, '
                "so it answers nothing.",
                fix="Move it under the heading it answers.", line=number))
            continue
        if current != "_unknown":
            lines[current].append((number, line))

    for key, heading, kind in FIELDS:
        if key not in seen:
            out.problems.append(Finding(
                key, f'The heading "{heading}" is missing.',
                fix=f'Put "## {heading}" back, with the answer under it.'))
            continue
        entries = lines.get(key, [])
        out.raw[key] = "\n".join(text for _, text in entries)
        if not entries:
            continue
        if kind == "prose":
            out.values[key] = prose(out.raw[key])
            continue
        if kind == "categories":
            chosen: list[str] = []
            for number, text_line in entries:
                for item in (p for p in text_line.split(",") if p.strip()):
                    value = _category(item)
                    if value is None:
                        out.problems.append(Finding(
                            key, f'"{item.strip()}" is not one of the '
                            "accepted spellings.",
                            fix="Write one or more of: " + ", ".join(CATEGORIES)
                                + ".", line=number))
                    elif value not in chosen:
                        chosen.append(value)
            if chosen and not any(p.field == key for p in out.problems):
                out.values[key] = chosen
            continue
        if len(entries) > 1:
            out.problems.append(Finding(
                key, f'"{heading}" has more than one line under it; it takes '
                "one answer.",
                fix="Keep the answer and nothing else on the line.",
                line=entries[1][0]))
            continue
        number, text_line = entries[0]
        value = _level(text_line) if kind == "level" else (
            _norm_value(text_line) if _norm_value(text_line) in YES_NO else None)
        if value is None:
            accepted = ", ".join(LEVELS) if kind == "level" else "yes, no"
            out.problems.append(Finding(
                key, f'"{text_line.strip()}" is not one of the accepted '
                "spellings.", fix=f"Write one of: {accepted}.", line=number))
        else:
            out.values[key] = value
    return out


def read(root: Path) -> Labels:
    target = path(root)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return Labels()
    return parse(text)


# --- what the labels have to agree with ---------------------------------------


def cannot_know(root: Path) -> bool | None:
    """Whether the ground truth's "What the model cannot know" is written.

    None when there is no ground truth to read at all.
    """
    try:
        text = (root / st.GROUND_TRUTH).read_text(encoding="utf-8")
    except OSError:
        return None
    inside, body = False, []
    for line in strip_comments(text).splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            title = heading.group("title").lower()
            inside = "cannot know" in title or "cannot be known" in title
            continue
        if inside and line.strip():
            body.append(line)
    words = " ".join(body).split()
    if words and len(words) <= NOTHING_WORDS and \
            NOTHING_RE.match(" ".join(words)):
        return False
    return bool(body)


def consistency(labels: Labels, root: Path) -> list[Finding]:
    """The rules that tie the first two labels to each other and to the answer."""
    out: list[Finding] = []
    under = labels.get("underspecified_task")
    level = labels.get("underspecification_level")
    if under == "yes" and level and level != FULL:
        out.append(Finding(
            "underspecification_level",
            f'The task is marked underspecified and the level is "{level}". '
            "Underspecified means Level 5: part of the request cannot be done "
            "without asking you.",
            fix=f'Make the level "{FULL}", or answer no if the model can '
                "settle every part on its own."))
    if under == "no" and level == FULL:
        out.append(Finding(
            "underspecification_level",
            f'The level is "{FULL}" and the task is marked not underspecified. '
            "Level 5 is the underspecified case.",
            fix="Answer yes if the model cannot finish without asking you; "
                "otherwise choose the level of the highest gap it can settle "
                "on its own."))
    written = cannot_know(root)
    if under == "yes" and written is False:
        out.append(Finding(
            "underspecified_task",
            "The task is marked underspecified and ground_truth.md has no "
            '"What the model cannot know" section written.',
            fix="Write that section -- what is missing, what the model should "
                "ask, and what it can still do -- or answer no."))
    if under == "no" and written:
        out.append(Finding(
            "underspecified_task",
            "The task is marked not underspecified and ground_truth.md has a "
            '"What the model cannot know" section written.',
            fix=f'If the model cannot finish without asking you, answer yes and '
                f'"{FULL}"; if it can, delete that section.'))
    return out


def failure(labels: Labels) -> list[Finding]:
    """The two labels written after grading."""
    out: list[Finding] = []
    chosen = labels.get("model_failure_category") or []
    if "correctness_reasoning" in chosen and (
            "grounding" in chosen or "exploration" in chosen):
        out.append(Finding(
            "model_failure_category",
            "correctness_reasoning is chosen alongside grounding or "
            "exploration. A wrong answer that follows from a misread or "
            "unopened source is that earlier failure, not also a reasoning one.",
            fix="Keep correctness_reasoning only if the model also asserted "
                "something false that no file had to be read to disprove.",
            blocking=False))
    text = labels.raw.get("model_failure_justification", "")
    if prose(text):
        kinds = markdown(text)
        if kinds:
            out.append(Finding(
                "model_failure_justification",
                "The failure justification uses " + listing(kinds)
                + "; it goes into a plain text field.",
                fix="Write it as plain sentences."))
        count = sentences(text)
        if count > MAX_FAILURE_SENTENCES:
            out.append(Finding(
                "model_failure_justification",
                f"The failure justification is {count} sentences; the most is "
                f"{MAX_FAILURE_SENTENCES}.",
                fix="Keep the most important failure and what it cost, and cut "
                    "the rest yourself."))
    return out


def browsing(labels: Labels, requests: list[dict] | None) -> list[Finding]:
    """The browsing label held against the web requests one run made.

    Reported and never blocking: a run is one run, and the label is about the
    task. `requests` is None where no run could be read, which says nothing.
    """
    answer = labels.get("browsing_required")
    if requests is None or answer not in YES_NO:
        return []
    hosts = sorted({h for r in requests for h in r.get("hosts") or []})
    if answer == "no" and requests:
        where = ", ".join(hosts[:5]) or "the web"
        return [Finding(
            "browsing_required",
            f"The answer is no and the graded run made {len(requests)} web "
            f"request(s) ({where}).",
            fix="Browsing is allowed either way; the label is whether the task "
                "needs it. If a correct answer depends on something only "
                "online, the answer is yes.",
            blocking=False)]
    if answer == "yes" and not requests:
        return [Finding(
            "browsing_required",
            "The answer is yes and the graded run made no web request.",
            fix="That can be the failure itself, if the model never looked. If "
                "a correct answer needs nothing from the web, the answer is no.",
            blocking=False)]
    return []


def run_requests(root: Path, job: Path | None = None) -> list[dict] | None:
    """The web requests of `job`, or of the last graded run; None if unreadable."""
    try:
        import grade_report as gr
        import review_run as rr
        import solver_answer as sa
        job = job or gr.latest_job(root)
        transcript = sa.find_trajectory(job) if job else None
        if not transcript:
            return None
        requests, _ = rr.browsing(transcript, job)
        return requests
    except Exception:
        return None


def unanswered(labels: Labels, keys: tuple[str, ...]) -> list[Finding]:
    out = []
    for key in keys:
        if key in labels.values:
            continue
        if any(p.field == key for p in labels.problems):
            continue
        if key not in labels.raw:
            continue  # the missing heading is already reported
        out.append(Finding(key, f'"{HEADING[key]}" is not answered yet.',
                           fix="Write the answer on the line under it."))
    return out


def check(root: Path, stage: str = "pre",
          requests: list[dict] | None = None) -> list[Finding]:
    """Everything that has to change in labels.md before `stage` is done.

    "pre" is step 3: the first three answered, and nothing answered so far
    unreadable. "post" is after grading: all five, and the browsing answer held
    against `requests`, the graded run's web requests, where those are given.
    """
    ensure(root)
    labels = read(root)
    keys = PRE if stage == "pre" else PRE + POST
    out = list(labels.problems)
    out += unanswered(labels, keys)
    out += consistency(labels, root)
    if stage == "post" or any(k in labels.values for k in POST):
        out += failure(labels)
    if stage == "post":
        out += browsing(labels, requests)
    return out


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.blocking]


def pre_digest(root: Path) -> str:
    """A digest of the answers under the first three headings, as read.

    Taken over the values rather than the bytes, so a formatting fix that
    leaves every answer the same leaves the digest the same.
    """
    values = read(root).values
    payload = json.dumps({k: values.get(k) for k in PRE}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summary(root: Path) -> dict:
    """How far labels.md has got, read without writing anything."""
    labels = read(root)
    findings = list(labels.problems) + consistency(labels, root)
    if any(k in labels.values for k in POST):
        findings += failure(labels)
    return {"exists": labels.exists,
            "answered": sum(k in labels.values for k in PRE + POST),
            "of": len(FIELDS), "to_fix": len(blocking(findings))}


def clarification(under: str | None, positive: int, total: int,
                  landed: bool) -> Finding | None:
    """Whether the Clarification criteria agree with the first label.

    `under` is the answer to "Is your task underspecified?"; `positive` and
    `total` count the criteria labelled clarification. None when they agree,
    or when the label is not answered yet.
    """
    if under == "no" and total:
        return Finding(
            "underspecified_task",
            f"The rubric has {total} Clarification criteri"
            f"{'on' if total == 1 else 'a'} and labels.md says the task is not "
            "underspecified. A Clarification line is only for a request the "
            "model cannot finish without asking you.",
            fix="Move the line under Completion if the model could settle it "
                "from your files, or answer yes in labels.md if it cannot.")
    if under == "yes" and not positive:
        return Finding(
            "underspecified_task",
            "labels.md says the task is underspecified and no positive "
            "Clarification criterion says the model raised the gap.",
            fix="Add one under ## Clarification naming the question you would "
                "accept, or answer no in labels.md.",
            blocking=landed)
    return None


# --- the taxonomy -------------------------------------------------------------


def taxonomy(root: Path) -> dict:
    """The labels in the shape the taxonomy step takes."""
    labels = read(root)
    try:
        justification = st.justification_file(root).read_text(encoding="utf-8")
    except OSError:
        justification = ""
    values = {
        "model_failure_category": labels.get("model_failure_category") or [],
        "model_failure_justification":
            labels.get("model_failure_justification") or "",
        "underspecified_task": labels.get("underspecified_task") or "",
        "underspecification_level": labels.get("underspecification_level") or "",
        "underspecification_justification": prose(justification),
        "browsing_required": labels.get("browsing_required") or "",
    }
    return {key: values[key] for key in TAXONOMY_KEYS}


def taxonomy_text(root: Path) -> str:
    return json.dumps(taxonomy(root), indent=2, ensure_ascii=False) + "\n"


# --- what the contributor sees ------------------------------------------------


def report(findings: list[Finding], stage: str) -> None:
    print()
    print(f"{LABELS}")
    print()
    if not findings:
        done = "all five labels" if stage == "post" else "the first three labels"
        print(f"  PASS  {done} read cleanly and agree with each other.")
        print()
        return
    for finding in findings:
        where = HEADING.get(finding.field, "labels.md")
        line = f", line {finding.line}" if finding.line else ""
        print(f"  {finding.level}  {where}{line}: {finding.what}")
        if finding.fix:
            print(f"        {finding.fix}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    ap.add_argument("--stage", choices=("pre", "post"), default="pre")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = st.task_root(args.task)
    if args.json:
        ensure(root)
        print(taxonomy_text(root), end="")
        return 0
    requests = run_requests(root) if args.stage == "post" else None
    findings = check(root, args.stage, requests)
    report(findings, args.stage)
    return 1 if blocking(findings) else 0


if __name__ == "__main__":
    sys.exit(main())
