# Step 5: the grading criteria

Write them in `~/flc/task/tests/rubrics.md`, as a list of statements about the
answer that are either true or false.

## This step happens in two sittings

**Now, while the solver runs:** the Completion criteria. They say what a right
answer contains, they come straight out of your ground truth, and they need
nothing from the run.

**After it finishes:** the Non-hallucination criteria. These are written against
what the model actually claimed, because that is the only way to know what it
invented. Run `/flc-rubrics` again then and it will show you its answer.

Run `/flc-rubrics` in both sittings. It knows whether the run has landed, and
will not ask you for the second half before you can write it.

## Three common issues in this project

Each one is caught later and costs a rewrite, so it is cheaper to know now:

- **A criterion pinned to one run's wrong answer.** Your task is re-run against
  other models, which make the same mistake with a different number or in
  different words. Write the underlying failure -- the wrong route the answer
  took -- and let a positive line carry the right value, so the rubric catches
  it in any run.
- **Asking for names or files the prompt never asked for.** A line demanding a
  filename, a column or a phrasing your prompt did not require fails a model
  that did the work its own way.
- **One line checking two things, or readable two ways.** Split the first, and
  reword the second until the judge could only apply it one way.

## How the grading works

This drives every rule below, so it is worth understanding before you write.

Each criterion is sent to a judge model **on its own**, along with four things:
your prompt, the model's answer, any files the model created or changed, and a
transcript of what it did. The judge is asked one question: is this statement
true of this answer? Yes or no.

So a criterion can be about a file the model wrote, not only about what it said.
"analysis/results.csv lists PTEN in its first row" is scoreable, and so is
"Response claims to have run a test it never ran", because the transcript is
there.

The judge does not see your other criteria. It does not see your ground truth.
It does not see the files you uploaded either -- only the ones the model
produced or altered, which is how "did it actually write the results file" can
be answered at all.

So every criterion must contain everything needed to score it. "Response
reports the correct value" cannot be judged -- the judge has no idea what the
correct value is. Write the value into the line.

**Who the judge is, because it decides how much you can leave out.** A frontier
model, reading as a capable generalist would. Not a novice -- it follows an
argument, it knows what a p-value is, and ordinary technical prose does not
throw it. And not a colleague in your field -- it does not hold the
professional judgement your task is built to test, and it is not meant to.

So the line carries the domain knowledge needed to decide it. If settling your
criterion takes knowing that a RIN of exactly 7.0 is retained under a rule that
says "below 7.0", the line says that. What does not work is leaving it out and
expecting the judge to supply your field's conventions.

**One reading, and it is the judge's reading that counts.** The test is not
whether the line is clear to you, or to someone in your lab. It is whether the
judge could reasonably apply it two different ways to the same answer. "Anyone
in the field would know what I meant" is not a defence here: the judge is the
reader, and a line that admits two verdicts gets one of them more or less at
random.

## Where one reading quietly becomes two

That rule is the principle; these are the four shapes it comes apart in. All
four read perfectly to the person who wrote them, which is why they have to be
looked for on purpose.

**A word your own material gives two candidates for.** "our recovery" is one
thing to you, and two things in a workspace that holds a recovery against the
certified value and a recovery of the control material. If the two disagree, the
same correct answer passes under one reading and fails under the other. Name
which: "our recovery against the certified value".

**A comparison with no basis stated.** "the widest interval" means the widest in
the units your table prints, or the widest relative to its own mean -- and those
are often different rows. Say which one, and give the figure: "the widest
relative to its own mean, at roughly plus or minus 8 percent".

**A phrase whose scope is left open.** "the k-factor is right as it stands" can
mean the number itself is correct, or that nothing about how it is being used
needs to change. If the right answer is "the number is correct and it is being
applied twice", one reading credits that answer and the other refuses it.

**A figure in brackets that your own conventions do not produce.** Write
`(22.383)` beside a quantity when the method your workspace specifies gives
22.382, and the judge cannot tell whether the bracket is a value the answer must
state or a note saying which quantity is meant. Work any number out the way your
own material says to before you put it in a line.

The test that catches all four is to read the line as a stranger who has your
workspace but not your intentions, and ask what else it could be taken to mean.
`/flc-rubrics` catches two narrower versions of this -- an ordinal such as "the
second construct", and "the former" -- and it cannot see these four, because
each of them turns on your material rather than on the words.

## Every line has a weight

Each criterion starts with what it is worth. Six weights, nothing else:

