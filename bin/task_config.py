#!/usr/bin/env python3
"""The small task-configuration commands, so a contributor never edits config.

    task_config.py skip-tests            grade this task by rubrics alone
    task_config.py enable-tests          undo that
    task_config.py add-package scanpy    add a dependency to the task image
    task_config.py add-package --apt libgeos-dev
    task_config.py add-package --r ComplexHeatmap
    task_config.py remove-package scanpy      undo that, whatever it was pinned to
    task_config.py check-packages        can every recorded package be installed?
    task_config.py block-domain example.com
    task_config.py unblock-domain example.com
    task_config.py show

Each subcommand rewrites the generated files it affects, so the task is always
consistent with its own state.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402

DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

# The suite the verifier runs, and where skip-tests puts it. `run_verifier.py`
# decides on the first path existing, and nothing it can read carries the state.
VERIFIER = "tests/verifier.py"
VERIFIER_SET_ASIDE = "tests/verifier.py.skipped"

# A package name reaches the image build as a shell word and, for R, as part of
# an R expression. Checked against each ecosystem's own naming rules here rather
# than escaped at each use.
PACKAGE_RE = {
    "pip": re.compile(r"^[A-Za-z0-9._+-]+(\[[A-Za-z0-9._,-]+\])?"
                      r"([<>=!~]=?[A-Za-z0-9._*+-]+)?"
                      r"(,[<>=!~]=?[A-Za-z0-9._*+-]+)*$"),
    "apt": re.compile(r"^[a-z0-9][a-z0-9.+-]*$"),
    "r": re.compile(r"^[A-Za-z][A-Za-z0-9._]*$"),
}


def cmd_skip_tests(root: Path, args) -> int:
    """Mark the task rubrics-only and move the suite out of the graded path.

    The verifier runs against whatever `tests/verifier.py` is on disk, so the
    file is renamed rather than the state flag alone being set.
    """
    live = root / VERIFIER
    aside = root / VERIFIER_SET_ASIDE
    moved = live.exists()
    if moved:
        live.replace(aside)

    state = st.load(root)
    state["unit_tests"] = "skipped"
    st.save(root, state)

    print("This task is now graded by rubrics alone.")
    if moved:
        print(f"{VERIFIER} has been set aside as {VERIFIER_SET_ASIDE}, so it is")
        print("neither graded nor delivered.")
    elif aside.exists():
        print(f"{VERIFIER} was already set aside as {VERIFIER_SET_ASIDE}.")
    else:
        print(f"There was no {VERIFIER} to set aside.")
    print()
    print("Changed your mind? Run: /flc-enable-tests")
    return 0


def cmd_enable_tests(root: Path, args) -> int:
    """Turn unit tests back on, restoring a suite that skip-tests set aside."""
    live = root / VERIFIER
    aside = root / VERIFIER_SET_ASIDE
    restored = aside.exists() and not live.exists()
    if restored:
        aside.replace(live)

    state = st.load(root)
    state["unit_tests"] = "unwritten"
    st.save(root, state)

    if restored:
        print(f"Unit tests are back on, and {VERIFIER} has been restored.")
    elif aside.exists():
        print(f"Unit tests are back on. {VERIFIER} already exists, so the earlier")
        print(f"{VERIFIER_SET_ASIDE} has been left where it is.")
    else:
        print(f"Unit tests are back on. Write them in {VERIFIER}.")
    print("Run /flc-check-tests when they are ready.")
    return 0


# Whether a package exists, asked of the machine that will have to install it.
#
# Three answers, not two. A probe that could not run is not a package that is
# missing, and reading the two alike either lets everything through or refuses a
# contributor the dependencies their task needs. So the same question is put
# first about a package that is certainly there: if that one cannot be found
# either, the index was never fetched or the tool is absent, and the answer is
# "unknown" rather than "no". Without that control an image whose apt lists are
# empty refuses every system package anyone names.
CONTROL = {"apt": "apt", "pip": "pip"}


def _ran(cmd: list[str]) -> int | None:
    """The command's exit status, or None when it could not be run at all."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=60, check=False).returncode
    except Exception:
        return None


def _seen(ecosystem: str, bare: str) -> int | None:
    if ecosystem == "apt":
        return _ran(["apt-cache", "show", bare])
    if ecosystem == "pip":
        # Installed here is the strongest answer there is, and the guide asks
        # for it anyway so the version can be pinned. The index is the fallback,
        # and it is the one that needs a network.
        if _ran([sys.executable, "-m", "pip", "show", bare]) == 0:
            return 0
        return _ran([sys.executable, "-m", "pip", "index", "versions", bare])
    return None


