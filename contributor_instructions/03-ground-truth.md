# Step 3: write down the answer

In two parts, either side of the first run. You do not write any code, and you
do not produce the answer files yourself.

**Before the first run: the answer.** In `~/flc/task/solution/ground_truth.md`,
write *The answer* and *How it is derivable* -- and *What the model cannot
know*, if your task is underspecified. A short version is enough. This takes
about ten minutes and it is the most valuable ten minutes in the whole process.
`/flc-run-solver` will not start until both are written, and every run keeps a
copy of them as they stood when it started.

**Once a run shows the task holds: the rest.** Before any further run:

1. the distractor section of `ground_truth.md` -- what should mislead a
   careless model;
2. `~/flc/task/solution/underspecification_justification.md` -- why that answer
   is the only one an expert could reach: what determines it, and what rules
   out the other paths a careful expert would consider. One paragraph of plain
   prose.
3. `~/flc/task/solution/labels.md` -- the first three answers: whether the task
   is underspecified, its level, and whether it needs browsing.

The split is there so an afternoon of polish is not spent on a prompt the model
solves on its first try.

## Why the answer comes before the model runs

If you write your grading criteria after seeing the model's answer, they drift.
You start judging what the model said instead of what a correct answer needs,
and a fluent wrong answer starts to look acceptable. Writing the answer down
first is what prevents that.

It also catches the worst failure early: a task that cannot actually be solved
from the files provided. That is only obvious when you try to say how.

The answer can still be corrected after a run -- one that turns out to be wrong
has to be. But the delivery record shows the answer as it stood before the
graded run beside the one delivered, so it is plain that it moved. What
it must never do is move towards what the model said.

The checks read your answer the way they read everything else: it is checked
against your files, not taken as given. Where one finds a statement in it
wrong -- a figure, a reason, a condition -- and three independent readings
confirm it, you are told which statement and why, and it is yours to correct,
along with every criterion and sentence that repeats it.

## The sections

**The answer.** Specific. If it is a number, write the number. If it is a name,
write the name plus any identifier that means the same thing -- a model that
answers with an Ensembl ID instead of a gene symbol is not wrong, and your
criteria should not treat it as wrong.

> GENE0421 (ENSG00000141510). log2 fold change 3.87, adjusted p-value 1.2e-5.

**How it is derivable.** Which files, and roughly what you do with them. Two or
three sentences.

> `data/counts_matrix_final.csv` has the counts; `analysis/notes.md` says the
> March run is the one that used the corrected sample sheet. Rank by the padj
> column, not the raw p-value, and the top row is GENE0421.

If you cannot write this section, stop. The task is not solvable from the files,
and nothing after this point can fix that.

**What should mislead a careless model.** Each distractor, and the specific wrong
answer it produces.

> `counts_matrix_v2.csv` is the superseded run -- ranking that one gives GENE1188
> instead. Ranking by raw p-value rather than padj gives GENE0033. The Zhang
> supplementary PDF is about a different tissue entirely, but it mentions three
> of the same genes.

This section is worth the most. Two steps from here it is what you read the
run against: each trap the model took becomes a criterion, and up to two it did
not take can be criteria as well. It can be finished after the first
run, but jot the traps down before you read that run.

Write down the wrong turns you built in even where you doubt a model would take
them. Up to two of your criteria may describe a failure the run does *not*
commit -- the ones that still catch something when your task is re-run against
another model -- and this is where you will look for them. After the
run it is hard to remember which traps went unsprung, and a trap the model
walks into is worth more than one it stepped over.

**What the model cannot know, if your task is underspecified.** Only then --
most tasks delete this section. Write what is missing, what the model should
ask, and what it must not do instead.

> Nothing in the folder says whether the March run or the March re-run is the
> one they mean, and the two give different top genes. The model should say it
> cannot tell them apart and ask which was intended. It can still report the
> filtering and the sample count, which are the same either way. What it must
> not do is pick one, stay silent about picking, and report that gene as the
> answer.

Two things to keep straight. This is not the same as a distractor: a distractor
has a right answer that a careless reader misses, and this has no right answer
until someone replies. And it does not excuse you from the section above -- the
part that *is* answerable still has to be derivable, and you still write down
what it comes to.

This section is the only reason to write a `## Clarification` criterion two
steps from here. If you deleted it, skip that heading too.

## The second file: why your answer is the only one

`~/flc/task/solution/underspecification_justification.md`, written once a run
shows the task holds and before any further run, while the alternatives are
still in your head. It is read to
confirm your answer without taking your word for it, and in six weeks nobody
will be able to reconstruct it, including you.