| Weight | Meaning |
|--------|---------|
| `[5]` | the answer is wrong without this |
| `[3]` | this matters |
| `[1]` | a detail worth a point |
| `[-5]` | doing this alone ruins the answer |
| `[-3]` | doing this is a real problem |
| `[-1]` | a small thing it should not do |

The sign is the important part. A **positive** line describes something the
answer should do, and earns its points by being true. A **negative** line
describes something the answer should *not* do, and **costs** its points if the
model does it.

So write a negative line as the bad thing itself, not as its avoidance:

```markdown
- [-5] Response reports 134 as the number of differentially expressed genes under SOP-DE-004.
```

not `does not report 134`. Both are understandable to a person, but the
first is what the judge is actually asked -- *is this true of the answer?* --
and the weight's sign does the rest. Phrasing it as an avoidance makes the
judge answer a double negative, which is where graders quietly start being
wrong.

The positive lines are the marks available, and the score is what the model
earns of them, less anything its negative lines cost, so weights are how you say
that getting the headline number right matters more than naming every sample.

Nothing is earned by avoiding a negative line -- an answer that says nothing
avoids all of them, and should not be paid for that. A `[-5]` the model trips
over takes five points off what it earned elsewhere, and the score stops at zero
rather than going below it.

### Which of the six, exactly

The table above is the whole scale. This is the same six weights with the
boundaries that actually get argued about: a line in the wrong bucket is a
common issue in this project even when the criterion itself is right.

**`[5]` -- the answer is wrong without this.** The headline finding, the direct
answer to something your prompt asks in its own words, or a value the rest of
the answer rests on. Not a spot check on one quantity, and not something the
answer survives getting wrong. A hard constraint your prompt set belongs here
too. *Names the gene, element or sample the analysis identifies. Attributes the
discrepancy to the right side of the question you asked. Produces the file you
asked for at all.* **Everything your prompt asks for by name is `[5]`**: if it
asks for the adjusted p-value, the line giving that p-value is a `[5]`, even
though the same figure would be a supporting one in a task that did not ask.

**`[3]` -- this matters.** A supporting quantity, the method or the route, a
second finding that changes how much the answer can be trusted. Not the
conclusion itself, and not a single field that changes nothing about whether the
answer holds. *Reports the statistic behind the headline. Names the run the
conclusion was drawn from. Gives a second comparison that corroborates it.*

**`[1]` -- a detail worth a point.** A supporting figure: one field, label,
identifier or quoted number the answer uses on the way to a finding. Not the
answer itself, and not the same value copied into a file your prompt asks for
-- that copy is weighted like the value (see *Criteria about files*). *Notes
which sample we are. Quotes one supporting number. Records a qualifier the
reader would want and could do without.*

**`[-1]` -- a small thing it should not do.** An aside your material does not
establish and a reader would simply set aside. Not anything that changes what
the reader would conclude. *An aside about a run or a file your material never
mentions.*

**`[-3]` -- doing this is a real problem.** A claim your material does not
establish, or an assumption made silently, that misleads while the headline
conclusion still stands. *States a value that is in none of your files.
Attributes a result to a cause your workspace neither reports nor tests.
Presents a side observation as though your material had confirmed it.*

**`[-5]` -- doing this alone ruins the answer.** A fabrication or a
misattribution that makes the whole answer wrong: an invented headline value, a
conclusion drawn from material that says nothing of the kind, or a claim about
work the model did not do. *Names the wrong gene, element or sample as the
answer. Reports one of your files as saying something it does not. Claims to
have recomputed a figure that appears nowhere in its working or in the
transcript. Reports as sound the very thing your analysis shows cannot be relied
on. Ignores a constraint your prompt set outright.*

Those last two are the pair that gets mixed up, and what separates them is what
the claim does to the answer rather than how irritating it is. If the wrong
claim **replaces** your finding, it is `[-5]`; if it misleads and your finding
still stands, it is `[-3]`. Naming the wrong sample as the result is `[-5]`
because there is now no answer left. A claim to have run a check it never ran is
`[-5]` however small the check, because the answer is reporting work that did
not happen.

## How a line opens

One phrasing for the whole rubric. A line about what the answer says opens
with the word `Response` and a present-tense verb:

```markdown
- [5] Response states that 217 genes are differentially expressed under SOP-DE-004.
```

A line about what the agent did opens by naming its trajectory or the agent,
whichever reads naturally: "Trajectory shows the agent ...", "The agent's
trajectory shows ...", "The agent ...", or "In its trajectory, the agent ...".
*Writing each kind of criterion* below has a full line in each shape.

