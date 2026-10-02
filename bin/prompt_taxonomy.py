#!/usr/bin/env python3
"""Classifying how hard a task's prompt is, and what the verdict means.

This module holds the parts that must give the same answer wherever they run:
the question put to the model, the level scale, and the thresholds that turn
samples into a verdict. It reads no files and takes no command line. Callers
supply the prompt text and a way of reaching a model.

`prompt_difficulty.py` uses it against delivered tasks; `prompt_check.py` uses
it inside the sandbox against the prompt being written.
"""

from __future__ import annotations

import json
import re
import statistics
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

LEVELS = {
    1: ("Basic", "High School"),
    2: ("Fundamental", "Intro Undergraduate"),
    3: ("Intermediate", "Advanced Undergraduate"),
    4: ("Advanced", "Graduate Core"),
    5: ("Specialized", "Advanced Graduate"),
    6: ("Frontier", "Research-Level"),
}

DEFAULT_MIN_LEVEL = 4
DEFAULT_SAMPLES = 3
DEFAULT_HTTP_MODEL = "claude-opus-5-5"
# The models a check falls back through when one declines to read the request.
# Only a refusal moves a call down the list; every other failure is raised from
# the model that met it.
LADDER = (DEFAULT_HTTP_MODEL, "claude-opus-5", "gpt-5.6-sol")
MAX_TOKENS = 2000
ANTHROPIC_VERSION = "2023-06-01"

VERDICTS = ("no", "borderline", "yes")


# Every reviewer in this sandbox is a model whose training data ends before
# the task it is reading was written, and none of them used to be told so. A
# contributor cited a paper published this year, the reviewer read the year as
# being in the future, reported the citation as fabricated, and delivery
# refused a task that was correct. The DOI resolved.
#
# The failure is not about dates. It is that a model asked whether something
# is true will answer from what it has seen, and what it has not seen is
# indistinguishable to it from what does not exist. That is a property of
# every blocking gate here that judges content, so the correction belongs
# beside the transport they all share rather than in whichever one it bit
# first.
#
# Stated as what not to conclude rather than as "be careful", because the
# careful version is the one the model already thought it was following.
CUTOFF_NOTE = """\
Today is {today}, and your training data ends before it. That gap is the
normal case here and not a signal about the material: a paper, standard,
revision or dataset published after what you have seen is one you have not
seen, and nothing more follows from it.

So never report a fact as false, invented or impossible on the strength of not
recognising it, and never call a date a future date. You are not in a position
to know either. Where recognising something is what a judgement would need and
you do not recognise it, that judgement is one you cannot make -- leave it
alone rather than resolving it against the material.
"""


def cutoff_note(today: str | None = None) -> str:
    """What a reviewer has to be told about its own horizon.

    The date is read at call time rather than pinned, because a pinned one is
    wrong the day after it is written and wrong in the direction that caused
    this: a reviewer confidently working from a date that has passed.
    """
    return CUTOFF_NOTE.format(
        today=today or datetime.now(timezone.utc).date().isoformat())

# What makes the task hard, as against how hard it is. Recorded beside the
# level and never part of the verdict: two prompts can be the same level for
# entirely different reasons, and the level alone cannot say which.
HARDNESS = {
    "own_material": "reading the author's own data or results correctly",
    "convention": "conventions and controls the request leaves unstated",
    "literature": "command of a specialised or unsettled literature",
    "volume": "finding the relevant material among a great deal of it",
    "underspecified": "noticing that something needed was not supplied",
    "routine": "nothing field-specific; a documented method on standard material",
}


