#!/usr/bin/env python3
"""Read a finished solver run and surface the claims worth checking.

    review_run.py                  the last run, written to review/
    review_run.py --job PATH       a specific run
    review_run.py --print          also print the document
    review_run.py --no-api         deterministic checks only
    review_run.py --quiet          write the file, say one line about it

The non-hallucination criteria are written by reading what the model claimed:
holding the answer up against the contributor's own material and noticing the
one figure that is in none of it. This does the mechanical half -- which
numbers in the answer appear nowhere, which cited files do not exist, which of
the planted traps the model walked into -- and leaves the judgement.

Every finding carries the evidence it was derived from: the sentence the claim
appears in, and the file or step it was checked against. Nothing here is a
verdict. A trajectory search is trustworthy when it says a file was opened and
untrustworthy when it says one was not, since `cat data/*.csv` reads a file
without naming it, so findings resting on an absence say so and are ranked
below the ones that do not.

It also answers a question that is not about criteria at all: whether the model
worked the answer out or read it off a page. Browsing is wanted, so the two
look identical as tool calls -- what separates them is whether the figure could
have come from anywhere else in the run. A run that looked the answer up is not
deliverable, and /flc-deliver refuses on the same function rather than on a
second reading of the same evidence.

Two things it does not do. It proposes negative criteria only, never completion
criteria. And it never writes to tests/rubrics.md.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import check_inputs as ci  # noqa: E402  -- its Office and PDF text extraction
import context_report as cr  # noqa: E402  -- it locates the session log
import flc_state as st  # noqa: E402
import solver_answer as sa  # noqa: E402
from prompt_taxonomy import (  # noqa: E402  -- what a reviewer must not conclude
    Refused, Unreachable, call_models, cutoff_note, looks_refused,
)

# The sandbox's credentials, resolved the same way for every caller.
from flc_state import gateway  # noqa: E402

# Imported rather than reimplemented, so the transcript is read here exactly the
# way the judge reads it.
from solver_answer import (  # noqa: E402
    final_message,
    find_job,
    find_trajectory,
    written_files,
)

# Text-bearing suffixes, kept in step with check_inputs.TEXT_EXT. Anything else
# is counted and reported as unreadable.
TEXT_EXT = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".xml", ".html", ".log", ".py", ".r", ".sh", ".sql", ".bed", ".gtf", ".gff",
    ".fa", ".fasta", ".fq", ".fastq", ".vcf", ".sam", ".pdb", ".mtx",
}

# Do not add \n to this class: it would span the joins and eat the filenames on
# either side of the blob. Same reasoning as judge._B64_BLOB, same pattern.
_B64_BLOB = re.compile(r"[A-Za-z0-9+/=]{2000,}")

# The boundaries matter more than they look. Without them the 19 in S19 and the
# 56 in ENSG00000000056 come out as figures, and a report padded with sample
# identifiers buries the one invented number it exists to show.
#
# A comma only counts as a thousands separator when it groups three digits.
# Accepting any comma reads the CSV row `...,01,10,...` as the number 110, so
# every spreadsheet in the workspace silently manufactured figures -- which is
# the dangerous direction here, since a manufactured figure is what makes an
# invented one look sourced.
NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?"
    r"(?![A-Za-z0-9_])")
PATH_RE = re.compile(r"[\w./-]*\w+\.[A-Za-z][A-Za-z0-9]{1,6}\b")
ACTION_RE = re.compile(
    r"\b(?:I|we)\s+(?:have\s+)?"
    r"(ran|run|executed|verified|checked|confirmed|validated|tested|computed|"
    r"calculated|measured|inspected|reviewed)\b",
    re.I,
)

# Below this, a figure is almost always a count of something small, a section
# number or a footnote marker, and flagging it as unsourced buries the findings
# that matter under noise.
MIN_INTERESTING = 10
MAX_PER_CHECK = 8
STEP_TEXT_CHARS = 700
TOOL_ARG_CHARS = 240

STRONG = "strong"
CHECK = "worth checking"
WEAK = "weak"
ORDER = {STRONG: 0, CHECK: 1, WEAK: 2}


# --- reading the material -----------------------------------------------------


def canon(raw: str) -> str:
    """A number as it would be recognised across differently formatted files.

    2,383 in a report and 2383 in a CSV are the same figure, and a trailing
    zero is not a difference worth a false positive. A token too large to be a
    number, such as the identifier `53e2893413`, is compared as written.
    """
    text = raw.replace(",", "").lstrip("+")
    try:
        value = float(text)
    except ValueError:
        return text
    if not math.isfinite(value):
        return text.lower()
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(round(value, 6))


def numbers_in(text: str) -> set[str]:
    return {canon(m.group()) for m in NUMBER_RE.finditer(text)}


def sentences(text: str) -> list[str]:
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for piece in re.split(r"(?<=[.!?])\s+", line):
            piece = piece.strip()
            if piece:
                parts.append(piece)
    return parts


def quote_for(text: str, needle: str) -> str:
    """The sentence a claim was made in, so the contributor can see it in context."""
    for sentence in sentences(text):
        if needle in sentence:
            return sentence if len(sentence) <= 300 else sentence[:297] + "..."
    return needle


def file_text(path: Path) -> str | None:
    """A file's readable text, or None if this cannot see inside it.

    Office files are zipped XML and a spreadsheet is where quantitative tasks
    keep their numbers, so leaving them out was not a small gap: on a workspace
    of four workbooks nothing at all was readable, and every figure the model
    computed came back as "in none of your files". Eight such findings buried
    the one real one, which is the specific failure this document exists to
    avoid causing.
    """
    suffix = path.suffix.lower()
    try:
        if suffix in ci.ZIP_XML_EXT:
            return ci._text_of_zip_xml(path, ci.ZIP_XML_EXT[suffix]) or None
        if suffix == ".pdf":
            return ci._text_of_pdf(path) or None
        if suffix in TEXT_EXT or suffix == "":
            return path.read_text(errors="replace")
    except OSError:
        return None
    return None


def workspace_corpus(root: Path) -> tuple[str, list[str]]:
    """Everything readable in the uploaded workspace, and what could not be read.

    The unreadable list is not a footnote: a task whose counts are in Parquet
    keeps its real numbers somewhere this cannot see, and a finding that says
    "this figure is in none of your files" has to be honest about that.
    """
    ws = root / "environment" / "workspace"
    chunks: list[str] = []
    unreadable: list[str] = []
    for rel in st.workspace_files(root):
        text = file_text(ws / rel)
        if text is None:
            unreadable.append(rel)
        else:
            chunks.append(text)
    return "\n".join(chunks), unreadable


def produced_corpus(job: Path, root: Path) -> tuple[str, list[str] | None]:
    """What the model wrote, read back as text where that is possible.

    A None file list means the run collected no workspace. Everything
    downstream has to keep that apart from an empty one: a claim to have
    written a file is only suspicious if we could have seen the file.
    """
    produced = written_files(job, root)
    if produced is None:
        return "", None
    workspace = sa.finished_workspace(job)
    chunks: list[str] = []
    if workspace is not None:
        for rel in produced:
            path = workspace / rel
            if path.is_file() and (path.suffix.lower() in TEXT_EXT or path.suffix == ""):
                try:
                    chunks.append(path.read_text(errors="replace"))
                except OSError:
                    pass
    return "\n".join(chunks), produced


ground_truth_sections = st.ground_truth_sections


# --- the trajectory -----------------------------------------------------------


_DESCRIPTION_KEYS = ("description", "explanation", "reason", "intent")


def _described(arguments) -> str:
    """The agent's own account of a call, from whichever key the dialect uses."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (ValueError, TypeError):
            return ""
    if isinstance(arguments, dict):
        for key in _DESCRIPTION_KEYS:
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _tool_calls(record: dict,
                limit: int | None = TOOL_ARG_CHARS) -> list[tuple[str, str, str, str]]:
    """Every (tool, argument, description, call id) in a record, across dialects.

    The call id is "" where the dialect carries none. `limit` is None for
    view_run.py, which shows the run unabridged. The dialects live here rather
    than in both files: a new one is easy to miss twice.
    """
    found: list[tuple[str, str, str, str]] = []

    def add(name, arg, note="", ident="") -> None:
        if not name:
            return
        # The description travels in its own field, so it comes out of the
        # argument: what is left is the command as it was run.
        if isinstance(arg, str) and note:
            try:
                arg = json.loads(arg)
            except (ValueError, TypeError):
                pass
        if isinstance(arg, dict):
            arg = {k: v for k, v in arg.items()
                   if not (k in _DESCRIPTION_KEYS and isinstance(v, str))}
        if isinstance(arg, (dict, list)):
            arg = json.dumps(arg)
        text = str(arg or "")
        note = str(note or "").strip()
        found.append((str(name),
                      text if limit is None else text[:limit],
                      note if limit is None else note[:limit],
                      str(ident or "")))

    for key in ("tool_calls", "tool_call", "function_call", "actions", "tools"):
        value = record.get(key)
        items = value if isinstance(value, list) else [value] if value else []
        for item in items:
            if isinstance(item, dict):
                fn = item.get("function") if isinstance(item.get("function"), dict) else item
                arg = fn.get("arguments") or fn.get("input") or item.get("args")
                add(fn.get("name") or item.get("function_name") or item.get("tool")
                    or item.get("type"), arg, _described(arg),
                    item.get("tool_call_id") or item.get("id"))
    content = record.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_call"):
                add(block.get("name"), block.get("input"),
                    _described(block.get("input")), block.get("id"))
    if record.get("tool_name") or record.get("command"):
        arg = record.get("command") or record.get("input") or record.get("args")
        add(record.get("tool_name") or "command", arg,
            _described(arg) or record.get("description") or "")
    return found


