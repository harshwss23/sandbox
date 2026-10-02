#!/usr/bin/env python3
"""Step 2 gate: is the material here, and can the image read it?

Checks, in the order a contributor cares about them:

  1. there are files, and the placeholder is gone
  2. prompt.md has been written
  3. the prompt does not give away which files matter or what the answer is
  4. there is enough material to be worth running against
  5. every file can actually be opened with what the base image ships

Only the amount of material is estimated here, and nothing is decided on it.
What a task puts in front of the model is measured from the finished run by
context_report.py.

Usage:
    check_inputs.py                     report on the current task
    check_inputs.py --required a.csv b/c.tsv    record which files are needed
    check_inputs.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_integrity  # noqa: E402
import flc_state as st  # noqa: E402
import prompt_check  # noqa: E402  -- for the recorded difficulty verdict

# Extensions the base image can open, mapped to what opens them. Anything not
# listed is reported as unknown rather than as broken.
READABLE = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".xml", ".html", ".log", ".py", ".r", ".sh", ".sql", ".ipynb", ".bed",
    ".gtf", ".gff", ".fa", ".fasta", ".fq", ".fastq", ".vcf", ".sam", ".pdb",
    ".xlsx", ".xls", ".docx", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".svg",
    ".h5", ".hdf5", ".h5ad", ".nc", ".parquet", ".zarr", ".npy", ".npz",
    ".gz", ".bz2", ".xz", ".zip", ".bam", ".bai", ".cram", ".bw", ".bigwig",
    ".rds", ".rdata", ".mtx", ".db", ".sqlite",
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".svg"}
TEXT_EXT = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".xml", ".html", ".log", ".py", ".r", ".sh", ".sql", ".bed", ".gtf", ".gff",
    ".fa", ".fasta", ".fq", ".fastq", ".vcf", ".sam", ".pdb", ".mtx",
}

# Claude reads an image as 28x28-pixel patches, so it costs
# ceil(w/28) * ceil(h/28) visual tokens, after being downscaled to fit both a
# long-edge limit and a token cap. Standard tier below; the high-resolution
# tier allows 2576px / 4784 tokens. Computed per image rather than approximated:
# a 200x200 figure costs 64 tokens and a 2000x1500 one costs 1564.
PATCH_PX = 28
MAX_LONG_EDGE = 1568
MAX_VISUAL_TOKENS = 1568
# SVG is markup and is counted as text.
RASTER_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"}

# The package a file of this type usually needs, so the check can name it.
# Not exhaustive: whatever the solver installs for itself is reported after the
# run by detect_packages.py.
FORMAT_PACKAGES = {
    ".fits": ["astropy"], ".fit": ["astropy"],
    ".h5ad": ["anndata"], ".loom": ["anndata"],
    ".bam": ["pysam"], ".sam": ["pysam"], ".cram": ["pysam"],
    ".vcf": ["pysam"], ".bcf": ["pysam"],
    ".fastq": ["biopython"], ".fq": ["biopython"], ".fasta": ["biopython"],
    ".fa": ["biopython"], ".gb": ["biopython"], ".genbank": ["biopython"],
    ".sdf": ["rdkit"], ".mol": ["rdkit"], ".mol2": ["rdkit"], ".smi": ["rdkit"],
    ".pdb": ["biopython"], ".cif": ["biopython"],
    ".dta": ["pandas"], ".sav": ["pyreadstat"], ".por": ["pyreadstat"],
    ".rdata": ["pyreadr"], ".rds": ["pyreadr"],
    ".mat": ["scipy"], ".nc": ["netCDF4"], ".nc4": ["netCDF4"],
    ".h5": ["h5py"], ".hdf5": ["h5py"],
    ".parquet": ["pyarrow"], ".feather": ["pyarrow"], ".orc": ["pyarrow"],
    ".dcm": ["pydicom"], ".nii": ["nibabel"],
    ".shp": ["geopandas"], ".geojson": ["geopandas"], ".gpkg": ["geopandas"],
    ".docx": ["python-docx"], ".doc": ["python-docx"],
    ".pptx": ["python-pptx"], ".pdf": ["pdfplumber"],
    ".dwg": ["ezdxf"], ".dxf": ["ezdxf"],
    ".mp3": ["pydub"], ".wav": ["soundfile"], ".flac": ["soundfile"],
    ".mp4": ["opencv-python-headless"], ".avi": ["opencv-python-headless"],
}


def image_size(path: Path) -> tuple[int, int] | None:
    """Pixel dimensions from the file header, without decoding the image.

    Pillow when it is installed, header parsing when it is not: this runs at
    input-check time on a contributor's machine, and a missing dependency must
    not silently change what the token gate measures.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except ImportError:
        pass
    except Exception:
        return None

    try:
        head = path.open("rb").read(32)
    except OSError:
        return None
    try:
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:3] == b"GIF":
            return struct.unpack("<HH", head[6:10])
        if head[:2] == b"BM":
            with path.open("rb") as f:
                f.seek(18)
                return struct.unpack("<ii", f.read(8))
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            with path.open("rb") as f:
                data = f.read(40)
            if data[12:16] == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if data[12:16] == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if data[12:16] == b"VP8X":
                w = int.from_bytes(data[24:27], "little") + 1
                h = int.from_bytes(data[27:30], "little") + 1
                return w, h
            return None
        if head[:2] == b"\xff\xd8":  # JPEG: walk the segments to find SOFn
            with path.open("rb") as f:
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    size = struct.unpack(">H", f.read(2))[0]
                    if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                        h, w = struct.unpack(">HH", f.read(5)[1:])
                        return w, h
                    f.seek(size - 2, 1)
        if head[:2] in (b"II", b"MM"):  # TIFF
            endian = "<" if head[:2] == b"II" else ">"
            with path.open("rb") as f:
                raw = f.read(65536)
            offset = struct.unpack(endian + "I", raw[4:8])[0]
            count = struct.unpack(endian + "H", raw[offset:offset + 2])[0]
            dims: dict[int, int] = {}
            for i in range(count):
                entry = offset + 2 + i * 12
                tag, typ = struct.unpack(endian + "HH", raw[entry:entry + 4])
                if tag in (256, 257):
                    fmt = "I" if typ == 4 else "H"
                    dims[tag] = struct.unpack(endian + fmt, raw[entry + 8:entry + 8 + struct.calcsize(fmt)])[0]
            if 256 in dims and 257 in dims:
                return dims[256], dims[257]
    except Exception:
        return None
    return None


