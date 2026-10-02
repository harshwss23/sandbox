---
description: Step 3 - write down the correct answer before the model runs
---

Get the contributor to fill in `~/flc/task/solution/ground_truth.md` and
`~/flc/task/solution/underspecification_justification.md`, and the first three
answers in `~/flc/task/solution/labels.md`. In two parts, either side of the
first run:

- **Before the first run:** *The answer* and *How it is derivable* -- and *What
  the model cannot know*, if the task is underspecified. A short version is
  enough. `run_solver.sh` refuses to start until both are written, and each run
  keeps a copy of them as they stood when it started.
- **Once a run shows the task holds, before any further run:** the distractor
  section, the justification, the first three labels, and
  `/flc-check-justification`.

Check which part they are on with `/flc-status`. If no run has landed yet, the
first part is all this step needs: do not hold them here for the justification.

This step exists because of what happens without it. The grading criteria are
written later, and half of them are written *after* the model has answered --
which is the only way to catch what it invented, and also the way a criterion
quietly drifts into describing whatever the model happened to say. The answer
written down here, before any of that, is what the completion criteria are held
to. It is the fixed point of the whole task.

So the answer is not paperwork, and it cannot be skipped or filled in later. It
can be corrected after a run, and a wrong one has to be; the delivery record
shows the answer each run started against beside the one delivered, so it
is plain that it moved. It must never move towards what the model said,
and if you see it doing that, say so.

Read what is there now:

```bash
cat ~/flc/task/solution/ground_truth.md
```

If it is still the template, explain the sections and let them write. Their own
words are fine -- this is prose, not code, and nobody runs it.

- **The answer.** Specific. If it is a number, the number. If a name, the name
  plus any identifier that means the same thing, since a model answering with an
  Ensembl ID instead of a gene symbol is not wrong.
- **How it is derivable.** Which files, and roughly what you do with them. Two
  or three sentences. If they cannot write this, the task is not solvable from
  the inputs, and nothing after this step can fix that.
- **What should mislead a careless model.** Each distractor and the wrong answer
  it leads to. These are the traps to look for in the run: the ones it took
  become criteria, and at most two it avoided can too; the rest come from the
  run. This one can be finished after the first run, though a line per
  trap is worth writing before they read it.
- **What the model cannot know** -- only if the task is underspecified. Most
  tasks have no such section and that is fine. See below.

Push back if the answer is vague. "The expression goes up" is not checkable;
"log2 fold change 3.87 for GENE0421, padj 1.2e-5" is. You are not deciding what
the answer is -- but you should say plainly when what they have written could
not be graded.

## If the task is underspecified by design

Some prompts deliberately leave out something the model cannot work out from the
files, to see whether it asks or just picks one and reports the result as if it
were the only possibility. That is what "underspecified" means here, and only
that: the gap turns on a fact only they hold, and each possible answer leads to
different work. A gap the model can close by exploring the files or applying a
convention is not one -- the task is then fully specified, however much
exploring it takes, and calling it underspecified is a common issue in this
project.

If the gap is real, get three things written down, because all three become
criteria:

- **what is missing**, and why the files cannot settle it
- **what the model should ask**, in the words they would accept -- "asks which
  of the two March runs to use" is checkable, "asks a sensible question" is not
- **what it can still do without an answer**, since a task that cannot be
  started is not a task, and this half is graded like any other completion

Then get the failure written too: the model picking one silently and presenting
it as the answer. That is the negative criterion, and it is the entire point of
building the task this way.

Do not let this replace the ordinary answer. The part that is answerable still
needs its value written down, exactly as above.

## The second file: why that answer is the only one

`solution/underspecification_justification.md`, once a run shows the task holds
and before any further run, while the alternatives are still in their head.
Read what is there:

```bash
cat ~/flc/task/solution/underspecification_justification.md
```

It asks them to explain why their ground truth is **objective**: that their
answer is the only one an expert could reach, despite what the prompt leaves
out. It is one paragraph of plain prose -- longer only when the prompt leaves
several things open -- with no headings, lists, bold or backticks, and it has
to cover two things:

- **what determines the answer** -- a published standard, a value or
  constraint in the workspace, a fact that eliminates the alternatives. Named
  and pinned, not gestured at.
- **the one or two other paths a careful expert would consider, and what rules
  each out** -- with its closing fact stated.

Three things to hold them to, and the first is the one that matters:

- **"It is standard practice", "any expert would know this", and their own
  preference do not determine a ground truth.** If they cannot point to what
  forces the answer, the answer is a judgement call rather than a fact. Say
  this plainly when it happens.
- **If any other path survives, the task has more than one answer and has to
  change.** The remedy is to add the material that closes it, or to make the
  gap deliberate -- the *What the model cannot know* section of the ground
  truth -- so that stating the assumption or asking becomes the expected
  answer. Both are ordinary. Finding this before a further run rather than
  after one is the whole reason the file is written here.
- **If the gap is deliberate, it inverts.** No default is defensible, and
  showing that is what makes asking the only correct answer. The
  justification then says why each candidate default fails.

Two shapes are common issues in this project, and worth naming when you see
them: text general enough that it would fit another task of the same kind
unchanged, and text that reads like a form -- commentary on the task's design
or level, or a list of every file in the folder. The first is fixed by one
sentence naming the file, value or clause that settles the answer; nothing
else has to grow.

**You do not write into `solution/underspecification_justification.md`, any
more than you write their criteria.** It is their account of why their own answer is forced,
and a justification an assistant composed is a model's opinion of a model's
reading -- the same defect as an assistant-written rubric, in the file that
exists to rule it out. Offering wording for something they have told you is
fine; typing it in is theirs. Ask what closes a path, and put nothing in the
file they have not said.

## The labels: the first three

`solution/labels.md`, with the justification. Ask them for the first three
answers, each on the line under its heading, in a spelling the file lists:

- **Is your task underspecified?** yes or no, in the sense above.
- **Underspecification level.** The highest gap in the task: `l1 - minimal`
  (standard practice supplies the method), `l2 - low` (a value the answer needs
  is in one file), `l3 - moderate` (several sources have to be put together),
  `l4 - high` (in neither prompt nor files, and a convention forces one
  default), `l5 - full` (only they hold it, and the branches lead to different
  work). Step 3 of the guides has the test for each.
- **Does your task require browsing?** yes if the model has to look something
  up online.

Yes, `l5 - full`, a written *What the model cannot know* section and a
Clarification criterion go together, and the checks refuse any of them without
the rest. Say so once if their answers point different ways; the choice is
theirs.

The last two headings wait until the run has been graded.

**When they say the file is filled in, read it yourself** and name each
formatting problem: a value spelled other than the way the file lists, an
answer under the wrong heading, template text left behind. Ask first whether
you may fix the formatting, saying you will not change anything they chose or
how they worded it. If they agree, make only those changes, show them what
you changed, ask them to confirm the file now says what they meant, and run
`python3 ~/flc/bin/labels.py`. Never choose a value they did not give -- a
missing answer is a question to ask them, not a gap to fill.

Then send them to `/flc-check-justification`, which checks the labels and
reads the justification against the prompt and the ground truth. Run it
**before any further run**: a justification that does not hold means the task
has to change, and a run against the old task is a run spent for nothing.

Before the first run, once *The answer* and *How it is derivable* are written,
move them on to `/flc-run-solver`, which starts the run in the background.
Explain the order if they expect to write criteria first: the run takes a
while, the completion criteria get written while it goes, and the
hallucination criteria can only be written once there is a run to read.
