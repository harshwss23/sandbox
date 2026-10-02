# When something goes wrong

First thing to try, always:

```
/flc-status
```

It tells you where you are and what the next step is. If you are stuck on
something specific, describe it to Claude Code in your own words -- it can read
the logs and diagnose it.

## The commands do not exist

If `/flc-check-inputs` comes back as an unknown command, the command set did not
install. Tell Claude Code the `/flc-` commands are missing: it reinstalls them.
Then close Claude Code and open it again so it picks them up. If they are still
missing, that is a technical issue on our side: reach out to the project team.

## Claude Code asks permission before every command

It should not: this machine is set up so it just runs them. If you are being
asked each time, close Claude Code and open it again. If it keeps asking, that
is a technical issue on our side: reach out to the project team.

You are asked once, on the very first launch, to accept that commands run
without your approval. Say yes. This machine is yours alone and is thrown away
when the task is delivered, so there is nothing here to damage. If you said no,
Claude Code closed itself; just open it again.

If you would rather be asked every time, tell Claude Code.

## "not enough material", or the run came in under the floor

Before the run, `/flc-check-inputs` says there may not be enough here. After it,
the measurement is exact: the task has to put 27,000 tokens in front of the
model, and only a run can say whether it did.

Everything in the folder counts, distractors included, because working out that
a file is irrelevant means reading it. So you can get there two ways: more of
the material the answer depends on, or more of the material a careful reader
would have to open before setting it aside.

If the folder is already large and the run still came in low, the model did not
have to read most of it. That is a prompt problem rather than a material one:
ask for something that cannot be answered without the rest of the folder, then
run the solver again. A big table on its own will not do it -- the model queries
it rather than reading it, so it contributes far less than its size suggests.

What will not help is filler -- files nobody would open at all. Those move the
number without making the task any longer to solve, and it is a common issue in
this project.

If your question genuinely only needs one small file and nothing else in the
folder is worth opening, it is not a long-context task. Consider a question that
requires cross-referencing several sources.

## A package is missing

```
/flc-add-package NAME
```

For a system package, `/flc-add-package --apt NAME`. For R,
`/flc-add-package --r NAME`.

You can do this at any point. Nothing has to be decided up front.

## The machine will not build

Claude Code reads the build error for you. Usually it is a misspelled package
name, or one that does not exist for this platform, and `/flc-add-package` with
the right name fixes it. Anything else is a technical issue on our side.

If something was installed by hand rather than with `/flc-add-package`, it
exists only on the machine you are working on right now, and the rebuild at
delivery will not have it. Add it with `/flc-add-package` so it is recorded.

## The solver run fails immediately

If the message names a missing package, add it with `/flc-add-package` and run
again. If the machine does not build, see above. Anything else is a technical
issue on our side, not your task: Claude Code notes it and tries again, and if
it cannot get the run going it will ask you to reach out to the project team.

## The run will not start

- **"/flc-check-inputs has not passed"**, or it passed on files that have since
  changed -- run `/flc-check-inputs` again (and `/flc-prompt-check` first if you
  changed the question), then start the run.
- **"Write the answer down before the model runs"** -- `solution/ground_truth.md`
  has nothing under *The answer* or *How it is derivable*. A short version of
  each is enough; see step 3.
- **"This run would be almost the same as run..."** -- your files, packages and
  block list are the same as that run's, and the prompt differs by a word or
  two. Running the same task again mostly shows the same thing again. If you
  still want it, say so and it starts. A changed block list is never held back
  like this, so after a run that read the answer off the web, block the site
  and run again.
- **"This would be solver run 6"** -- a task gets five counted runs, so there is
  budget left to grade and deliver. If another run is needed, say why in your
  own words; the reason is recorded with the task.

## The model gave up, or never found the files

Your folder may be too large or too disorganised to navigate at all, or the
question too vague to act on. Both are worth fixing: an unsolvable task measures
nothing.

Try making the question slightly more concrete about *what* you want, while
still not saying *where* it is.

This does not apply to a gap you left deliberately -- see below.

## The model asked me a question instead of answering

If your prompt left something out on purpose, that is the behaviour you were
looking for, and the problem is that your criteria did not credit it. Add a
`## Clarification` line for the question you wanted asked. [05-rubrics.md](05-rubrics.md)
has the shape.

If you did *not* leave a gap on purpose, the model found one anyway. Read what
it asked -- it is usually pointing at something genuinely ambiguous in your
material, and it is easier to fix now than to argue with.

## The model got everything right

Your task is too easy, and it cannot be delivered: the model has to score below
50%. This is not a threshold anyone can waive. A run where the model made no
mistake leaves a transcript with nothing to study, which is the one thing the
project cannot use -- so the task is unfinished rather than done.

See [07-grade.md](07-grade.md). This is a normal outcome for a first attempt,
and the grading step is where it is meant to surface.

## A command stops with an error instead of a result

Every check ends with PASS, WARN, FAIL or NOT MEASURED and tells you what to
do. If a command
stops with an error instead, that is a technical issue in the sandbox's own
tools. Nothing you wrote caused it, and it will not hold your task up.

Claude Code tries again, and fixes the fault itself where that is safe. Most of
these never reach you at all.

If it cannot fix one, it will say so and hand you a file -- a small zip with
everything the project team needs to work out what happened. Reach out to them
wherever you were told to ask for help, and send them that file. It matters
that you send it: what the sandbox records about a fault travels with the
finished task, so when the fault is the thing stopping you from finishing, the
file is the only way any of it reaches anyone.

- **Do not change your files, prompt, ground truth or criteria to get round
  it.** The problem is in the tool, so changing your task costs you a new run
  and a new grade and fixes nothing.

Carry on with anything that does not need that command in the meantime.

## I edited a file I should not have

Files like `task.toml`, `environment/Dockerfile` and `instruction.md` are
written for you, and your edits to them are overwritten the next time any
command runs. That is safe -- nothing is lost except the edit, and the next
`/flc-` command you run puts them back.

If one of those files looks wrong, that is our bug rather than yours. Say so
rather than editing it.

## I want to start over

Tell Claude Code you want to start the task again. Your old task is moved aside
rather than deleted: it sits in a folder next to `~/flc/task` with a timestamp
in its name.

## A step says the sandbox's own scripts have been changed

Nothing you wrote is involved: one of the sandbox's own scripts was changed.

```
/flc-restore-tools
```

puts it back, and Claude Code does this for you and notes it for the project
team. Then run the step you were on again; if it says the run or the grade has
to be taken again, do that too.