def steps(trajectory: Path) -> list[dict]:
    """The transcript as a list of turns, in the shape a person can read."""
    try:
        data = json.loads(trajectory.read_text(errors="replace"))
    except Exception:
        return []
    out: list[dict] = []
    for record in sa._records_of(data):
        if not isinstance(record, dict):
            continue
        speaker = ""
        for key in sa._SPEAKER_KEYS:
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                speaker = value.strip()
                break
        text = ""
        for key in sa._TEXT_KEYS:
            if key in record:
                text = sa._text_of(record[key]).strip()
                if text:
                    break
        text = _B64_BLOB.sub("[encoded image omitted]", text)
        tools = _tool_calls(record)
        if not speaker and not text and not tools:
            continue
        out.append({"speaker": speaker or "?", "text": text, "tools": tools})
    return out


def trajectory_text(trajectory: Path) -> str:
    """The whole transcript as plain text, for asking whether something appears."""
    try:
        raw = trajectory.read_text(errors="replace")
    except OSError:
        return ""
    return _B64_BLOB.sub("[encoded image omitted]", raw)


def session_observed_text(job: Path | None) -> str:
    """Tool results out of the agent's own session log.

    Harbor's trajectory.json carries the turns as prose and, on a real run, not
    one tool result: 19 messages, 356 characters of them anything that came
    back. So the "or its own output" half of the unsourced-number check was
    reading nothing, and six of eight figures reported as sourced nowhere were
    sitting in output the model had printed. That is the worst shape of bug
    this document can have -- a confident finding, with evidence named, that
    invites a criterion penalising the model for having done the work.

    The session log beside it holds the results. `context_report` reads the
    same file for the token usage and already said so in its own docstring,
    which is where this should have been noticed.
    """
    if job is None:
        return ""
    chunks: list[str] = []
    for record in cr.session_records(job):
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                chunks.append(sa._text_of(block.get("content")))
    return "\n".join(c for c in chunks if c)


def observed_text(trajectory: Path, job: Path | None = None) -> str:
    """Only what came back to the agent: tool results, and what it was asked.

    The distinction is the whole of the unsourced-number check. A transcript
    contains the answer, so searching all of it for a figure the answer states
    always succeeds and nothing is ever unsourced. What makes a figure sourced
    is having appeared in a file or in the output of something that ran -- not
    the model having said it.
    """
    try:
        data = json.loads(trajectory.read_text(errors="replace"))
    except Exception:
        data = None
    chunks: list[str] = [session_observed_text(job)]
    if data is None:
        return _B64_BLOB.sub("[encoded image omitted]", "\n".join(chunks))
    for record in sa._records_of(data):
        if not isinstance(record, dict) or sa._is_agent(record):
            continue
        for key in sa._TEXT_KEYS:
            if key in record:
                text = sa._text_of(record[key])
                if text:
                    chunks.append(text)
                    break
    # Tool results also arrive as content blocks inside an agent record.
    for record in sa._records_of(data):
        if not isinstance(record, dict):
            continue
        content = record.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    chunks.append(sa._text_of(block.get("content")))
    return _B64_BLOB.sub("[encoded image omitted]", "\n".join(chunks))


def actions_text(trajectory: Path) -> str:
    """Every command the agent ran, as it ran it.

    Separate from what came back, since the two support different claims. A
    filename in a tool result means the environment produced it. A filename in
    a command means only that the agent tried something with it, which is
    enough to stop a file being called invented.
    """
    try:
        data = json.loads(trajectory.read_text(errors="replace"))
    except Exception:
        return ""
    chunks: list[str] = []
    for record in sa._records_of(data):
        if isinstance(record, dict):
            for tool, arg, _, _id in _tool_calls(record):
                chunks.append(f"{tool} {arg}")
    return "\n".join(chunks)


# --- the checks ---------------------------------------------------------------


def finding(level: str, title: str, claim: str, why: str, evidence: str,
            draft: str = "", subject: str = "", subject_kind: str = "") -> dict:
    """One thing to look at. `subject` is the figure or path it turns on.

    A finding carries a subject only where it has one token that could be
    searched for in a criterion. `uncovered()` is what reads it.
    """
    return {"level": level, "title": title, "claim": claim, "why": why,
            "evidence": evidence, "draft": draft,
            "subject": subject, "subject_kind": subject_kind}


