#!/usr/bin/env python3
"""Statements that something in a task is inaccurate, and the blind vote on them.

A reading that finds something in the task inaccurate -- a wrong value, a wrong
statement, a misattribution, a wrong reference, a contradiction, an overstated
claim or reasoning that does not hold -- writes it out as a statement: the words,
where they are, what is wrong and the check that settles it. It counts only once
three more models, one from each of three model families, each find it
inaccurate on their own. The definitions and what a voter is told are exported
into review_spec/.

The vote is blind. A voter is shown where each statement is and its words, and
the task's material, and nothing else: not the reading's verdict, kind,
reasoning or check, and not the other votes. The flagged statements are mixed
with statements the same reading checked and found accurate, shuffled with a
recorded seed.

This module reads no task files and reaches no model on its own. Callers supply
the task's text and a way to run one voter on one model.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from prompt_taxonomy import Refused, Unreachable, cutoff_note, parse_object

SPEC_DIR = Path(__file__).resolve().parent / "review_spec"

KINDS = ("value", "statement", "misattribution", "reference", "contradiction",
         "overstated", "reasoning")
READINGS = ("inaccurate", "accurate")
VOTES = ("accurate", "inaccurate", "cannot_tell")
HIGH = "high"

GROUND_TRUTH = "ground truth"
JUSTIFICATION = "justification"
PROMPT = "prompt"
ANSWER = "answer"

# Each slot runs on the first model of its chain the gateway offers and that
# answers, and moves down the chain on a refusal as well as on a failure. Once
# the chain is used up, any other listed model of the slot's own families.
SLOTS: dict[str, tuple[str, ...]] = {
    "fable": ("anthropic/claude-fable-5-1", "gemini/gemini-3.8-flash",
              "gemini/gemini-flash-latest", "gemini/gemini-3.7-flash",
              "anthropic/claude-fable-5"),
    "opus": ("anthropic/claude-opus-5-5", "anthropic/claude-opus-5"),
    "gpt": ("openai/gpt-5.6-sol", "openai/gpt-6.1-sol"),
}
SLOT_FAMILIES = {"fable": ("claude-fable", "gemini"), "opus": ("claude-opus",),
                 "gpt": ("gpt",)}
VOTE_MODELS_ENV = "FLC_VOTE_MODELS"

MAX_TOKENS = 8000

VOTER_SYSTEM = (
    "You check statements made in one research task's material, against that "
    "material. You work alone. Reply in the shape you are asked for, and "
    "nothing else.")


def _load(name: str) -> str:
    try:
        return (SPEC_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def contract_text() -> str:
    """What an inaccuracy is, the bar for filing one, and what bears_on holds."""
    return _load("statements.md").strip()


def voter_text() -> str:
    """What a voter is told about checking a statement."""
    return _load("vote.md").strip()


def checks_text() -> str:
    """The two checks a statement's words do not suggest, as a voter is told them.

    Given to the readings that file statements as well, with what follows for
    filing: a cause that fails its test is an inaccuracy in its own right.
    """
    found = next((p for p in voter_text().split("\n\n")
                  if p.startswith("Two kinds of statement")), "")
    if not found:
        return ""
    return (found + " A stated cause, mechanism or condition that fails that test is "
            "an inaccuracy of kind reasoning, and it meets the bar once the test is "
            "run and its numbers given, even where whether the conclusion is right "
            "would take a judgement: file the cause as the statement, and leave the "
            "judgement about the conclusion in notes.")


def _source_version() -> str:
    try:
        source = json.loads(_load("SOURCE.json") or "{}")
    except ValueError:
        source = {}
    return str(source.get("ballot_version") or "")


# A vote cast under other instructions is stale rather than counted beside
# votes cast under these.
BALLOT_VERSION = (_source_version() + "-"
                  + hashlib.sha256((voter_text() + VOTER_SYSTEM).encode()).hexdigest()[:12])


def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    for dash in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212":
        text = text.replace(dash, "-")
    for quote in "\u2018\u2019\u201c\u201d":
        text = text.replace(quote, "'")
    return " ".join(text.split()).lower()


def quoted(claim: str, source: str) -> bool:
    """Whether a quotation is in the text it is attributed to.

    Long quotations are matched on their opening words, as the rubric review
    matches them: a copied sentence with one comma normalised is still quoted.
    """
    want, have = _norm(claim).strip("\"'"), _norm(source)
    if not want or not have:
        return False
    if want in have:
        return True
    words = want.split()
    return len(words) > 6 and " ".join(words[:6]) in have


# --- families and slots ---------------------------------------------------------


def bare(model: str) -> str:
    """The model's name without its provider prefix."""
    return str(model or "").strip().rsplit("/", 1)[-1]


