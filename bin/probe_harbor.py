#!/usr/bin/env python3
"""Find out what Harbor actually does with our task.toml. Run this on the VM.

    python3 bin/probe_harbor.py                 # the manifest we ship today
    python3 bin/probe_harbor.py --manifest 1.4  # the shape the reference task uses
    python3 bin/probe_harbor.py --manifest both # one run each, compared

Harbor is not on public PyPI and cannot be installed anywhere but the VM, so
this runs there. Four questions, in the order they matter:

1. **Does Harbor accept what we write?** We declare `schema_version = "1.1"` and
   emit `[task]`, `gpus`, `allow_internet` and `mcp_servers`, none of which
   appear in the 1.4 reference manifest -- which instead uses `network_mode`
   where we use `allow_internet`. If those keys are ignored, we are relying on
   defaults while believing we configured something.

2. **Does the verifier have a network?** This is the one with teeth. The judge
   calls a gateway and `test.sh` fails closed, so a verifier without a network
   scores every task zero and looks exactly like a model that failed. The
   reference task sets `[verifier].network_mode` for judge-graded tasks; we set
   nothing.

3. **Is what the model wrote collected?** A real run gathered `/logs/artifacts`
   and nothing else, so the finished workspace was gone before anything could
   read it. The reference manifest declares a top-level `artifacts` key for
   exactly this, and `[verifier].environment_mode = "shared"` so the verifier
   sees the live workspace and the trajectory.

4. **Does the deferral work?** `run_solver.sh` sets `FLC_DEFER_GRADING=1` and
   expects `task.toml` to carry it into the verifier through `[verifier.env]`.
   If that interpolation does not happen, the authoring run grades a
   half-written rubric, which is what this was all meant to stop.

The task it builds is tiny and asks for a file by name, so "was the file the
model wrote collected" has an unambiguous answer. It is thrown away afterwards
unless --keep.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROMPT = """Read `data/input.txt`. It contains a single integer.

Write that integer multiplied by three into `results/answer.txt`, creating the
`results` directory. Then state the result.
"""

# The multimodal variant. The number exists only as pixels: nothing in the
# workspace spells it, so an answer of 81 means something read the figure.
FIGURE_NUMBER = 27
MULTIMODAL_PROMPT = """`figures/reading.png` shows a meter display with a single
whole number on it.

Write that number multiplied by three into `results/answer.txt`, creating the
`results` directory. Then state the result, and say what the meter read.
"""

# A 5x7 cell per digit, scaled up when drawn. Hand-rolled, so the image builds
# on a VM without Pillow.
_DIGITS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}

# The 1.4 shape, from agent_smith_vm_qh1's reference task and rules document.
# `artifacts` to retain the workspace, `environment_mode = "shared"` to give the
# verifier the finished workspace and /logs/agent/trajectory.json, and a network
# for the judge's API calls.
MANIFEST_14 = """schema_version = "1.4"
artifacts = [
  {{ source = "/workspace" }},
]

[metadata]

[agent]
timeout_sec = 1800.0
network_mode = "public"

[verifier]
timeout_sec = 600.0
environment_mode = "shared"
network_mode = "public"

[environment]
os = "linux"
network_mode = "public"
build_timeout_sec = 1800.0
cpus = 2
memory_mb = 4096
storage_mb = 20480