NEGATIVE_LINE = re.compile(
    r"^\s*[-*]\s*\[-[135]\]\s*(?:\[[a-z_-]+\]\s*)?(.+)$", re.M)
ANY_LINE = re.compile(
    r"^\s*[-*]\s*\[([+-]?[135])\]\s*(?:\[[a-z_-]+\]\s*)?(.+)$", re.M)


def written_criteria(root: Path) -> list[str]:
    """Every criterion in tests/rubrics.md as it stands, with its weight."""
    try:
        text = (root / "tests" / "rubrics.md").read_text()
    except OSError:
        return []
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return [f"[{m.group(1)}] {m.group(2).strip()}" for m in ANY_LINE.finditer(text)]


def negative_criteria(root: Path) -> list[str]:
    """The negative criteria as the contributor has them now.

    Read from tests/rubrics.md rather than the compiled rubric, which is a
    sitting behind while the non-hallucination half is being written.
    """
    try:
        text = (root / "tests" / "rubrics.md").read_text()
    except OSError:
        return []
    return [m.group(1).strip() for m in NEGATIVE_LINE.finditer(text)]


def uncovered(findings: list[dict], criteria: list[str]) -> list[dict]:
    """The run's own mistakes that no negative criterion appears to name.

    Matched on the one thing a criterion can be searched for without a model: a
    figure, compared as a number so that 2,383 and 2383 are one, or a path.

    A criterion describing the same mistake in words of its own is not matched
    here, so this says where to look rather than what is missing, and it is
    reported and never gated. There are no verdicts at this point in the
    workflow -- the run has just finished and nothing has been graded -- so
    whether a criterion covers a mistake is not yet an answerable question.
    """
    if not criteria:
        return []
    body = "\n".join(criteria)
    figures = numbers_in(body)
    out = []
    for item in findings:
        subject = item.get("subject") or ""
        kind = item.get("subject_kind") or ""
        if not subject:
            continue
        if kind == "figure" and canon(subject) in figures:
            continue
        if kind == "path" and subject in body:
            continue
        out.append(item)
    return out


def check_trap_hits(answer: str, gt: dict[str, str]) -> list[dict]:
    """Figures the contributor planted as wrong answers, showing up in the answer.

    The strongest check there is, and the cheapest: they already wrote down
    what each trap is and what wrong answer it produces, so a hit is a
    finished thought rather than a suspicion.
    """
    distractors = gt.get("distractors", "")
    if not distractors.strip():
        return []
    planted = {n for n in numbers_in(distractors) if abs(float(n)) >= MIN_INTERESTING}
    true_answer = numbers_in(gt.get("answer", ""))
    out = []
    for value in sorted(planted & numbers_in(answer), key=float):
        if value in true_answer:
            continue  # a figure that is right and also near a trap is not a hit
        out.append(finding(
            STRONG,
            f"States {value}, which is one of your planted wrong answers",
            quote_for(answer, value),
            "This figure appears in the distractor section of your ground truth, "
            "and not in the answer section. The model took the bait.",
            f"solution/ground_truth.md names {value} among what should mislead "
            "a careless model",
            f"- [-5] Response states {value} as <what this figure is meant to be>",
            subject=value, subject_kind="figure",
        ))
    return out[:MAX_PER_CHECK]


def check_trap_files(answer: str, gt: dict[str, str], root: Path) -> list[dict]:
    """Files the contributor named as misleading, leaned on in the answer.

    Not every mention is a mistake -- an answer that says "the summary claims
    134, which is wrong" cites the trap correctly, and saying so is the job.
    That is why this asks rather than concludes: what matters is whether the
    file was used as evidence or ruled out.
    """
    distractors = gt.get("distractors", "")
    if not distractors.strip():
        return []
    known = set(st.workspace_files(root))
    named = {p for p in PATH_RE.findall(distractors) if p.strip("./") in known}
    out = []
    for path in sorted(named):
        if path not in answer:
            continue
        out.append(finding(
            CHECK,
            f"Leans on {path}, which you recorded as a distractor",
            quote_for(answer, path),
            "You named this file among what should mislead a careless model. "
            "Citing it is only a mistake if the answer treated it as evidence "
            "rather than ruling it out -- read the sentence and decide.",
            f"solution/ground_truth.md names {path} among the distractors",
            f"- [-3] Response relies on {path} for <the claim it draws from it>",
            subject=path, subject_kind="path",
        ))
    return out[:MAX_PER_CHECK]


def check_contradicts_ground_truth(answer: str, gt: dict[str, str]) -> list[dict]:
    """Figures the ground truth gives that the answer never states."""
    stated = numbers_in(gt.get("answer", ""))
    if not stated:
        return []
    missing = {n for n in stated if abs(float(n)) >= MIN_INTERESTING} - numbers_in(answer)
    if not missing:
        return []
    listed = ", ".join(sorted(missing, key=float)[:6])
    return [finding(
        CHECK,
        "Figures from your ground truth that the answer never gives",
        "",
        "These are in the answer section of your ground truth and nowhere in "
        "what the model said. That is usually a completion gap rather than a "
        "hallucination -- it belongs in your completion criteria, which are "
        "yours to write -- but a wrong figure in its place is a negative.",
        f"missing from the answer: {listed}",
    )]


def check_missing_paths(answer: str, root: Path, produced: list[str] | None,
                        observed: str, actions: str) -> list[dict]:
    """Files the answer cites that are in neither the workspace nor the output.

    A file the model created and then referred to would otherwise land here
    whenever the run collected no workspace, which is the worst false positive
    available: it invites a criterion penalising a model for work it did. So a
    name the environment reported back is dropped, and a name that only appears
    in a command it ran is reported as an open question rather than as a
    fabrication.
    """
    known = set(st.workspace_files(root)) | set(produced or [])
    basenames = {Path(p).name for p in known}

    def names_a_real_file(cited: str) -> bool:
        """Is this the name of something that exists, whole or in part?

        A path pattern cannot cross a space, so a workspace file called
        `TRANSECT BIRD SURVEY DATA.xlsx` is only ever matched as `DATA.xlsx`.
        Compared literally that is a file nobody has, and the reviewer leads
        with an invented citation for a file sitting in the workspace. So a
        fragment that completes a real name at a word boundary counts as that
        name. It errs towards saying nothing, which is the right direction for
        a check whose false positive is an accusation.
        """
        if cited in known or Path(cited).name in basenames:
            return True
        tail = Path(cited).name
        return any(name.endswith(tail) and name[:-len(tail)].endswith((" ", "_", "-"))
                   for name in basenames if len(name) > len(tail))

    out = []
    seen: set[str] = set()
    for match in PATH_RE.finditer(answer):
        cited = match.group().strip("./")
        if not cited or cited in seen:
            continue
        suffix = Path(cited).suffix.lower()
        if suffix not in TEXT_EXT and suffix not in {
                ".parquet", ".h5", ".hdf5", ".xlsx", ".xls", ".pdf", ".png",
                ".jpg", ".jpeg", ".zip", ".db", ".sqlite"}:
            continue
        seen.add(cited)
        if names_a_real_file(cited):
            continue
        if cited in observed or Path(cited).name in observed:
            continue  # something the model ran reported this name back
        if cited in actions or Path(cited).name in actions:
            out.append(finding(
                CHECK,
                f"Cites {cited}, which is not in the workspace but does appear "
                "in something it ran",
                quote_for(answer, match.group()),
                "The model worked with this name, so it most likely created it "
                "and the run did not collect a copy. Open the steps below and "
                "see. This is usually a gap in what the harness gathered rather "
                "than an invented file.",
                "the commands it ran, against environment/workspace/ and the "
                "files the run left behind",
            ))
            continue
        out.append(finding(
            STRONG,
            f"Cites {cited}, which is not in the workspace",
            quote_for(answer, match.group()),
            "No uploaded file has this name, the run left no such file behind, "
            "and nothing it ran mentions it.",
            "environment/workspace/, the files the run left behind, and every "
            "command it ran",
            f"- [-3] Response attributes a finding to {cited}, which does not exist",
        ))
    return out[:MAX_PER_CHECK]