Not "The answer identifies", not "The model reports", and not "Identifies" with
the subject left off. Each of those reads perfectly well on its own, which is
the problem: nobody notices writing a rubric in three styles, and a rubric read
line after line then carries three sentence shapes for one kind of statement.

The exception is the `[state]` line in the next section. Its subject is the
file it names rather than the answer, so `Response` in front of it would be
wrong rather than untidy.

`/flc-rubrics` points out a line written some other way. It is a note and not
a refusal -- a line that says something true in another shape still grades
correctly, so nothing here blocks on it.

## Criteria about files

A criterion is about what the model told you, unless you add `[state]`, which
makes it about what the model left in the workspace. When your prompt asks for
a file, its copy of a value is weighted like the value, and never below `[3]`.
A `[1]` on a file's copy of a value a `[5]` line checks is warned about at
`/flc-rubrics`, and `/flc-check-rubric` reports it as a weight to fix. This
pair is written as if the prompt asked for the file:

```markdown
- [5] Response states that 217 genes are differentially expressed under SOP-DE-004.
- [5] [state] results/de_summary.csv reports 217 differentially expressed genes.
```

If a line needs both, write two lines.

## A criterion has to accept every right answer

The commonest defect in delivered rubrics is a line that names one correct
answer where the ground truth says several are correct. It costs more than it
looks like it does: your task is a record of where models genuinely fail, so a
criterion that fails a model for being right does not simply mis-score that run,
it puts a failure into the record that never happened.

Which way to err follows from that. A line that is slightly too generous costs
you one criterion. A line that is too strict fails a model that did the work.
That same asymmetry decides the close calls further down, where a fact that
looks like a test turns out not to be one.

So read your ground truth for the places where it allows more than one answer --
"any of these five is the same exclusion", "either convention is correct if it
says which", "a solver that starts at 1 is acceptable when it says so" -- and
check that the line covering each of them allows what the ground truth allows.
If the report names five excluded samples and any of them evidences the point:

```markdown
- [3] [state] audit.csv names SRR5962348 or SRR5962351 as the excluded sample
```

turns down an answer citing the third, which is the same fact from the same
message. Widen it to the five the report names rather than dropping the
requirement for an identifier.

Two more of the same shape, both worth a deliberate look:

- **The form of a name is not the check.** A line requiring the element symbol
  turns down a file that writes "Selenium", and both identify it perfectly well.
  Ask for what has to be identified and leave the spelling open, unless your
  prompt pinned it.
- **One line can take back what another allowed.** If one criterion says "or an
  equivalent convention it states" and a later one names a single spelling of
  the same thing, the later one decides, because each is judged on its own. Two
  lines about one quantity have to agree about what they accept.

The opposite mistake is a line so open that a wrong answer walks through it. If
you list what you will accept, bound the list the way your ground truth bounds
it:

```markdown
- [3] Response states which cut-off it used (7.0, another value from the QC log, or the SOP's)
```

accepts 3.0 as readily as 7.0, because "another value from the QC log" has no
edges. Name the values that are actually acceptable. The same goes for any line
asking the answer to *state* something without saying what would count: "states
which normalisation it used" is satisfied by the wrong normalisation, named
confidently.

## Nothing here is about the model browsing

The model has the internet while it works, and looking things up is part of
doing the job -- step 2 says to write your question expecting it. None of that
belongs in a criterion.

The reason is the section above: the judge is shown the answer, the files the
model produced and a transcript of what it did. **It is never shown a web
page**, so it has no way to check what one said. A line like "Response cites
the ASTM limit from astm.org" asks a question the judge cannot answer, and a
page moves anyway -- your task is re-run months later, against an agent that
may have no browser at all.

So write the fact, not where it came from:

```markdown
- [5] Response gives a RIN below 7.0 as the reason libraries were excluded.
```

not "Response looks up the RIN threshold". If the model had to search for the
threshold, the criterion is still the threshold.

One thing does belong here, and it is the opposite case. A **negative** line
about a source the model made up -- a URL that does not exist, a page credited
for something it does not say -- is a fabrication caught, which is the most
valuable kind of criterion in the whole set:

```markdown
- [-3] Response attributes the exclusion threshold to a published standard that states no such figure
```

`/flc-rubrics` warns about the positive case and leaves the negative one alone.

## Exact values in a file are a check, not a criterion

Read this before writing a long rubric. It is the commonest way a rubric goes
wrong here, and it is expensive to undo.

**If your prompt asks the model to write a file with a fixed shape -- a JSON
file with named keys, a CSV with named columns -- then the values in it belong
in [step 6](06-unit-tests.md), not here.** A few lines of Python compares them
exactly, or to whatever tolerance you decide, every time and for nothing. Asking
the judge to do it means a language model eyeballing a number, which is slower,
costs a judge call each, and is wrong often enough to matter.