SYSTEM_PROMPT = """\
You classify the difficulty of research requests. You assess conceptual and
practical sophistication, never the amount of calculation.

What you are given is not an exam question. It is a research request written by
a working researcher and addressed to an AI agent, which will answer it against
a folder of the researcher's own material -- their data, their figures, their
manuscripts, their instrument output. You cannot see that material, and you
must not hold its absence against the request: a reference to a file you cannot
open is ordinary here. Judge the request as written.

You make four judgements about it.

FIRST, the comprehension. This is the one that decides the outcome. Could a
capable non-expert understand this request -- someone with a good general
education and a search engine, but no training in this field? The test is not
whether they could read the words, and not whether they could look the terms
up. It is whether they could state, in their own words, what is being asked and
what would count as having done it: what the request is for, which of the
things it names bear on the answer, and what a finished, correct response would
have to establish. Answer "no" if working that out requires domain expertise,
"yes" if a capable non-expert could arrive at it, and "borderline" if you
cannot tell.

Unfamiliar vocabulary is not by itself evidence, because a non-expert can look
a term up, and a request is not hard to understand merely because it is written
in the register of a field. What counts is whether the terms have to be
understood in relation to each other before the request means anything: whether
knowing what is being asked depends on knowing why these particular reagents,
instruments, controls, datasets or comparisons were named, and what follows
from them. Deep-sounding subject matter is not evidence. A request whose terms
are explained as though to a beginner, or which asks for a documented procedure
on a public dataset, or whose object is a lookup any careful reader could
verify, is one a non-expert can understand.

SECOND, the answer check. Could that same non-expert, shown a confident,
fluent, wrong answer to this request, tell that it was wrong? Answer "no",
"yes" or "borderline". Report this alongside the comprehension rather than
folding it in. The two can disagree, and a disagreement is worth seeing.

THIRD, the level. Which of these best describes the work the request asks for?
The levels are named after academic stages, but you are rating research work,
so the anchors below are what to apply.

1. Level 1 - Basic (High School): a single principle applied straightforwardly;
   a well-read layperson could reach the answer.
2. Level 2 - Fundamental (Intro Undergraduate): one or two introductory
   principles, moderate reasoning, nothing field-specific.
3. Level 3 - Intermediate (Advanced Undergraduate): standard, well-documented
   methods applied to a standard or public dataset. Someone competent in an
   adjacent quantitative field could carry it out after reading the method's
   documentation, and would know when they had it right.
4. Level 4 - Advanced (Graduate Core): needs the working knowledge of someone
   trained in this field. Typically: interpreting the author's own experimental
   data or instrument output, choosing between several readings of the same
   evidence, or applying conventions, controls and caveats that are written
   down nowhere in the request because a practitioner takes them for granted.
   Several field-specific principles have to be combined correctly.
5. Level 5 - Specialized (Advanced Graduate): needs command of a specialised
   literature, or original reasoning over the author's unpublished results, or
   resolving something the field has not settled for this case.
6. Level 6 - Frontier (Research-Level): frontier knowledge, an open problem, or
   concepts beyond any taught curriculum.

Two rules for choosing between them. If a request genuinely straddles two
levels, choose the lower one. But do not choose the lower level merely because
the individual techniques are routine -- running a PCR, reading a gel, fitting
a regression are all routine, and what sets the level is how much
field-specific judgement is needed to arrive at the right answer rather than a
plausible-looking one. Routine techniques applied to the author's own material,
where a non-practitioner would confidently reach a wrong conclusion, are
Level 4.

FOURTH, what makes it hard -- which is a different question from how hard it
is, and does not change the level. Two requests can sit at the same level for
entirely different reasons, and the level alone cannot say which. Pick the one
that most accounts for the difficulty, even where others apply:

- "own_material": it turns on reading the author's own experimental data,
  instrument output or unpublished results correctly.
- "convention": the method is documented, but arriving at the right answer
  needs conventions, controls or caveats a practitioner takes for granted and
  the request does not state.
- "literature": it turns on command of a specialised literature, or on
  something the field has not settled for this case.
- "volume": it turns on finding and reconciling the material that bears on the
  answer among a great deal that does not.
- "underspecified": it turns on noticing that something needed to answer was
  never supplied, and saying so rather than assuming.
- "routine": nothing field-specific; a documented method on standard material.

Do not attempt to answer the research question. Do not comment on whether the
request is clear, well-scoped or answerable -- a deliberately underspecified
request is a legitimate design here. Where the request does leave out something
needed, that is what "underspecified" records, and it is not a criticism.

Reply with a single JSON object and nothing else, in this shape:

{
  "reasoning": "a concise explanation of what understanding what is being asked \
takes, and what knowledge doing the work would need",
  "comprehension": "no" | "borderline" | "yes",
  "answer_check": "no" | "borderline" | "yes",
  "level": 1-6,
  "hardness": "own_material" | "convention" | "literature" | "volume" | \
"underspecified" | "routine",
  "expertise_markers": ["short quotes or terms from the request whose \
significance only a domain practitioner would grasp"],
  "generic_markers": ["short quotes or features a capable non-expert would \
understand unaided"],
  "field": "the field the request belongs to, in three words or fewer"
}
"""


