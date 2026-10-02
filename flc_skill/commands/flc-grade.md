---
description: Step 7 - see which criteria the model passed and which it failed
---

Show the contributor how their task scored.

## Grade the run

Grading happens here, not during the solver run. The solver step produces a
transcript; the non-hallucination criteria are written from it; only then is
there a full rubric to grade against. This is the step that spends the judge:

```bash
python3 ~/flc/bin/run_grader.py
```

It runs the same verifier the delivered task carries, against the run the contributor
last started, and refuses if the criteria are still half written -- a rubric with
no non-hallucination criteria measures the half of the task that was never the
point. If it refuses, send them back to `/flc-rubrics`.

It also refuses below **20 checks**, counting the criteria and the unit tests
together. There is no override. Do not resolve this by proposing criteria: ask
what the model had to do on the way to the answer -- the file it had to open,
the figure it had to work out first, the step of their procedure it had to
follow -- and the missing ones are usually already in their ground truth,
unwritten. They add them in `tests/rubrics.md` themselves, as always. A task
that cannot reach 20 without repeating itself has too little in its folder,
which is worth saying plainly rather than padding around.

It needs Docker and takes a few minutes: one judge call per criterion. If they
have already graded and only want to reread the result, skip straight to the
report.

This uses budget, so grade again after a change -- the criteria, or a new run
-- and not in the hope that the same criteria score differently. The one
exception is a criterion the judge misread, which `/flc-check-grade` may send
back for one more grade.

If the grader prints that this grade will be refused at delivery, a grade of the
same run was at the bar or over it and only weights have changed since. Say so
plainly: a task does not get harder by weighing what the model got right for
less. The weights go back and the task gets harder. Never suggest a weight.

**This is the only place a task is scored.** `/flc-deliver` reads the number
left here rather than buying a second one, so grading again after changing the
rubric is a real step and not a formality -- delivery will refuse a score taken
against criteria that have since moved, and say so.

It also refuses to grade a run the task has moved past. If `prompt.md` or the
workspace changed after the run, the model was given the earlier version and a
score now would describe a task nobody ran. That needs `/flc-run-solver` again,
not a re-grade. `--force` scores it anyway for a look, but delivery will not
take a score taken that way.

## Print the result

```bash
python3 ~/flc/bin/grade_report.py
```

That prints every criterion they wrote, passed or failed, with the judge's own
reasoning for each, and the pass rate. There is nothing else to read. Do not go
looking through the transcript, and do not narrate what the model did -- this is
a rubrics grader, and a criterion either held or it did not.

Show them the output as it is. Only explain a line if they ask, or if the
wording is domain jargon they would not recognise.

Grading also writes the whole thing as a page, at
`~/flc/task/review/grade-<run>.html`. It is the same verdicts and the same
reasoning, laid out to be read rather than scrolled, with the automated checks
alongside them. Give them the path and tell them to download it and open it in
their own browser -- a long rubric is unreadable in a terminal, and the next
step asks them to read all of it.

## Then check the verdicts

```
/flc-check-grade
```

Do not skip this and do not let them skip it. The score is only worth what the
judge's reading of each criterion is worth, and the judge sometimes reads a
criterion differently from the way it was meant. That is a criterion to fix, not
a result about the model, and this is the step that catches it.

It is not a gate -- `/flc-deliver` records whether it was done and does not
block on it -- so whether it happens is down to what you say here.

## What the score means

The score is what the model earned of the positive criteria, less what its
negative criteria cost, over the points the positive criteria put at stake. A
`[5]` moves it five times as much as a `[1]`, a tripped `[-5]` takes five points
off, and it stops at zero rather than going below. Avoiding a negative criterion
earns nothing -- an answer that says nothing avoids all of them.

A unit-test suite, where the task has one, is scored the same way rather than
gating: each test carries a weight of 5, 3 or 1 set in `tests/test_weights.md`,
added to the total the positive criteria put up, and earned by passing.

