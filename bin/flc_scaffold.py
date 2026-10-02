#!/usr/bin/env python3
"""Finish a freshly copied task folder. Called by new_task.sh, not by hand.

new_task.sh copies template_task/ verbatim; everything that depends on the task
id being minted -- the state file, task.toml, the Dockerfile, instruction.md --
is written here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flc_state as st  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        print("\nUsage: flc_scaffold.py [TASK_DIR]")
        return 0
    # Without this an option typo is taken for a path, and the scaffold lands in
    # a directory named after the flag.
    if args and args[0].startswith("-"):
        print(f"flc_scaffold.py: unknown option {args[0]!r}", file=sys.stderr)
        return 2

    root = Path(args[0]).resolve() if args else st.task_root()

    st.save(root, st.default_state(st.new_task_id()))

    # Both are inputs to the generated Dockerfile, so they have to exist from
    # the start or the very first build fails on a missing COPY source. Written
    # only when absent: in a seeded domain directory they arrive already
    # carrying that domain's packages and blocked sites, and overwriting them
    # here would silently throw the profile away.
    env = root / "environment"
    build = env / ".flc"
    build.mkdir(parents=True, exist_ok=True)
    if not (build / "packages.txt").exists():
        (build / "packages.txt").write_text(
            "# Extra packages for this task. Written by /flc-add-package.\n"
            "# One per line, prefixed with pip, apt or r.\n"
        )
    if not (build / "blocked_domains.txt").exists():
        (build / "blocked_domains.txt").write_text(
            "# Sites the solver must not reach. Written by /flc-block-domain.\n"
            "# One domain per line.\n"
        )
    (env / "workspace").mkdir(exist_ok=True)

    st.regenerate(root)
    print(f"scaffolded {root} as {st.load(root)['task_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