def visual_tokens(width: int, height: int) -> int:
    """What an image of this size costs, after the downscale Claude applies.

    Scales to the largest size that satisfies both the long-edge limit and the
    token cap, which is what the published per-size table reflects.
    """
    if width <= 0 or height <= 0:
        return 0
    long_edge = max(width, height)
    for scaled in range(min(long_edge, MAX_LONG_EDGE), 0, -1):
        factor = scaled / long_edge
        w = max(1, round(width * factor))
        h = max(1, round(height * factor))
        tokens = -(-w // PATCH_PX) * -(-h // PATCH_PX)
        if tokens <= MAX_VISUAL_TOKENS:
            return tokens
    return 1


# --- how much material is here, roughly -------------------------------------
#
# Crude, and it decides nothing. The number the floor is enforced against is
# measured after the run by context_report.py.
#
# What this step answers is whether there is so little material that no run
# could reach the floor. The threshold below is set far away from it.
CHARS_PER_TOKEN = 4

# Amplification from file content to measured context has run between about 1.2x
# on material that is simply read and about 4.7x where the analysis is intricate
# and the model's own working dominates. Below this, no multiplier observed so
# far reaches the floor.
MATERIAL_WARN_TOKENS = 5_000

# Decimal megabytes, the unit a file browser shows. A warning, never a refusal.
WORKSPACE_HEAVY_MB = 500
HEAVY_MESSAGE = (
    "We don't recommend workspaces over 500 MB. It isn't a hard limit, and a "
    "little over (say 600 MB) may still work, but a heavy workspace makes the "
    "sandbox slow to work in and can make the task fail to collect when you "
    "finish.")

# A table is queried rather than read, so what it contributes stops growing with
# its length: an agent prints a shape, a head, and the groups it needs. Counted
# at the cap below rather than at full volume.
TABULAR_EXT = {".csv", ".tsv", ".parquet", ".xlsx", ".xls"}
TABULAR_CAP_TOKENS = 2_000

ZIP_XML_EXT = {".xlsx": "xl/", ".docx": "word/", ".pptx": "ppt/"}
_XML_TAG = re.compile(rb"<[^>]+>")


def _text_of_zip_xml(path: Path, prefix: str) -> str:
    """The readable text inside an Office file.

    xlsx, docx and pptx are zipped XML, so this needs no third-party package.
    Returning 0 for them is what the old counter did, and a workspace of four
    spreadsheets therefore measured as empty.
    """
    import zipfile
    out = []
    try:
        with zipfile.ZipFile(path) as bundle:
            for name in bundle.namelist():
                if not name.startswith(prefix) or not name.endswith(".xml"):
                    continue
                try:
                    raw = bundle.read(name)
                except (OSError, zipfile.BadZipFile, KeyError):
                    continue
                out.append(_XML_TAG.sub(b" ", raw).decode("utf-8", "replace"))
    except (OSError, zipfile.BadZipFile):
        return ""
    return " ".join(out)


NO_PDF_READER = "pdf (no PDF reader on this machine, not counted)"

# Tried in order. pdfplumber is in most domains' package lists, so it is the
# one most often installed on the sandbox itself; pypdf is installed for every
# domain by provisioning.
PDF_READERS = ("pdfplumber", "pypdf", "PyPDF2")


def pdf_reader() -> str | None:
    """The first PDF library this machine can import, or None."""
    for module in PDF_READERS:
        try:
            __import__(module)
        except ImportError:
            continue
        return module
    return None


def _text_of_pdf(path: Path) -> str:
    for module in PDF_READERS:
        try:
            lib = __import__(module)
        except ImportError:
            continue
        try:
            if module == "pdfplumber":
                with lib.open(str(path)) as pdf:
                    return "\n".join((page.extract_text() or "") for page in pdf.pages)
            pdf = lib.PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
        except Exception:
            continue
    return ""


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN) if text else 0