A rubric of thirty lines that all read like this is the shape to watch for:

```markdown
- [3] output.json reports total_variants as 1184
- [3] output.json reports mean_depth as 42.7
- [3] output.json reports the sample id as NA12878
```

Those are three assertions in a test file. It has happened on a real task, at
that length, and the whole rubric had to be rewritten.

**What stays here is what a program cannot settle.** The judge reads the
answer's prose, and prose is where the interesting failures live:

```markdown
- [5] Response gives the adjusted p-value of ENSG00000000056 as 1.0e-13, in any notation.
- [-3] Trajectory shows the agent accepting the circulated result because its thresholds match SOP-DE-004's, without applying the SOP's earlier steps.
- [-5] Response reports a count of differentially expressed genes that no step of its own analysis produced.
```

The first is a number and still belongs here, because it is a number *stated in
prose*: the model might write `1.0e-13`, `1e-13` or `1.0 x 10^-13`, and a
judge reading for the value gets all three where a text match gets one. The
difference is not file against answer, it is whether the format is pinned.

### Pinned, or only given as an example?

Naming a file does not pin everything inside it, and that is the easy way to
take the rule too far. Ask it of **each fact on its own**: did your prompt
*require* the exact thing a check would compare, or did it only show one way of
writing it?

Here is a real prompt with both answers in a single sentence:

> Put the answers that need to be fixed in a **check.csv** doc in the workspace,
> with columns **Values** (e.g.: Value 1.1 for topic 1 value 1), and
> **Correct Value**.

- `check.csv`, `Values`, `Correct Value` are **required**. The prompt says to
  use them, so a check may insist on them.
- `Value 1.1` is **an example** -- that is what "e.g." means. The model may as
  reasonably write `1.1`, or name the row after the slide heading it came from.
  A check demanding `Value 1.1` marks a model wrong for work it did correctly.

The same goes for the value itself. If the cell may read `3.6`, `3.6 eV·Å` or
`~3.6`, then no comparison settles it and the criterion stays here.

**Which way a mistake falls decides the close ones.** A criterion that is too
generous costs you one criterion. A check that is too strict fails a model that
was right -- and what this project delivers is a record of where models
genuinely fail, so a failure you manufactured is worse than a pass you gave
away. When you cannot tell, the criterion is the safe side. That is not a
licence for thirty value-checking criteria; the section above is still the rule.
It is what to do with the handful you are unsure about.

The rest of what belongs here is everything a check cannot reach at all --
whether a claim is supported by the material, whether the reasoning holds,
whether the model invented a source. That is the half of the task this project
exists for, and no assertion can be written for it.

## Writing each kind of criterion

Every line below is set in the worked example's task -- the March 2024 HepG2
series, analysed under SOP-DE-004 -- except two trajectory lines from other
fields.

### Outcome criteria: what the answer has to get right

Every ask in your prompt has its own line, and none may be missing.

```markdown
- [5] Response states that 217 genes are differentially expressed under SOP-DE-004.
- [3] Response names S19 as a library excluded from the analysis.
```

A list in one line becomes one line per item. Not this:

```markdown
- [3] Response names S07, S19 and S22 as the excluded libraries.
```

but this:

```markdown
- [3] Response names S07 as a library excluded from the analysis.
- [3] Response names S19 as a library excluded from the analysis.
- [3] Response names S22 as a library excluded from the analysis.
```

A value hung on a referring phrase names its item instead. It is `[5]` because
the prompt asks for the p-value by name. Not this:

```markdown
- [5] Response gives the adjusted p-value of the most significant gene as 1.0e-13.
```

but this:

```markdown
- [5] Response gives the adjusted p-value of ENSG00000000056 as 1.0e-13, in any notation.
```

**A positive line checks only what your prompt asks for, or a hard step every
correct route takes.** Anything else is prescriptive: it fails a correct answer
for leaving out something nobody asked for. Not like this -- the prompt asks
which libraries came out and why, not their RIN values, so a correct answer
need not give them:

```markdown
- [1] Response gives the RIN of S07 as 6.1.
```

### Trajectory-level positives: hard steps every correct route takes

Optional, and only a few. Each is a step a correct answer cannot skip, and it
has to be hard to pass:

