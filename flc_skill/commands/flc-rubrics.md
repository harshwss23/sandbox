---
description: Step 5 - check the grading criteria and say what needs fixing
---

Check what the contributor has written in `~/flc/task/tests/rubrics.md` and tell
them what to fix.

## You never write a criterion

**The contributor writes every line themselves. You do not edit
`tests/rubrics.md`, and neither does anything this command runs.** Not the
completion criteria, not the non-hallucination ones, not a line they just agreed
to, and not a line whose wording is obvious once the mistake has been named.

What you do is review. Read what they wrote, say which lines cannot be scored
and why, and name a fact their criteria leave unmeasured so they can decide
whether it belongs. Proposing wording in the conversation is fine, and is often
the quickest way to explain a fix -- they are the one who types it.

The distinction is not bureaucratic. These criteria are a domain expert's
account of what a wrong answer looks like in their field, and that judgement is
the whole of what the task is worth. Criteria an assistant wrote are a model
grading a model, which is the thing this project exists to measure rather than
to produce. If they ask you to write them, say what the step is for and offer to
go through the answer with them instead.

## Which sitting this is

This step is done in two sittings, and which one this is depends on the solver
run. Check first:

```bash
python3 ~/flc/bin/rubrics_build.py
```

It reports whether the run is still going, and holds the criteria to the right
standard for the moment they are being written in.

## Three common issues in this project

Name them when you see them, as a common issue in this project -- one at a
time, against the line that has it, rather than as a list up front:

- **A criterion pinned to one run's wrong answer** rather than to the
  underlying failure. The task is re-run against other models, which make the
  same mistake with a different figure or wording.
- **Asking for names or files the prompt never asked for.** A line that
  demands what the prompt did not require fails a model that did the work its
  own way.
- **One line checking two things, or readable two ways.**

## How the grading actually works

Worth explaining once, because it drives every rule below: each criterion is
sent to a judge model **on its own**, with the model's answer, the files it
produced, and its transcript, and scored yes or no. The judge does not see the
other criteria, the ground truth, or the uploaded files. A criterion that
depends on something outside itself cannot be scored -- it will be guessed.

**What to assume about the judge, since it sets the bar for every line.** A
frontier model reading as a capable generalist: not a novice, and not a
colleague in their field. It will follow an argument and it will not supply
their discipline's conventions. So a criterion that only resolves for somebody
who already knows the field is one to fix, and the fix is to put the missing
fact in the line rather than to simplify the check.

Two things follow, and they are the two most common issues in this project. A line must admit **one reading to the judge** -- not to its
author, and not to another expert -- so the question to ask of a doubtful line
is whether the judge could land either way on the same answer. And a line must
not be satisfiable **without the model having read the material**.

### Where one reading quietly becomes two

The lints catch two narrow cases, an ordinal and "the former". The four that
matter most turn on the contributor's own material rather than on the words, so
they are yours to ask about while reading their lines beside their workspace:

- **A word their material gives two candidates for.** "our recovery", in a
  workspace holding a recovery against the certified value and a recovery of the
  control material. Ask which one, and have them name it in the line.
- **A comparison with no basis stated.** "the widest interval" -- widest in the
  units the table prints, or widest relative to its own mean, which are often
  different rows.
- **A phrase whose scope is left open.** "the k-factor is right as it stands" --
  the number is correct, or nothing about how it is used needs changing. Where
  the answer is "correct, and applied twice", the two readings disagree.
- **A figure in brackets their own conventions do not produce.** `(22.383)`
  where the method their workspace specifies gives 22.382: the judge cannot tell
  whether the bracket is a value the answer must state or a note saying which
  quantity is meant.

Read a doubtful line back to them the way a stranger holding their workspace
would, and ask what else it could be taken to mean. The fix is a few words, and
never a weaker check.

## Sitting one: while the run is going

Only the **Completion** criteria. Did the model get there -- the answer, the
numbers, the reasoning it had to show. Everything in them comes from
`solution/ground_truth.md`, so nothing here waits on the run.

`rubrics_build.py` will report the missing non-hallucination criteria as `TODO`
rather than a failure. Do not push them to invent negatives now. Guessing what a
model might make up is exactly the weak version of this step.

**Two coverage passes, and the second is the one that gets skipped.** Down the
ground truth, asking what it asserts that no line of theirs checks; then down
`prompt.md` sentence by sentence, asking of every thing it asks for which line
checks it. The second pass is where missing criteria are found, and a criterion
that should have been written counts against a delivered rubric exactly as a
wrong one does. A prompt asking for three yields, with a rubric careful about one
of them, has left two ungraded -- so an answer omitting both loses nothing. A
fact the suite asserts is covered; a qualifier only a reader can weigh is not.