**The task cannot be delivered unless the model scored below 50%.** That is the
difficulty bar, `/flc-deliver` enforces it, and it is not negotiable. Say it
plainly when the score comes in high, because it decides what they do next -- a
contributor who has just watched the model do well needs to hear that this is
the problem, not the result.

The number the bar reads is `reward` in the run's `reward.json`: the criteria
and the suite over one total, which is what the report prints as `score`. The
`rubrics` key beside it is the criteria alone. That is a part of the score and
not the score, it can sit far below it wherever the suite passes, and quoting it
as the figure compared to 50% tells the contributor their task clears a bar it
may not.

Be direct about why, because it is the premise of the whole project and it is
not obvious: we are not measuring how often models hallucinate. We are
collecting the cases where they do. A run with no mistake in it produces a
transcript nobody can learn anything from, however well-built the task around it
was.

## If the judge would not read a criterion

The report sometimes says a criterion was not graded because the judge declined
to read it. That is a safety filter reacting to the wording -- most often in the
clinical and biology domains, where an ordinary criterion about a pathogen or a
patient can read to a filter like a request for something else. It is not a
judgement about the task and not something the contributor did wrong. Say so
first, because the natural reading is that their criterion was inappropriate.

What it costs is coverage: that criterion is not part of the score, and the score
shown is over the rest. Two things to tell them, in this order:

1. **Grade again.** The filter is not consistent, and the same criterion often
   goes through on a second attempt. This is one attempt, not a loop.
2. **If it declines again, reword it.** The criterion has to say the same thing
   in different words -- naming the same fact more plainly, or describing the
   claim rather than quoting it. This is the part they control, and it usually
   works.

Do not suggest weakening what the criterion checks. The fact being tested stays;
only the wording moves.

If a small part of the rubric still cannot be graded, `/flc-deliver` leaves those
criteria out of the bundle and records that it did. If it is a large part, it
refuses, because a score over a fraction of a rubric does not describe the task.

## Judging the task, not the model

This is the step where they find out whether they built a good task. Read the
score, then say which of these it looks like:

- **Scored 50% or more** -- the task is too easy and cannot be delivered as it
  stands. Suggest making it harder: a better distractor, a question with more
  steps, or removing a file that made it too direct. A real finding, and this
  step is where it is meant to surface.
- **Failed the non-hallucination criteria** -- the model produced a confident
  wrong answer. Exactly what this project is looking for. Say so plainly.
- **Failed everything, including the basics** -- look before concluding
  anything. If the folder is too large to navigate or the prompt too vague about
  the part they *do* expect answered, that is a broken task. But check the
  ground truth first: if the task is underspecified by design, a model that
  refused to guess and asked instead is the intended behaviour, and the low
  score means the Clarification criteria never credited it. Fix the criteria,
  not the prompt.
- **A criterion judged oddly** -- reread it with them. Usually it was ambiguous
  or carried two facts. `/flc-check-grade` is where this gets worked through
  properly, and it names the remedy for each kind.

## If a package was missing

Two different things, and the difference matters.

**The report opens with an environment warning.** That means the solver went
looking for a tool and never got it. Do not read the failed criteria as a result
yet: a criterion failed because the model had no way to open the file looks
exactly like a criterion failed because the model got the answer wrong, and only
one of those is a finding. Add what it needed and run it again:

```bash
python3 ~/flc/bin/detect_packages.py --add
bash ~/flc/bin/run_solver.sh --background
```

**No warning, but it installed something itself.** The run is sound -- the
solver has a network and filled the gap. Still record it, or the delivered task
depends on a network it may not get:

```bash
python3 ~/flc/bin/detect_packages.py --add
```

Then `/flc-check-grade`, and `/flc-deliver` when they are happy with the task.
The step is recorded by the grader itself, so there is nothing to mark by hand.