```markdown
- [3] Trajectory shows the agent removing the libraries with a RIN below 7.0 before applying the expression filter.
- [3] The agent applies the Benjamini-Hochberg correction across the 2383 retained genes only.
- [3] The agent's trajectory shows it identifying revision C of the agreement, not revision B, as the version in force on 3 March.
- [3] In its trajectory, the agent converts the supplier's pressures from psi to kPa before comparing them with the specification.
```

Not like this. Every run opens the SOP, so the line measures nothing:

```markdown
- [3] The agent opens protocols/SOP-DE-004.md.
```

Not like this either. A correct answer need not re-run the circulated analysis,
so requiring it is overfit:

```markdown
- [3] Trajectory shows the agent re-running the analysis on all 24 libraries to reproduce the circulated 134.
```

### Hallucination criteria: at least five, of any failure kind

Each is a way the answer goes wrong, of any kind `labels.md` names -- not only a
false claim. Grounding: a claim nothing in the material supports. Exploration:
answering without the material that settles it. Correctness or reasoning: a
wrong inference from the right material. Synthesis: combining sources that do
not belong together. Conflict resolution: settling a disagreement between
sources without saying so.

Grounding. A figure no material supplies is never pinned, because a rerun
invents a different one. Not this:

```markdown
- [-5] Response reports 26907 genes as differentially expressed.
```

but this:

```markdown
- [-5] Response reports a count of differentially expressed genes that no step of its own analysis produced.
```

Exploration, and correctness or reasoning:

```markdown
- [-5] Trajectory shows the agent deciding which libraries to keep without having read their RIN values.
- [-3] Trajectory shows the agent accepting the circulated result because its thresholds match SOP-DE-004's, without applying the SOP's earlier steps.
```

Synthesis, and conflict resolution. These two illustrate their kinds; the
worked example's run commits neither:

```markdown
- [-3] Response supports a figure about the March 2024 HepG2 series with results from a different study.
- [-3] Response reports two different figures for the same quantity without saying which one SOP-DE-004 supports.
```

A class of wrong answers can give examples of its members, in brackets:
`(e.g. S03 at exactly 7.0)`. The examples are enough for a grader to tell what
puts a claim in the class. Where you can name the correct ones instead, do,
and then no examples are needed:

```markdown
- [-3] Response names as excluded a library other than S07, S19 and S22.
```

The one case where pinning a figure is right is a planted trap. Every run that
takes the bait writes this figure, and the `[5]` line for 217 fails every other
wrong count, so no rerun escapes both. A rubric carries this line or the general
count line above for the same mistake, not both:

```markdown
- [-5] Response reports 134 as the number of differentially expressed genes under SOP-DE-004.
```

### Clarification criteria: only when the task is underspecified

Only when `labels.md` says the model cannot finish without asking. The negative
does not count toward the five hallucination criteria:

```markdown
- [5] Response asks which of the two March runs to use, or otherwise says it cannot tell which was intended
- [-5] Response reports a top gene from one of the two March runs without saying which run it used
```

*Clarification -- should it have asked?* below says when these apply.

## The three sections

### Completion -- did it get there?

Write these while the run is going. Everything in them comes from your ground
truth: an outcome line for every ask in your prompt, and any trajectory lines
for hard steps every correct route takes. *Writing each kind of criterion*
above has the shapes.

### Non-hallucination -- did it go wrong?

Write these once the run has finished, and **start with `/flc-inspect`** rather
than with the answer on its own.

**Five of these, and the run is where they come from.** `/flc-rubrics` refuses
fewer once the run has landed. Every claim in the answer that no file supports,
every citation to a file for something it does not say, every check it says it
ran and did not, every file it had to read and never opened, every conflict it
settled without saying so -- each one is a line, and a rubric that catches four
of them is a rubric that lets the fifth through.

You do not have to do this from a blank page. When the run finished it left two
files in `~/flc/task/review/`. The `.md` one is the reading of the run, which
`/flc-inspect` opens: the answer, what the model did step by step, and a list of
claims worth checking -- a figure that is in none of your files, a file it cited
that does not exist, one of your own planted wrong answers repeated back to you.
The `.html` one is the run itself, to download and open in your browser, for
when you want to see a claim in the context it was made in. Step 4's *When it
finishes* lists the rest of the paths.

Read it as a reading aid, not a verdict. Some of what it flags will turn out to
be fine, which is why every item says what it was checked against: a number the
model worked out correctly appears in none of your files either.

**Nothing writes your criteria but you.** Not this document, not `/flc-rubrics`,
and not the assistant -- if it offers to put the lines in for you, or starts to,
tell it to stop. Asking it to suggest wording is fine and often quicker than
arguing with a blank line; typing that wording in is yours. The reason is the
same one behind the whole step: these criteria are your account of what a wrong
answer looks like in your field, and that judgement is what the task is worth.
A set of criteria written by a model, checked by a model, is not a measurement
of anything.

