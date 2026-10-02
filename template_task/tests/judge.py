# /// script
# dependencies = [
#   "openai>=1.0.0",
# ]
# ///
"""Score a model's answer against rubrics.json with an LLM judge.

Each criterion is judged in its own call, against the agent's answer, its
trajectory and the files it produced.

Reads:   /logs/agent/answer.txt, /logs/agent/trajectory.json (optional),
         /tests/rubrics.json, /tests/prompt.txt, /tests/system_prompt.txt,
         /tests/user_prompt_template.txt
Writes:  /logs/verifier/evaluation_results.json
Needs:   EVAL_API_KEY, EVAL_BASE_URL, EVAL_MODEL
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
import time
from typing import Any, Optional

from openai import OpenAI

ANSWER_PATH = os.environ.get("FLC_ANSWER", "/logs/agent/answer.txt")
TRAJECTORY_PATH = os.environ.get("FLC_TRAJECTORY", "/logs/agent/trajectory.json")
RUBRICS_PATH = "/tests/rubrics.json"
INPUTS_MANIFEST_PATH = "/tests/inputs_manifest.json"
PROMPT_PATH = "/tests/prompt.txt"
SYSTEM_PROMPT_PATH = "/tests/system_prompt.txt"
USER_PROMPT_TEMPLATE_PATH = "/tests/user_prompt_template.txt"
RESULTS_PATH = "/logs/verifier/evaluation_results.json"

MAX_RETRIES = 8
# An endpoint that has never answered gets this budget instead of the full one.
CONNECT_RETRIES = 2
# A criterion the model declines to judge gets this budget. The refusal is not
# reliably reproducible, so a retry is worth taking and a full ladder is not.
REFUSAL_RETRIES = 3
EXIT_UNREACHABLE = 3
MAX_TOKENS = 2048
# The part of the prompt every criterion shares is offered to the gateway's
# prompt cache. A shared part shorter than this is sent without a breakpoint.
CACHE_MIN_CHARS = 4000
# Set False for the rest of the run when a gateway turns the breakpoint down.
CACHE_ENABLED = True
# What each call was served from the cache, where the gateway reports it.
CACHE_READS: list[int] = []
TRAJECTORY_CHAR_BUDGET = 120_000
# What one step's tool result is shortened to before the transcript is measured
# against that budget. Halved towards the floor until the whole transcript fits.
STEP_OBSERVATION_CHAR_CAP = 10_000
STEP_OBSERVATION_CHAR_FLOOR = 400
# Per-step harness bookkeeping, dropped before the transcript is measured.
STEP_DROPPED_FIELDS = ("metrics",)
OUTPUT_CHAR_BUDGET = 30_000

# Encoded images in the transcript, dropped before it goes to the judge.
_B64_BLOB = re.compile(r'[A-Za-z0-9+/=]{2000,}')

_NUMBERING = re.compile(r"^\d+(\.\d+)*:\s*")


def _criterion(rubric: dict[str, Any]) -> str:
    """The criterion text. `title` is the older spelling of `criteria`."""
    text = rubric.get("criteria") or rubric.get("title") or ""
    return _NUMBERING.sub("", str(text)).strip()


def _rubric_id(rubric: dict[str, Any]) -> str:
    """A hash of the criterion text, so it is stable across rebuilds."""
    return hashlib.md5(_criterion(rubric).encode("utf-8")).hexdigest()


def _normalize_status(value: Any) -> Optional[str]:
    if value is None:
        return None
    status = str(value).strip().upper()
    if status in {"YES", "Y", "TRUE", "1"}:
        return "YES"
    if status in {"NO", "N", "FALSE", "0"}:
        return "NO"
    return None


def _normalize_score(value: Any) -> Optional[str]:
    if value is None:
        return None
    score = str(value).strip()
    if score in {"1", "1.0"}:
        return "1"
    if score in {"0", "0.0"}:
        return "0"
    lowered = score.lower()
    if lowered in {"yes", "true"}:
        return "1"
    if lowered in {"no", "false"}:
        return "0"
    return None


def _score_from_status(status: Optional[str]) -> Optional[str]:
    if status == "YES":
        return "1"
    if status == "NO":
        return "0"
    return None


def _canonicalize_judge_result(parsed: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return None

    judge_score = {
        "rubric_statement": parsed.get("rubric_statement"),
        "status": parsed.get("status"),
        "score": parsed.get("score"),
        "justification": parsed.get("justification"),
    }

    normalized_status = _normalize_status(judge_score.get("status"))
    normalized_score = _normalize_score(judge_score.get("score"))
    status_score = _score_from_status(normalized_status)

    mismatch = (
        normalized_status is not None
        and normalized_score is not None
        and status_score != normalized_score
    )

    # Status is canonical if present; score is the fallback. This is the judge's
    # verdict on the question it was asked, not points: the weight's sign turns
    # it into points, in `_earned`.
    canonical_raw_score = status_score if status_score is not None else normalized_score

    if canonical_raw_score in {"0", "1"}:
        effective_status = "YES" if canonical_raw_score == "1" else "NO"
    else:
        effective_status = normalized_status

    return {
        "rubric_statement": judge_score.get("rubric_statement"),
        "status": effective_status,
        "score": canonical_raw_score,
        "justification": judge_score.get("justification"),
        "judge_score": judge_score,
        "judge_score_canonical": canonical_raw_score,
        "judge_status_score_mismatch": mismatch,
    }


def _is_scored(score_obj: Any) -> bool:
    return isinstance(score_obj, dict) and str(score_obj.get("score")) in {"0", "1"}


def _json_objects(text):
    """Every JSON object written anywhere in the reply, in the order written.

    A fence is not what marks the verdict. The judge is free to quote the
    answer before it rates, and an answer carrying a JSON deliverable -- which
    a prompt is allowed to ask for -- gets quoted inside a fence of its own.
    Reading only the fence the reply opens with throws the verdict away and
    calls a graded criterion unmeasured, so the whole reply is read instead.

    `raw_decode` is what does the reading: it stops at the end of one value and
    reports where, which is how a brace inside a string stays a brace inside a
    string.
    """
    decoder = json.JSONDecoder()
    index = 0
    while True:
        index = text.find("{", index)
        if index == -1:
            return
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index += 1
            continue
        yield value
        index = end


def _parse_response(text):
    """The judge's rating, wherever in the reply it was written."""
    if not text:
        return None

    rating = None
    for value in _json_objects(text):
        if not isinstance(value, dict):
            continue
        ratings = value.get("ratings")
        if isinstance(ratings, list) and ratings and isinstance(ratings[0], dict):
            # The last one wins, not the first. Two objects both carrying
            # ratings means one of them is the answer being quoted back, and
            # the verdict is the thing the judge wrote once it had finished
            # quoting.
            rating = ratings[0]

    if rating is None:
        return None
    return {
        "rubric_statement": rating.get("rubric_statement"),
        "status": rating.get("status"),
        "score": rating.get("score"),
        "justification": rating.get("justification"),
    }