def family(model: str) -> str:
    """Which family a model belongs to: two versions of one model are one family."""
    name = re.sub(r"\[.*\]$", "", bare(model).lower())
    name = re.sub(r"-\d{8}$", "", name)
    if name.startswith("claude-"):
        return "-".join(name.split("-")[:2])
    if "gemini" in name:
        return "gemini"
    if name.startswith("gpt"):
        return "gpt"
    return name.split("-")[0]


def spellings(model: str) -> list[str]:
    out = [str(model).strip()]
    if bare(model) != out[0]:
        out.append(bare(model))
    return out


def chains() -> dict[str, tuple[str, ...]]:
    """The slots' chains: SLOTS, or FLC_VOTE_MODELS as `fable=a,b;opus=c;gpt=d`."""
    raw = os.environ.get(VOTE_MODELS_ENV, "").strip()
    if not raw:
        return dict(SLOTS)
    out = dict(SLOTS)
    for part in raw.split(";"):
        slot, _, names = part.partition("=")
        slot = slot.strip()
        listed = tuple(n.strip() for n in names.split(",") if n.strip())
        if slot in SLOTS and listed:
            out[slot] = listed
    return out


def candidates(slot: str, listed: list[str] | None,
               chain: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """The models a slot tries, in order.

    With the gateway's list, the chain's names it offers, under the spelling it
    offers them in, then any other listed model of the slot's families. With no
    list, every spelling of every name in the chain.
    """
    names = (chain or chains())[slot]
    if listed is None:
        out = []
        for name in names:
            out += [s for s in spellings(name) if s not in out]
        return out
    offered = {m.lower(): m for m in listed}
    out = []
    for name in names:
        hit = next((offered[s.lower()] for s in spellings(name) if s.lower() in offered), None)
        if hit and hit not in out:
            out.append(hit)
    extra = sorted((m for m in listed if family(m) in SLOT_FAMILIES.get(slot, ())
                    and m not in out), reverse=True)
    return out + extra


def list_models(key: str, base: str, timeout: int = 20) -> list[str] | None:
    """The models this key can reach, as the gateway lists them, or None if it will not say."""
    base = base.rstrip("/")
    urls = [f"{base}/v1/models", f"{base}/models"] if not base.endswith("/v1") \
        else [f"{base}/models"]
    for url in urls:
        request = urllib.request.Request(url, headers={
            "authorization": f"Bearer {key}", "x-api-key": key})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read())
        except Exception:  # noqa: BLE001 -- a gateway that will not list is not an error here
            continue
        rows = data.get("data") if isinstance(data, dict) else data
        names = [str(r.get("id")) for r in rows or [] if isinstance(r, dict) and r.get("id")]
        if names:
            return names
    return None


# --- statements -------------------------------------------------------------------


