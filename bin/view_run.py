#!/usr/bin/env python3
"""The run as a page you can read: what the model thought, did, and answered.

This is a renderer and nothing else. It ranks nothing, judges nothing and
leaves nothing out -- every record in the transcript is on the page, in order,
in full. review_run.py is the counterpart to it: a reading of the same run,
which does select and rank.

The file is self-contained: one HTML document with its own styling, no fonts,
scripts or images loaded from anywhere. Download it out of the sandbox and open
it in your own browser, offline, and it looks the same.

    python3 bin/view_run.py                 # the last run
    python3 bin/view_run.py --job PATH      # a specific one
    python3 bin/view_run.py --where         # where everything from the run is
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from datetime import datetime
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402
import review_run as rr  # noqa: E402
import solver_answer as sa  # noqa: E402

from solver_answer import (  # noqa: E402
    final_message,
    find_job,
    find_trajectory,
    finished_workspace,
)

# Below this a block is easier to read on the page than behind a click.
INLINE_CHARS = 400

# What came back to the agent, which is the bulk of a transcript, opens on
# demand. What the agent said is what the page is for and is always visible.
_RESULT_SPEAKERS = {"tool", "environment", "observation", "function", "system"}
_YOU_SPEAKERS = {"user", "human", "task"}
# What Claude Code posts into the conversation when a subagent finishes.
NOTIFICATION = "<task-notification>"

# Sniffed from the bytes, never read off the record's own media_type: a data:
# URL built from a string in the transcript is a way of putting markup on a
# page that is meant to be incapable of carrying any.
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def count(n: int) -> str:
    return f"{n:,} character{'' if n == 1 else 's'}"


# --- reading the transcript ---------------------------------------------------


def records(trajectory: Path) -> list:
    try:
        data = json.loads(trajectory.read_text(errors="replace"))
    except Exception:
        return []
    return [r for r in sa._records_of(data) if isinstance(r, dict)]


def speaker_of(record: dict) -> str:
    for key in sa._SPEAKER_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def is_notification(record: dict) -> bool:
    return (not sa._is_agent(record)
            and prose_of(record).lstrip().startswith(NOTIFICATION))


def kind_of(record: dict) -> str:
    """Who is talking, in the four parts a reader cares about."""
    if sa._is_subagent(record) or is_notification(record):
        return "helper"
    if sa._is_agent(record):
        return "model"
    speaker = speaker_of(record).lower()
    if speaker in _YOU_SPEAKERS:
        return "task"
    if speaker in _RESULT_SPEAKERS:
        return "result"
    return "other"


def prose_of(record: dict) -> str:
    for key in sa._TEXT_KEYS:
        if key in record:
            text = sa._text_of(record[key])
            if text.strip():
                return text
    return ""


def results_in(record: dict) -> list[tuple[str, str]]:
    """Tool output on the record, each paired with the id of the call it answers.

    Two dialects put it in two places: a `tool_result` block in `content`, and
    an `observation.results` list alongside the calls that produced it. The id
    is "" where the dialect carries none.
    """
    out: list[tuple[str, str]] = []
    content = record.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                text = sa._text_of(block.get("content"))
                if text.strip():
                    out.append((str(block.get("tool_use_id") or ""), text))
    observation = record.get("observation")
    if isinstance(observation, dict):
        results = observation.get("results")
        for item in results if isinstance(results, list) else []:
            if isinstance(item, dict):
                text = sa._text_of(item.get("content"))
                ident = str(item.get("source_call_id")
                            or item.get("tool_call_id") or "")
            else:
                text, ident = sa._text_of(item), ""
            if text.strip():
                out.append((ident, text))
    return out


def images_in(record: dict) -> list[str]:
    """Every base64 image attached to a record, as data URLs we built ourselves."""
    found: list[str] = []

    def take(value) -> None:
        if isinstance(value, str):
            url = data_url(value)
            if url:
                found.append(url)

    content = record.get("content")
    blocks = content if isinstance(content, list) else []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image":
            source = block.get("source")
            if isinstance(source, dict):
                take(source.get("data"))
            elif isinstance(source, str):
                take(source)
        image_url = block.get("image_url")
        if isinstance(image_url, dict):
            url = image_url.get("url")
            if isinstance(url, str) and "base64," in url:
                take(url.split("base64,", 1)[1])
    return found


def data_url(blob: str) -> str | None:
    """A data: URL for a blob, if the bytes really are an image we recognise."""
    blob = blob.strip()
    if len(blob) < 32:
        return None
    head = blob[:64]
    try:
        raw = base64.b64decode(head + "=" * (-len(head) % 4))
    except Exception:
        return None
    for magic, media in _MAGIC:
        if raw.startswith(magic):
            return f"data:{media};base64,{blob}"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return f"data:image/webp;base64,{blob}"
    return None


# --- the page -----------------------------------------------------------------


STYLE = """
:root {
  color-scheme: light dark;
  --bg: #f3f4f7; --card: #fff; --sunk: #f7f7fa; --line: #e3e4ec;
  --ink: #1b1b1f; --dim: #63636e; --faint: #9a9aa6;
  --model: #2f5bd7; --model-soft: #e9efff; --model-line: #c9d9ff;
  --task: #2f7a45; --task-soft: #e8f5ec; --task-line: #cbe6d4;
  --result: #6a4fa8; --result-soft: #f1edf9; --result-line: #ded4f2;
  --helper: #8a5a00; --helper-soft: #fdf3e1; --helper-line: #efd9ad;
  --other: #55555f; --other-soft: #eeeef2; --other-line: #dededf;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #121216; --card: #1c1c22; --sunk: #17171d; --line: #2d2d38;
    --ink: #e8e8ee; --dim: #a6a6b2; --faint: #77778a;
    --model-soft: #1a2440; --model-line: #2c3d66;
    --task-soft: #16281c; --task-line: #274a32;
    --result-soft: #221c33; --result-line: #3a2f57;
    --helper: #d9a441; --helper-soft: #2a2114; --helper-line: #4a3a1c;
    --other-soft: #22222a; --other-line: #33333e;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 0 6rem;
  font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        Helvetica, Arial, sans-serif;
  color: var(--ink); background: var(--bg);
}
.wrap { max-width: 58rem; margin: 0 auto; padding: 0 1.25rem; }