class Unreachable(RuntimeError):
    """No model answered, so nothing was measured."""


class Refused(Unreachable):
    """The model declined to read the request, so nothing was measured."""


# Every phrase the judge reads a refusal off, plus the wordings it misses. The
# judge's own list is held inside this one by the selftest.
REFUSAL_SIGNS = (
    "can't help with this", "cannot help with this", "can't assist",
    "cannot assist", "unable to assist", "won't be able to help",
    "not able to provide", "can't provide", "cannot provide",
    "against my guidelines", "usage policies", "usage policy",
    "acceptable use policy", "content policy", "safety policy",
    "i must decline", "i can't engage", "cannot engage with",
    "flagged this message", "safeguards", "/legal/aup",
    "can't help with that", "cannot help with that", "i can't help",
    "i cannot help", "unable to help", "not able to help",
)

# What a gateway puts in the body of a request it filtered before any model
# read it.
_FILTERED_SIGNS = ("content_filter", "content filtering", "content management policy",
                   "responsibleaipolicyviolation")


def looks_refused(text: str) -> bool:
    """Whether a reply that came back whole reads as the model declining."""
    lowered = text.lower()
    return any(sign in lowered for sign in REFUSAL_SIGNS)


def parse_object(text: str) -> dict:
    """The first JSON object in a reply, whatever it is wrapped in."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start >= 0:
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:index + 1])
                    break
    for blob in candidates:
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("the reply carried no JSON object")


_USAGE_KEYS = {"input_tokens": "input_tokens", "output_tokens": "output_tokens",
               "cache_creation_input_tokens": "cache_write_tokens",
               "cache_read_input_tokens": "cache_read_tokens",
               "prompt_tokens": "input_tokens", "completion_tokens": "output_tokens"}


def _usage(data: dict) -> dict:
    """The token counts a reply reports, under one spelling whichever gateway sent it."""
    raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    out = {}
    for key, name in _USAGE_KEYS.items():
        value = raw.get(key)
        if isinstance(value, (int, float)):
            out[name] = out.get(name, 0) + int(value)
    cached = (raw.get("prompt_tokens_details") or {}).get("cached_tokens")
    if isinstance(cached, (int, float)):
        out["cache_read_tokens"] = out.get("cache_read_tokens", 0) + int(cached)
    return out


def call_http(prompt: str, model: str, key: str, base: str, shape: str,
              system: str = "", max_tokens: int = MAX_TOKENS, prefix: str = "",
              usage: list | None = None, thinking: int = 0) -> str:
    """One classification over HTTP, in the wire shape the caller names.

    `system` names the question being put, and defaults to this module's own.
    `prefix` is text sent ahead of `prompt` and shared between calls; on the
    Anthropic shape it is marked for the prompt cache, and a gateway that
    refuses the mark is asked once more without it. The model reads the same
    characters either way. `usage`, when given, receives the reply's token
    counts. `thinking`, on the Anthropic shape, is a budget of reasoning tokens
    before the reply; a gateway that refuses it is asked once more without.
    """
    system = system or SYSTEM_PROMPT
    if shape == "anthropic":
        url = f"{base}/v1/messages"
        content = ([{"type": "text", "text": prefix,
                     "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": prompt}] if prefix else prompt)
        payload = {"model": model, "max_tokens": max_tokens + thinking,
                   "system": system,
                   "messages": [{"role": "user", "content": content}]}
        if thinking:
            payload["thinking"] = {"type": "enabled", "budget_tokens": thinking}
        headers = {"content-type": "application/json", "x-api-key": key,
                   "authorization": f"Bearer {key}",
                   "anthropic-version": ANTHROPIC_VERSION}
    else:
        url = f"{base}/chat/completions"
        payload = {"model": model, "max_tokens": max_tokens,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": prefix + prompt}]}
        headers = {"content-type": "application/json",
                   "authorization": f"Bearer {key}"}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        if thinking and shape == "anthropic" and exc.code == 400 and "thinking" in body.lower():
            return call_http(prompt, model, key, base, shape, system, max_tokens,
                             prefix=prefix, usage=usage)
        if prefix and shape == "anthropic" and exc.code == 400 and "cache" in body.lower():
            return call_http(prefix + prompt, model, key, base, shape, system,
                             max_tokens, usage=usage, thinking=thinking)
        if exc.code == 400 and any(sign in body.lower() for sign in _FILTERED_SIGNS):
            raise Refused(f"the gateway's content filter declined it: {body[:200]}") from exc
        raise Unreachable(f"{url} answered {exc.code}: {body}") from exc
    except Exception as exc:
        raise Unreachable(f"{url} did not answer ({type(exc).__name__}: {exc})") from exc
    if usage is not None:
        usage.append(_usage(data))
    if shape == "anthropic":
        if data.get("stop_reason") == "refusal":
            raise Refused("the model declined to read it (stop_reason: refusal)")
        if data.get("stop_reason") == "max_tokens":
            raise Unreachable("the reply was cut off at max_tokens")
        return "".join(part.get("text", "") for part in data.get("content", [])
                       if part.get("type") == "text")
    choice = (data.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "content_filter":
        raise Refused("the model declined to read it (finish_reason: content_filter)")
    if choice.get("finish_reason") == "length":
        raise Unreachable("the reply was cut off at the token limit")
    return str((choice.get("message") or {}).get("content", ""))


def call_models(prompt: str, models, key: str, base: str, shape: str,
                answered: list | None = None, expect_json: bool = True,
                **kwargs) -> str:
    """One call, moved down `models` for as long as each one declines.

    `models` is a name or a sequence of names; a single name is one attempt.
    Only a refusal moves to the next model: an unreachable gateway, a rate
    limit or a reply cut off is raised from the model that met it. Where
    `expect_json` is set, a reply carrying no JSON that reads as a refusal
    counts as one. `answered`, when given, receives the model that replied.
    Other keyword arguments are passed to `call_http`.
    """
    names = [models] if isinstance(models, str) else [m for m in models if m]
    if not names:
        raise ValueError("no model to ask")
    refused = []
    for name in names:
        try:
            text = call_http(prompt, name, key, base, shape, **kwargs)
        except Refused as exc:
            refused.append(f"{name}: {exc}")
            continue
        if expect_json and "{" not in text and looks_refused(text):
            refused.append(f"{name}: the model declined to read it")
            continue
        if answered is not None:
            answered.append(name)
        return text
    raise Refused("every model declined to read it (" + "; ".join(refused) + ")")


def answered_by(names: list[str]) -> str:
    """The models that replied, in the order they first did, with counts when mixed."""
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    if len(counts) <= 1:
        return next(iter(counts), "")
    return ", ".join(f"{name} x{n}" for name, n in counts.items())


def fell_back(names: list[str], first: str = DEFAULT_HTTP_MODEL) -> bool:
    """Whether any reply came from a model other than the first one asked."""
    return any(name != first for name in names)


def _three_way(parsed: dict, key: str) -> str:
    value = str(parsed.get(key, "")).strip().lower()
    if value not in VERDICTS:
        raise ValueError(f"the reply gave no {key} verdict: {parsed.get(key)!r}")
    return value


def classify_once(prompt: str, send) -> dict:
    """One sample. `send(prompt)` returns the model's reply as text."""
    parsed = parse_object(send(prompt))
    level = parsed.get("level")
    if isinstance(level, str):
        found = re.search(r"[1-6]", level)
        level = int(found.group()) if found else None
    if level not in LEVELS:
        raise ValueError(f"the reply gave no level in 1-6: {parsed.get('level')!r}")
    comprehension = _three_way(parsed, "comprehension")
    # Older replies carry no answer_check. Its absence is recorded as unknown
    # rather than refusing the sample, since comprehension is what decides.
    try:
        answer_check = _three_way(parsed, "answer_check")
    except ValueError:
        answer_check = ""
    # Likewise the hardness facet: it is recorded rather than judged, so an
    # unrecognised value is dropped instead of costing the whole sample.
    hardness = str(parsed.get("hardness", "")).strip().lower()
    if hardness not in HARDNESS:
        hardness = ""
    return {"level": level, "comprehension": comprehension,
            "answer_check": answer_check, "hardness": hardness,
            "reasoning": str(parsed.get("reasoning", "")).strip(),
            "expertise_markers": [str(m) for m in parsed.get("expertise_markers") or []],
            "generic_markers": [str(m) for m in parsed.get("generic_markers") or []],
            "field": str(parsed.get("field", "")).strip()}


