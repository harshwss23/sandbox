# Step 8: package it

```
/flc-deliver
```

## What it does

It throws away everything currently running and rebuilds your task's machine
from scratch, from your files alone, ignoring every shortcut and cached step.
Then it starts the grading machinery inside that fresh machine to prove it runs
there. Only then does it package anything.

This takes several minutes, and the wait is the point. It is the only check that
your task works for someone who has nothing but the files -- none of this
sandbox, and nothing you have typed into it along the way. A task that works
here and nowhere else is the failure this step exists to catch, and nothing
else would notice it until someone else tried to run your task.

It does not score your task again. The score is the one from
[07-grade.md](07-grade.md), and what this step checks is that it still belongs
to what is being packaged: the same prompt, the same files, the same criteria.
If you changed any of them afterwards, it tells you which and stops.

## If it fails

**The machine did not build.** Almost always a package installed by hand instead
of with `/flc-add-package`. Add it properly and run again:

```
/flc-add-package NAME
```

**Your run has not been graded.** The score is taken at
[07-grade.md](07-grade.md), so there has to be one. `/flc-grade`, then come
back.

**Your task has fewer than 20 checks.** Criteria and automated checks count
together. You should have met this at `/flc-grade`, so seeing it here usually
means a criterion was deleted afterwards. There is no way around it and no
exception that waves it through. [05-rubrics.md](05-rubrics.md) has what to add:
an outcome line for every ask in your prompt, at least five hallucination
criteria, and, for depth, a few lines about hard steps every correct route
takes. Add them, then `/flc-grade` again.

**Fewer than five hallucination criteria.** `/flc-rubrics` asks for five and
this asks again of the bundle, because a criterion the judge refused to read is
left out of what ships -- which takes the count under five without your having
changed a thing. The message says whether that is what happened. If it is,
reword those lines to say the same thing another way and `/flc-grade` again; if
not, write the rest under `## Non-hallucination`. [05-rubrics.md](05-rubrics.md)
is where the five are explained.

**More than two of your criteria describe a failure this run did not commit.**
The judge never charged the model for them, so they are wrong turns your task did
not compel rather than ones it recorded -- and a rubric mostly made of those
measures what one model happened to avoid rather than what your material does to
a model. The count only comes down when one of those lines fires or goes. Two
ways forward, and neither is to make a criterion easier: run the solver again
against material that pulls harder towards the wrong turns those lines
describe, so that they fire, or drop a line that describes a failure you
cannot point at in the answer at all. Writing lines for mistakes the run did
make is worth doing (`/flc-inspect`), but it does not bring this count down.
Then `/flc-grade`.

**Your criteria changed after you graded.** The score on record is of the older
criteria, so it is not a score of the task you are shipping. `/flc-grade` again
-- nothing else needs redoing, and it is the same few minutes as before.

The same goes for your automated checks and what they are worth. Editing
`tests/verifier.py` or a number in `tests/test_weights.md` moves the score by
the same mechanism a criterion does, so it needs the same re-grade, and the
message names whichever file it was.

**Your justification has not been checked, was checked before you last changed
it or your files, or has a finding to answer.** `/flc-check-justification`
reads `solution/underspecification_justification.md` against your prompt, your
answer and your files, and its verdict is only about the versions it read. Run
it, and again after any change to that file or to your files. If it names a finding, the remedy adds rather
than takes away: name what determines the answer, close the path, add the
material that closes it, or make the gap deliberate.
[03-ground-truth.md](03-ground-truth.md) has what it needs to cover.

**Your labels do not read cleanly or do not agree.** `solution/labels.md` is
checked again here, because an answer can move after the step that checked it:
each heading answered in one of the spellings it lists, yes going with
`l5 - full` and with a *What the model cannot know* section, Clarification
criteria only on a task marked yes, and the failure justification in at most
three plain sentences. The message names the heading and the line. Fix it in
`labels.md` and deliver again; nothing else needs redoing unless the answer to
the first question changed, in which case the rubric has to follow it.

**Your criteria have not been checked, or changed after the check.** Delivery
reads what `/flc-check-rubric` recorded and does not check them again, so the
check has to be of the criteria, prompt, ground truth, files and run you are
delivering. Run `/flc-check-rubric`, then deliver again.

**Findings in your criteria stop delivery.** `/flc-check-rubric` found them
every time it read your criteria, and together they are enough to stop the task
until they are fixed. Delivery names them, and `/flc-check-rubric` explains each
one and how to fix it. **None of the remedies is to make a criterion easier** --
each is the criterion saying more plainly what you already meant, a weight moved
to its bucket, or a line removed because another line already checks it. Fix
them in `tests/rubrics.md`, then `/flc-rubrics`, `/flc-check-rubric` and
`/flc-grade`. [05-rubrics.md](05-rubrics.md) has a section on each kind of
criterion.

**Your score counts automated checks that are not being shipped.** The checks
are graded from `tests/verifier.py`, so if that file is gone the task is graded
on your criteria alone -- and the score on record, which is what the
difficulty bar was read against, still has the checks' points in it. `/flc-grade`
again and the number will be of the task as it will actually be graded.