@dataclass
class Statement:
    """One statement a reading checked, and what became of it."""
    file: str
    quote: str
    reading: str
    kind: str = ""
    what_is_wrong: str = ""
    check: str = ""
    confidence: str = ""
    bears_on: list[str] = field(default_factory=list)
    source: str = ""
    votes: dict = field(default_factory=dict)
    confirmed: bool | None = None

    @property
    def ident(self) -> str:
        return hashlib.sha256(f"{_norm(self.file)}|{_norm(self.quote)}".encode()).hexdigest()[:16]

    @property
    def flagged(self) -> bool:
        """Inaccurate, settled by a check, and held with high confidence."""
        return (self.reading == "inaccurate" and self.confidence == HIGH
                and bool(self.check.strip()) and bool(self.what_is_wrong.strip()))

    @property
    def in_ground_truth(self) -> bool:
        return self.file == GROUND_TRUTH

    @property
    def rests(self) -> list[str]:
        """What graded rests on it: a criterion, a test or the justification."""
        return [b for b in self.bears_on if not b.startswith(ANSWER)]

    def where(self) -> str:
        if self.file == GROUND_TRUTH:
            return "the author's answer"
        if self.file == JUSTIFICATION:
            return "the justification"
        if self.file == PROMPT:
            return "the prompt"
        if self.file == ANSWER:
            return "the run's answer"
        if self.file.startswith("criterion "):
            return f"{self.file} of the rubric"
        if self.file.startswith("test "):
            return f"the unit {self.file}"
        return f"the file {self.file}"

    def as_dict(self) -> dict:
        return {"id": self.ident, "file": self.file, "where": self.where(),
                "quote": self.quote, "reading": self.reading, "kind": self.kind,
                "what_is_wrong": self.what_is_wrong, "check": self.check,
                "confidence": self.confidence, "bears_on": list(self.bears_on),
                "source": self.source, "flagged": self.flagged,
                "votes": dict(self.votes), "confirmed": self.confirmed}

    @classmethod
    def from_dict(cls, data: dict) -> "Statement":
        return cls(file=str(data.get("file") or ""), quote=str(data.get("quote") or ""),
                   reading=str(data.get("reading") or ""), kind=str(data.get("kind") or ""),
                   what_is_wrong=str(data.get("what_is_wrong") or ""),
                   check=str(data.get("check") or ""),
                   confidence=str(data.get("confidence") or ""),
                   bears_on=[str(b) for b in data.get("bears_on") or []],
                   source=str(data.get("source") or ""),
                   votes=dict(data.get("votes") or {}), confirmed=data.get("confirmed"))


def _criterion_ref(value, criteria: list[dict]) -> str:
    """"criterion N" for a number, "criterion 12", or a criterion's own words."""
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:criterion|line|#)?\s*(\d+)", text, re.I)
    if match:
        n = int(match.group(1))
        return f"criterion {n}" if 1 <= n <= len(criteria) else ""
    if len(_norm(text)) < 15:
        return ""
    for index, crit in enumerate(criteria, 1):
        if quoted(text, crit.get("text", "")) or quoted(crit.get("text", ""), text):
            return f"criterion {index}"
    return ""


def _where(value, criteria: list[dict], tests: list[str], workspace: list[str]) -> str:
    """The file a statement is in, in the one spelling the record keeps."""
    text = str(value or "").strip().strip("`")
    low = _norm(text)
    if low in ("ground truth", "the ground truth", "the author's answer", "author's answer",
               "solution/ground_truth.md", "authoring/ground_truth.md", "ground_truth.md"):
        return GROUND_TRUTH
    if "justification" in low:
        return JUSTIFICATION
    if low in ("prompt", "the prompt", "prompt.md", "instruction.md", "bundle/instruction.md"):
        return PROMPT
    if low in ("answer", "the answer", "the run's answer", "the graded run's answer"):
        return ANSWER
    if low.startswith(("criterion", "line", "#")) or low.isdigit():
        return _criterion_ref(text, criteria)
    if low.startswith("test "):
        name = text.split(None, 1)[1].strip()
        return f"test {name}" if name in tests else ""
    if text in tests:
        return f"test {text}"
    rel = text.removeprefix("/workspace/").removeprefix("environment/workspace/") \
        .removeprefix("bundle/environment/workspace/")
    return rel if rel in workspace else ""


def _bears(value, criteria: list[dict], tests: list[str]) -> str:
    text = str(value or "").strip()
    low = _norm(text)
    if not low:
        return ""
    if "justification" in low:
        return JUSTIFICATION
    if low in ("answer", "the answer", "the run's answer") or low.startswith("the run's answer"):
        return ANSWER
    if low.startswith("test "):
        name = text.split(None, 1)[1].strip()
        return f"test {name}" if name in tests else ""
    if text in tests:
        return f"test {text}"
    return _criterion_ref(text, criteria)