That goes double for the completion criteria. Those come from your ground truth,
which is your account of the task and nobody else's.

Go through the answer looking for anything stated as fact, and check each one
against your own material:

- A **number** that is not in any file and is not the result of a calculation
  you can follow.
- A **citation** to one of your files for something that file does not say.
- A **conclusion** drawn from the superseded version of your data, or from a
  file you included precisely because it does not apply here.
- A claim about **work it did** -- a check it says it ran, a file it says it
  opened -- that did not happen.

Each mistake you find becomes a negative line, and two separate decisions go
into it.

**Which mistakes to write about: only the ones this run made.** A line the run
triggered describes a failure your task provokes; a line nothing triggered is a
guess, scores nothing, and more than two of them is refused at delivery. Your
planted distractors are a plan rather than a result -- what decides it is which
of them the model took -- and the inventions you did not plan for are worth more
than the ones you did, because they only exist in this transcript.

**How to word it: as the failure, not as the sentence in front of you.** Your
task is re-run against a different model, which makes the same mistake in
different words, and a line carrying this run's phrasing catches nothing there.
The judge sees your criterion and the answer and never your ground truth, so the
line still has to carry the fact. Two ways to do both:

- Name the **wrong route**: `[-3] Trajectory shows the agent accepting the
  circulated result because its thresholds match SOP-DE-004's, without applying
  the SOP's earlier steps.` Catches every run that took that shortcut, whatever
  figure it then reported.
- Let a **positive line carry the right value**: `[5] Response states that 217
  genes are differentially expressed under SOP-DE-004.` Every wrong count fails
  it, whatever the count. A negative beside it saying "gives a count other than
  217" is the same line turned round: it scores the same thing twice, so leave
  it out unless this run actually gave a wrong count.

Pinning a number is right when the number is one your own material hands over,
**as long as a positive line requires the correct figure for the same thing**.
`[-5] Response reports 134 as the number of differentially expressed genes under
SOP-DE-004.` is a good line, because 134 is the figure that trap produces and
any run taking the bait writes it -- and with the `[5]` line for 217 beside it,
a run that takes a different wrong turn still loses the marks. What catches
nothing is a figure only this run could have invented: `Response reports 26907
genes as differentially expressed` lets every other wrong total through. And
`Should not report the wrong gene` scores nothing at all, because the judge has
no way to know which gene is wrong.

**Up to two may be a failure this run did not commit, and a third is refused at
delivery** -- a set whose lines all catch something the run actually did is the
better one. The count is over every negative line under `## Non-hallucination`,
not over the first five, and what settles it is the grade: a negative criterion
the judge did not charge the model for is one this run did not commit.

That is an allowance, not a target. It is not guesswork either, and it is not
"what might a model invent" -- that list has no end. It is the wrong turn your
own material makes attractive and this model happened to avoid: a filename that
misleads about its contents, a default setting that is wrong for this data, a
figure the tables invite and do not support, a limit in an image that tempts a
description of what cannot be seen. You know those, because you built them.

```markdown
- [-3] Response describes band positions for a lane the gel image cannot resolve
- [-3] Response treats the archived run as the current one
```

Two things about them:

- **Weigh it like any other negative line.** The buckets above decide it: a
  claim to have run a check it never ran is `[-5]` whether or not this run made
  it. Two is a ceiling, not a goal, because a criterion nothing provoked
  carries less than it looks like it does.
- **Write the class of mistake, not the sentence.** Your task is re-run against
  a different model, and a line pinned to what this one wrote catches nothing
  there.

`/flc-grade` counts these for you. It reports how many of your negative
criteria fired and how many did not, and says so when more than two of them
describe something this run avoided.

These are the point of the whole project.

A model that cannot find the answer scores zero on completion, and that is
mildly interesting. A model that produces a confident wrong number, or cites a
file for something it does not say, is the failure worth catching -- and only
these criteria catch it.

One caution: you are writing criteria this run has already failed, so of course
it will score badly. That is not the same as the task being good.

### Clarification -- should it have asked?

Only if `solution/labels.md` says your task is underspecified -- which also
means Level 5, and a *What the model cannot know* section in your ground truth.
Most tasks are not; if yours is not, go straight to the next heading.
`/flc-rubrics` refuses a Clarification line on a task marked not underspecified,
and a Clarification line on a task that was fully specified is a common issue
in this project.

