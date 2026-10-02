---
description: Add a software package the task needs
---

Add a package to the task's environment: $ARGUMENTS

The image carries Python plus the handful of packages this domain usually needs,
not everything -- so a missing package is expected and routine, not a mistake
anyone made. Check whether it is genuinely missing first:

```bash
python3 -c "import NAME; print(NAME.__version__)"
```

If it is missing, install it here first so the exact version can be pinned, then
record it:

```bash
pip install NAME
python3 ~/flc/bin/task_config.py add-package NAME
```

For a system package use `--apt`, for an R package `--r`:

```bash
python3 ~/flc/bin/task_config.py add-package --apt libgeos-dev
python3 ~/flc/bin/task_config.py add-package --r ComplexHeatmap
```

## Taking one off

```bash
python3 ~/flc/bin/task_config.py remove-package NAME
```

`--apt` and `--r` the same way, and the name alone is enough -- what is on the
list carries the version it was pinned to.

To read the whole list, and be told which entries cannot be installed:

```bash
python3 ~/flc/bin/task_config.py check-packages
```

Use this the moment a build fails on a package: it names every bad entry at
once, instead of one rebuild per name. A `?` means this machine could not
check that one -- an R package, or no package index here -- which is not a
problem with it.

Adding a package this machine cannot find is refused, since the image would
only fail to build later. If the name really is right and this machine simply
cannot see it, add it with `--force`.

Most of the list is not typed by hand: `detect_packages.py --add` writes it from
what the solver ran. A wrong entry there is not something the contributor chose,
and the first thing it stops is the image build -- which stops the run, the
grade and the delivery at once. So if the build fails on a package that should
not be there, take it out with the command above rather than editing
`environment/.flc/packages.txt`, which is a task file and is regenerated from
the task's state.

Pinning matters: an unpinned dependency is how a task that worked here stops
working months later. Installing it locally first is what lets the exact version
be recorded, so do that rather than adding the name blind.

Reassure them this is routine and can be done at any point -- nothing has to be
got right up front. `/flc-deliver` rebuilds from scratch and will not package
the task unless every recorded package installs cleanly.
