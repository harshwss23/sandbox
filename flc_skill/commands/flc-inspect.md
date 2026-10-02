---
description: Read the solver run and find the claims worth checking
---

Build the review document for the finished run and walk them through it.

```bash
python3 ~/flc/bin/review_run.py
python3 ~/flc/bin/view_run.py --where
```

This uses budget. Build it again only after something changed -- a new run, or
criteria written since -- and otherwise open the document already there.

The first writes `~/flc/task/review/<job>.md` and reports how many findings it
has. Open that file and read it before saying anything, because what is in it
is what you are about to discuss. The second prints where everything from the
run is, which is what they need in front of them.

The document holds the model's answer, its steps, the files it produced, and a
list of findings. Each finding carries the claim, why it was flagged, and what
it was checked against.

Tell them about `~/flc/task/review/<job>.html` while you work through it. It is
the whole run as a page -- the model's reasoning, every command it ran, what
came back from each one, and its final answer -- and it is meant to be
downloaded out of the sandbox and opened in their own browser. Anyone who wants
to see a claim in context should be sent there rather than to the JSON, and
`/flc-view` rebuilds it.

## First, before any of the findings

The document may open with **this run is not deliverable**. If it does, that is
the whole conversation and the findings below it are beside the point -- there
is no use writing criteria against a run that is being replaced.

It means a figure their own ground truth gives as the answer came back from a
web request, and appears in none of their files, in nothing the model produced,
and in the output of nothing else it ran. The model did not work it out; it
read it. Browsing is wanted and most of it is ordinary work, which is exactly
why this is worth catching: the tool call that looks something up and the one
that looks the *answer* up are the same call.

The remedy is two commands, and the document names the site:

```
/flc-block-domain <the site>
/flc-run-solver
```

**Say plainly that nothing they wrote is at fault.** Their files, prompt,
ground truth and criteria all stand, and none of that work is lost -- it is the
run being replaced. Contributors read a refusal as a verdict on their task, and
this one is not. `/flc-deliver` asks the same question and refuses the same
way, so there is nothing to be gained by carrying on to it.

The **Where it went on the web** section lists every request the run made, and
it is what to read together when they ask what else to block. A host the task
already blocks that answered anyway is flagged too: the block is name-level and
does not stop a raw address.

**What your criteria may not reach yet** appears once they have written some
negative criteria, and it is the weakest section in the document by
construction: it can only match a figure or a filename, so a criterion that
describes the same mistake in words of its own reads as a gap here and is
perfectly correct. Use it to ask whether each one is covered. Do not read it as
a list of criteria they owe, and do not write any of them.

## Then, their answer beside the model's

The document opens with their answer as it was written before this run, next to
the model's final answer. Ask them whether the model got there; do not answer
that for them.

- **If it did**, the task needs to change before anything else is written: the
  prompt or the files, then another run. Criteria for a task about to change
  are work spent twice.
- **If it did not**, and step 3 is only half done, that comes next: the
  distractors, the justification, the labels and `/flc-check-justification`,
  before any further run. Then the second sitting of `/flc-rubrics`.

The document shows the answer as it stood when this run started, so an edit
made since is not in it. A correction is fine and is recorded; an answer
rewritten to match the model is the thing to say plainly.

## What this is for

They are about to write the non-hallucination criteria, which means holding an
answer up against a folder of their own material and spotting the one figure
that is not in any of it. This does the mechanical half. The judgement is
theirs and has to stay theirs.

## How to talk about it

Go finding by finding, strongest first, and for each one ask them the question
the finding is really asking. Not "is this a hallucination" -- they will say
yes because the tool flagged it. Ask what the figure should have been, or
whether that file says what the model claims it says.

**Everything in it can be wrong.** A number the model derived correctly appears
in none of their files, and the document says so, but a contributor reading
quickly will still treat a flag as a verdict. When a finding turns out to be
fine, say so plainly and move on -- being wrong about a third of the time is
the expected behaviour of the checks, not a fault in their task.

Findings marked `weak` depend on something *not* appearing in the transcript,
and a command can do work without naming it. Never let a `weak` finding become
a criterion on its own evidence. Confirm it against the steps first.

If the document has an **Also suggested by a model** section, treat those with
more suspicion than the rest, not less. They came from a model reading the
answer, which is the same kind of thing that produced the mistakes being
catalogued. Each one has to be true of their task before it goes anywhere.

## Turning a finding into a criterion

**You do not write it. They do, in their own editor.** The drafts in the
document are starting points with the unknown part left in angle brackets,
because the tool does not know what a figure was meant to be. Work out the
missing part with them and say what the finished line would look like, then let
them type it into `tests/rubrics.md` under `## Non-hallucination`.

One case goes elsewhere, and only on a task `solution/labels.md` marks as
underspecified. If the model filled the gap rather than asking, that is two
lines, and both go under `## Clarification`: the question it should have
raised, and the choice it made silently.

You never write into `tests/rubrics.md`, and nothing this step runs writes into
it either. The criteria are the
contributor's account of what a wrong answer looks like in their field, and a
task whose criteria an assistant wrote is not the task this project is buying.
That holds even when the finding is obviously real and the wording is obvious
too -- see `/flc-rubrics`.

Hold them to the same thing `/flc-rubrics` does: the line describes the
mistake, not this sentence. This task will be re-run against a different
model, and a criterion quoting one exact wording catches nothing there.

Do not offer completion criteria from this. Those come from the ground truth
and were written before the run; nothing in a transcript should change them.

## If a check could not run

The document says so where that check's findings would be, under **One check
could not run**. That is the sandbox's own tools failing, not their task, and
the rest of the document is complete. Nothing is blocked, so follow *A
technical issue on our side never stops them* in the skill: say nothing about
it unless they ask, and carry on with the rest. Never change their files to
make the check run.

## If nothing was flagged

That is not a clean bill of health, and say so. The checks only find what
arithmetic and string matching can find -- a plausible method that the protocol
forbids, or a conclusion that does not follow from the table it cites, passes
all of them. Read the answer against the ground truth together anyway.

Then, once step 3 is finished and checked, go back to `/flc-rubrics` for the
second sitting.