**Where the answer is a list of similar things** -- a row per sample, a call per
case -- the convention is at most five spot checks plus one line about the extent
of the group, and both halves are counted. Without the extent line, three rows of
a twelve-row table earn every criterion there is; past five spot checks the
rubric is flagged for the opposite problem. Read their group back to them and ask
which half it is short of.

End the sitting by telling them the run is still going and that you will come
back to it.

## Sitting two: once the run has finished

The **Non-hallucination** criteria, written against what the model actually
claimed. The run left a review document behind; open it with them:

```bash
python3 ~/flc/bin/review_run.py
```

It holds the answer, the steps the model took, and the claims worth checking --
figures in none of their files, cited files that do not exist, their own
planted wrong answers repeated back. `/flc-inspect` is the same thing with
guidance on how to talk it through, and is worth using if there is a lot in it.

Everything it flags can be wrong, and a contributor reading quickly will take a
flag for a verdict. Each finding says what it was checked against; use that
rather than the flag. `python3 ~/flc/bin/solver_answer.py --files` still prints
the answer alone if that is all you need.

To settle whether a finding is real, send them to `~/flc/task/review/<run>.html`
-- the run itself, downloaded and opened in their own browser, where the claim
can be read next to whatever came back from the command that preceded it.
`/flc-view` rebuilds it.

Read the answer with them and pull out anything stated as fact: a number that is
in none of their files, a citation to a file for something it does not say, a
conclusion drawn from the superseded data, a claim about a check it never ran.
Their planted distractors are a plan rather than a result: what counts is which
of them this run took, and the unplanned inventions are the valuable part -- ask
about anything in the answer they did not expect.

Each one they judge to be a real mistake becomes a negative line, describing the
mistake rather than its avoidance -- written by them, including when you have
just said aloud what the line should say.

Two things to hold them to here:

