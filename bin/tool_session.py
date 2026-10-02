#!/usr/bin/env python3
"""A model session that can run Python on the task's files.

The model is given one tool, run_python. Its code runs in a container started
from the task's own image, with no network, the task's files mounted read-only,
and nothing else from this machine: no environment is passed in, so the
gateway key never enters it. Each call has a time limit and its output is cut
at a length; a session has a limit on calls. Where no container can be started
the session is one plain call, and the caller records that as a fault of the
sandbox's own tooling.

A refusal is raised as `Refused` at whichever turn it comes, and every other
failure as `Unreachable`, as prompt_taxonomy raises them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

from prompt_taxonomy import (  # noqa: E402
    ANTHROPIC_VERSION, Refused, Unreachable, _FILTERED_SIGNS, _usage, call_http,
    looks_refused,
)

TOOL_NAME = "run_python"
CALL_SECONDS = 120
OUTPUT_CHARS = 20_000
MAX_CALLS = 30
# Turns allowed after the calls run out, for the model to give its answer.
GRACE_TURNS = 2
SESSION_SECONDS = 1800
REQUEST_SECONDS = 300
CPUS = "2"
MEMORY = "4g"

TOOL_DESCRIPTION = (
    "Run Python 3 code and get back what it prints, stdout and stderr together. "
    "Each call is a fresh python3 process; files written under /tmp are kept "
    "for the rest of this session. There is no network.")
SCHEMA = {"type": "object",
          "properties": {"code": {"type": "string",
                                  "description": "the Python source to run"}},
          "required": ["code"]}


class Sandbox:
    """Where run_python runs. `paths` names what is mounted, for the model."""
    paths: dict[str, str] = {}

    def run(self, code: str) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def describe(self) -> str:
        where = "; ".join(f"{what} at {path}" for what, path in self.paths.items())
        return (f"You can run Python with the {TOOL_NAME} tool, to read the task's "
                f"files whole and recompute from them. They are there read-only: "
                f"{where}. Use it wherever a check needs the data rather than the "
                f"extracts above. There is no network. You have {MAX_CALLS} calls, "
                f"each limited to {CALL_SECONDS} seconds, and output past "
                f"{OUTPUT_CHARS:,} characters is cut.")


def _cut(text: str) -> str:
    if len(text) <= OUTPUT_CHARS:
        return text
    return text[:OUTPUT_CHARS] + f"\n[... {len(text) - OUTPUT_CHARS:,} more characters cut]"


class DockerSandbox(Sandbox):
    """One container from the task's image, kept for a session."""

    def __init__(self, image: str, mounts: dict[str, Path], docker: str = "docker"):
        self.image, self.docker, self.cid = image, docker, ""
        self.mounts = {f"/{name}": Path(path) for name, path in mounts.items()
                       if Path(path).is_dir()}
        self.paths = {("the task's workspace" if target == "/workspace" else
                       "the files the run produced" if target == "/output" else target):
                      target for target in self.mounts}

    def argv(self) -> list[str]:
        out = [self.docker, "run", "-d", "--rm", "--network", "none",
               "--cpus", CPUS, "--memory", MEMORY, "--pids-limit", "512",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        for target, source in self.mounts.items():
            out += ["-v", f"{source}:{target}:ro"]
        return out + ["--entrypoint", "sleep", self.image, "infinity"]

    def start(self) -> None:
        done = subprocess.run(self.argv(), capture_output=True, text=True, timeout=120)
        if done.returncode != 0 or not done.stdout.strip():
            raise Unreachable(f"the container would not start: {done.stderr.strip()[-300:]}")
        self.cid = done.stdout.strip()

    def run(self, code: str) -> str:
        if not self.cid:
            self.start()
        try:
            done = subprocess.run([self.docker, "exec", "-i", "-w", "/tmp", self.cid,
                                   "python3", "-"], input=code, capture_output=True,
                                  text=True, timeout=CALL_SECONDS)
        except subprocess.TimeoutExpired:
            self.close()
            return (f"The call ran past {CALL_SECONDS} seconds and was stopped. "
                    "The session's files under /tmp were lost with it.")
        out = (done.stdout or "") + (done.stderr or "")
        if done.returncode:
            out += f"\n[exit status {done.returncode}]"
        return _cut(out.strip() or "(no output)")

    def close(self) -> None:
        if self.cid:
            subprocess.run([self.docker, "rm", "-f", self.cid], capture_output=True,
                           text=True, timeout=60)
            self.cid = ""


def task_image(root: Path) -> tuple[str, str]:
    """(the task's image, "") once it exists, or ("", why not).

    The image is the one build_image.sh builds; it is built when missing, which
    after a solver run reuses the build's cached layers.
    """
    docker = shutil.which("docker")
    if not docker:
        return "", "docker is not available on this machine"
    import flc_state as st  # noqa: PLC0415
    try:
        task_id = str(st.load(root).get("task_id") or "local").rsplit("-", 1)[-1]
    except Exception:  # noqa: BLE001
        task_id = "local"
    image = f"flc-task:{task_id}"
    have = subprocess.run([docker, "image", "inspect", image], capture_output=True, text=True)
    if have.returncode != 0:
        try:
            built = subprocess.run(["bash", str(BIN_DIR / "build_image.sh"), str(root),
                                    "--tag", image, "--quiet"], capture_output=True,
                                   text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            return "", "the task's image did not build within 30 minutes"
        if built.returncode != 0:
            return "", f"the task's image did not build: {built.stderr.strip()[-300:]}"
    return image, ""


def task_mounts(root: Path, job: Path | None = None) -> dict[str, Path]:
    """The task's workspace, and the files the run produced where they were kept."""
    mounts = {"workspace": root / "environment" / "workspace"}
    if job is not None:
        try:
            import solver_answer as sa  # noqa: PLC0415
            finished = sa.finished_workspace(job)
        except Exception:  # noqa: BLE001
            finished = None
        if finished is not None:
            mounts["output"] = Path(finished)
    return mounts


class Tools:
    """What one check needs to read with tools and to put statements to the vote.

    The image is made ready once, and each session gets a container of its own.
    What stopped a session having tools is kept in `faults`, for the caller to
    record as a fault of the sandbox's own tooling.
    """

    def __init__(self, root: Path, job: Path | None, key: str, base: str, shape: str,
                 usage: list | None = None, sandboxes: bool = True):
        import threading  # noqa: PLC0415
        self.root, self.job, self.key, self.base, self.shape = root, job, key, base, shape
        self.usage = usage if usage is not None else []
        self.faults: list[str] = []
        self.sessions: list[dict] = []
        self._lock = threading.Lock()
        self._image: str | None = None if sandboxes else ""
        self._why = "" if sandboxes else "sessions were asked to run without tools"

    def _fault(self, why: str) -> None:
        with self._lock:
            if why and why not in self.faults:
                self.faults.append(why)

    def sandbox(self) -> Sandbox | None:
        with self._lock:
            if self._image is None:
                self._image, self._why = task_image(self.root)
        if not self._image:
            self._fault(self._why)
            return None
        box = DockerSandbox(self._image, task_mounts(self.root, self.job),
                            shutil.which("docker") or "docker")
        try:
            box.start()
        except (Unreachable, subprocess.TimeoutExpired, OSError) as exc:
            self._fault(str(exc))
            return None
        return box

    def reading(self, message: str, models, *, system: str, prefix: str = "",
                max_tokens: int = 16000, thinking: int = 0,
                answered: list | None = None) -> str:
        """One reading with tools, moved down `models` on a refusal."""
        stats: dict = {}
        try:
            return run_models(message, models, answered=answered, make_sandbox=self.sandbox,
                              system=system, key=self.key, base=self.base, shape=self.shape,
                              prefix=prefix, max_tokens=max_tokens, thinking=thinking,
                              usage=self.usage, stats=stats)
        finally:
            with self._lock:
                self.sessions.append(dict(stats, kind="reading"))

    def vote(self, statements: list, prefix: str, seed_basis: str = "") -> dict:
        """Put the flagged statements to the slots, each voter with tools of its own."""
        import statement_vote as sv  # noqa: PLC0415
        listed = sv.list_models(self.key, self.base)

        def run_voter(model: str, message: str) -> str:
            box = self.sandbox()
            stats: dict = {}
            try:
                return run(message, system=sv.voter_system(), model=model, key=self.key,
                           base=self.base, shape=self.shape, sandbox=box, prefix=prefix,
                           max_tokens=sv.MAX_TOKENS, usage=self.usage, stats=stats)
            finally:
                if box is not None:
                    box.close()
                with self._lock:
                    self.sessions.append(dict(stats, kind="vote", model=model))

        return sv.vote(statements, run_voter, listed, seed_basis)

    def summary(self) -> dict:
        with self._lock:
            done = list(self.sessions)
        return {"sessions": len(done),
                "with_tools": sum(1 for s in done if s.get("tools")),
                "calls": sum(int(s.get("calls") or 0) for s in done),
                "capped": sum(1 for s in done if s.get("capped")),
                "faults": list(self.faults)}


# --- the loop -----------------------------------------------------------------------


def _post(url: str, payload: dict, headers: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        if exc.code == 400 and any(sign in body.lower() for sign in _FILTERED_SIGNS):
            raise Refused(f"the gateway's content filter declined it: {body[:200]}") from exc
        raise _Rejected(exc.code, body) from exc
    except Exception as exc:  # noqa: BLE001
        raise Unreachable(f"{url} did not answer ({type(exc).__name__}: {exc})") from exc


class _Rejected(Unreachable):
    def __init__(self, code: int, body: str):
        super().__init__(f"the gateway answered {code}: {body}")
        self.code, self.body = code, body


def _tool_call(sandbox: Sandbox, arguments, stats: dict) -> str:
    if stats["calls"] >= MAX_CALLS:
        stats["capped"] = True
        return ("No more calls are available in this session. Reply now with "
                "your answer, in the shape you were asked for.")
    stats["calls"] += 1
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "The call's arguments were not JSON; pass {\"code\": \"...\"}."
    code = (arguments or {}).get("code") if isinstance(arguments, dict) else None
    if not isinstance(code, str) or not code.strip():
        return "Pass the Python to run as {\"code\": \"...\"}."
    try:
        return sandbox.run(code)
    except Exception as exc:  # noqa: BLE001 -- the model is told, the session goes on
        stats["errors"] += 1
        return f"The call could not be run: {type(exc).__name__}: {exc}"


def _anthropic(message, system, model, key, base, sandbox, prefix, max_tokens,
               thinking, usage, stats, deadline) -> str:
    url = f"{base}/v1/messages"
    headers = {"content-type": "application/json", "x-api-key": key,
               "authorization": f"Bearer {key}", "anthropic-version": ANTHROPIC_VERSION}
    first = ([{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}]
             if prefix else [])
    messages = [{"role": "user", "content": first + [
        {"type": "text", "text": message + "\n\n" + sandbox.describe()}]}]
    tools = [{"name": TOOL_NAME, "description": TOOL_DESCRIPTION, "input_schema": SCHEMA}]
    grace = GRACE_TURNS
    while True:
        if time.monotonic() > deadline:
            raise Unreachable(f"the session ran past {SESSION_SECONDS} seconds")
        payload = {"model": model, "max_tokens": max_tokens + thinking,
                   "system": system, "messages": messages, "tools": tools}
        if thinking:
            payload["thinking"] = {"type": "enabled", "budget_tokens": thinking}
        try:
            data = _post(url, payload, headers)
        except _Rejected as exc:
            if thinking and exc.code == 400 and "thinking" in exc.body.lower():
                thinking = 0
                continue
            if exc.code == 400 and "cache" in exc.body.lower() and messages[0]["content"][0].get("cache_control"):
                messages[0]["content"][0].pop("cache_control", None)
                continue
            raise
        if usage is not None:
            usage.append(_usage(data))
        if data.get("stop_reason") == "refusal":
            raise Refused("the model declined to read it (stop_reason: refusal)")
        content = data.get("content") or []
        uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        if not uses:
            if data.get("stop_reason") == "max_tokens":
                raise Unreachable("the reply was cut off at max_tokens")
            return "".join(b.get("text", "") for b in content
                           if isinstance(b, dict) and b.get("type") == "text")
        if stats["capped"]:
            grace -= 1
            if grace < 0:
                raise Unreachable("the session ran out of calls without answering")
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.get("id"),
             "content": _tool_call(sandbox, b.get("input"), stats)} for b in uses]})


