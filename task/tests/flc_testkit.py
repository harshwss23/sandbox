"""Helpers available to a task's verifier.py.

`read_*` reads the model's finished workspace; `source_*` reads
`/tests/source_workspace`, an untouched copy of the uploaded inputs, so a
statistic can be recomputed from a file the model cannot have edited.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

__all__ = [
    "WORKSPACE",
    "ANSWER",
    "SOURCE",
    "read_text",
    "read_json",
    "read_lines",
    "source_text",
    "source_json",
    "trajectory_text",
    "opened",
    "ran",
]

WORKSPACE = Path(os.environ.get("FLC_WORKSPACE", "/workspace"))
SOURCE = Path(os.environ.get("FLC_SOURCE", "/tests/source_workspace"))
_ANSWER_PATH = Path(os.environ.get("FLC_ANSWER", "/logs/agent/answer.txt"))
_TRAJECTORY_PATH = Path(os.environ.get("FLC_TRAJECTORY", "/logs/agent/trajectory.json"))


# The shape of a trajectory depends on the agent that produced it. Two dialects
# are known to arrive: {"messages": [{"role": "assistant", "content": ...}]},
# and the ATIF form, whose records carry "source" and "message" instead.
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
_REPLY_SEPARATOR = "\n\n---\n\n"


def _text_of(value) -> str:
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


def _records_of(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in _RECORD_LISTS:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _is_agent(record: dict) -> bool:
    for key in _SPEAKER_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.strip().lower() in _AGENT_MARKERS:
            return True
    return False


def _fields(record: dict) -> tuple:
    extra = record.get("extra")
    return (record, extra) if isinstance(extra, dict) else (record,)


def _is_subagent(record: dict) -> bool:
    return any(holder.get(key) is True
               for holder in _fields(record) for key in _SUBAGENT_KEYS)


def _stop_reason(record: dict) -> str | None:
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


def _final_message() -> str:
    """The agent's replies from the transcript, joined by _REPLY_SEPARATOR.

    A reply is a message of the agent's own, not a subagent's, whose stop
    reason ends the turn. The last message the agent wrote is always the last
    reply, including in a transcript that records no stop reasons.
    """
    try:
        data = json.loads(_TRAJECTORY_PATH.read_text(errors="replace"))
    except Exception:
        return ""
    spoken = [r for r in _records_of(data)
              if isinstance(r, dict) and _is_agent(r) and not _is_subagent(r)
              and _said(r)]
    if not spoken:
        return ""
    ended = [r for r in spoken[:-1]
             if _stop_reason(r) is not None and _stop_reason(r) not in _TURN_GOES_ON]
    return _REPLY_SEPARATOR.join(_said(r) for r in ended + [spoken[-1]])


def _read_answer() -> str:
    """The answer the judge scored: the agent's final message, or answer.txt.

    Resolved exactly as the judge resolves it, so a test that greps the answer
    sees what was graded rather than something subtly different.
    """
    try:
        raw = _ANSWER_PATH.read_text(errors="replace").strip()
    except FileNotFoundError:
        raw = ""
    if raw:
        if "<<FINAL_ANSWER>>" in raw:
            parts = raw.split("<<FINAL_ANSWER>>")
            if len(parts) >= 2:
                return parts[1].strip()
        return raw
    return _final_message()


ANSWER = _read_answer()


def _resolve(root: Path, rel: str, label: str) -> Path:
    path = (root / rel).resolve()
    # A test that walks out of the workspace is a mistake every time, and the
    # failure it produces otherwise ("no such file") points nowhere useful.
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise AssertionError(f"{rel!r} points outside the {label}") from None
    if not path.exists():
        raise AssertionError(f"no {rel!r} in the {label}")
    return path


def read_text(rel: str) -> str:
    """Read a file from the model's finished workspace, as text."""
    return _resolve(WORKSPACE, rel, "workspace").read_text(errors="replace")


def read_lines(rel: str) -> list[str]:
    """Read a file from the model's finished workspace, as a list of lines."""
    return read_text(rel).splitlines()


def read_json(rel: str):
    """Read a JSON file from the model's finished workspace."""
    raw = read_text(rel)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{rel!r} is not valid JSON: {exc}") from None


def source_text(rel: str) -> str:
    """Read one of the ORIGINAL input files, as text."""
    if not SOURCE.exists():
        raise AssertionError(
            "no pristine copy of the inputs is available to this test "
            f"(expected {SOURCE}) -- repackage the task with /flc-deliver"
        )
    return _resolve(SOURCE, rel, "original inputs").read_text(errors="replace")


def source_json(rel: str):
    """Read one of the ORIGINAL input files as JSON."""
    raw = source_text(rel)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"source {rel!r} is not valid JSON: {exc}") from None


# --- what the model did, rather than what it produced -------------------------
#
# The trajectory is every command the model ran and everything those commands
# printed. Flattened to one searchable string on first use, so a test does not
# have to know whether tool calls live under `tool_calls` or inside a `content`
# list.

_flat: str | None = None


def trajectory_text() -> str:
    """Everything the model ran and saw, as one searchable string.

    Empty when no trajectory was captured, so a check written against it fails
    with its own message rather than a missing-file error.
    """
    global _flat
    if _flat is not None:
        return _flat
    try:
        raw = _TRAJECTORY_PATH.read_text(errors="replace")
    except OSError:
        _flat = ""
        return _flat
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # JSONL is the other shape in the wild. Falling back to the raw text
        # loses structure but keeps every substring a check might look for.
        _flat = raw
        return _flat

    chunks: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            chunks.append(node)

    walk(data)
    # On an image task the transcript carries the encoded bytes of every figure
    # the model looked at, which no check wants to search and which would make
    # this string enormous.
    _flat = re.sub(r"[A-Za-z0-9+/=]{2000,}", "[encoded image omitted]",
                   "\n".join(chunks))
    return _flat


def opened(rel: str) -> bool:
    """Did the model appear to open this file?

    Substring search over the trajectory, which makes it reliable in one
    direction only. True is trustworthy. False is not: `cat data/*.csv`, a glob
    in Python, or `find | xargs grep` all read a file without ever naming it.

    So assert on it to check a file WAS used. To check one was ignored, write a
    rubric instead -- the judge reads the same trajectory and can weigh what the
    model actually did with what it found.
    """
    text = trajectory_text()
    name = rel.rsplit("/", 1)[-1]
    return rel in text or (name in text if name else False)


def ran(fragment: str) -> bool:
    """Did any command the model ran contain this text?"""
    return fragment in trajectory_text()