- **The line must describe the mistake, not this sentence.** This task is re-run
  against a different model, so a criterion pinned to this run's wording catches
  nothing on any other run, and `/flc-check-rubric` flags one that is. Two
  ways stay broad and still carry the fact the judge needs: name the wrong
  route ("takes the figure from the circulated summary rather than from the
  counts it analysed"), and let a positive line carry the right value. A
  negative that restates that positive the other way round ("gives a sample
  count other than the 12 it contains") scores the same thing twice unless this
  run gave a wrong count. A number their own material hands over is fine to
  pin, since any run taking that bait writes it -- as long as a positive line
  requires the correct figure for the same thing. A number only this run could
  have invented catches only this run.
- **Do not weaken the completion criteria to match what the model managed.**
  They were written from the ground truth and the ground truth has not changed.

**Five hallucination criteria, and the run is where they come from.** Fewer is
a FAIL once the run has landed, and so is a heading with nothing negative under
it. Work the run with them until there are five: every claim no file supports,
every citation to a file for something it does not say, every check it says it
ran and did not, every file it had to read and never opened, every conflict it
settled without saying so. They can be of any failure kind -- grounding,
exploration, correctness or reasoning, synthesis, conflict resolution -- and
not only a false claim.

**Up to two may be a failure the run did not provoke, and more than two is
refused at delivery.** A set where all of them fired is better than one where two
did not. Everything drawn from what this model did is still only what one model
did, and the delivered task is re-run against a different one -- so the allowance
exists, but it is an allowance rather than a quota to fill, and it is counted
over every negative criterion rather than over the first five. When the count is
over, only a line firing or going brings it down: drop the anticipated ones they
cannot point at in the answer, or change the prompt or the workspace so the
next run pulls towards them. Criteria for mistakes the run made that they had
not noticed are worth writing, but they do not reduce the count.

What makes one of these admissible is that the task's own setup pulls towards
it -- a filename that misleads about its contents, a default that is wrong for
this data, an inference the material invites without supporting, a resolution
limit that tempts a description of evidence the model cannot actually read. Ask
them which wrong turn they built in that this run avoided; they know, because
they built it. Weigh them by the buckets like any other negative line; no
fixed weight applies to them.

What this is not is an invitation to enumerate inventions. The set of failures
no model committed has no end, and a rubric can be padded with them
indefinitely without measuring anything more. At most two, admissible on that
test, and written as the class of mistake rather than as a sentence.

There is no label for these, and nothing at `/flc-rubrics` can tell them from
the rest: whether a criterion was anticipated is only visible after grading, as
a negative one that did not fire. What `/flc-rubrics` can count is how many
hallucination criteria there are, which is the five. `/flc-grade` reports how many
of them the run provoked, and says so when more than two went quiet.

## Clarification is only for an underspecified task

A `## Clarification` line exists only when `solution/labels.md` answers **yes**
to "Is your task underspecified?", which also means Level 5 and a *What the
model cannot know* section in the ground truth. `rubrics_build.py` refuses one
on a task marked **no**, and refuses a task marked **yes** that has no positive
line under Clarification once the run has landed. A Clarification line on a
task that was fully specified is a common issue in this project: if the model
could work it out from the material or from a convention every expert would
apply, the line is a Completion one.

When the task is underspecified, the criteria come in pairs and both halves go
under **Clarification**: that the model raised the gap, and that it chose one
reading without saying so. The part of the work it could do regardless is
ordinary **Completion**:

```markdown
## Clarification
- [5] Response asks which of the two March runs to use, or otherwise says it cannot tell which was intended
- [-5] Response reports a top gene from one of the two March runs without saying which run it used

## Completion
- [3] Response reports that 21 libraries passed the RIN filter, which is the same under either run
```

What never goes under Clarification is something the model invented, however
the gap led to it -- that is a Non-hallucination line.

Two things to hold them to:

- **The criterion names the question, not the act of asking.** "Asks a
  clarifying question" cannot be scored -- the judge has no way to know which
  question was the right one.
- **Allow the model to say it rather than ask it.** "I can't tell which of these
  you meant" is the behaviour under test, and a criterion that requires a
  question mark misses it. `or otherwise says it cannot tell` is the usual fix.

And warn them off "does not ask" as a negative line. A model that says "assuming
you meant the corrected run" has flagged its assumption and behaved reasonably.
The failure being caught is the silent pick presented as the only answer.

## Every line has a weight

`[5]`, `[3]`, `[1]` for what the answer should do; `[-5]`, `[-3]`, `[-1]` for
what it should not. Nothing else is accepted. The positive criteria are the
points at stake and a tripped negative subtracts from what was earned, so at
least one `[5]` is required, or nothing can fail the
answer.

The sign does the work: a positive line earns its points by being true, a
negative line by being false. So a negative line is written as the bad claim
itself -- `[-5] Response reports GENE1188 as the most significant gene` --
never as "does not report". The judge is always asked the same question, *is this true of the
answer*, and phrasing it as an avoidance makes it answer a double negative.

Two boundaries are worth knowing, because a line in the wrong bucket is a
common issue in this project even where the criterion itself is right. `[5]` is for the
answer being wrong without it, not for a spot check on one quantity. And between
the two large negatives: if the wrong claim **replaces** their finding it is
`[-5]`, and if it misleads while the finding still stands it is `[-3]`. Naming
the wrong sample as the result is `[-5]`; an unsupported aside beside a correct
answer is `[-3]`; a claim to have run a check it never ran is `[-5]` however
small the check, because the answer is reporting work that did not happen.
`05-rubrics.md` has all six in full.

## A line has to accept every right answer

The largest class of defect found in delivered rubrics, and the one worth most of
your attention here: a line naming one correct answer where the contributor's own
ground truth says several are correct. Which way the error falls is why it
matters, and it is the same asymmetry that decides a close call between a
criterion and a check. A generous line costs one criterion; a strict line fails a
model that did the work, and the whole value of the deliverable is that its
failures are real.

So read their lines beside `solution/ground_truth.md` and stop on anything the
ground truth treats as a choice:

- **One member of a set their material treats alike.** Five excluded samples
  named in the report, and a line naming two of them refuses an answer citing the
  third. Widen it to the set rather than dropping the identifier.
- **A convention their own answer calls a choice.** Where either sign convention
  is correct if stated, the line asks for the magnitudes and for the convention
  to be stated.
- **The form of a name.** A line demanding the symbol refuses "Selenium". Ask for
  what has to be identified and leave the spelling open, unless the prompt
  pinned it.
- **Two lines that disagree about what they accept.** One reading "or an
  equivalent convention it states" and a later one naming a single spelling: each
  is judged alone, so the strict one is the one that decides.

The same rule from the other end: a list of accepted forms needs the edges the
ground truth gives it. `(7.0, another value from the QC log, or the SOP's)`
accepts 3.0 as readily as 7.0. And a line asking the answer to *state* something
without saying what would count is satisfied by a wrong answer, stated
confidently.

## One phrasing for every line

A line about what the answer says opens with the word `Response` and a
present-tense verb -- `Response reports ...`, `Response identifies ...`,
`Response claims ...`. A line about what the agent did names its trajectory or
the agent, whichever reads naturally: `Trajectory shows the agent ...`, `The
agent's trajectory shows ...`, `The agent ...`, `In its trajectory, the agent
...`. The exception is a `[state]` line, whose subject is the file it names.

This matters when you propose wording, which is most of what you do here: a
suggestion in any other shape is one the contributor types in, and a rubric
mixing "Response reports", "The answer reports" and a bare "Reports" is three
sentence shapes for one kind of statement. Read back what they have already
written before suggesting a line, and match it.

## The two labels, neither of which they type out

Each delivered criterion is labelled twice, and both labels are worked out for
them. Explain them only if asked, or if a line looks mislabelled.

- **What it measures** -- `task completion` under `## Completion`,
  `clarification` under `## Clarification`, `hallucination` under
  `## Non-hallucination`. The section is the label, and the weight's sign has
  nothing to do with it.
- **Where it is checked** -- `user facing` by default, meaning the criterion is
  about what the model told the user. A criterion about a file the model wrote
  or changed takes `[state]` after the weight and is labelled `state change`:
  `- [3] [state] analysis/results.csv lists Pten in its first row`.

Both are things the user relies on; the tag only says where to look to check it.
A line tagged both `[state]` and `[user-facing]` is an error -- it is two
criteria, so split it.

## Explaining the findings

- **Refers to something outside itself** -- a FAIL, and the most common one.
  "the correct value", "as described above". Ask what value they mean and put it
  in the line.
- **Checking more than one thing** -- one criterion, one claim. If the answer
  gets the gene right and the p-value wrong, a combined line scores zero and
  they lose the distinction they wanted. What holds them to it is what
  stacking does to the score: a line carrying four claims pays all four points
  or none, which makes the reward spiky, high in variance and easy to game.
  "But the four parts are all about the same issue" is the case being
  described, not a defence against it.

  **A list is the shape to watch for**, because it does not read as stacked.
  `names S07, S19 and S22 as the excluded libraries` is three criteria: a
  response naming two of them and a wrong third scores zero for the two it got
  right. Same for values paired with items -- `6.1 for S07, 5.4 for S19 and
  6.8 for S22` is three. Say something about the weights while they split:
  three lines replacing one `[5]` are weighed by the bucket definitions, which
  usually leaves at most one at `[5]` -- otherwise the topic quietly triples
  its share of the rubric.

  **And not the other extreme.** One claim is not one word, and splitting
  until each line holds a fragment that says nothing is the same defect from
  the other side.

  **An item stated with the property that identifies it is not this.** "the
  Sh ble cassette conferring zeocin resistance" names which cassette is meant;
  it does not ask for the phenotype as a second fact, and a response that
  names the cassette has satisfied it. Splitting that would leave two lines a
  response could satisfy without ever connecting them. This shape is often
  mistaken for a stacked line, so if they ask, that is the answer.
- **Does not open with 'Response' or the agent** -- a WARN, and the quickest
  one to resolve: the line says the right thing in the wrong shape. `Indicates
  that any file under data/ was modified` becomes `Response indicates that
  ...`, `The answer states ...` becomes `Response states ...`, and `The model
  reads ...` becomes `The agent reads ...` when it is about what the agent did.
  A line whose subject is a file it names is the exception and is not
  flagged.
- **Asks for a judgement** -- "thorough", "well-reasoned", "sensible". Ask what
  they would actually look for. Usually there is a concrete fact behind it.
- **No hallucination criteria** -- a TODO while the run is going, a FAIL
  after it, and it fires on a heading holding only positive lines as well as on
  an empty one. Walk them through the run, then their distractors.
- **Short of five hallucination criteria** -- a TODO while the run is going
  and a FAIL after it. Not a padding problem: the mistakes are in the run and
  the reading is the work. Take it a claim at a time with them rather than
  naming a number, and if the answer genuinely made fewer than five claims
  worth catching, up to two may be a wrong turn the material invites that this
  run avoided.
- **Nothing weighted [5]** -- a FAIL. Ask which criteria carry the answer.
- **Two lines measuring the same thing** -- an overlap scores one mistake twice.
  Ask whether each line names a fact no other line names. Where one line
  already contains another, say so: they can remove the contained line or merge
  it into the other, since the containing line still checks it. Beyond that,
  never suggest cutting a line that measures something real to tidy the list.
  The costly version is two negatives for one wrong claim, a general one and
  one naming the particular route this run took to it: the model is charged
  twice for a single sentence, and the score the difficulty bar reads moves.
- **Fewer than 20 checks** -- a TODO while the run is going and a WARN after it,
  and grading refuses below it. Do not resolve this by suggesting lines. Go
  through the parts of a rubric with them: an outcome line for every ask in the
  prompt, at least five hallucination criteria from the run, and, for depth, a
  few lines about hard steps every correct route takes -- which figure it had
  to work out first, which two sources it had to reconcile -- never an easy
  step like opening a file. The missing criteria are usually already in their
  ground truth, unwritten. A task that cannot reach 20 without repeating itself
  is a task with too little in the folder, which is a step 1 problem and worth
  saying plainly rather than padding around.
- **A negative under Clarification** -- a WARN, and often nothing to do. Ask
  which it is: a question the model should have asked is right where it is, and
  something the model invented belongs under `## Non-hallucination`.
- **Uses an ordinal the judge cannot resolve** -- a WARN. "the second
  recombination", "the first construct": the judge is shown one criterion with
  nothing else, so it has no way to know which round or which construct. The
  fix is to name the thing -- "the hygromycin construct" rather than "the
  second construct" -- which costs a few words and grades the same on any run.
  An ordinal indexing a position in something the line names, like "its first
  row", is self-contained and is not caught.
- **Points outside itself** -- a WARN on "the former", "the latter", "the
  previous". Nothing in the line says what they refer to. Note that "the
  other" is fine where the line establishes both ends: "one allele carries the
  zeocin construct and the other carries the hygromycin construct" is
  complete.
- **Lists what the run did rather than the mistake** -- a WARN on a
  non-hallucination line that enumerates three or more identifiers without
  saying what makes them wrong. `claims clones 5, 16, 27 and 28 were
  transformed` holds only against the run that named those four;
  `presents any clone other than 8, 18 and 22 as a double transformant`
  catches the same error on any run. The list is not the problem -- using it
  to define what is *correct* is the fix. It is a WARN because an enumerated
  set genuinely is the class when the material has exactly those wrong turns
  in it, and only they can tell.
- **Quotes a phrase out of the answer** -- a WARN on the same half. A
  criterion pinned to one wording scores nothing against a model that made the
  same mistake in other words.
- **Credits the model for looking something up** -- a WARN, and only on a
  positive line. The judge is shown the answer, the produced files and the
  transcript, and never a web page, so a criterion resting on what a site
  said cannot be scored -- and the bundle is re-run later against an agent
  that may have no browser. Browsing is wanted and the prompt can ask for it;
  the criterion is the fact that came back, so "gives the threshold as 7.0"
  replaces "looks up the threshold". A **negative** line about a source the
  model invented is the opposite case and is deliberately not caught.
- **Checks an exact value in a file** -- a WARN, and the one to act on rather
  than wave through. See below.

## Values in a produced file belong in the suite

Watch for this while they write, because it is the commonest way a rubric goes
wrong and it is expensive to undo. If the prompt asks for a file with a fixed
shape -- JSON with named keys, CSV with named columns -- then criteria like
`output.json reports total_variants as 1184` are assertions, not criteria. A
real task arrived here with thirty-six of them and the whole rubric had to be
rewritten.

Say why rather than just moving them: a criterion spends a judge call per value
to have a language model eyeball a number that `assert got == 1184` settles
exactly, in a second, for nothing, and reports which value was wrong. They are
weighted on the same scale either way, so nothing is lost by moving them.

Three things not to overcorrect into. A number **stated in prose** stays a
criterion -- the model may write `1.2e-5` or `0.000012` and both are right,
which a judge handles and a text match does not.

**A fact the prompt only exemplified stays too**, and naming a file does not
settle this: check what the prompt *required* against what it merely showed. A
prompt reading `columns Values (e.g.: Value 1.1 for topic 1 value 1), and
Correct Value` requires the two column names and gives the row label as an
example, so the labels may be spelled any sensible way and a check demanding
`Value 1.1` would fail a correct model. Same for the cell: `3.6`, `3.6 eV·Å` and
`~3.6` are one answer in three spellings. Ask which it is per fact rather than
per file, and remember which way the error falls -- a generous criterion costs
one criterion, a strict check invents a failure in a deliverable whose whole
value is that its failures are real.

And if the contributor does not write Python, leave the criteria where they are:
the trade is worth it, and `/flc-skip-tests` is a supported outcome.

When it passes it writes `tests/rubrics.json`, which is what ships. Tell them how
many criteria they ended up with in each section.

Next, when both sittings are done: `/flc-check-rubric`, then `/flc-check-tests`
-- or `/flc-skip-tests` if the answer is prose and there is nothing mechanical
to check.
