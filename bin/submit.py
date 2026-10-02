#!/usr/bin/env python3
"""Confirm a packaged delivery is ready to be collected, and record that it was.

    python3 submit.py
    python3 submit.py --json

/flc-deliver produces delivery/ and checks that everything in it holds together.
This is the last thing run before the contributor finishes the task, and it does
two jobs.

For the contributor it answers one question -- is this ready -- and the useful
half of that is the one delivery cannot answer: whether anything moved *since*
delivery checked it. Delivery compares the grade against the files at the moment
it runs. Between that moment and the contributor finishing there is a window,
and an edit made in it would otherwise be collected alongside a validation.json
describing a different task.

For whoever validates the task afterwards it leaves `delivery/readiness.json`: a
digest of every file being handed over, taken at a named time. Nothing here can
stop a file being changed after this runs -- the collection happens outside the
VM and there is no secret in here to sign with, so a determined edit that also
rewrites the receipt is not detectable from the contents alone. What the receipt
does is make an ordinary edit *visible*, by giving the validator something to
recompute against instead of nothing.

It does not archive anything. The platform collects `flc/task/delivery/` and
`flc/task/review/` from the VM directly, so a zip built here would either sit
outside those paths and be collected by nobody, or sit inside one and be a
second copy of everything already being collected.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402
import labels as lb  # noqa: E402

RECEIPT = "readiness.json"
SCHEMA = "1"

# What a delivery has to contain. Named rather than only digested, so an empty
# folder is reported as that rather than as a digest mismatch.
REQUIRED = (
    "validation.json",
    "AUDIT.md",
    "bundle/task.toml",
    "bundle/instruction.md",
)


def digests(directory: Path, skip: set[str] = frozenset()) -> dict[str, str]:
    """Every file under a directory, by path, with its sha256."""
    out = {}
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory).as_posix()
        if rel in skip:
            continue
        out[rel] = st.sha256_file(path)
    return out


def authoring_drift(root: Path, delivery: Path, report: dict) -> list[str]:
    """Where delivery/authoring/ and the files it was copied from have moved apart.

    The justification is held to the digest its check was taken against, in
    both places it is collected. Every other copy is held to its source.
    """
    problems: list[str] = []
    authoring = delivery / "authoring"
    sources = st.authoring_sources(root)
    just_name = Path(st.JUSTIFICATION).name
    sources.pop(just_name, None)
    just_src = st.justification_file(root)
    just_rel = just_src.relative_to(root).as_posix()
    checked = (report.get("justification_check") or {}).get("justification_sha256")
    if not checked:
        problems.append("This delivery record does not say which justification "
                        "was checked, so the one being collected cannot be "
                        "compared with it. Run /flc-deliver again.")
    else:
        if st.sha256_file(just_src) != checked:
            problems.append(f"{just_rel} changed after /flc-check-justification "
                            "passed it, so the justification being collected is "
                            "not the one that was checked. Run "
                            "/flc-check-justification, then /flc-deliver again.")
        if st.sha256_file(authoring / just_name) != checked:
            problems.append(f"delivery/authoring/{just_name} is not the "
                            "justification that was checked. Run /flc-deliver "
                            "again.")
    for name, src in sources.items():
        copy = authoring / name
        if not src.exists() and not copy.exists():
            continue
        if st.sha256_file(src) != st.sha256_file(copy):
            problems.append(f"delivery/authoring/{name} no longer matches "
                            f"{src.relative_to(root).as_posix()}, so the copy a "
                            "reviewer reads is not your task's. Run /flc-deliver "
                            "again.")
    return problems


def taxonomy_drift(root: Path, delivery: Path, report: dict) -> list[str]:
    """delivery/authoring/taxonomy.json against its digest and the labels now."""
    copy = delivery / "authoring" / "taxonomy.json"
    recorded = report.get("taxonomy_sha256")
    if not recorded:
        return ["This delivery record does not say which labels were delivered, "
                "so the taxonomy being collected cannot be compared with it. Run "
                "/flc-deliver again."]
    if st.sha256_file(copy) != recorded:
        return ["delivery/authoring/taxonomy.json is not the one /flc-deliver "
                "wrote. Run /flc-deliver again."]
    if copy.read_text(encoding="utf-8") != lb.taxonomy_text(root):
        return [f"{lb.LABELS} or the justification changed after this delivery "
                "was packaged, so the taxonomy being collected no longer "
                "describes your task. Run /flc-deliver again."]
    return []


def review_drift(root: Path, state: dict, report: dict) -> list[str]:
    """Whether the criteria were checked again after this delivery read the check.

    Delivery holds the criteria to the review /flc-check-rubric recorded. A
    review taken again afterwards is one the delivery never read.
    """
    shipped = report.get("rubric_review_inputs")
    entry = state.get("rubric_check") or {}
    if shipped and entry.get("inputs_sha256") and entry["inputs_sha256"] != shipped:
        return ["The criteria were checked again after this delivery was "
                "packaged, so the delivery holds an earlier check. Run "
                "/flc-deliver again."]
    return []


def newest_mtime(directory: Path) -> float | None:
    times = [p.stat().st_mtime for p in directory.rglob("*") if p.is_file()]
    return max(times) if times else None


def check(root: Path, state: dict) -> tuple[list[str], list[str]]:
    """Problems that stop this being ready, and notes that do not."""
    problems: list[str] = []
    notes: list[str] = []
    delivery = root / "delivery"

    if not delivery.is_dir():
        return (["There is no delivery/ directory. Run /flc-deliver first."], notes)

    validation = delivery / "validation.json"
    report = {}
    if not validation.exists():
        problems.append("delivery/validation.json is missing, so nothing records "
                        "that this delivery passed its checks. Run /flc-deliver "
                        "again.")
    else:
        try:
            report = json.loads(validation.read_text())
        except json.JSONDecodeError:
            report = {}
            problems.append("delivery/validation.json is not readable. Run "
                            "/flc-deliver again.")
        if report and report.get("verdict") != "PASS":
            problems.append("The last delivery did not pass its checks. Run "
                            "/flc-deliver and fix what it reports.")
        failed = [c["check"] for c in report.get("checks", []) if not c.get("passed")]
        if failed:
            problems.append("Checks that did not pass: " + ", ".join(failed)
                            + ". Run /flc-deliver and fix what it reports.")

    missing = [name for name in REQUIRED if not (delivery / name).exists()]
    if missing:
        problems.append("Missing from delivery/: " + ", ".join(missing)
                        + ". Run /flc-deliver again.")

    # The task cannot have moved since delivery checked it: delivery compares
    # the grade against the files, and this compares the files against the
    # delivery.
    #
    # Regenerated first. What is fingerprinted is instruction.md and the
    # manifest rather than prompt.md and the workspace, so an edit to a source
    # file does not show until the generated one has caught up.
    if not problems:
        st.regenerate(root)
        current = st.fingerprint(root)
        recorded = report.get("grade_inputs") or {}
        moved = st.fingerprint_drift(recorded, current, tuple(st.GRADE_INPUTS))
        named = st.drift_names(root, moved)
        if named:
            problems.append(
                ", ".join(named)
                + " changed after this delivery was packaged, so what would be "
                  "collected is not what was checked. Run /flc-deliver again.")
        elif moved:
            problems.append(
                "This delivery record was written before part of what is now "
                "checked, so it cannot be compared against your task. Run "
                "/flc-deliver again.")
        problems += authoring_drift(root, delivery, report)
        problems += taxonomy_drift(root, delivery, report)
        problems += review_drift(root, state, report)

    # Reported, never blocking. The review is written by the post-run hook and
    # is collected from review/ rather than from delivery/.
    if not any((root / "review").glob("*.md")):
        notes.append("No read of the run in review/. /flc-inspect writes it, and "
                     "review/ is collected alongside delivery/.")
    return problems, notes


def receipt(root: Path, state: dict, problems: list[str],
            notes: list[str]) -> dict:
    delivery = root / "delivery"
    review = root / "review"
    now = datetime.now(timezone.utc)
    validation = {}
    try:
        validation = json.loads((delivery / "validation.json").read_text())
    except Exception:
        pass

    delivered = digests(delivery, skip={RECEIPT})
    reviewed = digests(review) if review.is_dir() else {}
    return {
        "schema_version": SCHEMA,
        "verdict": "PASS" if not problems else "FAIL",
        "problems": problems,
        "notes": notes,
        "task_id": state.get("task_id"),
        "seed_version": state.get("seed_version"),
        "checked_at": now.isoformat(timespec="seconds"),
        "checked_at_unix": round(now.timestamp(), 3),
        # The VM's clock, recorded to compare against file mtimes after
        # collection: a file whose mtime is later than this was written after
        # the check.
        "delivery_newest_mtime": newest_mtime(delivery),
        "delivery_file_count": len(delivered),
        "delivery_bytes": sum(p.stat().st_size for p in delivery.rglob("*")
                              if p.is_file() and p.name != RECEIPT),
        "delivery_files": delivered,
        "review_file_count": len(reviewed),
        "review_files": reviewed,
        # Repeated from validation.json on purpose. Two records of the same
        # number in two files disagree when one of them is edited, and that
        # disagreement is checkable downstream without any of our code.
        "packaged_at": validation.get("packaged_at"),
        "graded_job": validation.get("graded_job"),
        "solver_reward": validation.get("solver_reward"),
        "context_added": validation.get("context_added"),
        "rubric_count": validation.get("rubric_count"),
        "overrides": validation.get("overrides") or [],
        # Repeated from validation.json for the same reason the numbers above
        # are, and because this is the file a validator recomputes from: a
        # collected task whose machinery was not ours has to be answerable
        # without opening the delivery.
        "integrity": (validation.get("integrity") or {}).get("verdict"),
        "integrity_findings": [
            {k: f.get(k) for k in ("path", "where", "tier", "state", "actual")}
            for f in ((validation.get("integrity") or {}).get("findings") or [])],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = st.task_root(args.task)
    state = st.load(root)
    delivery = root / "delivery"
    problems, notes = check(root, state)

    # Written whatever the verdict, so long as there is a delivery to write it
    # into. A failed check that left an earlier PASS in place would be the worst
    # of both: the contributor is told it is not ready, the folder is collected
    # anyway, and it carries a receipt saying everything was fine.
    #
    # The directory is never created here. An empty delivery/ is collected just
    # as readily as a full one, so conjuring one to hold a failure notice would
    # manufacture the exact thing being guarded against.
    record = None
    if delivery.is_dir():
        record = receipt(root, state, problems, notes)
        (delivery / RECEIPT).write_text(json.dumps(record, indent=2) + "\n")

    # Before either output path, so that asking for the machine-readable form
    # is not quietly a different command than asking for the readable one.
    if not problems:
        st.mark_done(root, "submit")

    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems,
                          "notes": notes, "receipt": record}, indent=2))
        return 0 if not problems else 1

    if problems:
        print("  Not ready.\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("  Ready.\n")
    print(f"  {delivery}/")
    print("    bundle/          the task, ready to run")
    print("    run/             what the solver did and how it scored")
    print("    authoring/       the prompt, rubric source, ground truth and labels")
    print("    AUDIT.md         what was checked, and anything acknowledged")
    print(f"    {RECEIPT}   this check, and a digest of every file above")
    for note in notes:
        print(f"\n  Note: {note}")
    print()
    print("  Nothing here needs downloading or attaching. Finish the task and")
    print("  this folder is collected with it, along with review/.")
    print()
    print("  Stop here. Do not edit anything, and do not run any more commands")
    print("  -- /flc-inspect and /flc-view rewrite files too, even though they")
    print("  only show you things. If you do change something, run /flc-submit")
    print("  again afterwards so this record matches what gets collected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