Every task needs this file, whether or not it is underspecified. Write it as
one paragraph of plain prose: no headings, lists, bold or backticks, and never
more than 600 words or five paragraphs. Write more than a paragraph only when
the prompt leaves several things open. It has to do two things. Say what
determines the answer: the specific thing that forces it, and where it is -- a
clause of a standard or procedure, a value or constraint in one of your files,
a fact that eliminates the alternatives. Then name every other path a careful
expert would plausibly take -- usually one or two -- and what rules each one
out, said in your own words.

> SOP-DE-004 section 1.1 sets the RIN threshold at 7.0 and says below, so S03
> at exactly 7.0 is retained; excluding it would misread that rule.
> analysis/notes.md records the March run as the one that used the
> corrected sample sheet, which rules out counts_matrix_v2.csv, the run it
> superseded. Ranking by raw p-value instead of padj is ruled out by section 4.3
> of the SOP, which requires multiple-testing correction.

Write about your material, not about the task's design or its level. Two
things are common issues in this project: text general enough that it would
fit another task of the same kind unchanged, and text that reads like a form
filled in. One sentence naming the file, value or clause that settles the
answer fixes the first.

**"It is standard practice", "any expert would know this", and your own
preference do not determine a ground truth.** If you cannot point to what
forces your answer, the answer is a judgement call rather than a fact.

**If any other path survives, the task has more than one answer and has to
change.** Either add the material that closes it, or make the gap
deliberate -- the *What the model cannot know* section above -- so that stating
the assumption or asking becomes the expected answer rather than a wrong one.
Better to find that now than after a run.

If the gap is deliberate, the justification reads the other way round: show
that **no** default is defensible, and say why each candidate fails. That is what makes
asking the only correct answer.

## The labels

`~/flc/task/solution/labels.md` has five headings. Answer the first three with
the justification, each on the line under its heading, in one of the spellings the file lists; the
last two wait until the run has been graded.

**Is your task underspecified?** Yes only if part of the request cannot be done
without asking you: it turns on a fact only you hold, and each possible answer
leads to different work. If the model can settle everything by exploring your
files or by applying a convention, the answer is no, however much exploring
that takes.

**Underspecification level.** The level is the highest gap in the task:

- **l1 - minimal** -- the deliverable is stated and the method is not; standard
  practice supplies it. Five experts given only the prompt would agree on the
  output and how to get it.
- **l2 - low** -- a value, identifier or constraint the answer needs is missing
  from the prompt and present in your files. You can point to the file and the
  place that settles it.
- **l3 - moderate** -- no single source settles it; the model has to combine or
  reconcile several. You can name the sources, and show one alone is not
  enough.
- **l4 - high** -- something the answer needs is in neither the prompt nor the
  files, and domain convention forces exactly one default. You can name the
  missing input and the one default an expert would apply.
- **l5 - full** -- the answer depends on a fact only you hold, and the branches
  lead to different work rather than different values, so asking is the only
  correct action. If listing the branches would be an acceptable answer, the
  task is ambiguous rather than underspecified, and has to change.

Yes, l5, a written *What the model cannot know* section and a `## Clarification`
criterion go together: each one needs the others, and the checks refuse any of
them without the rest. No means none of them.

**Does your task require browsing?** Yes if the model has to look something up
online; no if the prompt and your files are enough.

The assistant can check the file's formatting and, if you agree, fix it -- a
spelling, an answer under the wrong heading -- but the answers are yours.

## Then

```
/flc-ground-truth
```

Before the first run it asks only for the answer and how it is derivable. Once
those are written, go to step 4 and start the run.

When the run lands, `/flc-inspect` puts your answer beside the model's. If the
model got there, change the prompt or the files and run again -- checking the
prompt with `/flc-prompt-check` first if you changed it -- because the rest of
this step is written for the task that survives. If it did not, come back here
for the rest, and then:

```
/flc-check-justification
```

It checks the labels first -- that they read cleanly and agree with each other
and with your ground truth -- then reads your justification against your
prompt, your recorded answer and your files, recomputing from the files where
it needs to, and says whether it holds together. A couple of
minutes, and it has to come **before any further run**: a justification that
does not hold means the task itself has to change, and a run against the old
task is a run spent for nothing.

Nothing it reports asks you to weaken your answer. Every remedy adds -- name
the determiner, close the path, add the material that closes it, or make the
gap deliberate. Some findings are marked as not stopping the task, and they
still need fixing unless the finding is wrong: each is a common issue in this
project.

Next: [04-run-the-solver.md](04-run-the-solver.md)