def check_unsourced_numbers(answer: str, corpora: dict[str, str],
                            unreadable: list[str]) -> list[dict]:
    """Figures that appear nowhere this can read.

    The check most in need of its caveat: a figure the model worked out
    correctly also appears nowhere, having not existed until the analysis
    produced it. So this asks a question rather than answering one -- is this a
    number that can be traced?
    """
    sourced: set[str] = set()
    for text in corpora.values():
        sourced |= numbers_in(text)
    caveat = ("A number the model derived correctly also appears in none of "
              "these -- the point of the check is to make you look at it, not "
              "to say it is wrong.")
    if unreadable:
        caveat += (f" {len(unreadable)} file(s) could not be read as text "
                   f"({', '.join(unreadable[:3])}), so a figure that came out "
                   "of one of them lands here too.")
    out = []
    for value in sorted(numbers_in(answer) - sourced, key=float):
        if abs(float(value)) < MIN_INTERESTING:
            continue
        out.append(finding(
            CHECK,
            f"States {value}, which is in none of your files or its own output",
            quote_for(answer, value),
            caveat,
            "the uploaded files, the files it wrote, the output of everything "
            "it ran, and your ground truth",
            f"- [-3] Response states {value} as <what this figure is meant to be>",
            subject=value, subject_kind="figure",
        ))
    return out[:MAX_PER_CHECK]


# --- browsing: research, or the answer read off a page ------------------------
#
# The model has the internet on purpose, and looking something up is part of
# doing the work. Reading the *answer* off a page is not, and both are the same
# tool call -- what separates them is whether the figure the answer states
# could have come from anywhere else in the run. If the model worked it out,
# the number appears in the output of whatever it ran. If its only appearance
# in the whole run is in what came back from a web request, it was looked up.
#
# Requests are paired to their results by tool-call id, which is what lets a
# figure be attributed to the page it came off rather than to the transcript at
# large. A call whose result cannot be paired still counts as the run having
# browsed; it cannot support a finding about a figure, and does not.

WEB_TOOL = re.compile(
    r"web[_\- ]?(?:search|fetch|browse|read)|websearch|webfetch|browser|"
    r"fetch_url|open_url|url_fetch|http_get|google_search", re.I)

# A shell that reached the internet. Needs a URL alongside it to count, so
# `curl` against the model gateway is not read as research.
WEB_COMMAND = re.compile(
    r"\b(?:curl|wget|lynx|w3m|httpie)\b|requests\.(?:get|post)\b|"
    r"\burllib\b|\burlopen\b|\bhttpx\b", re.I)