@dataclass
class Verdict:
    """What a set of samples came to."""
    samples: list[dict] = field(default_factory=list)
    level: int | None = None
    comprehension: str = ""
    answer_check: str = ""
    hardness: str = ""
    verdict: str = "UNMEASURED"
    why: str = ""
    agreement: str = ""
    model: str = ""

    @property
    def clears(self) -> bool:
        return self.verdict in ("PASS", "WARN")

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "model": self.model,
                "level": self.level, "comprehension": self.comprehension,
                "answer_check": self.answer_check,
                "hardness": self.hardness,
                "hardness_why": HARDNESS.get(self.hardness, ""),
                "agreement": self.agreement, "why": self.why,
                "field": self.samples[0]["field"] if self.samples else "",
                "samples": self.samples}


def judge(result: Verdict, min_level: int = DEFAULT_MIN_LEVEL) -> Verdict:
    """The verdict the signals come to together.

    Comprehension is the bar and is the only thing that refuses on its own. The
    level is a second opinion: at the bar exactly it warns rather than refuses.
    The answer check is recorded and never decides. WARN clears; FAIL does not.
    """
    levels = [s["level"] for s in result.samples]
    votes = [s["comprehension"] for s in result.samples]
    checks = [s.get("answer_check") for s in result.samples if s.get("answer_check")]
    kinds = [s.get("hardness") for s in result.samples if s.get("hardness")]
    result.level = int(statistics.median_low(sorted(levels)))
    result.comprehension = max(set(votes), key=votes.count)
    result.answer_check = max(set(checks), key=checks.count) if checks else ""
    result.hardness = max(set(kinds), key=kinds.count) if kinds else ""
    spread = f"{min(levels)}-{max(levels)}" if min(levels) != max(levels) else "unanimous"
    count = len(result.samples)
    result.agreement = (f"{count} sample{'' if count == 1 else 's'}, levels "
                        f"{spread}, comprehension {'/'.join(sorted(set(votes)))}")
    if len(set(kinds)) > 1:
        result.agreement += f", what makes it hard {'/'.join(sorted(set(kinds)))}"
    if min(levels) < min_level <= max(levels):
        result.agreement += " -- the samples straddle the bar"

    named = f"Level {result.level} ({LEVELS[result.level][0]})"
    if result.comprehension == "yes":
        result.verdict = "FAIL"
        result.why = ("a non-expert could work out what this prompt is asking "
                      "and what would count as having answered it, which is the "
                      "bar it has to clear")
        if result.answer_check == "no":
            result.why += (" -- though they could not tell a wrong answer from a "
                           "right one, so this is worth a second look")
    elif result.level < min_level:
        result.verdict = "FAIL"
        result.why = (f"the work is {named}, below the Level {min_level} bar")
        if result.comprehension == "no":
            result.why += (", though understanding what it asks does take an "
                           "expert -- worth a second look before dropping it")
    elif result.level == min_level:
        result.verdict = "WARN"
        result.why = (f"{named} work, at the bar rather than above it")
        if result.comprehension == "borderline":
            result.why += (", and it is not clear that understanding what it "
                           "asks needs an expert")
    elif result.comprehension == "borderline":
        result.verdict = "WARN"
        result.why = ("the work is deep enough, but it is not clear that "
                      "understanding what the prompt asks needs an expert")
    else:
        result.verdict = "PASS"
        result.why = (f"{named} work, and understanding what it asks takes an "
                      "expert")
    return result


def collect(prompt: str, send, samples: int = DEFAULT_SAMPLES,
            min_level: int = DEFAULT_MIN_LEVEL, model: str = "") -> Verdict:
    """Take `samples` classifications and judge them together.

    Returns an UNMEASURED verdict carrying the reason when nothing answered,
    which is never the same as a prompt that was measured and failed.
    """
    result = Verdict(model=model)
    if not prompt.strip():
        result.why = "the prompt is empty"
        return result
    problems = []
    for _ in range(samples):
        try:
            result.samples.append(classify_once(prompt, send))
        except (Refused, ValueError) as exc:
            problems.append(str(exc))
        except Unreachable as exc:
            problems.append(str(exc))
            break
    if not result.samples:
        result.why = "; ".join(problems) or "nothing answered"
        return result
    judge(result, min_level)
    if len(result.samples) < samples:
        result.agreement += f" ({samples} asked for: {'; '.join(problems)})"
    if model:
        result.agreement += f", {model}"
    return result