def _openai(message, system, model, key, base, sandbox, prefix, max_tokens, usage,
            stats, deadline) -> str:
    url = f"{base}/chat/completions"
    headers = {"content-type": "application/json", "authorization": f"Bearer {key}"}
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": prefix + message + "\n\n" + sandbox.describe()}]
    tools = [{"type": "function", "function": {"name": TOOL_NAME,
                                               "description": TOOL_DESCRIPTION,
                                               "parameters": SCHEMA}}]
    grace = GRACE_TURNS
    while True:
        if time.monotonic() > deadline:
            raise Unreachable(f"the session ran past {SESSION_SECONDS} seconds")
        data = _post(url, {"model": model, "max_tokens": max_tokens,
                           "messages": messages, "tools": tools}, headers)
        if usage is not None:
            usage.append(_usage(data))
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "content_filter":
            raise Refused("the model declined to read it (finish_reason: content_filter)")
        said = choice.get("message") or {}
        calls = said.get("tool_calls") or []
        if not calls:
            if choice.get("finish_reason") == "length":
                raise Unreachable("the reply was cut off at the token limit")
            return str(said.get("content") or "")
        if stats["capped"]:
            grace -= 1
            if grace < 0:
                raise Unreachable("the session ran out of calls without answering")
        messages.append({"role": "assistant", "content": said.get("content") or "",
                         "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            messages.append({"role": "tool", "tool_call_id": call.get("id"),
                             "content": _tool_call(sandbox, fn.get("arguments"), stats)})