def _sampled(text: str) -> int:
    """What a table contributes: a shape and a sample, not all of its rows."""
    return min(estimate_tokens(text), TABULAR_CAP_TOKENS)


def file_tokens(path: Path) -> tuple[int, str]:
    """Roughly what this file is worth in context, and how that was arrived at."""
    suffix = path.suffix.lower()
    if suffix in RASTER_EXT:
        size = image_size(path)
        if size is None:
            return 0, "image (dimensions unreadable, not counted)"
        w, h = size
        return visual_tokens(w, h), f"image {w}x{h}"
    if suffix in ZIP_XML_EXT:
        text = _text_of_zip_xml(path, ZIP_XML_EXT[suffix])
        if not text:
            return 0, "office file (unreadable, not counted)"
        n = _sampled(text) if suffix in TABULAR_EXT else estimate_tokens(text)
        return n, "office file (sampled)" if suffix in TABULAR_EXT else "office file"
    if suffix == ".pdf":
        text = _text_of_pdf(path)
        if text.strip():
            return estimate_tokens(text), "pdf"
        if pdf_reader() is None:
            return 0, NO_PDF_READER
        return 0, "pdf (no text layer, not counted)"
    if suffix in TEXT_EXT or suffix == "" or suffix == ".svg":
        try:
            text = path.read_text(errors="replace")
        except OSError as exc:
            return 0, f"unreadable ({exc}), not counted"
        if suffix in TABULAR_EXT:
            return _sampled(text), "table (sampled)"
        return estimate_tokens(text), "text"
    return 0, "binary (not counted)"


STATE_KEY = "input_check"


def workspace_digest(root: Path) -> str:
    """The digest of the manifest describing the workspace as it stands now.

    tests/inputs_manifest.json rather than the files themselves, so the one
    digest is comparable with GRADE_INPUTS["workspace"] at the run, the grade
    and the delivery. Callers refresh the manifest first.
    """
    return st.sha256_file(root / st.GRADE_INPUTS["workspace"])


