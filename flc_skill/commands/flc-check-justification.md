---
description: Step 3 - check the labels, then the justification against the prompt and the answer
---

Check `solution/labels.md`, then review
`solution/underspecification_justification.md` against the two documents it is
about.

```bash
python3 ~/flc/bin/justification_check.py
```

It reads the first three labels first. If any of them cannot be read, or they
disagree with each other or with the ground truth, it says so and stops there:
the justification is read against the level they chose. Otherwise it asks
whether the justification holds together: does it name something that
actually forces the answer, does it rule out the other routes an expert could
take, and does it contradict itself, the prompt, the recorded answer or their
files. It can open their files whole and recompute from them, and it checks
the reasons the justification gives as well as its figures. The recorded
answer is one of the things it checks, not proof: a sentence is not right
because the answer says the same.

A finding that something is untrue or contradicted stops the task only once
three more readings, each on a different model and told nothing about why it
was raised, all find the same statement wrong. One they do not confirm is
never shown.

This uses budget. Run it again after a change -- to the justification, the
labels, the prompt, the answer or the files -- and not in the hope of a
different reading of the same text.

Read the output before saying anything. Exit 0 is a pass, 1 is something to
fix, 2 is our check having failed rather than their justification: run it once
more, and if it still fails, say the one sentence in *A technical issue on our
side* in the skill and carry on -- it blocks nothing and is recorded.

## When the labels are what stopped it

A spelling, a missing answer or an answer under the wrong heading: read the
file yourself, name each problem, and ask first whether you may fix the
formatting, saying you will not change anything they chose or how they worded
it. If they agree, make only those changes, show them what you changed, ask
them to confirm it now says what they meant, and run the check again. Never
choose a value they did not give.

A disagreement between answers is theirs to settle, and the output names both
sides:

- **underspecified yes with a level below `l5 - full`, or `l5 - full` with
  no** -- yes means Level 5 and nothing else.
- **yes with no *What the model cannot know* section in the ground truth, or
  no with one written** -- the section is what makes the task underspecified;
  either it is written and the answer is yes, or it is deleted.

## Run it after the first run, and before any further one

The first run comes before this, on purpose: it shows whether the task holds at
all, and a justification polished for a prompt the model solves at once is an
afternoon spent for nothing. Once a run shows the task holds, this comes next.
A justification that does not hold means the **task** has to change -- material
added, or the gap made deliberate -- and a further solver run against the old
task is a run spent for nothing.
If they are about to start a second run and this has not been run, say so once.

## What the findings mean

These stop the task:

- **No determiner** -- nothing is named that forces the answer. This is the
  common one, and it is worth being plain about: "it is standard practice",
  "any expert would know this" and their own preference do not determine a
  ground truth. A justification that can only appeal to the author's
  authority is reporting that the answer is a judgement call rather than a
  fact, and that is a finding about the task.
- **Path not eliminated** -- a route an expert could plausibly take is open.
  If another path survives, two experts reach two answers.
- **Contradicts the prompt / the ground truth / itself** -- two statements
  that cannot both be true. The finding quotes both.
- **Not true** -- a file named that the task does not supply, a value the
  files or a recomputation give differently, or a reason given for why a route
  fails that the data does not bear out, even where the conclusion stands.

**Your answer states something a check shows is wrong** is the same finding
about `solution/ground_truth.md`, where the justification repeats it. It stops
the task. Say which statement, what is wrong and the check, and that the fix is
to correct the answer and the justification together. Changing the answer
after the run is expected here and is recorded with the task; say so, since
the guides told them the answer is set before the run. You never edit the
answer. If they are sure it is right, ask what the check got wrong and let
them say it more plainly in the answer.
- **Markdown** or **too long** -- headings, lists, bold or backticks, or past
  600 words or five paragraphs. The justification is read as plain prose, and
  most are one paragraph.

These two are listed first, under "Check these against your files first".
They do not stop the task, and they are the most serious of the warnings:

- **Contradicts the files** -- a statement one of their files gives
  differently. The output shows their sentence beside the file's passage and
  names the file. Ask them to look at the file: if the file is right, the
  justification is corrected; if the justification is right, the file is what
  needs a second look. It stays a warning even once confirmed.
- **Generic** -- text that could fit another task of the same kind unchanged,
  naming nothing from this prompt, these files or this answer. One sentence
  naming the file, value or clause that settles the answer is the fix; the
  rest stays.

These are listed under "Fix this before you go on". They do not stop the task,
and each one is a common issue in this project:

- **Vague** -- something pointed at rather than named: "the protocol" with no
  protocol identified, "the usual threshold" with no value. One sentence
  naming what is meant is the fix; the rest stays.
- **Reads as generated** -- stock phrasing, commentary on the task's design or
  level, a list of every file in the folder.
- **Gap is not real** -- the task is marked underspecified, and the material or
  a convention settles the gap.
- **Longer than the level needs** -- a Level 1 task usually needs one short
  paragraph.

**Treat each of these as something to fix, not as a note.** Read it out, say
what the fix is, and expect them to make it. The only reason to leave one is
that the finding is wrong: if they say so and say why, accept it and do not
bring it up again. Do not wave one through on their behalf, and do not tell
them it can wait. `/flc-status` keeps showing it until a check comes back
without it, and `/flc-deliver` names it again.

## The remedies, and what they are not

**Nothing here asks them to weaken their answer**, and it is worth saying so
before they start editing. Every remedy adds: name the determiner, close the
path, add the material that closes it, or make the gap deliberate so that
stating the assumption or asking becomes the expected answer rather than a
wrong one.

Making the gap deliberate is a normal outcome and not a retreat. A task where no
default is defensible is a good task -- it is the shape the project wants ~30%
of the time -- and there the justification's job inverts: it shows that every
candidate default fails, which is what makes asking the only correct answer.
If they go that way, `solution/labels.md` becomes yes and `l5 - full`,
`solution/ground_truth.md` gains its fourth section, and `tests/rubrics.md`
will need a `## Clarification` criterion.

If a path genuinely cannot be closed and the gap cannot be made deliberate,
the task has more than one answer. Better heard now than after another run.

## You do not write it

The same rule as the criteria, and for the same reason. Propose wording in the
conversation for something they have told you; they type it in. A
justification an assistant composed is a model's opinion of a model's reading,
which is the defect this file exists to rule out.

`/flc-deliver` asks for a current pass on this: if they change the
justification after it passes, it needs `/flc-check-justification` again before
delivering.