def available(ecosystem: str, name: str) -> str:
    """"yes", "no" or "unknown" -- whether this package can be installed."""
    bare = re.split(r"[<>=!~\[]", name, 1)[0].strip()
    if not bare or ecosystem not in CONTROL:
        return "unknown"  # R is not probed: nothing here can ask CRAN offline.
    status = _seen(ecosystem, bare)
    if status == 0:
        return "yes"
    if status is None:
        return "unknown"
    return "no" if _seen(ecosystem, CONTROL[ecosystem]) == 0 else "unknown"


def _pinned_version(ecosystem: str, name: str) -> str | None:
    """Ask the live container what it just installed, so the pin is exact.

    An unpinned dependency is how a task that worked in the sandbox stops
    working three months later somewhere else.
    """
    if ecosystem != "pip":
        return None
    bare = re.split(r"[<>=!~\[]", name, 1)[0].strip()
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "show", bare],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.lower().startswith("version:"):
            return f"{bare}=={line.split(':', 1)[1].strip()}"
    return None


def cmd_add_package(root: Path, args) -> int:
    ecosystem = "apt" if args.apt else "r" if args.r else "pip"
    name = args.name.strip()
    if not name:
        raise SystemExit("no package named")
    if not PACKAGE_RE[ecosystem].match(name):
        raise SystemExit(
            f"'{name}' is not a valid {ecosystem} package name.\n"
            "Expected a name such as scanpy, scanpy==1.10.3, libgeos-dev or "
            "ComplexHeatmap.\nIf the package really is named this, say so and "
            "it can be added by hand.")

    # The shape gate above says only that this could be a package name. `to`,
    # `enable` and `page` all pass it, and all three reached a task's list from
    # a sentence the solver wrote. What a name looks like is not whether it
    # exists, and the first thing that notices the difference is the image
    # build -- which stops the run, the grade and the delivery together.
    if not getattr(args, "force", False) and available(ecosystem, name) == "no":
        raise SystemExit(
            f"no {ecosystem} package is called '{name}', so the image would "
            f"fail to build.\n"
            "Check the spelling, or the name the installer actually uses -- it "
            "is often\nnot the name you import (PyMuPDF is imported as fitz).\n"
            "If the package really is named this and this machine simply cannot "
            "see it,\nadd it with --force.")

    state = st.load(root)
    packages = state.setdefault("packages", [])

    spec = name
    if ecosystem == "pip" and "==" not in name:
        pinned = _pinned_version(ecosystem, name)
        if pinned:
            spec = pinned
            print(f"pinned to {spec} (the version installed here)")
        else:
            print(f"warning: {name} is not installed in this sandbox, so it could not")
            print("         be pinned to a version. It will be installed unpinned.")

    if any(p["ecosystem"] == ecosystem and p["spec"] == spec for p in packages):
        print(f"{spec} is already on the list.")
        return 0

    packages.append({"ecosystem": ecosystem, "spec": spec})
    st.save(root, state)
    st.write_packages(root)
    print(f"added: {ecosystem} {spec}")
    print()
    print("The task image will install it on the next build. Nothing else to do --")
    print("/flc-deliver rebuilds and checks it before the task is packaged.")
    return 0


def cmd_block_domain(root: Path, args) -> int:
    domain = args.domain.strip().lower()
    # A pasted URL is the likeliest slip. Reduce it to the apex: the blocker
    # covers the www. form itself, and storing "www.example.com" would leave
    # example.com reachable -- a block that looks applied and is not.
    domain = re.sub(r"^[a-z]+://", "", domain).split("/")[0].split("@")[-1]
    domain = re.sub(r"^www\.", "", domain)
    if not DOMAIN_RE.match(domain):
        raise SystemExit(f"{args.domain!r} does not look like a domain (expected e.g. wikipedia.org)")

    state = st.load(root)
    blocked = state.setdefault("blocked_domains", [])
    if domain in blocked:
        print(f"{domain} is already blocked.")
        return 0
    blocked.append(domain)
    blocked.sort()
    st.save(root, state)
    st.write_blocked_domains(root)
    print(f"blocked: {domain}")
    print()
    print("The solver will not be able to resolve it. This stops the model")
    print("wandering onto a page that gives the answer away; it is not a security")
    print("boundary, and it does not stop a request to a raw IP address.")
    return 0


def cmd_unblock_domain(root: Path, args) -> int:
    # Normalized exactly as blocking normalizes it, or a domain blocked from a
    # pasted URL could not be removed the same way it was added.
    domain = args.domain.strip().lower()
    domain = re.sub(r"^[a-z]+://", "", domain).split("/")[0].split("@")[-1]
    domain = re.sub(r"^www\.", "", domain)
    state = st.load(root)
    blocked = state.setdefault("blocked_domains", [])
    if domain not in blocked:
        print(f"{domain} was not blocked.")
        return 0
    blocked.remove(domain)
    st.save(root, state)
    st.write_blocked_domains(root)
    print(f"unblocked: {domain}")
    return 0