[verifier.env]
EVAL_API_KEY = "${{OPENAI_API_KEY}}"
EVAL_BASE_URL = "${{OPENAI_API_BASE}}"
EVAL_MODEL = "${{EVAL_MODEL:-anthropic/claude-opus-4-5-20251101}}"
FLC_DEFER_GRADING = "${{FLC_DEFER_GRADING:-0}}"
"""


def write_number_png(path: Path, number: int, scale: int = 16) -> None:
    """Draw `number` as a grayscale PNG, using only the standard library."""
    import binascii
    import struct
    import zlib

    glyphs = [_DIGITS[c] for c in str(number)]
    pad, gap = 3, 2
    cols = sum(len(g[0]) for g in glyphs) + gap * (len(glyphs) - 1) + pad * 2
    rows = len(glyphs[0]) + pad * 2
    cells = [[0] * cols for _ in range(rows)]
    x = pad
    for glyph in glyphs:
        for r, line in enumerate(glyph):
            for c, bit in enumerate(line):
                if bit == "1":
                    cells[pad + r][x + c] = 1
        x += len(glyph[0]) + gap

    raw = bytearray()
    for row in cells:
        for _ in range(scale):
            raw.append(0)  # PNG filter type 0 for this scanline
            for cell in row:
                raw.extend(bytes([0 if cell else 235]) * scale)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF))

    width, height = cols * scale, rows * scale
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n {title}\n{'=' * 70}")


def cli_surface(report: dict) -> None:
    """Harbor's own help, recorded verbatim.

    Worth having whatever else happens: every question here is really "what does
    this build of Harbor support", and the help text is the only documentation
    available outside the VM.
    """
    section("1. What this Harbor is")
    version = run(["harbor", "--version"])
    print(f"  version: {version.stdout.strip() or version.stderr.strip() or '(unknown)'}")
    report["version"] = version.stdout.strip()
    for args in (["harbor", "--help"], ["harbor", "run", "--help"]):
        out = run(args)
        report["help"][" ".join(args)] = out.stdout + out.stderr
    # The levers this probe is about. If the build knows them, the help text
    # says so.
    helptext = "\n".join(report["help"].values())
    for word in ("artifacts", "environment_mode", "network_mode", "schema",
                 "collect", "validate"):
        print(f"  mentions {word!r}: {word in helptext}")


def source_tree() -> Path:
    """The sandbox tree to probe, in either layout this script lives in.

    On the VM the seed *is* the tree -- this file sits in its `bin/` alongside
    `template_task/`. In the repository the same file sits at the root, with the
    trees beside it. Neither layout is assumed.
    """
    if (ROOT / "template_task").is_dir():
        return ROOT
    return ROOT / "flc_vm_rubrics_only"


def build_task(home: Path, manifest: str, multimodal: bool = False) -> Path:
    """A scaffolded task with one input and one requested output."""
    tree = source_tree()
    if not (tree / "template_task").is_dir():
        sys.exit(f"no sandbox tree found at {tree}")
    shutil.copytree(tree, home, dirs_exist_ok=True)
    task = home / "task"
    env = dict(os.environ, FLC_HOME=str(home), FLC_TASK=str(task))
    run([sys.executable, str(home / "bin" / "flc_scaffold.py"), str(task)], env=env)

    workspace = task / "environment" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    for stray in workspace.glob("PUT_YOUR_FILES_HERE.txt"):
        stray.unlink()
    rubrics = task / "tests" / "rubrics.md"
    required = "figures/reading.png" if multimodal else "data/input.txt"
    if multimodal:
        (workspace / "figures").mkdir(exist_ok=True)
        write_number_png(workspace / "figures" / "reading.png", FIGURE_NUMBER)
        (task / "prompt.md").write_text(MULTIMODAL_PROMPT)
        answer = FIGURE_NUMBER * 3
        rubrics.write_text(
            "## Completion\n\n"
            f"- [5] Response states that the result is {answer}\n"
            f"- [3] A file results/answer.txt exists and contains {answer}\n\n"
            "## Non-hallucination\n\n"
            f"- [-5] Response states a result other than {answer}\n"
            f"- [-5] Response states a meter reading other than {FIGURE_NUMBER}\n"
        )
    else:
        (workspace / "data").mkdir(exist_ok=True)
        (workspace / "data" / "input.txt").write_text("14\n")
        (task / "prompt.md").write_text(PROMPT)
        rubrics.write_text(
            "## Completion\n\n"
            "- [5] Response states that the result is 42\n"
            "- [3] A file results/answer.txt exists and contains 42\n\n"
            "## Non-hallucination\n\n"
            "- [-5] Response states a result other than 42\n"
        )
    run([sys.executable, str(home / "bin" / "rubrics_build.py")], env=env)
    run([sys.executable, str(home / "bin" / "flc_state.py"), "regenerate"], env=env)

    # run_solver.sh will not start until check_inputs has passed, so the probe
    # takes that step rather than around it: a run started by a route no
    # contributor has would stop being evidence about the workflow they use.
    checked = run([sys.executable, str(home / "bin" / "check_inputs.py"),
                   "--required", required], env=env)
    if checked.returncode != 0:
        sys.exit("check_inputs refused the probe's own task, so no run can start:\n"
                 + (checked.stdout or checked.stderr))

    if manifest == "1.4":
        (task / "task.toml").write_text(MANIFEST_14)

    # Let the verifier grade, so "can it reach the judge" gets a real answer.
    toml = task / "task.toml"
    text = toml.read_text()
    if "FLC_GRADE_NOW" not in text:
        text = text.replace('FLC_DEFER_GRADING = "${FLC_DEFER_GRADING:-0}"',
                            'FLC_DEFER_GRADING = "${FLC_DEFER_GRADING:-0}"\n'
                            'FLC_GRADE_NOW = "${FLC_GRADE_NOW:-0}"')
        toml.write_text(text)
    print(f"  task built at {task} with the {manifest} manifest")
    return task


def solve(home: Path, task: Path, report: dict) -> Path | None:
    """One run, in the foreground, with grading left on.

    Grading is *not* deferred here. Whether the verifier can reach the gateway
    is only visible if the judge is allowed to try.
    """
    section("2. One run, start to finish")
    # `run_solver.sh` exports FLC_DEFER_GRADING=1 unconditionally, so removing
    # it from this environment achieves nothing. FLC_GRADE_NOW is the override
    # test.sh honours, and build_task() adds it to [verifier.env] so it reaches
    # the container.
    env = dict(os.environ, FLC_HOME=str(home), FLC_TASK=str(task),
               FLC_GRADE_NOW="1")
    started = time.time()
    out = run(["bash", str(home / "bin" / "run_solver.sh"), "--attempts", "1"], env=env)
    report["run"] = {
        "returncode": out.returncode,
        "seconds": round(time.time() - started, 1),
        "stdout_tail": out.stdout[-6000:],
        "stderr_tail": out.stderr[-6000:],
    }
    print(f"  exit {out.returncode} after {report['run']['seconds']}s")

    blob = (out.stdout + out.stderr).lower()
    # Harbor rejecting a key is the answer to question 1, and it is the kind of
    # thing that scrolls past in a long log.
    complaints = [line for line in (out.stdout + out.stderr).splitlines()
                  if any(w in line.lower() for w in
                         ("unknown field", "unexpected key", "unrecognized",
                          "not permitted", "invalid", "schema", "validation"))]
    report["manifest_complaints"] = complaints[:40]
    print(f"  complaints about the manifest: {len(complaints)}")
    for line in complaints[:8]:
        print(f"    {line.strip()[:120]}")
    if "no such option" in blob or "usage:" in blob:
        print("  NOTE: a CLI argument was rejected -- see the tail in the report")

    state = json.loads((task / ".flc" / "state.json").read_text())
    job = state.get("last_job")
    return Path(job) if job and Path(job).is_dir() else None


def multimodal_answers(job: Path, rels: list[str], found) -> None:
    """Did the solver read the figure, and did it read it by looking?

    The number is only in the pixels, so a correct answer means something
    decoded the image -- but that something could be a script the agent wrote,
    which would answer a different question than the one being asked. The
    trajectory settles how, and only in one direction: a command naming the file
    proves a program was involved, while the absence of one is weak evidence
    (`cat figures/*` names nothing). So the two are reported separately rather
    than collapsed into a verdict.
    """
    expected = str(FIGURE_NUMBER * 3)
    answers = [p for p in job.rglob("*/answer.txt")]
    text = ""
    for path in answers:
        try:
            text = path.read_text(errors="replace").strip()
        except OSError:
            continue
        break
    found("the solver read the number in the figure", expected in text,
          f"results/answer.txt says {text[:40]!r}, expected {expected}"
          if text else "no answer file came back, so this is unanswered")

    trajectory = next((p for p in job.rglob("trajectory.json")), None)
    blob = ""
    if trajectory is not None:
        try:
            blob = trajectory.read_text(errors="replace").lower()
        except OSError:
            blob = ""
    tools = [w for w in ("pil", "pillow", "opencv", "cv2", "tesseract", "ocr",
                         "imagemagick", "convert ", "xxd", "base64 ")
             if w in blob]
    found("it decoded the figure with a program instead", bool(tools),
          f"the trajectory mentions {', '.join(tools)}" if tools
          else "no image-decoding tool appears in the trajectory -- weak "
               "evidence, since a command need not name what it reads")


def inspect(job: Path, report: dict) -> None:
    section("3. What came back")
    files = sorted(p for p in job.rglob("*") if p.is_file())
    report["job"] = {"path": str(job), "file_count": len(files)}
    report["job_tree"] = [str(p.relative_to(job)) for p in files[:400]]
    print(f"  {len(files)} file(s) under {job}")
    for rel in report["job_tree"][:40]:
        print(f"    {rel}")
    if len(files) > 40:
        print(f"    ... {len(files) - 40} more (full list in the report)")

    def found(label: str, hit: bool, why: str) -> None:
        report["answers"][label] = hit
        print(f"  [{'YES' if hit else 'NO '}] {label} -- {why}")

    section("4. The four questions")
    rels = report["job_tree"]

    found("the trajectory was collected",
          any("trajectory" in r for r in rels),
          "the judge and every review tool read the run from it")

    # A path component of exactly `workspace`, not a substring. The agent's own
    # session directory is `agent/sessions/projects/-workspace/`, which matched
    # a substring test and reported a collected workspace on a run that brought
    # back none -- the exact false positive this probe exists to rule out.
    workspace_like = [r for r in rels if "workspace" in Path(r).parts]
    found("the finished workspace was collected", bool(workspace_like),
          f"{len(workspace_like)} path(s) under a workspace directory")

    produced = [r for r in rels if r.endswith("answer.txt")]
    found("the file the model was asked to write came back", bool(produced),
          produced[0] if produced else "results/answer.txt is nowhere in the job")

    if report.get("multimodal"):
        multimodal_answers(job, rels, found)

    graded = [r for r in rels if r.endswith("evaluation_results.json")]

    summaries = [p for p in job.rglob("grading_summary.json")]
    status = rubrics_status = None
    for path in summaries:
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        status = payload.get("status")
        rubrics_status = payload.get("rubrics")
        report["answers"]["grading_status"] = status
        break

    # `unreachable` is the sharpest evidence the run can produce: the judge got
    # far enough to open a connection, which means it was handed an endpoint and
    # a key, and the connection is what failed.
    found("the verifier reached the judge", bool(graded),
          "per-criterion results exist, so the verifier had a network and "
          "credentials" if graded
          else "the judge had credentials and could not reach the endpoint"
          if rubrics_status == "unreachable"
          else "no evaluation_results.json -- either the verifier had no "
               "network, or grading was deferred")

    if status is not None:
        # Three of these prove the interpolation. `deferred` means
        # FLC_DEFER_GRADING arrived as "1" and `graded` means FLC_GRADE_NOW did;
        # `error` means the EVAL_ credentials arrived, since the judge exits
        # before opening a connection without them. What it cannot be, if
        # [verifier.env] works at all, is missing.
        found("[verifier.env] interpolation works",
              status in ("graded", "deferred")
              or rubrics_status == "unreachable",
              f"grading_summary.json says {status!r}, so a variable set on the "
              "host reached test.sh inside the verifier")
        if status == "deferred":
            print("  NOTE: grading was deferred, so 'the verifier reached the "
                  "judge' above is unanswered rather than False.")
        if rubrics_status == "unreachable":
            print("  NOTE: the verifier has no route to the gateway. Grading on"
                  " request\n        (bin/run_grader.py) goes through the host "
                  "network instead.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", choices=("current", "1.4", "both"), default="current")
    ap.add_argument("--keep", action="store_true", help="leave the task behind")
    ap.add_argument("--multimodal", action="store_true",
                    help="put the number in a figure instead of a text file, "
                         "so a right answer means the solver can see images")
    ap.add_argument("--out", default="harbor_probe.json")
    args = ap.parse_args()

    if not shutil.which("harbor"):
        print("harbor is not on PATH. This probe only means anything on the VM.",
              file=sys.stderr)
        return 2

    variants = ["current", "1.4"] if args.manifest == "both" else [args.manifest]
    reports = {}
    for variant in variants:
        report: dict = {"manifest": variant, "help": {}, "answers": {},
                        "multimodal": args.multimodal}
        home = Path(tempfile.mkdtemp(prefix=f"flc-probe-{variant}-"))
        try:
            cli_surface(report)
            task = build_task(home, variant, multimodal=args.multimodal)
            job = solve(home, task, report)
            if job is None:
                print("\n  no job directory was recorded -- the run did not start.")
                print("  The stdout tail in the report says why.")
            else:
                inspect(job, report)
        finally:
            reports[variant] = report
            if not args.keep:
                shutil.rmtree(home, ignore_errors=True)

    out = Path(args.out).resolve()
    out.write_text(json.dumps(reports, indent=2, sort_keys=True) + "\n")
    section("Verdict")
    for variant, report in reports.items():
        print(f"  {variant}:")
        for label, value in report.get("answers", {}).items():
            print(f"    {label}: {value}")
        if report.get("manifest_complaints"):
            print(f"    Harbor complained {len(report['manifest_complaints'])} time(s)")
    print(f"\n  full report: {out}")
    print("  Send this back and the manifest gets fixed from it rather than guessed at.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