def run(message: str, *, system: str, model: str, key: str, base: str, shape: str,
        sandbox: Sandbox | None, prefix: str = "", max_tokens: int = 16000,
        thinking: int = 0, usage: list | None = None, stats: dict | None = None,
        expect_json: bool = True) -> str:
    """One session on one model, returning its final reply.

    With no sandbox it is one plain call. `stats`, when given, receives the
    calls made, whether the cap was reached, and whether it ran with tools.
    """
    stats = stats if stats is not None else {}
    stats.update(calls=0, errors=0, capped=False, tools=sandbox is not None)
    if sandbox is None:
        text = call_http(message, model, key, base, shape, system, max_tokens,
                         prefix=prefix + "\n\n" if prefix else "", usage=usage,
                         thinking=thinking)
    else:
        deadline = time.monotonic() + SESSION_SECONDS
        if shape == "anthropic":
            text = _anthropic(message, system, model, key, base, sandbox,
                              prefix + "\n\n" if prefix else "", max_tokens, thinking,
                              usage, stats, deadline)
        else:
            text = _openai(message, system, model, key, base, sandbox,
                           prefix + "\n\n" if prefix else "", max_tokens, usage,
                           stats, deadline)
    if expect_json and "{" not in text and looks_refused(text):
        raise Refused("the model declined to read it")
    return text


def run_models(message: str, models, *, answered: list | None = None,
               make_sandbox=None, **kwargs) -> str:
    """One session, moved down `models` for as long as each one declines.

    As prompt_taxonomy.call_models: only a refusal moves to the next model.
    `make_sandbox()` gives each attempt a fresh sandbox, or None; each is
    closed when its attempt ends.
    """
    names = [models] if isinstance(models, str) else [m for m in models if m]
    if not names:
        raise ValueError("no model to ask")
    refused = []
    for name in names:
        sandbox = make_sandbox() if make_sandbox else None
        try:
            text = run(message, model=name, sandbox=sandbox, **kwargs)
        except Refused as exc:
            refused.append(f"{name}: {exc}")
            continue
        finally:
            if sandbox is not None:
                sandbox.close()
        if answered is not None:
            answered.append(name)
        return text
    raise Refused("every model declined to read it (" + "; ".join(refused) + ")")