class GatewayUnreachable(Exception):
    """The endpoint never answered, so there is nothing to grade against."""


class Refused:
    """The model declined to judge a criterion instead of judging it."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


_REFUSAL_SIGNS = (
    "can't help with this", "cannot help with this", "can't assist",
    "cannot assist", "unable to assist", "won't be able to help",
    "not able to provide", "can't provide", "cannot provide",
    "against my guidelines", "usage policies", "usage policy",
    "acceptable use policy", "content policy", "safety policy",
    "i must decline", "i can't engage", "cannot engage with",
    "flagged this message", "safeguards", "/legal/aup",
)


def _is_content_refusal(subject: Any) -> bool:
    """Did the model decline the work, as against failing to reach or parse it?

    Read off a response that came back whole, so it is neither a connection
    failure nor a truncation. A reply that parsed into a verdict never reaches
    here, so a criterion whose justification discusses refusal is not caught.
    """
    finish = getattr(subject, "finish_reason", None) or getattr(subject, "stop_reason", None)
    if isinstance(finish, str) and finish.lower() in {"content_filter", "refusal"}:
        return True
    text = str(subject).lower()
    return any(sign in text for sign in _REFUSAL_SIGNS)


_CONNECT_SIGNS = (
    "connection error", "connection refused", "connection aborted",
    "failed to establish", "name or service not known", "nodename nor servname",
    "temporary failure in name resolution", "no route to host",
    "network is unreachable", "cannot connect to host", "getaddrinfo",
)


def _is_connection_error(exc: Exception) -> bool:
    """Did the request fail to reach anything, as against being refused work?

    A status the host returned, such as a 429 or a 500, is not a connection
    error and takes the ordinary ladder.
    """
    try:
        from openai import APIConnectionError, APITimeoutError
        if isinstance(exc, APITimeoutError):
            return False
        if isinstance(exc, APIConnectionError):
            return True
    except Exception:  # noqa: BLE001
        pass
    return any(sign in str(exc).lower() for sign in _CONNECT_SIGNS)


def _retry_after(exc: Exception) -> float | None:
    """The wait the gateway asked for, if it asked for one.

    Read off the response headers where the client exposes them, and off the
    message where it does not.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        for name in ("retry-after", "Retry-After",
                     "x-ratelimit-reset-after", "anthropic-ratelimit-tokens-reset"):
            try:
                value = headers.get(name)
            except Exception:  # noqa: BLE001 - header maps vary between clients
                value = None
            if value:
                try:
                    return max(0.0, float(str(value).strip().rstrip("s")))
                except ValueError:
                    continue
    match = re.search(r"try again in ([0-9.]+)\s*(m?s|s|seconds)", str(exc), re.I)
    if match:
        seconds = float(match.group(1))
        return seconds / 1000 if match.group(2).lower() == "ms" else seconds
    return None


