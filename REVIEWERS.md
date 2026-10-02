# Reviewing somebody else's task

This is for a review pass: a task that was authored in another sandbox and
handed to you to check, and possibly to fix. If you are building a task of your
own, this file is not for you -- start at
`contributor_instructions/00-start-here.md`.

## Start here

```
/flc-restore
```

Your sandbox came up fresh, with the work beside it rather than in it. Nothing
looks there on its own, so until you run this you will be told the solver never
ran. Run it with no arguments to see what it would move, then with `--apply`.

It also checks what arrived against the receipt the last person left, and marks
this session as a review pass so that anything you deliver says so.

Then read, in this order:

1. `delivery/AUDIT.md` -- what was checked, what was waved through, what the
   model scored and which model produced it. It is prose, and it is the fastest
   way to know what you are looking at.
2. `/flc-inspect` -- the run, read for you: what the model answered, what it
   actually did, and the claims worth checking.
3. `solution/ground_truth.md` and `tests/rubrics.md` -- the answer the task is
   graded against, and the criteria that grade it.

Do not start with a new run. The criteria were written against the run that is
already here, and a fresh one is a different run: the non-hallucination
criteria quote what *that* model claimed, and against a new transcript they
will catch nothing while looking like they still work.

## What you are actually checking

The task's own record answers most of it. What it cannot answer is judgement,
which is why a person is doing this:

- **Does the ground truth hold?** It is the fixed point. Everything else is
  measured against it, and nothing downstream can tell you it is wrong.
- **Do the completion criteria come from the ground truth**, or were they
  fitted to what the model happened to do? `AUDIT.md` says whether the ground
  truth was rewritten after the run, which is the loudest version of this.
- **Do the non-hallucination criteria describe a mistake any run could make?**
  A criterion quoting one sentence of one transcript catches nothing when the
  bundle is re-run against a different agent.
- **If there are clarification criteria, could the prompt really not be
  answered without asking?** `AUDIT.md` gives the count of each kind. That
  heading is for a gap the contributor left on purpose; a question the model
  could have settled from the material is a completion criterion wearing the
  wrong label, and it credits the model for asking about something it should
  have worked out.
- **If the task has automated checks, is each one worth what it says?**
  `AUDIT.md` gives the weighted total and `tests/test_weights.md` gives the
  reasoning per check. A check on a value the answer turns on is a 5 and a
  check on a filename is a 1, and the pressure runs the same way as everywhere
  else here -- the bar is a ceiling, so a passing check reweighted down is the
  shape to look for.
- **Is the prompt answerable from the workspace**, rather than from what a
  model already knows? A task whose answer is a published finding measures
  nothing, whatever the blocklist says.
- **Is there anything to rule out?** `delivery/authoring/materials.md` lists
  which files the author said carry the answer and which are there to be set
  aside, together with what the ground truth says about the same files, and
  notes where the two disagree. A task where every file is required has no
  triage in it. Read the disagreements as questions rather than findings: a
  published figure can honestly be both the evidence and the trap, and the
  comparison is a filename search over prose, so it proves a mention and never
  an absence.
- **Did the judge read each criterion the way it was meant?**
  `/flc-check-grade` walks them one at a time.

## Fixing what you find

You have every command the author had. Editing costs time, and `/flc-status`
now says how much before you spend it -- editing the prompt means the run again
and the grade again, editing a criterion means the grade again.

The rule that overrides the cost: **a criterion the judge misread, a prompt
that says the wrong thing, or a ground truth that is wrong all get fixed, no
matter what it costs and no matter what it does to the score.** The pressure
here runs one way -- the difficulty bar is a ceiling, so the criteria most
tempting to leave alone are the ones the model passed -- and a task that ships
with a defect nobody wanted to pay for is worth less than nothing, because it
looks like data.

## Delivering after a review

Run `/flc-deliver` exactly as the author would. It keeps their record rather
than replacing it: `validation.json` carries every earlier delivery, and
`AUDIT.md` opens with a provenance section saying this was a review pass, what
was delivered before and what it scored then. Nothing you do erases what they
handed over.

You do not have to run `/flc-submit`. The same check runs when you finish the
task.

## Two things that are not yours to change

**The sandbox's own scripts.** If a step refuses because a grading or run
script is not the one the seed shipped, that is a real finding about the task
you are reviewing, not an obstacle. Put the file back with
`/flc-restore-tools`, note what was changed, and re-take whatever evidence was
taken while it was changed.

**The record of what happened.** `delivery/` and `review/` are collected as
they stand. Everything you find belongs in the delivery record, which is
written for you, rather than in an edit that makes the problem invisible.