**You chose to skip the automated checks and a `tests/verifier.py` is still
there.** What runs the checks looks at that file and nothing else, so leaving it
would grade and ship checks you decided against -- and on a task that asked for
none, those are the examples the file came with, failing against files nobody
wrote. `/flc-skip-tests` sets it aside. If you would rather they counted after
all, `/flc-enable-tests` and then `/flc-check-tests`. Either way `/flc-grade`
again afterwards, because the score changes.

**There are no automated checks and nothing says that was the intention.** An
empty `tests/verifier.py` slot scores nothing either way, so the question is
whether you meant it. `/flc-skip-tests` is how to say you did, and it is the
right answer for a task whose answer is a finding rather than a file. If you did
mean to write checks, [06-unit-tests.md](06-unit-tests.md) is the step.

**Your prompt's difficulty was never checked, was checked before you last
changed it, or did not clear.** Run `/flc-prompt-check`. If it does not clear,
the prompt has to change, and a changed prompt means running the solver and
grading again.

**Your files and question were never checked, or changed since.** Run
`/flc-check-inputs` again, and deliver again.

**One of the sandbox's own scripts was changed.** That is not your work.
`/flc-restore-tools` puts it back -- Claude Code does this -- and then the step
it names is taken again.

**The judge gave no verdict on a criterion, or declined to read too much of the
rubric.** Reword the criteria it names to say the same thing more plainly, then
`/flc-grade` again. If it happens again after that, it is a technical issue on
our side: reach out to the project team.

**How much your task put in front of the model could not be measured.** That is
our instrument, not your task. Claude Code can deliver anyway, recording a
reason in your own words.

**Your prompt or your files changed after the run.** This one needs more than a
re-grade. The model was given the earlier version, so shipping now would mean
handing over one task and, as the evidence for it, a recording of a different
one. Run `/flc-run-solver` again, then `/flc-grade`.

**Your run was started with a different model.** It was started with a
setting that swaps the model, or the program driving it, for a comparison, so
its score is not a score of the model this sandbox measures. Run
`/flc-run-solver` again, read the new run with `/flc-inspect`, then
`/flc-grade`. Your files, prompt and ground truth stand. Your hallucination
criteria were written from the old run, so check them against the new one.

**The model looked the answer up.** A figure you wrote down as the answer came
back from a web page, and it is in none of your files, in nothing the model
produced, and in the output of nothing it ran -- so this run did not work it
out. `/flc-inspect` said the same thing and named the site.

**Nothing you have written is at fault, and none of it is lost.** Your files,
your prompt, your ground truth and your criteria all stand. It is the run that
gets replaced, and two commands do it:

```
/flc-block-domain example.com
/flc-run-solver
```

Then grade again. This is the failure the block list in
[04-run-the-solver.md](04-run-the-solver.md) exists to prevent, and it is worth
spending the five minutes there before the next run rather than finding this
twice.

**Your task put too little in front of the model.** It tells you the number and
how far short it is. This is measured from the run -- what the model actually
had to read -- not from the size of your folder, so a large folder the model
skimmed does not clear it. Add material to `environment/workspace/` that the
question cannot be answered without, or widen `prompt.md` so the work has to
cover more of what is already there. Then run `/flc-run-solver` again and grade
it again. Both of those are needed: the measurement comes from the run, so a new
run is the only thing that changes the number.

**The model scored 50% or more.** Your task is too easy to deliver. Nothing is
broken -- this is the difficulty bar, and it is the one failure here that is
about the task rather than the machinery. There is no way around it and no
exception that waves it through: a task the model gets right leaves a transcript
with no mistake in it, which is the one thing this project cannot use. Make it
harder, run the solver again, and grade it again. [07-grade.md](07-grade.md) has
what usually works.

**The score came under the bar through weights alone.** An earlier grade of this
same run was at the bar or over it, and nothing has changed since except the
weights of some lines. A task the model can already pass does not become
deliverable by weighing what it got right for less. The message names the lines
and their weights before and after: put them back and make the task harder
instead. A weight moved to the one `/flc-check-rubric` named for that line does
not count here.

**Too few of your criteria are separate.** `/flc-check-rubric` found, every time
it read them, that some lines only repeat what another line checks. Those do not
count towards the 20; the line they repeat still does, and so does every line
that checks something of its own. The message names them. Take each one out or
fold it into the line it repeats, and add a line for something your prompt asks
that no line covers yet, a hallucination criterion from the run, or a hard
trajectory line. Then `/flc-rubrics`, `/flc-check-rubric` and `/flc-grade`.

Delivery can also note, without stopping anything, the score your run would get
if the weights and repeated lines the check found were put right. When that
reaches the bar, your task is harder only because of those lines: fixing them
is still right, and then the task needs to get harder.

## What you get

```
~/flc/task/delivery/
  bundle/          your task, ready for someone else to run
  run/             what the model did and how it scored
  run_removals/    the rest of the run's files, kept but not needed
  authoring/       your prompt, criteria, answer, justification and labels,
                   and a note of which files carry it -- not shipped
  validation.json  the record that all the checks passed
  AUDIT.md         the same record, in plain English
```

Next: [09-submit.md](09-submit.md)