def read_statements(parsed: dict, source: str, texts: dict[str, str],
                    criteria: list[dict], tests: list[str] | None = None,
                    workspace: list[str] | None = None, read_file=None
                    ) -> tuple[list[Statement], list[str]]:
    """The statements in one reply that can be held to their words, and what was dropped.

    `texts` carries the text of the ground truth, the justification, the prompt,
    the answer and the workspace extracts, under GROUND_TRUTH, JUSTIFICATION,
    PROMPT, ANSWER and "workspace". A quotation that is not in the text it is
    attributed to drops the statement: a statement nobody can find is not one
    anybody can check. `read_file(path)`, where given, reads a workspace file
    whole for that test.
    """
    tests, workspace = list(tests or []), list(workspace or [])
    kept, dropped = [], []
    for raw in parsed.get("statements") or [] if isinstance(parsed, dict) else []:
        if not isinstance(raw, dict):
            continue
        reading = _norm(raw.get("reading"))
        if reading not in READINGS:
            dropped.append(f"statement {raw.get('id')!r}: no reading")
            continue
        where = _where(raw.get("file"), criteria, tests, workspace)
        quote = str(raw.get("quote") or "").strip().strip('"\u201c\u201d')
        if not where or not quote:
            dropped.append(f"statement {raw.get('id')!r}: not somewhere in this task")
            continue
        if where.startswith("criterion "):
            text = criteria[int(where.split()[1]) - 1].get("text", "")
        elif where.startswith("test "):
            text = texts.get("tests", "")
        elif where in (GROUND_TRUTH, JUSTIFICATION, PROMPT, ANSWER):
            text = texts.get(where, "")
        else:
            text = texts.get("workspace", "")
            if not quoted(quote, text) and read_file is not None:
                try:
                    text = read_file(where) or ""
                except Exception:  # noqa: BLE001 -- an unreadable file is not a quote found
                    text = ""
        if not quoted(quote, text):
            dropped.append(f"statement {raw.get('id')!r}: its words are not in {where}")
            continue
        kind = _norm(raw.get("kind"))
        bears = raw.get("bears_on")
        bears = bears if isinstance(bears, list) else ([bears] if bears else [])
        resolved = []
        for entry in bears:
            ref = _bears(entry, criteria, tests)
            if ref and ref not in resolved:
                resolved.append(ref)
            elif not ref:
                dropped.append(f"statement {raw.get('id')!r}: bears_on {str(entry)[:60]!r} "
                               "is nothing graded in this task")
        kept.append(Statement(
            file=where, quote=quote, reading=reading,
            kind=kind if kind in KINDS else ("statement" if reading == "inaccurate" else ""),
            what_is_wrong=str(raw.get("what_is_wrong") or "").strip(),
            check=str(raw.get("check") or "").strip(),
            confidence=_norm(raw.get("confidence")),
            bears_on=resolved, source=source))
    return kept, dropped


def ids(parsed: dict, statements: list[Statement]) -> dict[str, str]:
    """The reply's own statement ids, mapped to the identity the record keeps."""
    out = {}
    raws = [r for r in (parsed.get("statements") or []) if isinstance(r, dict)]
    for raw in raws:
        quote = _norm(str(raw.get("quote") or "").strip().strip('"\u201c\u201d'))
        match = next((s for s in statements if _norm(s.quote) == quote), None)
        if match is not None and str(raw.get("id") or "").strip():
            out[str(raw["id"]).strip()] = match.ident
    return out


def merge(*lists: list[Statement]) -> list[Statement]:
    """One list, one entry per statement. A flagged reading wins over a cleared one."""
    merged: dict[str, Statement] = {}
    for batch in lists:
        for s in batch:
            held = merged.get(s.ident)
            if held is None or (s.flagged and not held.flagged):
                if held is not None:
                    s.bears_on = list(dict.fromkeys(s.bears_on + held.bears_on))
                merged[s.ident] = s
            else:
                held.bears_on = list(dict.fromkeys(held.bears_on + s.bears_on))
    return list(merged.values())