/* --- the bar that stays put ------------------------------------------- */
.topbar {
  position: sticky; top: 0; z-index: 10; background: var(--card);
  border-bottom: 1px solid var(--line); padding: .85rem 0;
  margin-bottom: 1.75rem;
}
.topbar .wrap { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.topbar h1 { font-size: 1.05rem; margin: 0; letter-spacing: -.01em; }
.topbar .meta { color: var(--dim); font-size: .8rem; margin: 0; }
.controls { display: flex; gap: .5rem; margin-left: auto; align-items: center; }
.controls input {
  padding: .45rem .75rem; border: 1px solid var(--line); border-radius: 999px;
  font: inherit; font-size: .875rem; background: var(--bg); color: inherit;
  min-width: 15rem;
}
.controls button {
  padding: .45rem .85rem; border: 1px solid var(--line); border-radius: 999px;
  background: var(--bg); font: inherit; font-size: .8rem; cursor: pointer;
  color: var(--dim); white-space: nowrap;
}
.controls button:hover { color: var(--ink); }
#found { font-size: .78rem; color: var(--faint); min-width: 5.5rem; }

h2 { font-size: .95rem; margin: 0 0 .6rem; letter-spacing: .01em; }
.note {
  color: var(--dim); font-size: .9rem; margin: 0 0 1.75rem;
  border-left: 2px solid var(--line); padding-left: .9rem;
}

/* --- the answer, pinned above the conversation ------------------------ */
.answer {
  border: 1px solid var(--line); border-left: 3px solid var(--model);
  border-radius: 12px; padding: 1.1rem 1.25rem; background: var(--card);
  margin: 0 0 2.25rem;
}
.answer .hint { color: var(--dim); font-size: .82rem; margin: 0 0 .8rem; }
.answer pre {
  font: inherit; font-size: .95rem; line-height: 1.7; white-space: pre-wrap;
}

/* --- the conversation -------------------------------------------------- */
ol.thread { list-style: none; margin: 0; padding: 0; }
li.step { display: flex; gap: .7rem; margin: 0 0 1.15rem; align-items: flex-start; }
li.step[data-kind="task"] { flex-direction: row-reverse; }
.avatar {
  flex: 0 0 auto; width: 1.85rem; height: 1.85rem; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: .7rem; font-weight: 700; letter-spacing: .02em;
  border: 1px solid transparent; margin-top: .15rem;
}
li.step[data-kind="model"] .avatar {
  background: var(--model-soft); color: var(--model); border-color: var(--model-line);
}
li.step[data-kind="task"] .avatar {
  background: var(--task-soft); color: var(--task); border-color: var(--task-line);
}
li.step[data-kind="result"] .avatar {
  background: var(--result-soft); color: var(--result); border-color: var(--result-line);
}
li.step[data-kind="other"] .avatar {
  background: var(--other-soft); color: var(--other); border-color: var(--other-line);
}
li.step[data-kind="helper"] .avatar {
  background: var(--helper-soft); color: var(--helper); border-color: var(--helper-line);
}
.bubble {
  flex: 1 1 auto; min-width: 0; border: 1px solid var(--line);
  border-radius: 14px; padding: .85rem 1rem; background: var(--card);
}
li.step[data-kind="model"] .bubble { border-top-left-radius: 4px; }
li.step[data-kind="task"] .bubble {
  border-top-right-radius: 4px; background: var(--task-soft);
  border-color: var(--task-line);
}
li.step[data-kind="result"] .bubble { background: var(--sunk); }
li.step[data-kind="helper"] .bubble {
  background: var(--helper-soft); border-color: var(--helper-line);
}
.who {
  display: flex; align-items: baseline; gap: .5rem; margin-bottom: .45rem;
  flex-wrap: wrap;
}
li.step[data-kind="task"] .who { flex-direction: row-reverse; }
.name { font-size: .8rem; font-weight: 600; color: var(--dim); }
li.step[data-kind="model"] .name { color: var(--model); }
li.step[data-kind="task"] .name { color: var(--task); }
li.step[data-kind="result"] .name { color: var(--result); }
li.step[data-kind="helper"] .name { color: var(--helper); }
.n { color: var(--faint); font-size: .74rem; }
.reply {
  font-size: .74rem; font-weight: 600; color: var(--model);
  background: var(--model-soft); border: 1px solid var(--model-line);
  border-radius: 999px; padding: 0 .55rem;
}
.prose { overflow-wrap: anywhere; }
.prose pre {
  font: inherit; white-space: pre-wrap; margin: 0 0 .5rem;
}
.prose pre:last-child { margin-bottom: 0; }

/* --- a tool call ------------------------------------------------------- */
.call {
  border: 1px solid var(--line); border-radius: 10px; background: var(--sunk);
  padding: .6rem .75rem; margin: .7rem 0 0;
}
.callhead {
  display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap;
  margin-bottom: .4rem;
}
.tool {
  font: 600 .72rem/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  text-transform: none; letter-spacing: .02em; padding: .28rem .5rem;
  border-radius: 6px; background: var(--model-soft); color: var(--model);
  border: 1px solid var(--model-line);
}
.said { font-size: .875rem; color: var(--ink); font-style: italic; }
code.inline {
  font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: var(--card); border: 1px solid var(--line); border-radius: 6px;
  padding: .18rem .45rem; overflow-wrap: anywhere;
}
.callhead:last-child { margin-bottom: 0; }
.arg { margin: .4rem 0 0; }
.argkey {
  display: block; font-size: .7rem; text-transform: uppercase;
  letter-spacing: .06em; color: var(--faint); margin-bottom: .18rem;
}
pre {
  white-space: pre-wrap; overflow-wrap: anywhere; margin: 0;
  font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.arg pre, details pre {
  background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  padding: .55rem .7rem; max-height: 32rem; overflow: auto;
}
details { margin: .5rem 0 0; }
summary {
  cursor: pointer; font-size: .82rem; color: var(--dim); padding: .2rem 0;
  list-style: revert;
}
summary:hover { color: var(--ink); }
details[open] > summary { margin-bottom: .4rem; }
details.raw > summary { color: var(--faint); font-size: .74rem; }
img.shot {
  max-width: 100%; border: 1px solid var(--line); border-radius: 10px;
  margin: .6rem 0 0; display: block; background: var(--card);
}
footer {
  margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid var(--line);
  color: var(--dim); font-size: .85rem;
}
footer code { word-break: break-all; }
@media (max-width: 40rem) {
  .controls { margin-left: 0; width: 100%; }
  .controls input { min-width: 0; flex: 1; }
}
"""

# Progressive enhancement only: the controls are hidden until this runs, so a
# browser that will not run it shows a page with no dead buttons on it. Nothing
# here is required to read anything.
SCRIPT = """
(function () {
  var bar = document.getElementById('controls');
  var box = document.getElementById('find');
  var all = document.getElementById('expand');
  var tally = document.getElementById('found');
  var steps = Array.prototype.slice.call(
    document.querySelectorAll('li.step'));
  if (!bar || !box || !all) { return; }
  bar.hidden = false;
  box.addEventListener('input', function () {
    var needle = box.value.toLowerCase();
    var hits = 0;
    steps.forEach(function (step) {
      var hit = !needle || step.textContent.toLowerCase().indexOf(needle) >= 0;
      step.style.display = hit ? '' : 'none';
      if (hit) { hits++; }
    });
    if (tally) {
      tally.textContent = needle
        ? hits + ' of ' + steps.length + ' steps'
        : '';
    }
  });
  all.addEventListener('click', function () {
    var open = all.getAttribute('data-open') !== 'yes';
    document.querySelectorAll('li.step details').forEach(function (d) {
      d.open = open;
    });
    all.setAttribute('data-open', open ? 'yes' : 'no');
    all.textContent = open ? 'collapse all' : 'expand all';
  });
})();
"""

LABEL = {"model": "the model", "task": "the task", "result": "what came back",
         "helper": "a helper the model started", "other": ""}

AVATAR = {"model": "AI", "task": "T", "result": "&larr;", "helper": "H",
          "other": "&middot;"}


def helper_label(record: dict) -> str:
    """Which side of a helper's work a record is."""
    if is_notification(record):
        return "a helper reporting back"
    if sa._is_agent(record):
        return "a helper the model started"
    return "the model, to its helper"


def readable(argument: str) -> str:
    """A tool's argument laid out, when it arrived as a line of JSON.

    Whitespace only: every key and every character of every value survives,
    which is the rule this file lives by.
    """
    try:
        parsed = json.loads(argument)
    except (ValueError, TypeError):
        return argument
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    return argument


# A lone short argument -- a path, a pattern -- reads better beside the tool's
# name than under a heading of its own.
INLINE_ARG_CHARS = 160


def argument_blocks(argument: str) -> tuple[str, str]:
    """A call's arguments as (one-liner, blocks), whichever of the two fits.

    A string value is shown as the text it is rather than as a JSON scalar, so
    a shell script keeps its line breaks instead of arriving full of \\n. The
    description is left out here because it is the heading above these blocks;
    every other key and every character of every value is on the page.
    """
    try:
        parsed = json.loads(argument)
    except (ValueError, TypeError):
        parsed = None
    if not isinstance(parsed, dict) or not parsed:
        if ("\n" not in argument) and len(argument) <= INLINE_ARG_CHARS:
            return argument, ""
        return "", maybe_collapsed(readable(argument), "the rest of the argument")

    keys = [k for k, v in parsed.items()
            if not (k in rr._DESCRIPTION_KEYS and isinstance(v, str))]
    if len(keys) == 1:
        only = parsed[keys[0]]
        if (isinstance(only, str) and "\n" not in only
                and 0 < len(only) <= INLINE_ARG_CHARS):
            return only, ""

    out = []
    for key in keys:
        value = parsed[key]
        shown = (value if isinstance(value, str)
                 else json.dumps(value, indent=2, ensure_ascii=False))
        out.append(f'<div class="arg"><span class="argkey">{esc(key)}</span>'
                   f'{maybe_collapsed(shown, "the rest of it")}</div>')
    return "", "".join(out)


def came_back_html(text: str) -> str:
    return (f"<details><summary>what came back -- {count(len(text))}</summary>"
            f"{render_prose(text)}</details>")


def collapsed(text: str, summary: str) -> str:
    return (f"<details><summary>{esc(summary)} -- {count(len(text))}</summary>"
            f"<pre>{esc(text)}</pre></details>")


def maybe_collapsed(text: str, summary: str) -> str:
    """Behind a click only when it is long enough to be in the way."""
    if len(text) <= INLINE_CHARS:
        return f"<pre>{esc(text)}</pre>"
    return collapsed(text, summary)


def render_prose(text: str) -> str:
    """Prose, with any encoded image in it shown as the picture it is.

    A blob is never dropped and never cut: it becomes the image, or it stays as
    the characters it is, behind a click. Splitting on the same pattern the
    judge strips with keeps the filenames on either side of it intact.
    """
    parts = rr._B64_BLOB.split(text)
    blobs = rr._B64_BLOB.findall(text)
    out = [f"<pre>{esc(parts[0])}</pre>"] if parts and parts[0] else []
    seen: set[str] = set()
    for blob, tail in zip(blobs, parts[1:]):
        url = data_url(blob)
        if url and url not in seen:
            seen.add(url)
            out.append(f'<img class="shot" alt="an image from the run" '
                       f'src="{esc(url)}">')
        elif url:
            # A record that carries the same picture twice is shown once, and
            # the repeat keeps every character of itself behind the click.
            out.append(f"<details><summary>the same image again -- "
                       f"{count(len(blob))}</summary><pre>{esc(blob)}</pre>"
                       f"</details>")
        else:
            out.append(f"<details><summary>encoded data -- {count(len(blob))}"
                       f"</summary><pre>{esc(blob)}</pre></details>")
        if tail:
            out.append(f"<pre>{esc(tail)}</pre>")
    return "".join(out) or f"<pre>{esc(text)}</pre>"


def render_step(index: int, record: dict, reply: str = "") -> str:
    kind = kind_of(record)
    speaker = speaker_of(record)
    label = (helper_label(record) if kind == "helper"
             else LABEL.get(kind) or esc(speaker) or "a record")
    parts = [f'<li class="step" data-kind="{kind}">',
             f'<div class="avatar" aria-hidden="true">{AVATAR.get(kind, "?")}</div>',
             '<div class="bubble">',
             f'<div class="who"><span class="name">{esc(label)}</span>',
             f'<span class="n">step {index}']
    if speaker and LABEL.get(kind) and speaker.lower() != label:
        parts.append(f" &middot; {esc(speaker)}")
    parts.append("</span>")
    if reply:
        parts.append(f'<span class="reply">{esc(reply)}</span>')
    parts.append("</div>")

    text = prose_of(record)
    if text:
        # What the model said is the page; what came back to it waits behind a
        # click.
        parts.append(collapsed(text, "what came back") if kind == "result"
                     else f'<div class="prose">{render_prose(text)}</div>')

    came_back = results_in(record)
    by_call = {ident: text for ident, text in came_back if ident}
    answered: set[str] = set()

    for tool, argument, said, ident in rr._tool_calls(record, limit=None):
        inline, blocks = argument_blocks(argument) if argument else ("", "")
        parts.append('<div class="call"><div class="callhead">')
        parts.append(f'<span class="tool">{esc(tool)}</span>')
        if inline:
            parts.append(f'<code class="inline">{esc(inline)}</code>')
        if said:
            parts.append(f'<span class="said">{esc(said)}</span>')
        parts.append("</div>")
        parts.append(blocks)
        if ident in by_call:
            answered.add(ident)
            parts.append(came_back_html(by_call[ident]))
        parts.append("</div>")

    for ident, result in came_back:
        if ident and ident in answered:
            continue
        parts.append(came_back_html(result))

    for url in images_in(record):
        parts.append(f'<img class="shot" alt="an image from the run" src="{esc(url)}">')

    raw = json.dumps(record, indent=2, default=str, ensure_ascii=False)
    parts.append(f"<details class=\"raw\"><summary>the raw record</summary>"
                 f"<pre>{esc(raw)}</pre></details>")
    parts.append("</div></li>")
    return "".join(parts)


def render(job: Path, trajectory: Path, root: Path) -> str:
    rows = records(trajectory)
    answer = final_message(trajectory)
    size = trajectory.stat().st_size if trajectory.exists() else 0
    when = datetime.now().strftime("%d %B %Y at %H:%M")

    replies = {id(r): n for n, r in enumerate(sa.reply_records(rows), start=1)}
    def tag(record: dict) -> str:
        n = replies.get(id(record))
        if n is None:
            return ""
        return ("its answer, shown above" if len(replies) == 1 else
                f"part of its answer: reply {n} of {len(replies)}")
    steps = "".join(render_step(i, r, tag(r)) for i, r in enumerate(rows, start=1))
    if not rows:
        steps = ("<li class=\"step\" data-kind=\"other\">"
                 "<div class=\"avatar\" aria-hidden=\"true\">&middot;</div>"
                 "<div class=\"bubble\"><div class=\"who\">"
                 "<span class=\"name\">nothing to show</span></div>"
                 "<pre>This transcript could not be read as a list of steps. "
                 "The raw file is at the path in the footer, and /flc-inspect "
                 "will say more about the run.</pre></div></li>")

    answer_html = (f"<pre>{esc(answer)}</pre>" if answer else
                   "<pre>The model never gave a final answer. A run that was "
                   "killed before it finished looks like this.</pre>")

    workspace = finished_workspace(job)
    produced = (f"<p>The files it produced are in the sandbox at "
                f"<code>{esc(workspace)}</code>.</p>" if workspace else
                "<p>No copy of the finished workspace came back with this run, "
                "so the files it wrote are not on disk to look at. That is a "
                "broken run rather than a model that wrote nothing -- "
                "<code>/flc-inspect</code> says what to do about it.</p>")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What the model did -- {esc(job.name)}</title>
<style>{STYLE}</style>
</head>
<body>
<header class="topbar">
<div class="wrap">
<div>
<h1>What the model did</h1>
<p class="meta">{esc(job.name)} &middot; {len(rows)} step{'' if len(rows) == 1 else 's'}
 &middot; {size:,} bytes &middot; written {esc(when)}</p>
</div>
<div class="controls" id="controls" hidden>
<input id="find" type="search" placeholder="find a word, a number, a filename">
<span id="found"></span>
<button id="expand" type="button" data-open="no">expand all</button>
</div>
</div>
</header>

<div class="wrap">
<p class="note">Everything the model said and did on this run, in order, complete
and unedited. Its own words are shown as it wrote them; what came back from each
thing it ran opens on a click, so the page reads as the model's reasoning with
the evidence underneath it. Work done by a helper the model started is marked
as the helper's, not the model's. Nothing here is a judgement about the run -- for
that, read the review document in the sandbox.</p>

<section class="answer">
<h2>Its answer</h2>
<p class="hint">This is the answer your criteria are graded against. When the model
replied more than once, every reply is here, in order. The grader is also shown
the steps below, as the record of what the model did.</p>
{answer_html}
</section>

<ol class="thread">{steps}</ol>

<footer>
{produced}
<p>Raw transcript: <code>{esc(trajectory)}</code></p>
<p>Task: <code>{esc(root)}</code></p>
</footer>
</div>
<script>{SCRIPT}</script>
</body>
</html>
"""


# --- where everything is ------------------------------------------------------


def where(root: Path, job: Path) -> str:
    """The paths a contributor needs after a run, resolved rather than described.

    This is what the end of a run prints.
    """
    found = [("the read of the run", root / "review" / f"{job.name}.md"),
             ("the run itself", root / "review" / f"{job.name}.html")]
    workspace = finished_workspace(job)
    if workspace:
        found.append(("the files it produced", workspace))
    trajectory = find_trajectory(job)
    if trajectory:
        found.append(("the raw transcript", trajectory))

    lines = ["  What to look at, in order:", ""]
    for number, (label, path) in enumerate(found, start=1):
        lines.append(f"    {number}. {label:<24} {path}")
        if label == "the run itself":
            lines.append("       download that file and open it in your own browser")
    return "\n".join(lines)


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
    ap.add_argument("--out", help="where to write the page")
    ap.add_argument("--where", action="store_true",
                    help="print where everything from the run is, and stop")
    ap.add_argument("--quiet", action="store_true",
                    help="write the page and say one line about it")
    args = ap.parse_args()

    root = st.task_root(args.task)
    job = find_job(root, args.job)
    if not job or not job.is_dir():
        print("No solver run found. Start one with /flc-run-solver.", file=sys.stderr)
        return 2

    if args.where:
        print(where(root, job))
        return 0

    trajectory = find_trajectory(job)
    if not trajectory:
        print(f"No transcript in {job}.\n"
              "If the run is still going, wait for it to finish:\n"
              "  bash bin/run_solver.sh --status", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else root / "review" / f"{job.name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(job, trajectory, root), encoding="utf-8")

    if args.quiet:
        print(f"  run written:    {out}  (download and open in a browser)")
    else:
        print(f"\n  wrote {out}")
        print("\n  Download that file out of the sandbox and open it in your")
        print("  own browser. It is the whole run -- what the model thought,")
        print("  what it ran, what came back, and what it answered.\n")
    warn_if_submitted(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