def _wait_for(exc: Exception, attempt: int) -> float:
    """How long to wait before the next attempt.

    The doubling ladder is the fallback, used when the gateway named no delay of
    its own. Every wait carries jitter.
    """
    asked = _retry_after(exc)
    ladder = min(2 ** (attempt + 1), 60)
    base = min(asked, 60.0) if asked is not None else ladder
    return round(base + random.uniform(0, min(2.0, base / 2 or 1)), 1)


def unreachable_note(base_url: str, exc: Exception) -> str:
    """What to print when the endpoint cannot be reached at all."""
    lines = [
        "ERROR: the judge could not reach the grading endpoint.",
        f"  endpoint: {base_url}",
        f"  error:    {exc}",
        "",
        "  Nothing was graded. The zeroed reward beside this is the crash-safe",
        "  default, not a result about the model.",
    ]
    host = re.sub(r"^\w+://", "", base_url or "").split("/")[0].split(":")[0]
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        lines[3:3] = [
            "",
            f"  {host!r} inside this verifier is the verifier's own container,",
            "  not the machine running the gateway. A judge-graded task needs an",
            "  endpoint the verifier container can resolve, or a verifier on the",
            "  host network.",
        ]
    return "\n".join(lines)


def _cacheable_prefix(template: str, fields: dict[str, str]) -> Optional[str]:
    """The leading part of the prompt that is identical for every criterion.

    None when the criterion placeholder appears other than once, or when what
    precedes it is too short for a cache breakpoint to pay for itself.
    """
    if template.count("{title}") != 1:
        return None
    head = template.partition("{title}")[0].format(**fields)
    return head if len(head) >= CACHE_MIN_CHARS else None