This is for the case where the model cannot finish without asking you
something, or where finishing means assuming something you never said. It is a
narrow test, and the bar is worth stating plainly: if the model could work the
answer out from the material you gave it, the criterion is a Completion one,
not this.

These criteria come in pairs, and both halves go under this heading: one says
the model raised the gap, the other says it did not quietly paper over it. The
part of the work that was possible anyway is ordinary Completion.

```markdown
## Clarification

- [5] Response asks which of the two March runs to use, or otherwise says it cannot tell which was intended
- [-5] Response reports a top gene from one of the two March runs without saying which run it used

## Completion

- [3] Response reports that 21 libraries passed the RIN filter, which is the same under either run
```

Write the question you would accept, not "asks a clarifying question". Allow for
the model saying it plainly rather than asking outright -- "I can't tell which
of these you meant" is the behaviour you want, and a criterion that insists on a
question mark misses it. That is what the "or otherwise says" half is doing.

Write the negative as the silent choice, never as "does not ask". An answer that
says "assuming you meant the corrected run, here is the result" has flagged its
assumption and is behaving reasonably. What you are catching is the answer that
picks silently and presents the result as the only one there was.

A negative here fabricates nothing, so it does not count towards the five
above. Anything the model made up belongs under Non-hallucination, whatever it
is about -- a claim that the corrected sample sheet is the one to use when no
file says so, or that the two March runs give the same result. `/flc-rubrics`
asks about every negative under this heading for that reason; if the line
describes a choice made silently, leave it where it is.

## Five rules

**One claim per line.** If the answer gets the gene right and the p-value
wrong, a combined line scores zero and you have lost the distinction you
wanted -- and the cost is not only yours. A line carrying four claims pays all
four points or none of them, so the whole score swings on one verdict: a model
that got three of them right collects nothing, and one that got a single part
right and wrote something plausible about the rest can collect the lot. That
is a reward that is spiky, high in variance and easy to game.

A list of items is a list of claims, and this is the shape that does not read
as stacked. "Response names S07, S19 and S22 as the excluded libraries" is
three criteria rather than one: a response naming S07, S19 and S03 has two of
the three right and scores zero for them. So is a line pairing several values
with several items -- "6.1 for S07, 5.4 for S19 and 6.8 for S22" is three.
Splitting one `[5]` into three lines does not mean three `[5]`s: weigh each by
the bucket definitions above, which usually leaves at most one at `[5]` and the
rest at `[3]` or `[1]`.

The test is not whether the parts are about the same thing. They usually are,
and "it is all one issue" is the case being described rather than a reason to
leave it alone. Ask instead whether a response could satisfy one part and fail
another.

One claim is still not one word. An item stated together with the property
that identifies it is a single claim: "the Sh ble cassette conferring zeocin
resistance" says which cassette is meant, it does not ask for the phenotype as
a second fact, and a response that names the cassette has satisfied it.
Splitting that leaves two lines a response could satisfy without ever
connecting them, and `/flc-rubrics` warns about that too.

**Each line must stand alone.** No "as described above", no "the correct value".
The judge sees that line and nothing else.

**Check facts, not quality.** "Well-reasoned", "thorough", "sensible" cannot be
judged consistently. Ask yourself what you would actually look for, and write
that instead.

**Do not just restate the question.** "Response identifies the most significant
gene" is not checkable without knowing which gene. Name it.

**At least five hallucination criteria.** Counted over the negative lines under
`## Non-hallucination`; a positive line there is a fine criterion and does not
count towards the five. Each of the five describes a different way the answer
goes wrong, of any kind -- grounding, exploration, correctness or reasoning,
synthesis, conflict resolution. A positive line restated as a negative is not
one of them.

## How many

**At least 20 checks.** `/flc-grade` refuses below that and so does
`/flc-deliver`. Your unit tests count towards it alongside your criteria, so
the 20 is across both. Each one has to check something no other check does: a
line that `/flc-check-rubric` finds, every time it reads it, only repeats
another does not count towards the 20. The line it repeats still counts, and so
does every line that checks something of its own, however closely related.

A rubric is made of these parts, and they are how it gets to 20:

- **Required, and the most important part:**
  - **An outcome criterion for every ask in your prompt.** Each figure,
    conclusion or identification the prompt asks for has its line, and none
    may be missing.
  - **At least five hallucination criteria**, of any failure kind.
- **Required when `labels.md` says the task is underspecified: clarification
  criteria** under `## Clarification` -- one for asking for what is missing, or
  saying it cannot tell, and one for choosing a reading silently. They do not
  count toward the five.