def record(root: Path, files: int) -> dict:
    """Write which workspace passed the check into the task state."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": "PASS",
        "files": files,
        "workspace_sha256": workspace_digest(root),
    }
    state = st.load(root)
    state[STATE_KEY] = entry
    st.save(root, state)
    return entry


def recorded(root: Path, state: dict) -> tuple[dict | None, bool]:
    """The recorded pass, and whether it was taken against this workspace.

    A workspace that changed after the check passed is the gap this closes:
    steps_done alone said a check had happened without saying what it looked
    at, so material nobody had checked could reach both the run and the bundle.
    """
    entry = state.get(STATE_KEY)
    if not isinstance(entry, dict) or entry.get("verdict") != "PASS":
        return None, False
    return entry, entry.get("workspace_sha256") == workspace_digest(root)


def check(root: Path, required: list[str] | None) -> dict:
    state = st.load(root)
    # prompt.md has just been edited by hand; instruction.md is generated from
    # it and would otherwise still hold whatever it said at scaffold time. The
    # manifest is regenerated for the same reason, and because what passes here
    # is recorded as a digest of it.
    st.write_instruction(root)
    st.write_inputs_manifest(root)
    if required is not None:
        known = set(st.workspace_files(root))
        unknown = [f for f in required if f not in known]
        if unknown:
            raise SystemExit(
                "these files are not in environment/workspace/:\n  "
                + "\n  ".join(unknown)
            )
        state["required_files"] = sorted(required)
        state["distractor_files"] = sorted(known - set(required))
        st.save(root, state)

    files = st.workspace_files(root)
    findings: list[dict] = []

    def add(level: str, title: str, detail: str = "", fix: str = "") -> None:
        findings.append({"level": level, "title": title, "detail": detail, "fix": fix})

    # 1. files present
    if not files:
        add("FAIL", "No files uploaded",
            "environment/workspace/ is empty.",
            "Upload your zip into environment/workspace/, then run /flc-unpack.")
    elif (root / "environment" / "workspace" / "PUT_YOUR_FILES_HERE.txt").exists():
        add("WARN", "The placeholder file is still there",
            "PUT_YOUR_FILES_HERE.txt would be visible to the model.",
            "Delete environment/workspace/PUT_YOUR_FILES_HERE.txt.")

    # 1b. leftovers from unpacking the upload. Files are uploaded as one zip and
    # unzipped in place, so the archive and macOS's __MACOSX sidecar are both
    # easy to leave behind -- and both would be shown to the model as task
    # material and counted towards the context floor.
    macosx = [f for f in files if f.split("/")[0] == "__MACOSX"]
    if macosx:
        add("WARN", "__MACOSX is still in the workspace",
            f"{len(macosx)} file(s) macOS added when the zip was made.",
            "Run /flc-unpack, which clears these out.")
    zips = [f for f in files if f.lower().endswith(".zip")]
    if zips:
        add("WARN", "There is a .zip in the workspace",
            ", ".join(zips[:5]),
            "If this is the archive you uploaded, run /flc-unpack -- it unpacks "
            "it and deletes it. Left alone the model sees every file twice. If "
            "it is task material the model is meant to open, leave it.")

    # 1b'. size.
    sizes = []
    for rel in files:
        try:
            sizes.append(((root / "environment" / "workspace" / rel).stat().st_size, rel))
        except OSError:
            continue
    total_mb = sum(s for s, _ in sizes) / 1_000_000
    if total_mb > WORKSPACE_HEAVY_MB:
        largest = ", ".join(f"{rel} ({size / 1_000_000:,.0f} MB)"
                            for size, rel in sorted(sizes, reverse=True)[:3])
        add("WARN", f"The workspace is heavy ({total_mb:,.0f} MB)",
            f"{HEAVY_MESSAGE} Largest files: {largest}.")

    # 1c. the answer, uploaded with the material by mistake.
    #
    # Only environment/ reaches the model: the ground truth and the rubrics sit
    # outside it and are never copied into the image. The one way round that is
    # to put a copy inside the workspace, which hands the model the answer and
    # ships it in the bundle as task material. Both halves of the task would
    # then be measuring nothing, and the run would look like a model that did
    # very well.
    leaked = [f for f in files
              if re.search(r"ground.?truth|rubric|answer.?key|\bsolution\b",
                           Path(f).name, re.I)]
    if leaked:
        add("FAIL", "The answer looks like it is in the workspace",
            ", ".join(leaked[:5]) + " -- the model reads everything in "
            "environment/workspace/.",
            "Move these out of environment/workspace/. The ground truth belongs "
            "in solution/ground_truth.md and the criteria in tests/rubrics.md, "
            "neither of which the model can see. If the name is a coincidence "
            "and the file really is task material, rename it.")

    # 2. prompt written
    prompt = st.contributor_prompt(root)
    if not prompt:
        add("FAIL", "No prompt written",
            "prompt.md is empty once the template guidance is stripped.",
            "Open prompt.md, delete everything in it, and write your prompt.")
    elif len(prompt) < 80:
        add("WARN", "The prompt is very short",
            f"{len(prompt)} characters.",
            "A one-line prompt rarely leaves room for the model to go wrong in "
            "an interesting way.")

    # 3. prompt does not do the model's work for it
    if prompt:
        named = [f for f in files if f and f in prompt]
        if named:
            add("WARN", "The prompt names files directly",
                "mentions " + ", ".join(named[:5]),
                "Working out which files matter is the task. Describe what you "
                "want, not where it is.")
        if re.search(r"^\s*(?:#+\s|task:|requirements?:|steps?:|\d+[.)]\s)",
                     prompt, re.IGNORECASE | re.MULTILINE):
            add("WARN", "The prompt reads like a specification",
                "It has headings, numbered steps or a 'Task:' label.",
                "Rewrite it as a message to a colleague.")

    # 3b. the difficulty bar, read from what /flc-prompt-check recorded.
    #
    # Read rather than taken here: classifying costs three model calls, and this
    # command is run repeatedly while a workspace is being assembled. A verdict
    # taken against a different prompt is treated as no verdict at all.
    if prompt:
        entry, current = prompt_check.recorded(state, prompt)
        if entry is None:
            add("FAIL", "Nobody has checked whether the prompt is hard enough",
                "The bar is that someone outside your field could not work out "
                "what the prompt is asking, or what would count as answering it.",
                "Run /flc-prompt-check, then run this again.")
        elif not current:
            add("FAIL", "The prompt has changed since it was checked",
                f"The recorded verdict was {entry['verdict']}, taken against an "
                "earlier version of prompt.md.",
                "Run /flc-prompt-check again, then run this again.")
        elif entry["verdict"] == "UNMEASURED":
            add("WARN", "The prompt could not be checked",
                entry.get("why", "nothing was classified") + ".",
                "This is a technical issue on our side, not your task, and it "
                "is not holding you up. /flc-prompt-check once more, then carry on.")
        elif entry["verdict"] == "FAIL":
            add("FAIL", "The prompt is not hard enough", entry.get("why", ""),
                "Edit prompt.md so that answering it takes someone in your "
                "field: your own data rather than a public dataset, a judgement "
                "between readings that look equally reasonable, or a convention "
                "an outsider would not know to apply. Then run /flc-prompt-check "
                "again. /flc-prompt-check prints what it read the prompt as "
                "asking, which is the place to start.")
        else:
            add(entry["verdict"], f"The prompt reads as Level {entry['level']} work",
                entry.get("why", ""),
                "Run /flc-prompt-check to see the reasoning behind this.")

    # 4. the 32k floor
    #
    # Counted over everything in the workspace, not just the files that carry
    # the answer. A distractor the agent has to open and rule out is real
    # context work -- that is what a distractor is for -- so excluding them
    # would measure something narrower than the job the model actually faces.
    per_file = []
    for rel in files:
        n, kind = file_tokens(root / "environment" / "workspace" / rel)
        per_file.append({"file": rel, "tokens": n, "kind": kind,
                         "required": rel in set(state["required_files"])})
    if not state["required_files"]:
        add("FAIL", "Nobody has said which files are needed to solve the task",
            "The split between the files carrying the answer and the rest is "
            "what makes the task reviewable.",
            "Answer the question the command asks, or rerun with "
            "--required file1 file2 ...")
    else:
        total = sum(f["tokens"] for f in per_file)
        required_total = sum(f["tokens"] for f in per_file if f["required"])
        state["material_estimate"] = total
        state["required_estimate"] = required_total
        st.save(root, state)

        split = (f"roughly {total:,} tokens of material across {len(per_file)} "
                 f"file(s) -- {required_total:,} in the "
                 f"{len(state['required_files'])} needed to solve it, "
                 f"{total - required_total:,} in the rest")
        uncounted = [f["file"] for f in per_file if "not counted" in f["kind"]]
        if total < MATERIAL_WARN_TOKENS:
            detail = f"{split}."
            if uncounted:
                detail += (f" {len(uncounted)} file(s) could not be read here "
                           f"({', '.join(uncounted[:3])}) and may carry more.")
            add("WARN", "There may not be enough here to make a long-context task",
                detail,
                "Add material the question cannot be answered without, or material "
                "a careful reader would have to open before ruling it out. The real "
                "figure is measured after /flc-run-solver, and that is the one that "
                "has to clear the floor.")
        else:
            add("PASS", "There is a reasonable amount of material here", split + ".",
                "This is an estimate from the files. What counts is how much of it "
                "the model ends up holding, which /flc-run-solver measures.")

        # Every file mattering means there is nothing to triage, and triage is
        # where the interesting failures live.
        if not state["distractor_files"]:
            add("WARN", "Every file is needed to solve the task",
                "There is nothing here the model has to open and set aside.",
                "Consider adding material that looks relevant and is not -- a "
                "stale version, a neighbouring cohort, a near-miss identifier.")

    # A file nothing could read is invisible to every check that reads the
    # workspace, whichever list it is on. Which of the two causes it is decides
    # whose problem it is.
    ours = [f["file"] for f in per_file if f["kind"] == NO_PDF_READER]
    if ours:
        st.record_issue(root, "no_pdf_reader",
                        f"no PDF library importable; unread: {', '.join(ours)}",
                        "check_inputs.py")
        add("WARN", "Some PDFs could not be read by this check",
            f"{', '.join(ours[:5])}{' and more' if len(ours) > 5 else ''}. This "
            "is a technical issue on our side, not a problem with your files.",
            "Nothing to do: it does not stop you, the model can still open them, "
            "and it has been noted for the project team.")
    blank = [f["file"] for f in per_file
             if f["tokens"] == 0 and "not counted" in f["kind"]
             and f["kind"] != NO_PDF_READER and not f["kind"].startswith("binary")]
    if blank:
        add("WARN", "Some files have no text that could be read",
            f"{', '.join(blank[:5])}{' and more' if len(blank) > 5 else ''} -- "
            "for example a scanned PDF, an image, or a file that would not open.",
            "Fine as material, since the model can look at it, but nothing in it "
            "is counted here. If it was meant to be text, check the file opens "
            "and has a text layer.")

    # 5. readability
    #
    # Judged against what this task's image actually installs, not a fixed list
    # of formats, and reported by naming the package that is missing.
    present = {p["spec"].split("==")[0].split("=")[0].lower()
               for p in state.get("packages", [])}
    extensions = {Path(f).suffix.lower() for f in files if Path(f).suffix}

    wanted: dict[str, list[str]] = {}
    for ext in sorted(extensions):
        for package in FORMAT_PACKAGES.get(ext, []):
            if package.lower() not in present:
                wanted.setdefault(package, []).append(ext)
    if wanted:
        detail = "; ".join(f"{pkg} (for {', '.join(exts)})"
                           for pkg, exts in sorted(wanted.items()))
        add("WARN", "These files probably need a package this image does not have",
            detail,
            "Add them now: " + "  ".join(f"/flc-add-package {p}" for p in sorted(wanted))
            + ". Anything missed is caught after the solver run, which reports "
              "whatever the model had to install for itself.")

    unknown = sorted(e for e in extensions
                     if e not in READABLE and e not in FORMAT_PACKAGES)
    if unknown:
        add("WARN", "Some file types are not recognised",
            "unrecognised extensions: " + ", ".join(unknown),
            "Not a problem on its own, and no action needed now. If the solver "
            "cannot open them it will install what it needs, and that is "
            "reported after the run.")

    return {
        "task_id": state["task_id"],
        "files": len(files),
        "required": len(state["required_files"]),
        "distractors": len(state["distractor_files"]),
        "material_estimate": state.get("material_estimate"),
        "required_estimate": state.get("required_estimate"),
        "per_file": per_file,
        "prompt_check": state.get(prompt_check.STATE_KEY),
        "findings": findings,
        "verdict": "FAIL" if any(f["level"] == "FAIL" for f in findings) else "PASS",
    }


GATE_NEVER = ("/flc-check-inputs has not passed on this task, and it is what "
              "looks at the workspace and the prompt before a whole run goes "
              "into them.")
# A pass recorded before this digest existed, on a task authored under an
# earlier seed. Reporting it as never run would be a lie about what somebody
# did, and the remedy is the same either way.
GATE_UNPINNED = ("/flc-check-inputs passed on this task, but the record does "
                 "not say which workspace it looked at, so nothing can tell "
                 "whether the material has changed since. Run it again.")
GATE_STALE = ("environment/workspace/ has changed since /flc-check-inputs "
              "passed, so what would be run against is not what was checked.")
GATE_PROMPT = ("prompt.md has changed since /flc-prompt-check checked it, so "
               "the run would be taken on a question nobody has checked. Run "
               "/flc-prompt-check, then start the run.")
GATE_PROMPT_FAIL = ("the question in prompt.md did not clear /flc-prompt-check, "
                    "so a run on it could not be delivered. /flc-prompt-check "
                    "says what moves a prompt up.")


def gate(root: Path) -> str:
    """"" when the input check covers the workspace as it stands, else why not.

    The manifest is refreshed first: it is generated from the workspace, and
    comparing against a stale copy would report a change that is only this
    file not having caught up.
    """
    st.write_inputs_manifest(root)
    state = st.load(root)
    entry, fresh = recorded(root, state)
    if entry is None:
        return (GATE_UNPINNED if "check_inputs" in (state.get("steps_done") or [])
                else GATE_NEVER)
    if not fresh:
        return GATE_STALE
    # The question can change after the files were checked, and a run on a
    # question that no longer matches its verdict is a run spent on a prompt
    # that may not ship. A verdict that could not be measured still passes.
    verdict, current = prompt_check.recorded(state, prompt_check.prompt_text(root))
    if verdict is None or not current:
        return GATE_PROMPT
    return GATE_PROMPT_FAIL if verdict.get("verdict") == "FAIL" else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", default=None)
    ap.add_argument("--required", nargs="*", default=None,
                    help="workspace-relative paths of the files needed to solve the task")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true",
                    help="exit 0 if the recorded pass covers this workspace, "
                         "without re-running the check")
    args = ap.parse_args()

    root = st.task_root(args.task)
    if not args.gate:
        # Not on the gate path: that runs from inside run_solver.sh, which has
        # already asked the same question about its own step.
        check_integrity.announce(root, "check_inputs")

    if args.gate:
        why = gate(root)
        if why:
            print(why, file=sys.stderr)
        return 1 if why else 0

    report = check(root, args.required)

    # Before either output path, so that asking for the machine-readable form
    # is not quietly a different command than asking for the readable one.
    if report["verdict"] == "PASS":
        st.mark_done(root, "check_inputs")
        record(root, report["files"])
    else:
        # A step that failed has to leave a trace. Without one, a later session
        # reads "not in steps_done" as "never attempted" and says so.
        first = next(f for f in report["findings"] if f["level"] == "FAIL")
        st.mark_failed(root, "check_inputs", first["title"], first["detail"])

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["verdict"] == "PASS" else 1

    print(f"  files uploaded:  {report['files']}")
    print(f"  needed to solve: {report['required']}")
    print(f"  distractors:     {report['distractors']}")
    if report["material_estimate"] is not None:
        print(f"  material:        ~{report['material_estimate']:,} tokens (estimate)")
    print()
    for f in report["findings"]:
        print(f"  [{f['level']}] {f['title']}")
        if f["detail"]:
            print(f"         {f['detail']}")
        if f["fix"]:
            print(f"         -> {f['fix']}")
    print()
    print(f"  {report['verdict']}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