def cmd_remove_package(root: Path, args) -> int:
    """Take a package off the list, by name, whatever version it was pinned to.

    The inverse of add-package, and the reason it exists: the list is written
    for the contributor by `detect_packages.py --add`, reading a solver run. A
    wrong entry there is not a typo the contributor can see coming, and the
    first thing it stops is the image build -- which stops the run, the grade
    and the delivery at once. Without this the file is a task file, so no one,
    contributor or assistant, may edit it, and the task is finished.
    """
    ecosystem = "apt" if args.apt else "r" if args.r else "pip"
    wanted = args.name.strip().lower()
    if not wanted:
        raise SystemExit("no package named")

    state = st.load(root)
    packages = state.setdefault("packages", [])
    # Matched on the name alone: what is on the list carries the version it was
    # pinned to, and nobody asked to remove `numpy==1.26.4`.
    def name_of(spec: str) -> str:
        return re.split(r"[=<>!~\[]", spec, 1)[0].strip().lower()

    keep = [p for p in packages
            if not (p["ecosystem"] == ecosystem and name_of(p["spec"]) == wanted)]
    if len(keep) == len(packages):
        here = [f"{p['ecosystem']} {p['spec']}" for p in packages]
        print(f"{ecosystem} {wanted} is not on the list.")
        if here:
            print("On it:")
            for line in here:
                print(f"  {line}")
        else:
            print("The list is empty.")
        return 0

    for spec in [p["spec"] for p in packages if p not in keep]:
        print(f"removed: {ecosystem} {spec}")
    state["packages"] = keep
    st.save(root, state)
    st.write_packages(root)
    print()
    print("The next build stops installing it. Nothing else to do.")
    return 0


def cmd_check_packages(root: Path, args) -> int:
    """Ask, of every package on the list, whether it can be installed.

    The gate in add-package only guards what is added from now on. A list
    written before it, or on a machine that could not answer, is read here --
    which is how a contributor whose build already fails finds out which
    entries are the reason, rather than one rebuild per name.
    """
    packages = st.load(root).get("packages", [])
    if not packages:
        print("No extra packages are recorded for this task.")
        return 0

    missing, unknown = [], []
    for entry in packages:
        ecosystem, spec = entry["ecosystem"], entry["spec"]
        answer = available(ecosystem, spec)
        mark = {"yes": "ok", "no": "NOT FOUND", "unknown": "?"}[answer]
        print(f"  {mark:<9} {ecosystem} {spec}")
        if answer == "no":
            missing.append(entry)
        elif answer == "unknown":
            unknown.append(entry)

    print()
    if unknown:
        # Said plainly rather than folded in with the failures: not knowing is
        # not a finding, and a contributor who reads it as one starts removing
        # packages their task needs.
        print(f"{len(unknown)} could not be checked on this machine -- an R package, "
              "no network,")
        print("or no package index here. That is not a problem with them.")
        print()
    if not missing:
        print("Nothing on the list is known to be missing.")
        return 0

    print(f"{len(missing)} cannot be installed, so the image build fails on them:")
    for entry in missing:
        flag = {"apt": " --apt", "r": " --r"}.get(entry["ecosystem"], "")
        bare = re.split(r"[<>=!~\[]", entry["spec"], 1)[0]
        print(f"  python3 bin/task_config.py remove-package{flag} {bare}")
    return 1


def cmd_show(root: Path, args) -> int:
    state = st.load(root)
    print(json.dumps(state, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("skip-tests").set_defaults(fn=cmd_skip_tests)
    sub.add_parser("enable-tests").set_defaults(fn=cmd_enable_tests)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    sub.add_parser("check-packages").set_defaults(fn=cmd_check_packages)

    p = sub.add_parser("add-package")
    p.add_argument("name")
    p.add_argument("--apt", action="store_true", help="a system package rather than a Python one")
    p.add_argument("--r", action="store_true", help="an R package rather than a Python one")
    p.add_argument("--force", action="store_true",
                   help="add it even though this machine cannot find it")
    p.set_defaults(fn=cmd_add_package)

    p = sub.add_parser("remove-package")
    p.add_argument("name")
    p.add_argument("--apt", action="store_true", help="a system package rather than a Python one")
    p.add_argument("--r", action="store_true", help="an R package rather than a Python one")
    p.set_defaults(fn=cmd_remove_package)

    p = sub.add_parser("block-domain")
    p.add_argument("domain")
    p.set_defaults(fn=cmd_block_domain)

    p = sub.add_parser("unblock-domain")
    p.add_argument("domain")
    p.set_defaults(fn=cmd_unblock_domain)

    args = ap.parse_args()
    root = st.task_root(args.task)
    rc = args.fn(root, args)
    st.regenerate(root)
    return rc


if __name__ == "__main__":
    sys.exit(main())