def _messages(system_prompt: str, user_content: str,
              prefix: Optional[str]) -> list[dict[str, Any]]:
    """The request body, with a cache breakpoint after `prefix` where given.

    The prompt is sent as one string when there is no prefix to mark, or when
    what was given is not the start of it.
    """
    user: Any = user_content
    if prefix and user_content.startswith(prefix):
        user = [
            {"type": "text", "text": prefix,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": user_content[len(prefix):]},
        ]
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def _cache_read(response: Any) -> int:
    """Prompt tokens this call was served from the cache.

    0 when the gateway reports none, under either the Anthropic or the OpenAI
    spelling.
    """
    usage: Any = getattr(response, "usage", None)
    if usage is None:
        return 0
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
        found = (usage.get("cache_read_input_tokens"),
                 details.get("cached_tokens") if isinstance(details, dict) else None)
    else:
        details = getattr(usage, "prompt_tokens_details", None)
        found = (getattr(usage, "cache_read_input_tokens", None),
                 getattr(details, "cached_tokens", None) if details is not None else None)
    for value in found:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 0


def evaluate_single_rubric(client, model, system_prompt, user_prompt_template,
                           problem_statement, model_answer, trajectory, outputs, rubric,
                           reached: Optional[list] = None):
    """Evaluate one rubric criterion. Returns the parsed result, a Refused, or None.

    Raises GatewayUnreachable when the endpoint has never answered and cannot be
    reached now. Once any call has succeeded the same error is treated as
    transient and gets the ordinary ladder. A model that declines the work
    returns Refused after REFUSAL_RETRIES attempts.
    """
    title = _criterion(rubric)
    rubric_id = _rubric_id(rubric)
    fields = {
        "problem_statement": problem_statement,
        "model_answer": model_answer,
        "trajectory": trajectory,
        "outputs": outputs,
    }
    user_content = user_prompt_template.format(title=json.dumps(title), **fields)
    prefix = _cacheable_prefix(user_prompt_template, fields)

    def ask() -> Any:
        """One request.

        While nothing has been graded yet, a request the gateway turns down is
        tried again without the cache breakpoint, and a success that way stops
        it being offered for the rest of the run.
        """
        global CACHE_ENABLED
        offer = prefix if CACHE_ENABLED else None
        try:
            return client.chat.completions.create(
                model=model,
                messages=_messages(system_prompt, user_content, offer),
                max_tokens=MAX_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001 - re-raised unless it is the breakpoint
            if (offer is None or (reached or [])
                    or _is_connection_error(exc) or _is_content_refusal(exc)):
                raise
            response = client.chat.completions.create(
                model=model,
                messages=_messages(system_prompt, user_content, None),
                max_tokens=MAX_TOKENS,
            )
            CACHE_ENABLED = False
            print("  note: the gateway did not accept the prompt cache "
                  "breakpoint; grading without it", file=sys.stderr)
            return response

    started = time.time()
    refusals = 0
    for attempt in range(MAX_RETRIES):
        try:
            response = ask()
            CACHE_READS.append(_cache_read(response))
            text = response.choices[0].message.content or ""
            parsed = _parse_response(text)
            status_score = _score_from_status(_normalize_status(parsed.get("status"))) if parsed else None
            parsed_score = _normalize_score(parsed.get("score")) if parsed else None
            if reached is not None:
                reached.append(True)
            if parsed and (status_score in {"0", "1"} or parsed_score in {"0", "1"}):
                parsed["rubric_id"] = rubric_id
                parsed["retries"] = attempt
                parsed["wall_seconds"] = round(time.time() - started, 1)
                return parsed
            # A reply that came back whole and declined the work is a refusal,
            # not an unparseable answer, and the two have different remedies.
            if _is_content_refusal(response.choices[0]) or _is_content_refusal(text):
                refusals += 1
                if refusals >= REFUSAL_RETRIES:
                    return Refused(" ".join(text.split())[:300] or "no reason given")
                print(f"  retry {refusals}/{REFUSAL_RETRIES}: the judge declined to "
                      f"grade {rubric_id}", file=sys.stderr)
                continue
            print(f"  retry {attempt + 1}/{MAX_RETRIES}: unparseable response for {rubric_id}",
                  file=sys.stderr)
        except Exception as exc:
            cold = _is_connection_error(exc) and not (reached or [])
            if not cold and _is_content_refusal(exc):
                refusals += 1
                if refusals >= REFUSAL_RETRIES:
                    return Refused(" ".join(str(exc).split())[:300])
                print(f"  retry {refusals}/{REFUSAL_RETRIES}: the judge declined to "
                      f"grade {rubric_id}", file=sys.stderr)
                continue
            budget = CONNECT_RETRIES if cold else MAX_RETRIES
            if attempt + 1 >= budget:
                if cold:
                    raise GatewayUnreachable(str(exc)) from exc
                break
            wait = _wait_for(exc, attempt)
            print(f"  retry {attempt + 1}/{budget}: {exc}, waiting {wait}s", file=sys.stderr)
            time.sleep(wait)

    return None


# A transcript's keys depend on the agent that produced it, so these are matched
# as a set rather than as one schema: the OpenAI-shaped
# {"messages": [{"role": "assistant", "content": ...}]} and the ATIF form, whose
# records carry "source" and "message", both arrive here.
_AGENT_MARKERS = {"assistant", "agent", "ai", "model"}
_SPEAKER_KEYS = ("role", "source", "sender", "author", "speaker")
_RECORD_LISTS = ("messages", "steps", "trajectory", "events", "history", "turns")
_TEXT_KEYS = ("content", "message", "text", "final_answer", "output", "response")
# A record written by a subagent the agent started, rather than by the agent.
_SUBAGENT_KEYS = ("is_sidechain", "isSidechain")
_STOP_KEYS = ("stop_reason", "finish_reason")
# Stop reasons after which the agent's turn continues into a tool call.
_TURN_GOES_ON = {"tool_use", "tool_calls", "function_call"}
# Placed between two replies when the answer is made of several.
REPLY_SEPARATOR = "\n\n---\n\n"


def _text_of(value: Any) -> str:
    """The prose in a content field, whatever shape that field takes."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner
        return ""
    if isinstance(value, list):
        parts = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text", "output_text"):
                parts.append(_text_of(block))
        return "\n".join(p for p in parts if p.strip())
    return ""


def _records_of(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in _RECORD_LISTS:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _is_agent(record: dict) -> bool:
    """Whether this record is the agent speaking. An explicit marker is
    required; there is no fallback to the last record holding any text."""
    for key in _SPEAKER_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.strip().lower() in _AGENT_MARKERS:
            return True
    return False


def _read_trajectory_json() -> Any:
    try:
        return json.loads(open(TRAJECTORY_PATH, errors="replace").read())
    except Exception:
        return None


def _fields(record: dict) -> tuple:
    extra = record.get("extra")
    return (record, extra) if isinstance(extra, dict) else (record,)


def _is_subagent(record: dict) -> bool:
    return any(holder.get(key) is True
               for holder in _fields(record) for key in _SUBAGENT_KEYS)


def _stop_reason(record: dict) -> Optional[str]:
    for holder in _fields(record):
        for key in _STOP_KEYS:
            if isinstance(holder.get(key), str):
                return holder[key]
    return None


def _said(record: dict) -> str:
    for key in _TEXT_KEYS:
        if key in record:
            text = _text_of(record[key]).strip()
            if text:
                return text
    return ""


def _replies(data: Any) -> list[str]:
    """What the agent said at the end of each of its turns, in order.

    A reply is a message of the agent's own, not a subagent's, whose stop
    reason ends the turn. The last message the agent wrote is always the last
    reply, including in a transcript that records no stop reasons.
    """
    spoken = [r for r in _records_of(data)
              if isinstance(r, dict) and _is_agent(r) and not _is_subagent(r)
              and _said(r)]
    if not spoken:
        return []
    replies = [r for r in spoken[:-1]
               if _stop_reason(r) is not None and _stop_reason(r) not in _TURN_GOES_ON]
    return [_said(r) for r in replies + [spoken[-1]]]


def _final_message() -> str:
    """The agent's replies, joined by REPLY_SEPARATOR, from the transcript."""
    return REPLY_SEPARATOR.join(_replies(_read_trajectory_json()))


def _no_answer_reason() -> str:
    """Why no answer could be read, in enough detail to act on."""
    if not os.path.exists(TRAJECTORY_PATH):
        return f"no transcript at {TRAJECTORY_PATH} and no {ANSWER_PATH}"
    data = _read_trajectory_json()
    if data is None:
        return f"the transcript at {TRAJECTORY_PATH} is not readable JSON"
    records = _records_of(data)
    if not records:
        top = ", ".join(sorted(data)[:12]) if isinstance(data, dict) else type(data).__name__
        return f"the transcript holds no recognised list of records (top level: {top})"
    keys, speakers = set(), set()
    for record in records:
        if isinstance(record, dict):
            keys.update(record)
            for key in _SPEAKER_KEYS:
                if isinstance(record.get(key), str):
                    speakers.add(f"{key}={record[key]}")
    return (f"{len(records)} record(s), none marked as the agent. "
            f"Keys seen: {', '.join(sorted(keys)[:12]) or 'none'}. "
            f"Speakers seen: {', '.join(sorted(speakers)[:8]) or 'none'}")


def _load_answer() -> str:
    """The agent's answer: answer.txt if the task asked for one, else its final
    message."""
    if os.path.exists(ANSWER_PATH):
        answer = open(ANSWER_PATH, errors="replace").read().strip()
        if "<<FINAL_ANSWER>>" in answer:
            parts = answer.split("<<FINAL_ANSWER>>")
            answer = parts[1].strip() if len(parts) >= 2 else answer
        if answer:
            return answer
    return _final_message()


def _load_outputs() -> str:
    """What the model left in the workspace that was not given to it.

    Read from the finished workspace mounted at /workspace, against the
    fingerprints of the uploaded inputs. Only new and changed files are shown.
    """
    workspace = os.environ.get("FLC_WORKSPACE", "/workspace")
    if not os.path.isdir(workspace):
        return "(the workspace was not available to the verifier)"
    try:
        manifest = json.load(open(INPUTS_MANIFEST_PATH))
    except Exception:
        return "(no record of the original inputs, so new files cannot be identified)"

    import hashlib

    produced = []
    for base, _, names in os.walk(workspace):
        for name in sorted(names):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, workspace)
            try:
                raw = open(full, "rb").read()
            except OSError:
                continue
            if rel in manifest:
                if manifest[rel] and hashlib.sha256(raw).hexdigest() == manifest[rel]:
                    continue
                label = "changed"
            else:
                label = "new"
            produced.append((rel, label, raw))

    if not produced:
        return "(the model left no new or modified files in the workspace)"

    produced.sort(key=lambda p: (p[1] != "new", p[0]))
    budget = OUTPUT_CHAR_BUDGET
    sections = [f"{len(produced)} file(s) the model created or changed:\n"
                + "\n".join(f"  {label:<8} {rel}  ({len(raw):,} bytes)"
                            for rel, label, raw in produced)]
    for rel, label, raw in produced:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            sections.append(f"\n--- {rel} ({label}) ---\n(binary, {len(raw):,} bytes)")
            continue
        if budget <= 0:
            sections.append(f"\n--- {rel} ({label}) ---\n(not shown, budget spent)")
            continue
        if len(text) > budget:
            text = text[:budget] + f"\n... [truncated, {len(text) - budget:,} more characters]"
        budget -= len(text)
        sections.append(f"\n--- {rel} ({label}) ---\n{text}")
    return "\n".join(sections)


def _shorten_observations(steps: list[Any], cap: int) -> list[Any]:
    """A copy of `steps` with each step's tool result shortened to `cap` chars.

    What the agent said and what it called are left as they are; only the
    result that came back is shortened, and the bookkeeping fields are dropped.
    Encoded images go first, so a blob does not spend the cap.
    """
    out = []
    for step in steps:
        if not isinstance(step, dict):
            out.append(step)
            continue
        shortened = {k: v for k, v in step.items() if k not in STEP_DROPPED_FIELDS}
        if "observation" in shortened:
            observation = shortened["observation"]
            text = (observation if isinstance(observation, str)
                    else json.dumps(observation, default=str))
            text = _B64_BLOB.sub("[encoded image omitted]", text)
            if len(text) > cap:
                text = (text[:cap]
                        + f"\n... [{len(text) - cap:,} more characters of this "
                          "result omitted]")
            shortened["observation"] = text
        out.append(shortened)
    return out


def _fit_steps(steps: list[Any]) -> str:
    """Serialise every step, shortening tool results until it fits the budget.

    The cap is halved towards the floor, and a run with too many steps for even
    that drops the results altogether rather than dropping steps: what the
    agent did and said is kept in every case.

    Returns the empty string when no step carries a tool result to shorten.
    """
    if not any(isinstance(s, dict) and "observation" in s for s in steps):
        return ""
    cap = STEP_OBSERVATION_CHAR_CAP
    while True:
        text = json.dumps(_shorten_observations(steps, cap), indent=2, default=str)
        if len(text) <= TRAJECTORY_CHAR_BUDGET or cap == 0:
            return text
        cap = 0 if cap <= STEP_OBSERVATION_CHAR_FLOOR else max(
            STEP_OBSERVATION_CHAR_FLOOR, cap // 2)


def _load_trajectory() -> str:
    """Flatten the agent transcript to text the judge can read.

    Every step is kept, with the tool results shortened to fit the budget. A
    transcript in no recognised step shape, or one still over budget with its
    results at the floor, is cut in the middle instead and says so.

    An absent transcript is reported as such rather than raising.
    """
    if not os.path.exists(TRAJECTORY_PATH):
        return "(no trajectory was captured for this run)"
    try:
        raw = open(TRAJECTORY_PATH, errors="replace").read()
    except OSError:
        return "(the trajectory could not be read)"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        text = raw
    else:
        if isinstance(data, dict):
            steps = data.get("steps") or data.get("messages") or data
        else:
            steps = data
        if isinstance(steps, str):
            text = steps
        else:
            text = (_fit_steps(steps) if isinstance(steps, list) else "") \
                or json.dumps(steps, indent=2, default=str)

    text = _B64_BLOB.sub("[encoded image omitted]", text)

    if len(text) > TRAJECTORY_CHAR_BUDGET:
        half = TRAJECTORY_CHAR_BUDGET // 2
        text = (text[:half]
                + f"\n\n... [{len(text) - TRAJECTORY_CHAR_BUDGET} characters omitted from the middle] ...\n\n"
                + text[-half:])
    return text


def _earned(result: dict[str, Any]) -> bool:
    """Did this criterion earn its points?

    A positive criterion earns when the judge said its statement is true of the
    answer; a negative one earns by that statement being false.
    """
    said_true = str(result["score"]["score"]) == "1"
    return said_true if int(result.get("weight", 5)) >= 0 else not said_true


def _row(rubric: dict[str, Any], judge_result: Any) -> dict[str, Any]:
    """One criterion's result, with a name for whatever went wrong.

    The two ways a criterion goes ungraded are told apart here, because they
    are repaired differently downstream: a refusal is dropped from the bundle
    under the coverage limit, and a reply that never became a verdict is not.
    """
    refused = isinstance(judge_result, Refused)
    result = None if refused else (
        _canonicalize_judge_result(judge_result) if judge_result else None)
    row = {
        "id": _rubric_id(rubric),
        "title": _criterion(rubric),
        "weight": int(rubric.get("weight", 5)),
        # Carried through so a reader of this file alone can tell what each
        # criterion measures, rather than joining back to rubrics.json on the
        # criterion text.
        "type": [t for t in (rubric.get("type") or []) if isinstance(t, str)],
        "score": result,
    }
    if refused:
        # Distinguished from an unparseable reply because the remedy is
        # different: this criterion has to be reworded, not re-judged.
        row["unmeasured"] = "judge_refused"
        row["unmeasured_reason"] = judge_result.reason
    elif not _is_scored(result):
        # Named rather than left as a null score. It is outside the reward
        # either way, so without a name for it the rubric shrinks and every
        # number still looks right.
        row["unmeasured"] = "judge_no_score"
        row["unmeasured_reason"] = ("the judge never answered in the yes-or-no "
                                    "form the criterion asks for, through "
                                    "every retry")
    return row


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """The score, and the counts it was computed from.

    The positive criteria put up the marks available. A negative criterion is a
    penalty rather than a mark to collect: nothing is earned by avoiding it, and
    its weight comes off for doing what it describes. Computed over the criteria
    that were scored, so an unparseable judge response costs that one alone.
    """
    scored = [r for r in results if _is_scored(r["score"])]
    passed = sum(1 for r in scored if _earned(r))
    refused = [r for r in results if r.get("unmeasured") == "judge_refused"]
    ungraded = [r for r in results if not _is_scored(r["score"])]

    # How much of the rubric went unjudged, by weight rather than by count: a
    # [5] criterion and a [1] one are not the same loss. Negatives count too --
    # a trap that was never checked is the half of the rubric this project is
    # for. Every ungraded criterion counts, whatever the reason: the coverage
    # argument does not depend on why the judge did not answer.
    total_weight = sum(abs(int(r.get("weight", 5))) for r in results)
    refused_weight = sum(abs(int(r.get("weight", 5))) for r in ungraded)

    max_reward = sum(int(r.get("weight", 5)) for r in scored if int(r.get("weight", 5)) > 0)
    earned = sum(int(r.get("weight", 5)) for r in scored
                 if int(r.get("weight", 5)) > 0 and _earned(r))
    lost = sum(abs(int(r.get("weight", 5))) for r in scored
               if int(r.get("weight", 5)) < 0 and not _earned(r))
    agent_score = earned - lost

    return {
        "total": len(results),
        "scored": len(scored),
        "unscored": len(results) - len(scored),
        "refused": len(refused),
        "coverage_lost": round(refused_weight / total_weight, 4) if total_weight else 0.0,
        "passed": passed,
        "max_reward": max_reward,
        # Not floored, so a run that gave back more than it earned reads as
        # negative here.
        "agent_score": agent_score,
        # `count_rate` is the same tally with the weights ignored.
        "rate": max(0.0, agent_score / max_reward) if max_reward else 0.0,
        "count_rate": (passed / len(scored)) if scored else 0.0,
    }


def main() -> int:
    api_key = os.environ.get("EVAL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = (os.environ.get("EVAL_BASE_URL")
                or os.environ.get("OPENAI_API_BASE")
                or os.environ.get("OPENAI_BASE_URL"))
    model = os.environ.get("EVAL_MODEL", "anthropic/claude-opus-4-5-20251101")

    if not api_key or not base_url:
        print("ERROR: EVAL_API_KEY and EVAL_BASE_URL must be set", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    rubrics = json.load(open(RUBRICS_PATH))
    answer = _load_answer()

    if not answer:
        reason = _no_answer_reason()
        print(f"no answer to grade -- every rubric scores 0\n  {reason}")
        payload = {
            "reason": f"no answer could be read from this run: {reason}",
            "overall": {"total": len(rubrics), "scored": 0, "unscored": len(rubrics),
                        "passed": 0, "max_reward": 0, "agent_score": 0,
                        "rate": 0.0, "count_rate": 0.0},
            "rubric_scores": [],
        }
        with open(RESULTS_PATH, "w") as f:
            json.dump(payload, f, indent=2)
        return 0

    system_prompt = open(SYSTEM_PROMPT_PATH).read()
    user_prompt_template = open(USER_PROMPT_TEMPLATE_PATH).read()
    problem_statement = open(PROMPT_PATH).read().strip() if os.path.exists(PROMPT_PATH) else ""
    trajectory = _load_trajectory()
    outputs = _load_outputs()

    client = OpenAI(api_key=api_key, base_url=base_url)
    results: list[dict[str, Any]] = []
    reached: list = []
    for rubric in rubrics:
        text = _criterion(rubric)
        try:
            judge_result = evaluate_single_rubric(
                client, model, system_prompt, user_prompt_template,
                problem_statement, answer, trajectory, outputs, rubric, reached,
            )
        except GatewayUnreachable as exc:
            # No results file is written: a partial one would be read as a score.
            print(unreachable_note(base_url, exc), file=sys.stderr)
            return EXIT_UNREACHABLE
        row = _row(rubric, judge_result)
        results.append(row)
        refused = row.get("unmeasured") == "judge_refused"
        result = row["score"]
        weight = row["weight"]

        if _is_scored(result):
            raw = result.get("judge_score_canonical")
            mark = "PASS" if _earned(results[-1]) else "FAIL"
            print(f"  {mark}  [{weight:+d}]  {text} [raw={raw}]")
        elif refused:
            print(f"  ????  {text}  (the judge declined to grade this criterion)")
        else:
            print(f"  ????  {text}  (judge gave no usable score)")

    payload = {
        "judge_model": model,
        "cache_read_tokens": sum(CACHE_READS),
        "overall": _aggregate(results),
        "rubric_scores": results,
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    o = payload["overall"]
    print()
    print(f"  rubrics: {o['passed']}/{o['scored']} criteria held"
          + (f" ({o['unscored']} unscored)" if o["unscored"] else ""))
    print(f"  points:  {o['agent_score']} of {o['max_reward']}")
    print(f"  score:   {o['rate']:.1%}")
    if payload["cache_read_tokens"]:
        print(f"  cached:  {payload['cache_read_tokens']:,} prompt tokens "
              "served from cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