# --- the ballot -------------------------------------------------------------------


def ballot(flagged: list[Statement], cleared: list[Statement], seed_basis: str = ""
           ) -> tuple[list[dict], dict]:
    """(what a voter is shown, the key to it): flagged and cleared, shuffled.

    As many cleared statements as flagged ones, and at least one where any was
    cleared. The seed is recorded, so the same ballot comes out the same way.
    """
    decoys = [s for s in cleared if s.ident not in {f.ident for f in flagged}]
    decoys = decoys[:max(1, len(flagged))]
    pool = [(s, True) for s in flagged] + [(s, False) for s in decoys]
    digest = hashlib.sha256(json.dumps(
        [BALLOT_VERSION, [[_norm(s.file), _norm(s.quote), f] for s, f in pool]],
        ensure_ascii=False).encode()).hexdigest()
    seed = int(hashlib.sha256(f"{seed_basis}\0{digest}".encode()).hexdigest()[:12], 16)
    order = list(range(len(pool)))
    random.Random(seed).shuffle(order)
    items, key = [], {}
    for n, i in enumerate(order, 1):
        s, is_flagged = pool[i]
        vid = f"v{n}"
        items.append({"id": vid, "where": s.where(), "quote": s.quote})
        key[vid] = {"statement": s.ident, "flagged": is_flagged}
    return items, {"digest": digest, "seed": seed, "version": BALLOT_VERSION, "items": key}


def voter_message(items: list[dict]) -> str:
    """What one voter is asked, after the material: the statements and nothing about why."""
    listed = "\n".join(f"{i['id']}. In {i['where']}: \u201c{i['quote']}\u201d" for i in items)
    return "\n\n".join([
        voter_text(),
        "The task's material is above: the prompt, the author's answer, the "
        "justification, the criteria, the run's answer and extracts of the "
        "files. Where you can run Python, the task's files are there whole; "
        "recompute from them rather than from the extracts.",
        f"Statements:\n{listed}",
        "Reply with a single JSON object and nothing else:\n"
        '{"votes": [{"id": "v1", "verdict": "accurate | inaccurate | cannot_tell", '
        '"check": "what you checked and what it gave, with the numbers"}]}\n'
        "One row for every statement above, by its id.",
    ])


def voter_system() -> str:
    return cutoff_note() + "\n" + VOTER_SYSTEM


def parse_votes(text: str, wanted: list[str]) -> dict[str, dict]:
    """A voter's reply, one row per ballot id; an id left out is cannot_tell."""
    parsed = parse_object(text)
    rows = parsed.get("votes")
    if not isinstance(rows, list):
        raise ValueError("the reply carried no votes")
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        vid = str(row.get("id") or "").strip()
        verdict = _norm(row.get("verdict")).replace(" ", "_")
        if vid in wanted:
            out[vid] = {"verdict": verdict if verdict in VOTES else "cannot_tell",
                        "check": str(row.get("check") or "").strip()[:600]}
    if not out:
        raise ValueError("the reply voted on none of the statements")
    for vid in wanted:
        out.setdefault(vid, {"verdict": "cannot_tell", "check": "no row was given"})
    return out


# --- the vote ---------------------------------------------------------------------


def cast(slot: str, names: list[str], run, wanted: list[str], used: set[str],
         lock: threading.Lock) -> dict:
    """One slot's vote: the first model down its list that answers.

    A refusal, a failure and a reply that is not a vote all move to the next
    model. A model of a family another slot is already voting with is passed
    over. A slot that runs out abstains, and an abstention confirms nothing.
    """
    tried = []
    for name in names:
        fam = family(name)
        with lock:
            if fam in used:
                tried.append({"model": name, "why": "its family is already voting"})
                continue
            used.add(fam)
        try:
            votes = parse_votes(run(name), wanted)
        except (Refused, Unreachable, ValueError) as exc:
            with lock:
                used.discard(fam)
            kind = "refused" if isinstance(exc, Refused) else \
                "failed" if isinstance(exc, Unreachable) else "unreadable"
            tried.append({"model": name, "why": f"{kind}: {str(exc)[:200]}"})
            continue
        return {"slot": slot, "model": name, "votes": votes, "tried": tried,
                "abstained": False}
    return {"slot": slot, "model": "", "abstained": True, "tried": tried,
            "votes": {vid: {"verdict": "cannot_tell", "check": "the slot abstained"}
                      for vid in wanted}}


