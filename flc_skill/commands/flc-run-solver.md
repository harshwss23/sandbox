---
description: Step 4 - start the model working on the task
---

Start the solver.

This uses budget. Start another run only after a meaningful change -- the
prompt, the files, the packages or the block list.

## Before starting

Check the task is ready, since a run takes real time and money:

```bash
python3 ~/flc/bin/status.py
```

Files and prompt must be done, and the ground truth's *The answer* and *How it
is derivable* written. The rest of step 3 -- the distractors, the justification
and the labels -- waits for the first run to show the task holds. The rubrics
are **not** expected yet either; they come next, while this runs. If files or
prompt are missing, say what and stop; do not start a run to "see what
happens".

**Read the `blocked` line back to them and ask the question it implies.** This
is the last moment it is free. The model browses while it works, that is
wanted, and a run where it read the answer off a page is a run thrown away --
so before spending one, ask them for the single page that would most spoil
their own task: the paper the dataset came from, the database entry for the
accession in the question, a public copy of one of their files, the vendor page
carrying the figure. If it is not on the list, `/flc-block-domain` it now.

Ask once and take their answer. A contributor who says the list covers it has
said so with the list in front of them, which is the point. Do not block
anything on your own initiative -- the list is theirs, it is what their task
can reach, and a site their material genuinely needs would cost them a
diagnosis later.

Two things to be straight about if they ask how much it buys: it blocks by
name, so a raw IP address is not stopped, and it does not empty search results
-- an unreachable page can still be quoted in a summary. If their answer is
something the whole internet repeats, no list saves the task and the question
needs to be more specific to their data.

## Run

```bash
bash ~/flc/bin/run_solver.sh --background
```

It prints the command it is running, starts it detached, and hands the terminal
straight back. Do not wait for it and do not offer to watch it: the point of
this step is that the contributor writes their completion criteria while it
goes.

**This step does not grade.** The run scores nothing; scoring happens at
`/flc-grade`, once all the criteria are written. If they see "Grading deferred"
or a zero in the run's output, nothing has been measured yet -- say only that.

When the run lands it writes two things by itself. The review document -- the
answer, the steps it took, and what is worth checking in what it claimed, which
`/flc-inspect` opens. And a readable page of the whole run, to download and open
in a browser, which `/flc-view` rebuilds. Both only read the run; they grade
nothing and touch no rubric.

## When it stops to ask, or refuses

The script checks four things before a run starts, and none of them calls a
model:

- **`/flc-check-inputs` has not passed on the files as they are now.** Run it
  again (and `/flc-prompt-check` first if the question changed), then start the
  run.

- **The answer is not written down.** It names the empty section. Send them to
  `/flc-ground-truth`; a short version is enough. There is no way past this.
- **Exit 3: all but the same run again.** The files, packages and block list
  match an earlier run, and the prompt differs by a word or two. Read the
  message to them as it is and ask whether they want the run anyway. Only once
  they say yes, start it again with `--confirm-rerun`. Do not decide for them,
  and never change the prompt or the files to get past this check.
- **The run limit.** A task gets five counted runs. Past that, a run needs
  `--limit-reason "..."`, and the reason is theirs: ask why another run is
  needed and pass their words exactly as they said them. Never write the
  reason, shorten it or improve it.

A run that crashed, never answered, came back without the model's files, or
read the answer off the web does not count, so none of those cost them a run.

Do not suggest running the same task again to see whether a failure is
reliable: that is the rerun the check asks about, and it usually shows the
same thing again. Never pass `--attempts`.

## Then tell them to move on

Say plainly that it is running in the background and that the next thing to do
is now:

> While that runs, write the criteria for what a right answer contains -- they
> come from your ground truth and need nothing from the run. Type `/flc-rubrics`.
> When the run lands, we come back and write the criteria that catch anything it
> invented.

If they ask why that order: the criteria that matter most are the ones about
invented claims, and nobody can guess what a model will invent. Those are
written against what it actually said.

**Do not give them an estimate of how long the run will take**, even if asked,
and do not derive one from the timeout in `task.toml` -- that is a cap, not a
duration. How long a run takes depends on the task, and a number given here is
one the contributor will hold you to: too high and they walk away from a run
that finished in minutes, too low and they think it has hung. Tell them it runs
in the background, that `--status` is how they check, and that there is nothing
to wait for in the meantime.

## Checking on it

```bash
bash ~/flc/bin/run_solver.sh --status
```

Says whether it is still going, and where the live output is. `/flc-status`
shows the same thing in the step list.

**When it says FINISHED, do not send them to `/flc-rubrics` on its own.** Offer
`/flc-inspect` first and say what it is for: it reads the run and lists the
claims worth checking, which is what the non-hallucination criteria are written
from. A contributor who goes straight to the rubrics writes them from the answer
alone, and an invented figure reads exactly like a correct one there. This has
happened; it is the easiest step in the workflow to walk past.

`--status` prints the paths itself when a run has finished. Tell them the two
that matter, in one sentence each: the read of the run, which `/flc-inspect`
walks them through, and the run itself as a page
(`~/flc/task/review/<run>.html`) to download and open in their own browser --
it is self-contained and works offline. The other paths are for you. If the
block is missing anything, `python3 ~/flc/bin/view_run.py --where` prints it on
its own.

Starting a second run while one is going is refused, to stop two runs fighting
over the same task.

## If it fails to start

- **The image fails to build** -- `~/flc/.build.log` has the real error. A
  missing or misspelled package is `/flc-add-package`, and that is theirs to
  fix; say so plainly.
- **Anything else** -- `harbor` not found, connection errors, `UnknownApiError`
  -- is a technical issue on our side. Read the log named by `--status` and
  `~/.flc/harbor_upgrade.log`, and `bash ~/flc/bin/proxy_setup.sh` diagnoses a
  gateway that cannot be reached; then follow *A technical issue on our side
  never stops them* in the skill. Tell the contributor one sentence, not the
  diagnosis.
