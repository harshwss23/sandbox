---
description: Check the criteria against the task for the common issues in this project, before delivering
---

Check this task's grading criteria for the defects that are common issues in
this project.

```bash
python3 ~/flc/bin/rubric_check.py
```

It reads `tests/rubrics.md`, the prompt, the ground truth, the justification,
the workspace and -- once there is a run -- the model's answer and what it did.
It asks one reading for each group of defects: how a line is worded, what the
prompt asks for that nothing checks, whether a line holds up against the files,
whether two lines score one thing, the weights, and whether a rerun could walk
past a negative line. Each is judged by the definitions this project holds
every rubric to. When what it finds is enough to matter, it reads those
criteria twice more, and only a finding seen every time can stop delivery. It
takes a few minutes and records the answer, and `/flc-deliver` reads that
record rather than checking again.

The reading about whether a line holds up can open the files whole and
recompute from them, and it checks their answer the same way it checks a line:
the answer is one of the things it reads, not the reference it trusts. A
statement it finds wrong counts only once three independent readings, each on
a different model and told nothing about why, all find it wrong too.

This uses budget. It reads again only when something it reads has changed: run
twice in a row, it shows the check already taken and says so. `--force` reads
again, and is only for when they ask.

## You never write a criterion, and neither does this

**The contributor writes every line themselves.** This command names defects; it
does not repair them, it writes nothing into `tests/rubrics.md`, and its findings
are not lines to paste. Where a fix is obvious once the defect is named, say the
wording aloud and let them type it -- that distinction is the whole reason the
rubric is worth anything, and this step is the one most likely to blur it,
because a named defect with an obvious repair is exactly the case. Removing a
line is the same: you may say which line can go and why, and they delete it.

## How to present it -- once

Say where the task stands first, in one sentence: nothing to fix, findings worth
fixing, or findings that stop delivery. Then the findings that stop delivery,
one at a time; then the other new findings; then the "seen before" ones, as the
one-line list the output already gives -- named, and not argued again.

For example, when findings stop delivery: "Three problems in your criteria stop
delivery. The first: criteria 13 and 17 both check that sedoheptulose comes out
of the cascade, and 17 already covers 13. Removing 13, or folding it into 17,
fixes it. You make the change in tests/rubrics.md; I don't edit your criteria.
Ready for the next one?"

For each finding, say what it is and what the fix is, and **treat it as
something to fix, not as a note** -- the same as the justification check's
findings. Each is a common issue in this project, and a finding that does not
stop delivery can still be a real defect in the rubric that ships. Propose
nothing beyond the finding's own remedy -- no extra rewording, no tidying of
lines nobody flagged.

## What the results mean

**MUST FIX** -- these findings were seen every time the criteria were read, and
together they stop delivery until they are fixed. None of them can be set
aside. Take them one at a time. Each has a remedy they control:

- a criterion that rejects a right answer is **widened** to what their ground
  truth allows -- not deleted, and not loosened until it checks nothing;
- a criterion that reads two ways gets **the missing few words**;
- something uncovered gets **a new criterion**, from their ground truth;
- a criterion that states something the files or a check show is wrong is
  **corrected**; where it only repeats their answer, the answer is what is
  wrong, which is the section below;
- a negative a rerun could walk past is **reworded as the mistake** -- the
  wrong route an answer takes -- with a positive line carrying the right value;
- a line another line already contains is **removed, or merged into it**: the
  containing line still checks it;
- a weight in the wrong bucket **moves to the bucket the finding names**.

If they think one of these is wrong, the way through is the same: the line says
more plainly what they meant, and the next check reads it afresh. Then
`/flc-rubrics`, this command again, and `/flc-grade` -- a rubric edit
invalidates the score.

**NOTHING STOPS DELIVERY** -- findings worth fixing, none of which stops
delivery. Treat each as something to fix unless it is wrong: it is one model's
reading of their rubric, and they are the expert on their task, so if they say
it is wrong and why, accept that and do not raise it again. There is nothing to
answer or type at delivery. When the output adds that the rubric would be
refused at delivery if every finding were right, say so plainly: those findings
are the ones to look at first.

**CLEAR** -- every category was read and this check found nothing against any
criterion. That is not the same as the rubric being good: it catches some
defects, not all of them. Before moving on, the two passes in `/flc-rubrics` --
down the prompt and down the ground truth, for anything no line checks -- are
still worth a few minutes.

**NOTHING TO FIX** -- some categories could not be read this time and what was
read found nothing. Say there is nothing to fix from this check -- never that
the criteria are clear. Do not mention the part that could not be read: it is
recorded, and the next check reads it again.

**NOT MEASURED** -- our check failed, not their rubric. Run it once more
yourself; if it still cannot measure, say the one sentence in *A technical
issue on our side* in the skill and move on: delivery lets the task through
when this could not measure it, and it is recorded for the project team.

**Read in part** -- when the findings come with a note that some categories
could not be read, present what it found exactly as usual, and do not mention
the part that could not be read.

## When their answer is what is wrong

**MUST FIX -- your answer states something a check shows is wrong** means three
independent readings each found one statement in `solution/ground_truth.md`
wrong, by a check anyone can rerun, and a line, a test or the justification
repeats it. It stops delivery. Say which statement, what is wrong with it and
the check, in their words, and which lines repeat it. The fix is theirs:
correct the answer, and every line and sentence that repeats it. Say plainly
that changing the answer after the run is expected here and is recorded with
the task -- the guides told them the answer is set before the run, and this is
the one case that asks them to move it.

You never edit the ground truth, or offer to. If they are sure the answer is
right, ask what the check got wrong and let them say it more plainly in the
answer itself; the next check reads it afresh. A statement nothing graded
repeats is shown the same way and does not stop delivery; treat it as
something to fix unless they say why it is wrong. A statement the independent
readings did not confirm is never shown, so there is nothing to say about one.

**Do not let a finding become a reason to cut a criterion that measures
something real.** The difficulty bar is a ceiling, so a contributor who has just
seen a score over it has an interest in a smaller rubric, and this step must
not become the way there. The one removal this check can ask for is a line
another line already contains, and there the containing line still checks it.

## If they ask how much to trust it

Say what it is. A model reading their rubric against the definitions this
project holds every rubric to, with anything it could not evidence thrown away
before they see it -- a finding whose quotation is not really in their prompt,
one whose own wording hedges, one naming a criterion that is not in the rubric,
one an exception rules out. Only findings seen every time it read the criteria
can stop delivery, and only when there are enough of them. A finding that
something is factually wrong counts only once three more readings, on three
different models, confirm it without being told why it was raised.

It is also the same instrument the project is built to catch out, which is worth
saying rather than hiding: it is right often enough to be worth a few minutes,
and it is not the authority on their field.

`--json` prints the record it wrote.