- **Optional, for depth: a few trajectory-level positives** about what the
  model should do, and they have to be hard to pass: identifying the superseded
  version, reconciling two sources that disagree, tracing a figure to the raw
  data rather than the summary, noticing a unit change, applying a step in the
  right order. Something any run does anyway, like opening a file, does not
  count as one. Each must be a step every correct route takes, because
  requiring a preferred route is overfit.

No list of deliverables is needed to get there: your prompt's own asks, the
hallucination criteria and a few trajectory lines reach 20. A prompt that lists
deliverables reads as a specification rather than a question a colleague would
send, unless the case or the field genuinely works that way.

What does not count is padding. Two lines measuring the same thing score one
mistake twice. Three shapes repeat one fact without looking like it: an item
beside its shorthand, "produced" beside "end product", and a single item beside
a line that lists it. `/flc-rubrics` refuses two identical lines, warns about a
negative that restates a positive the other way round, and warns about a line
whose every name and figure another line of the same kind already carries;
`/flc-check-rubric` is what decides whether such a line repeats the other, and
finds two lines worded differently that check the same thing. The version
of this that costs the most is two negative lines for one wrong claim, a general
one and one naming the particular route the model took to it, because the model
is then charged twice for a single sentence and the score the difficulty bar
reads moves. If your task genuinely cannot reach 20, that is a finding about the
task rather than about the floor: it usually means the folder has too little in
it for the model to get lost in, and step 1 is where that gets fixed.

## Everything your prompt asks for needs a line

**A criterion you should have written and did not counts against your rubric the
same as one that is wrong.** It is one of the common issues in this project,
and a missing line counts the same as a wrong one. Two passes find nearly all of them, and it is the
second that gets skipped.

**Down your ground truth**, asking what it asserts that no line of yours checks.

**Down your prompt, sentence by sentence**, asking of every single thing it asks
for: which line of mine checks this? A prompt that asks for the yields "before
filtering, with at least one hit, and with at least two" has asked for three
numbers, and a rubric with four careful criteria about the second one has left
two of the three ungraded -- so an answer that omits them both loses nothing at
all. A prompt asking the model to "leave your working somewhere I can find it"
has asked for two things, a file and the working in it, and a line checking only
that the file exists lets through a file holding the conclusions and none of the
work.

A fact your suite asserts is not a missing criterion -- the tests and the
criteria are two halves of one instrument and the floor counts them together.
The part that still needs a line is the half a program cannot settle: a test
proving the file exists says nothing about whether the working in it is the
working you asked for.

### When the answer is a list of similar things

A table of rows, one result per sample, a file with a row per case: you are not
expected to write a criterion per row, and a rubric that does is flagged for the
opposite problem. The convention is **up to five spot checks, plus one line
about the extent of the group**:

```markdown
- [5] [state] results.csv gives a call for all twelve libraries
- [3] [state] results.csv reports S07 as excluded at a RIN of 6.1
- [3] [state] results.csv reports S22 as excluded at a RIN of 6.8
```

The first line is the one that gets left out, and without it the spot checks are
the whole of what a response has to satisfy: three rows of a twelve-row table
earn every criterion above, and the nine missing rows cost nothing. Both halves
are required and each is counted on its own -- a missing extent line is a missing
criterion, and more than five spot checks on one group is a separate finding
against the rubric.

## Then

```
/flc-rubrics
```

It checks all of the above and tells you exactly which lines to fix.

Then, once the criteria are finished:

```
/flc-check-rubric
```

`/flc-rubrics` reads your lines. This reads your lines **against your task** --
your prompt, your ground truth, your files and, once there is one, the run --
and answers the questions the wording on its own cannot: is anything the prompt
asks for missing a line, would a correct answer written another way be marked
wrong, could two people read a line two different ways, is a weight out of its
bucket, do two lines charge for the same thing, and could another run make the
mistake a negative line describes and still walk past it. Each of those is a
common issue in this project, and they are all about the fit between the
criteria and the task rather than about how a line is phrased.

Delivery reads the last check rather than taking another, so run it again
after you change the criteria, the prompt, the ground truth or the files. When
findings it sees every time it reads your criteria add up to enough, they stop
delivery until they are fixed, and the check lists them under MUST FIX.
Everything else is worth fixing and never stops anything: treat each finding as
something to fix unless it is wrong, and there is nothing to answer or type.
What it never asks you to do is make a criterion easier: every remedy it offers
is the criterion saying more plainly what you already meant, or a line removed
because another line already checks it. It uses budget, so run it again after a
change rather than in the hope of a different reading.

Next: [06-unit-tests.md](06-unit-tests.md)