# Only an explicit scheme. A bare `curl example.com` is missed, and that is the
# safe direction for something that refuses a delivery: under-detection costs a
# finding, over-detection costs a contributor a run they did nothing wrong in.
URL_IN = re.compile(r"https?://(?:www\.)?([A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.I)

# Reaching these is not research. A run that pip-installed scanpy made a
# network request and looked nothing up, and the gateway is how the model is
# answering at all.
#
# `host.docker.internal` is the one that has to be here rather than the one it
# looks like: `proxy_setup.sh` rewrites the gateway's loopback address to that
# alias for the agent, so it is the form a real run actually calls. A bare
# `localhost` or `127.0.0.1` cannot reach this set at all -- URL_IN wants a dot
# followed by letters -- so listing them would be decoration.
INFRASTRUCTURE = {
    "host.docker.internal",
    "pypi.org", "files.pythonhosted.org", "pythonhosted.org",
    "cran.r-project.org", "r-project.org", "bioconductor.org",
    "deb.debian.org", "security.debian.org", "archive.ubuntu.com",
    "ports.ubuntu.com", "registry.npmjs.org",
    "api.anthropic.com", "api.openai.com",
}


def _result_blocks(record: dict) -> list[dict]:
    """The tool-result blocks in a record, whichever level they sit at.

    A session-log entry wraps its content in `message`; a trajectory record
    carries it directly.
    """
    for holder in (record.get("message"), record):
        content = holder.get("content") if isinstance(holder, dict) else None
        if isinstance(content, list):
            return [b for b in content if isinstance(b, dict)]
    return []


def browsing(trajectory: Path, job: Path | None = None) -> tuple[list[dict], str]:
    """Every request the run made to the internet, and what came back from
    everything else.

    The second half is the point of returning both from one walk: deciding that
    a figure was looked up means knowing it appeared in no *other* tool result,
    and splitting that across two functions would read the transcript twice and
    let the two disagree.
    """
    records: list[dict] = []
    try:
        data = json.loads(trajectory.read_text(errors="replace"))
    except Exception:
        data = None
    if data is not None:
        records += [r for r in sa._records_of(data) if isinstance(r, dict)]
    if job is not None:
        records += [r for r in cr.session_records(job) if isinstance(r, dict)]

    results: dict[str, str] = {}
    unkeyed: list[str] = []
    for record in records:
        for block in _result_blocks(record):
            if block.get("type") not in ("tool_result", "function_result"):
                continue
            text = sa._text_of(block.get("content"))
            ident = str(block.get("tool_use_id") or block.get("id") or "")
            if ident:
                results[ident] = results.get(ident, "") + "\n" + text
            else:
                unkeyed.append(text)

    requests: list[dict] = []
    web_ids: set[str] = set()
    for record in records:
        for tool, arg, _note, ident in _tool_calls(record, limit=None):
            hosts = {h.lower() for h in URL_IN.findall(arg)} - INFRASTRUCTURE
            by_name = bool(WEB_TOOL.search(tool))
            by_shell = bool(hosts) and bool(WEB_COMMAND.search(arg)
                                            or WEB_COMMAND.search(tool))
            if not (by_name or by_shell):
                continue
            ident = str(ident or "")
            if ident:
                web_ids.add(ident)
            requests.append({
                "tool": tool,
                "hosts": sorted(hosts),
                "asked": arg[:TOOL_ARG_CHARS],
                "result": results.get(ident, ""),
                "paired": bool(ident and ident in results),
            })

    offline = "\n".join([text for ident, text in results.items()
                         if ident not in web_ids] + unkeyed)
    return requests, _B64_BLOB.sub("[encoded image omitted]", offline)


def answer_lookup(gt: dict[str, str], answer: str, requests: list[dict],
                  elsewhere: str) -> list[dict]:
    """Figures from the ground truth's answer that only a web page supplied.

    Returned as data rather than as findings, because two callers need it: the
    review document reports it, and delivery refuses on it. Parsing it back out
    of a finding's title would be one of them guessing what the other meant.

    Four conditions, and the fourth is the one doing the work. The figure has
    to be part of the answer the contributor wrote down, it has to be one the
    model stated, it has to appear in what came back from a web request, and it
    has to appear nowhere else in the run -- not in the uploaded files, not in
    what the model produced, and not in the output of anything else it ran. A
    figure the model computed is printed by the thing that computed it.
    """
    stated = {n for n in numbers_in(gt.get("answer", ""))
              if abs(float(n)) >= MIN_INTERESTING}
    said = stated & numbers_in(answer)
    if not said:
        return []
    derivable = numbers_in(elsewhere)
    out: list[dict] = []
    # No guard on request["paired"] here, and one was written before it was
    # removed. An unpaired call carries no result text at all -- a result is
    # only ever attributed through the id of the call it answered, and one with
    # no id goes to the offline corpus, where it makes a figure derivable
    # rather than looked up. So the guard could not fire, and the harness said
    # so. `paired` stays where it does work: telling the contributor, in the
    # document, that a request's result could not be matched to it.
    for request in requests:
        for value in sorted(said & numbers_in(request["result"]) - derivable,
                            key=float):
            out.append({
                "value": value,
                "hosts": request["hosts"],
                "tool": request["tool"],
                "asked": request["asked"],
                "quote": quote_for(answer, value),
            })
    return out


def run_lookups(root: Path, job: Path, trajectory: Path) -> tuple[list[dict], list[dict]]:
    """The answer figures this run read off the web, and every web request it made.

    The one reading of a run that delivery refuses on and that the run guard
    does not count, so both ask it here.
    """
    requests, offline = browsing(trajectory, job)
    workspace_text, _ = workspace_corpus(root)
    produced_text, _ = produced_corpus(job, root)
    lookups = answer_lookup(ground_truth_sections(root), final_message(trajectory),
                            requests, "\n".join([offline, workspace_text,
                                                 produced_text]))
    return lookups, requests


def check_answer_lookup(lookups: list[dict]) -> list[dict]:
    """The strongest finding there is, and the only one that stops a delivery."""
    out = []
    for hit in lookups:
        where = ", ".join(hit["hosts"]) or f"a {hit['tool']} call"
        out.append(finding(
            STRONG,
            f"Read {hit['value']} off the web rather than working it out",
            hit["quote"],
            f"{hit['value']} is part of the answer you wrote down, the model "
            f"states it, and it came back from {where}. It appears in none of "
            "your files, in nothing the model produced, and in the output of "
            "nothing else it ran -- so this run did not derive it.\n\n"
            "**This run is not deliverable.** Block that site and run the "
            "solver again:\n\n"
            f"    /flc-block-domain {hit['hosts'][0] if hit['hosts'] else 'the-site.com'}\n"
            "    /flc-run-solver\n\n"
            "Nothing you have written is at fault and none of it is lost. Your "
            "criteria, ground truth and files all stand; it is this run that "
            "has to be replaced.",
            f"{where} returned it, and {hit['value']} is in "
            "solution/ground_truth.md under the answer",
        ))
    return out[:MAX_PER_CHECK]


def check_block_held(requests: list[dict], blocked: list[str]) -> list[dict]:
    """A site on the task's own block list that the run reached anyway.

    Worth saying whether or not a figure came back with it: the list is
    name-level and does not stop a raw address, so a reachable entry on it is
    the contributor's own guard not holding.
    """
    if not blocked:
        return []
    listed = {d.lower() for d in blocked}
    reached: dict[str, bool] = {}
    for request in requests:
        for host in request["hosts"]:
            if host in listed or any(host.endswith("." + d) for d in listed):
                reached[host] = reached.get(host, False) or bool(request["result"])
    out = []
    for host, answered in sorted(reached.items()):
        out.append(finding(
            STRONG if answered else CHECK,
            f"Reached {host}, which this task blocks",
            "",
            ("Something came back from it, so the block did not hold -- it is "
             "name-level and does not stop a request to a raw address."
             if answered else
             "Nothing came back, so the block did as much as it can. Worth "
             "knowing anyway: the model went looking there, which is a fair "
             "guess at where else it might look.")
            + " Read the steps below for what it asked for.",
            "the host appears in a request, and on this task's block list",
        ))
    return out[:MAX_PER_CHECK]


def check_claimed_actions(answer: str, transcript: str) -> list[dict]:
    """Claims to have done something, with nothing in the transcript to match.

    Always weak. A shell line can run a check without naming it in any way this
    can search for, so this cannot tell you the model did not do the thing --
    only that the transcript does not obviously show it.
    """
    out = []
    for match in ACTION_RE.finditer(answer):
        sentence = quote_for(answer, match.group())
        verb = match.group(1).lower()
        anchors = [w for w in re.findall(r"[\w./-]{4,}", sentence)
                   if not w.isalpha() or w.islower()]
        if any(a in transcript for a in anchors[:6]):
            continue
        out.append(finding(
            WEAK,
            f"Says it {verb} something the transcript does not obviously show",
            sentence,
            "Nothing in the transcript matches the words in this claim. A "
            "command can do the work without naming it, so treat this as a "
            "prompt to look at the steps below rather than as a finding.",
            "searched the whole transcript for the terms in this sentence",
            f"- [-3] Response claims to have {verb} <what it says it did> "
            "when it did not",
        ))
        if len(out) >= 4:
            break
    return out


def check_claimed_files(answer: str, produced: list[str] | None, root: Path,
                        transcript: str) -> list[dict]:
    """Files the answer says it wrote that are not in the finished workspace.

    Silent when the run collected no workspace, and silent when the transcript
    shows the write. Both are the same mistake if made: telling a contributor
    that a file the model really did write is an invention, which is the one
    error this whole tool cannot afford. A criterion written against that would
    penalise a model for doing the work.
    """
    if produced is None:
        return []
    if not produced and "wrote" not in answer and "saved" not in answer:
        return []
    given = set(st.workspace_files(root))
    out = []
    # Windowed from the verb, inside one sentence. `sentences()` splits on a
    # period followed by whitespace, so a filename keeps its extension.
    for sentence in sentences(answer):
        verb = re.search(r"\b(?:wrote|saved|created|written to|output to)\b",
                         sentence, re.I)
        if not verb:
            continue
        for path_match in PATH_RE.finditer(sentence[verb.end():verb.end() + 80]):
            cited = path_match.group().strip("./")
            if cited in produced or Path(cited).name in {Path(p).name for p in produced}:
                continue
            if cited in given or Path(cited).name in {Path(p).name for p in given}:
                continue
            if cited in transcript or Path(cited).name in transcript:
                continue  # the transcript shows the write; the collection missed it
            out.append(finding(
                CHECK,
                f"Says it wrote {cited}, which is not in the finished workspace",
                quote_for(answer, path_match.group()),
                "The run's workspace holds no such file, and it is not one of "
                "the files that were uploaded.",
                f"the run produced: {', '.join(produced) if produced else 'nothing'}",
                f"- [-3] Response claims to have written {cited} when no such "
                "file exists",
                subject=cited, subject_kind="path",
            ))
    return out[:MAX_PER_CHECK]


# --- the model pass -----------------------------------------------------------
#
# A second opinion, not the opinion. The deterministic checks above can only
# find what arithmetic and string matching can find: they cannot see that a
# sentence describes a method the SOP forbids, or that a conclusion does not
# follow from the table it cites. A model reading the answer against the ground
# truth can, and is wrong often enough that everything it returns is labelled
# as its own and kept below the findings that carry evidence.
#
# It runs through the credentials the sandbox already has, resolved in the same
# order proxy_setup.sh resolves them, so no contributor enters a key and nothing
# new is exposed. When the gateway will not answer, the document is written
# without this section and says so.

REVIEW_MODEL_ENV = "FLC_REVIEW_MODEL"
GT_CHARS = 6_000
ANSWER_CHARS = 12_000
MAX_SUGGESTED = 6

PROMPT = """\
You are helping someone write grading criteria that catch a model going wrong
on a task. Below is the true answer to the task, written by a domain expert
before any model ran, the criteria already written, and what a model answered.

Name the claims in the answer that the true answer contradicts, and the
figures, files or sources the answer relies on that nothing in the true answer
gives any basis for.

Rules:
- Reply with criterion lines only, one per line, nothing else.
- Every line must have the form: - [-5] Response ... (or -3, or -1)
- -5 is a claim that ruins the answer, -3 a real error, -1 a minor one.
- Write each line as the mistake itself, never as its avoidance. Write
  "Response states X" and never "Response does not state X".
- Describe the mistake in terms any run could make, not this one's exact
  wording. A different model will be graded against these lines.
- Each line must be checkable from the answer text alone, and must contain the
  fact it checks: a grader sees one line at a time and nothing else.
- Never write a line against something the true answer itself says.
- Do not restate a criterion already written, in any wording.
- Say nothing about what the answer got right or failed to cover. Only claims
  it made that it should not have.
- If nothing qualifies, reply with the single word NONE.

THE TRUE ANSWER (written before the run):
{ground_truth}

THE CRITERIA ALREADY WRITTEN:
{criteria}

WHAT THE MODEL ANSWERED:
{answer}
{already}"""

CRITERION_RE = re.compile(r"^-?\s*\[?\s*(-[135])\s*\]?\s*(.+?)\s*$")
CRITERIA_CHARS = 6_000

# The framing words of a criterion, left out when comparing what two lines
# turn on.
_WORD = re.compile(r"[a-z0-9][a-z0-9.\-]*[a-z0-9]|[a-z0-9]")
_FILLER = frozenset("""
a an and any are as at be been being but by did do does for from had has have
in into is it its of on or than that the their them then there these this those
to was were which while with without not no nor
response agent trajectory model answer states state stated reports reported
gives given claims claimed names named says said presents presented describes
described lists listed treats treated uses used identifies identified calls
called concludes concluded attributes attributed cites cited quotes quoted
asserts asserted shows showed
""".split())


def _content(text: str) -> set[str]:
    """The words and figures a line turns on."""
    out = set()
    for token in _WORD.findall((text or "").lower()):
        if token in _FILLER or (len(token) < 3 and not token.isdigit()):
            continue
        out.add(canon(token) if NUMBER_RE.fullmatch(token) else token)
    return out


def _restates(body: str, written: list[str]) -> bool:
    """Whether a suggestion says what a written criterion already says."""
    mine = _content(body)
    if not mine:
        return False
    for other in written:
        theirs = _content(re.sub(r"^\[[+-]?\d\]\s*", "", other))
        if theirs and (mine <= theirs
                       or len(mine & theirs) / len(mine | theirs) >= 0.6):
            return True
    return False


def _against_the_answer(body: str, sealed_answer: str, traps: set[str]) -> bool:
    """Whether a suggested negative is made only of what the sealed answer says.

    A suggestion naming a figure the ground truth lists as a trap is kept.
    """
    mine = _content(body)
    if len(mine) < 3 or numbers_in(body) & traps:
        return False
    return mine <= _content(sealed_answer)


def suggest(root: Path, answer: str, findings: list[dict]) -> tuple[list[str], str]:
    """Candidate negative criteria from a model, or an empty list and a reason."""
    creds = gateway()
    if not creds:
        return [], ("No model pass: no gateway credentials were found, so this "
                    "document holds the mechanical checks only.")

    gt = ground_truth_sections(root)
    truth = "\n".join(f"## {name}\n{body}" for name, body in gt.items() if body.strip())
    if not truth.strip():
        return [], "No model pass: solution/ground_truth.md is empty."
    written = written_criteria(root)
    listed_criteria = "\n".join(f"- {c}" for c in written) or "(none yet)"
    sealed_answer = st.sealed_sections(root).get("answer", "")
    traps = numbers_in(st._strip_html_comments(gt.get("distractors", "")))
    already = ""
    if findings:
        listed = "\n".join(f"- {f['title']}" for f in findings)
        already = ("\nAlready found mechanically, so do not repeat these:\n"
                   + listed + "\n")

    key, base = creds
    models = st.check_models(None, REVIEW_MODEL_ENV)
    answered: list[str] = []
    try:
        # This pass proposes negative criteria, so a claim it does not
        # recognise is one it is being invited to call invented. It is the
        # cheapest place for the horizon to do damage and the least visible:
        # the lines land in front of a contributor as suggestions.
        text = call_models(PROMPT.format(ground_truth=truth[:GT_CHARS],
                                         criteria=listed_criteria[:CRITERIA_CHARS],
                                         answer=answer[:ANSWER_CHARS],
                                         already=already),
                           models, key, base, st.gateway_shape(), answered=answered,
                           expect_json=False, system=cutoff_note(), max_tokens=1200)
    except Refused as exc:
        st.record_issue(root, "check_unmeasured", f"run review suggestions: {exc}",
                        "review_run.py")
        return [], "No model pass: the model declined to read this run."
    except Unreachable as exc:
        st.record_issue(root, "check_unmeasured", f"run review suggestions: {exc}",
                        "review_run.py")
        return [], "No model pass: the gateway did not answer."

    by = f" (suggested by {answered[0]})" if answered else ""
    if not text.strip():
        return [], "No model pass: the model returned nothing."
    if text.strip().upper().startswith("NONE"):
        return [], f"The model pass found nothing to add{by}."

    # Negatives only, none restating a written criterion, and none made only
    # of what the sealed answer says.
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip().lstrip("*").strip()
        if not line:
            continue
        match = CRITERION_RE.match(line)
        if not match:
            continue
        weight, body = match.group(1), match.group(2)
        if not body or len(body) < 12:
            continue
        if _restates(body, written) or _against_the_answer(body, sealed_answer, traps):
            continue
        out.append(f"[{weight}] {body}")
        if len(out) >= MAX_SUGGESTED:
            break
    if not out:
        if looks_refused(text):
            return [], "No model pass: the model declined to read this run."
        return [], "The model pass returned nothing in the expected form."
    return out, (f"Suggested by {answered[0]}." if answered else "")


# --- the document -------------------------------------------------------------


def render(answer: str, findings: list[dict], suggested: list[str],
           run_steps: list[dict], produced: list[str] | None, job: Path,
           trajectory: Path, api_note: str, requests: list[dict] | None = None,
           lookups: list[dict] | None = None,
           unmatched: list[dict] | None = None,
           sealed: dict[str, str] | None = None,
           sealed_at_start: bool = True) -> str:
    lines: list[str] = []
    add = lines.append
    unmatched = unmatched or []
    sealed = sealed or {}

    made = ("no workspace collected" if produced is None
            else f"{len(produced)} file(s) produced")
    add("# What the solver did, and what to look at")
    add("")
    requests = requests or []
    lookups = lookups or []
    web = f", {len(requests)} web request(s)" if requests else ""
    add(f"Run `{job.name}`, {len(run_steps)} step(s), {made}{web}.")
    add("")
    # Above the count of findings, because it is not one of them: the rest of
    # this document is material for writing criteria, and there is no point
    # writing criteria against a run that has to be replaced.
    if lookups:
        values = ", ".join(sorted({h["value"] for h in lookups}, key=float))
        hosts = ", ".join(sorted({h for hit in lookups for h in hit["hosts"]}))
        add(f"> **This run is not deliverable.** It read {values} off "
            f"{hosts or 'the web'} rather than working it out from your "
            "files, and that is the figure your own ground truth gives as the "
            "answer.")
        add(">")
        add("> Block the site and run the solver again. Nothing you have "
            "written is at fault and none of it is lost -- your files, your "
            "prompt, your ground truth and your criteria all stand, and it is "
            "this run that gets replaced.")
        add(">")
        add("> ```")
        for host in sorted({h for hit in lookups for h in hit["hosts"]}) or ["the-site.com"]:
            add(f"> /flc-block-domain {host}")
        add("> /flc-run-solver")
        add("> ```")
        add("")
    strong = [f for f in findings if f["level"] == STRONG]
    if strong:
        add(f"**{len(strong)} thing(s) worth looking at first**, and "
            f"{len(findings) - len(strong)} more below.")
    elif findings:
        add(f"{len(findings)} thing(s) to check. None of them is conclusive on "
            "its own.")
    else:
        add("Nothing was flagged. That is not the same as nothing being wrong: "
            "read the answer against your ground truth, because the checks "
            "below only cover what can be found mechanically.")
    add("")
    add("This is a reading aid, not a verdict. Every item says what it was "
        "checked against so you can confirm it yourself. Nothing here has "
        "been written into your criteria.")
    add("")
    add("---")
    add("")

    # The answer written down before the run, beside the one the model gave.
    # No verdict on which is right: that is the contributor's reading, and the
    # score comes from /flc-grade once the criteria exist.
    add("## Your answer, as written down before this run")
    add("")
    if not sealed_at_start:
        add("_This run recorded no sealed answer, so this is the ground truth "
            "as it stands now._")
        add("")
    for key, name in (("answer", "The answer"),
                      ("derivation", "How it is derivable"),
                      ("unknowable", "What the model cannot know")):
        if sealed.get(key):
            add(f"**{name}**")
            add("")
            add("> " + sealed[key].replace("\n", "\n> "))
            add("")
    if not sealed:
        add("_Nothing was written down._")
        add("")

    add("## What it answered")
    add("")
    add("> " + answer.replace("\n", "\n> "))
    add("")
    add("Read the two side by side. Whether the model got there is your call; "
        "the score comes from /flc-grade once the criteria are written.")
    add("")

    add("## Worth checking")
    add("")
    if not findings:
        add("_Nothing was flagged mechanically._")
        add("")
    for item in sorted(findings, key=lambda f: ORDER[f["level"]]):
        add(f"### {item['title']}")
        add("")
        add(f"`{item['level']}`")
        add("")
        if item["claim"]:
            add("It said:")
            add("")
            add("> " + item["claim"].replace("\n", " "))
            add("")
        add(item["why"])
        add("")
        add(f"_Checked against: {item['evidence']}._")
        add("")
        if item["draft"]:
            add("If you decide this is a real mistake, a line for it might start as:")
            add("")
            add("```markdown")
            add(item["draft"])
            add("```")
            add("")
            add("Write the mistake rather than this sentence -- your task is "
                "re-run against a different model, and a criterion pinned to "
                "one exact wording catches nothing there.")
            add("")

    if unmatched:
        add("## What your criteria may not reach yet")
        add("")
        add("Each of these turns on a figure or a filename that none of your "
            "negative criteria mentions. That is a place to look rather than a "
            "list of criteria you are missing: a line describing the same "
            "mistake in words of its own is right, and this cannot see it.")
        add("")
        for item in unmatched:
            add(f"- **{item['subject']}** -- {item['title']}")
        add("")

    if suggested:
        add("## Also suggested by a model")
        add("")
        add("These came from a model reading the answer against your ground "
            "truth, so treat them with the suspicion this whole document is "
            "built on. Each one still has to be true of your task.")
        add("")
        for line in suggested:
            add(f"- {line}")
        add("")
        if api_note:
            add(f"_{api_note}_")
            add("")
    elif api_note:
        add(f"_{api_note}_")
        add("")

    add("## What it actually did")
    add("")
    add("<details>")
    add(f"<summary>{len(run_steps)} step(s) -- click to open</summary>")
    add("")
    for index, step in enumerate(run_steps, 1):
        add(f"**{index}. {step['speaker']}**")
        add("")
        for tool, arg, note, _ in step["tools"]:
            add(f"- `{tool}` {arg}".rstrip())
            if note:
                add(f"  - it said this was to: {note}")
        if step["tools"]:
            add("")
        if step["text"]:
            text = step["text"]
            if len(text) > STEP_TEXT_CHARS:
                text = text[:STEP_TEXT_CHARS] + f" ... [{len(step['text'])} chars]"
            add("> " + text.replace("\n", "\n> "))
            add("")
    add("</details>")
    add("")

    add("## Files it produced")
    add("")
    if produced is None:
        add("This run collected no copy of the workspace, so what the model "
            "wrote cannot be listed. **That is not the same as it having "
            "written nothing**, and no criterion should be written on the "
            "strength of this section. If it says it wrote something, look for "
            "the write in the steps above.")
    elif produced:
        for name in produced:
            add(f"- `{name}`")
    else:
        add("_None -- it answered without writing anything._")
    add("")

    add("## Where it went on the web")
    add("")
    if not requests:
        add("_Nothing. The model answered from your files alone._")
    else:
        add("Every request the run made to the internet. Browsing is part of "
            "the work, so most of this is ordinary -- what it is here for is "
            "the site you would block if you ran this again.")
        add("")
        for request in requests:
            where = ", ".join(request["hosts"]) or "(a search, no host)"
            add(f"- **{where}** via `{request['tool']}`")
            add(f"  - asked: {request['asked'][:160]}")
            if not request["paired"]:
                add("  - what came back could not be matched to this call, so "
                    "no figure has been attributed to it")
    add("")

    add("## What to do with this")
    add("")
    add("1. Confirm each item above against your own files. Some will be wrong.")
    add("2. Turn the ones that are real mistakes into `## Non-hallucination` "
        "lines in `tests/rubrics.md`, phrased as the mistake itself.")
    add("3. If your task is marked underspecified and the model filled the "
        "gap instead of asking, that is two lines under `## Clarification`: "
        "the question it should have asked, and the choice it made silently.")
    add("4. Leave your completion criteria alone. They come from your ground "
        "truth, which has not changed because of anything in this run.")
    add("")
    add(f"Full transcript: `{trajectory}`")
    add("")
    return "\n".join(lines)


# --- entry point --------------------------------------------------------------


def _unrun(name: str, exc: Exception) -> dict:
    """A check that failed to run, reported where its findings would have been."""
    return finding(
        WEAK, f"One check could not run: {name}", "",
        "This is a technical issue on our side, not in your task, and "
        "nothing you wrote needs to change. The rest of this document is "
        "complete, and the issue is noted for the project team "
        f"(`{type(exc).__name__}: {str(exc)[:160]}`).",
        "the check raised an error before it finished")


def _guarded(name: str, check, *args) -> list[dict]:
    try:
        return check(*args)
    except Exception as exc:  # noqa: BLE001
        return [_unrun(name, exc)]


def collect(root: Path, job: Path, trajectory: Path) -> tuple[
        str, list[dict], list[dict], list[str], list[str], list[dict], list[dict]]:
    answer = final_message(trajectory)
    gt = ground_truth_sections(root)
    workspace_text, unreadable = workspace_corpus(root)
    produced_text, produced = produced_corpus(job, root)
    transcript = trajectory_text(trajectory)
    observed = observed_text(trajectory, job)
    actions = actions_text(trajectory)

    # Where the model went, and whether the answer came back from there. The
    # figure has to be absent from everything else in the run, so the uploaded
    # files and what the model produced go in alongside the other tool results.
    requests, offline = browsing(trajectory, job)
    findings: list[dict] = []
    try:
        lookups = answer_lookup(gt, answer, requests,
                                "\n".join([offline, workspace_text, produced_text]))
    except Exception as exc:  # noqa: BLE001
        lookups = []
        findings.append(_unrun("whether the answer was read off the web", exc))

    findings += _guarded("the answer read off the web", check_answer_lookup, lookups)
    findings += _guarded("the block list", check_block_held, requests,
                         st.load(root).get("blocked_domains") or [])
    findings += _guarded("planted wrong answers", check_trap_hits, answer, gt)
    findings += _guarded("paths the answer names", check_missing_paths,
                         answer, root, produced, observed, actions)
    findings += _guarded("files the answer claims", check_claimed_files,
                         answer, produced, root, observed)
    findings += _guarded("files set as traps", check_trap_files, answer, gt, root)
    findings += _guarded("figures with no source", check_unsourced_numbers, answer, {
        "workspace": workspace_text,
        "produced": produced_text,
        "observed": observed,
        "actions": actions,
        "ground_truth": "\n".join(gt.values()),
    }, unreadable)
    findings += _guarded("contradicting the ground truth",
                         check_contradicts_ground_truth, answer, gt)
    findings += _guarded("checks the answer claims to have run",
                         check_claimed_actions, answer, transcript)
    return (answer, findings, steps(trajectory), produced, unreadable,
            requests, lookups)


def warn_if_submitted(root) -> None:
    """Say so when this has just rewritten a file that was already signed off.

    `/flc-submit` records a digest of `review/` as well as `delivery/`, and both
    are collected. These two commands only display a run, but they write the
    file they display, so re-reading a run after submitting puts the record out
    of step with what will be collected. The remedy is `/flc-submit` again, and
    it is printed here rather than left in a guide.
    """
    try:
        if "submit" in (st.load(root).get("steps_done") or []):
            print("  Note: you have already run /flc-submit, and this rewrote a "
                  "file in\n        review/. Run /flc-submit again so the record "
                  "matches what\n        gets collected.")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="a job directory (default: the last run)")
    ap.add_argument("--task", help="the task folder")
    ap.add_argument("--out", help="where to write the document")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print the document as well as writing it")
    ap.add_argument("--no-api", action="store_true",
                    help="skip the model pass, deterministic checks only")
    ap.add_argument("--quiet", action="store_true",
                    help="write the file and say one line about it")
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

    (answer, findings, run_steps, produced, _,
     requests, lookups) = collect(root, job, trajectory)
    if not answer:
        print(f"The transcript at {trajectory} has no final message from the "
              "agent.\nThe run may have been killed before it answered.",
              file=sys.stderr)
        return 2

    suggested, api_note = ([], "")
    if not args.no_api:
        suggested, api_note = suggest(root, answer, findings)

    at_start = st.run_record(st.load(root), job).get("sealed")
    document = render(answer, findings, suggested, run_steps, produced, job,
                      trajectory, api_note, requests, lookups,
                      uncovered(findings, negative_criteria(root)),
                      sealed=(at_start if isinstance(at_start, dict)
                              else st.sealed_sections(root)),
                      sealed_at_start=isinstance(at_start, dict))
    out = Path(args.out) if args.out else root / "review" / f"{job.name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document)

    if args.show:
        print(document)
    strong = sum(1 for f in findings if f["level"] == STRONG)
    if args.quiet:
        print(f"  review written: {out}  ({len(findings)} to check, {strong} strong)")
    else:
        print(f"\n  wrote {out}")
        print(f"  {len(findings)} thing(s) to check, {strong} of them strong")
        print("\n  Open it in the editor and press the preview button, or ask "
              "Claude Code to walk you through it.\n")
    warn_if_submitted(root)
    # Said on the terminal as well as in the document, because this one does
    # not wait to be read: everything after it is material for writing criteria
    # against a run that has to be replaced.
    if lookups:
        values = ", ".join(sorted({h["value"] for h in lookups}, key=float))
        hosts = sorted({h for hit in lookups for h in hit["hosts"]})
        print(f"  This run is not deliverable: it read {values} off "
              f"{', '.join(hosts) or 'the web'}")
        print("  rather than working it out from your files. Block the site "
              "and run again;")
        print("  nothing you have written is at fault and none of it is lost.")
        for host in hosts or ["the-site.com"]:
            print(f"    /flc-block-domain {host}")
        print("    /flc-run-solver")
    return 0


if __name__ == "__main__":
    sys.exit(main())