def vote(statements: list[Statement], run_voter, listed: list[str] | None = None,
         seed_basis: str = "", chain: dict[str, tuple[str, ...]] | None = None,
         parallel: bool = True) -> dict:
    """Put every flagged statement to the slots, blind, and record what they said.

    `run_voter(model, message)` runs one voter and returns its reply. Sets each
    flagged statement's votes and whether it is confirmed: every slot answered
    and every one found it inaccurate. Returns the ballot, the key and each
    slot's result, for the record.
    """
    flagged = [s for s in statements if s.flagged]
    cleared = [s for s in statements if s.reading == "accurate"]
    for s in statements:
        if not s.flagged:
            s.confirmed, s.votes = None, {}
    if not flagged:
        return {"asked": False}
    items, key = ballot(flagged, cleared, seed_basis)
    message = voter_message(items)
    wanted = [i["id"] for i in items]
    used: set[str] = set()
    lock = threading.Lock()
    slots = list((chain or chains()).keys())

    def one(slot: str) -> dict:
        return cast(slot, candidates(slot, listed, chain), lambda m: run_voter(m, message),
                    wanted, used, lock)

    if parallel and len(slots) > 1:
        with ThreadPoolExecutor(max_workers=len(slots)) as pool:
            results = list(pool.map(one, slots))
    else:
        results = [one(slot) for slot in slots]
    by_ident = {s.ident: s for s in flagged}
    for vid, entry in key["items"].items():
        s = by_ident.get(entry["statement"])
        if s is None or not entry["flagged"]:
            continue
        s.votes = {r["slot"]: {"model": r["model"], **r["votes"][vid]} for r in results}
        s.confirmed = (len(results) == len(slots)
                       and all(not r["abstained"] and r["votes"][vid]["verdict"] == "inaccurate"
                               for r in results))
    return {"asked": True, "version": BALLOT_VERSION, "digest": key["digest"],
            "seed": key["seed"], "items": key["items"], "listed": listed is not None,
            "slots": {r["slot"]: {"model": r["model"], "abstained": r["abstained"],
                                  "tried": r["tried"]} for r in results},
            "decoys_called_inaccurate": sum(
                1 for vid, e in key["items"].items() if not e["flagged"]
                for r in results if r["votes"][vid]["verdict"] == "inaccurate")}


# --- what the confirmed statements come to ---------------------------------------


def still_in(statement: Statement | dict, ground_truth: str) -> bool:
    quote = statement.quote if isinstance(statement, Statement) else statement.get("quote", "")
    return quoted(quote, ground_truth)


def consistency(statements: list[Statement | dict], ground_truth: str | None = None) -> dict:
    """Whether the author's answer holds a confirmed inaccuracy graded material rests on.

    FAIL where something graded repeats one, WARN where nothing does, PASS
    otherwise. With `ground_truth`, a statement no longer in it has been fixed
    and is left out.
    """
    rows = [s if isinstance(s, Statement) else Statement.from_dict(s) for s in statements]
    found = [s for s in rows if s.in_ground_truth and s.confirmed
             and (ground_truth is None or still_in(s, ground_truth))]
    seen, unique = set(), []
    for s in found:
        if s.ident not in seen:
            seen.add(s.ident)
            unique.append(s)
    resting = [s for s in unique if s.rests]
    verdict = "FAIL" if resting else "WARN" if unique else "PASS"
    return {"verdict": verdict, "resting": [s.as_dict() for s in resting],
            "unresting": [s.as_dict() for s in unique if not s.rests]}
