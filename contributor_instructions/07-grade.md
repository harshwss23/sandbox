# Step 7: see what happened

With the run finished and all your criteria written:

```
/flc-grade
```

You get every criterion, passed or failed, with the judge's reasoning in its own
words, and a score.

Grading happens here and nowhere earlier. The solver step produced a transcript;
your non-hallucination criteria came out of that transcript; this is the first
moment there is a whole rubric to grade against. It takes a few minutes -- the
judge reads your criteria one at a time -- and you can run it again after
changing them.

## If it says you have too few checks

`/flc-grade` refuses below **20 checks**, counting your criteria and your unit
tests together. It says how many you have and stops before spending anything.

There is no way round it, and the fix is not to write shorter criteria until
there are twenty of them. Go through the parts of a rubric: an outcome line for
every ask in your prompt, at least five hallucination criteria from the run,
and, for depth, a few lines about hard steps every correct route takes -- the
figure it had to work out before it could work out the final one, the two
sources it had to reconcile, the step in your procedure it had to apply in
order. Never an easy step like opening a file. What is missing is usually
already written down in your ground truth and simply never became a criterion.

Add them with `/flc-rubrics`, then come back here.

## The 50% bar

**Your task cannot be delivered unless the model scored below 50%.**

That is the difficulty bar, it is checked again at `/flc-deliver`, and it does
not bend.

The score it reads is your criteria and your unit tests counted **together** --
the points the model earned out of the points available across both. Tests it
passes raise that number the same way criteria it holds do. `/flc-grade` prints
the two parts underneath the score so you can see which is which, but the one
the bar compares to 50% is the combined figure, never the criteria on their own.

The reason is worth stating plainly, because it runs against the instinct: we
are not measuring how often models get things wrong. We are collecting the cases
where they do, so that the pattern behind them can be studied. A run in which
the model made no mistake produces a transcript with nothing in it to learn
from, no matter how much work went into the task around it.

So a high score here is not a task that went well. It is a task that is not
finished.

## Reading the result

The score is what the model earned of the positive criteria, less what its
negative criteria cost, so a `[5]` moves it five times as much as a `[1]` and a
tripped `[-5]` takes five points off. It stops at zero rather than going below.
Your unit tests sit in that same total at the weights you gave them, which is
why the score can be well above your criteria's own rate.
Past the bar above, the number is not the interesting part. Three things are:

**Did it get the answer right?** Compare it against what you wrote in step 3.

**Which criteria failed, and why?** The judge records its reasoning for every
one, and the next section is about reading it.

**Did it invent anything you had not already written down?** You wrote your
non-hallucination criteria from this run, so the ones it fails are no surprise.
Read the answer once more for anything you missed the first time.

**How many of your negative criteria never fired?** The report gives you this
line:

```
non-hallucination criteria: 7 written, 5 fired, 2 did not
```

The two that did not fire are ones describing a failure this run avoided, and
they will still be doing work when your task is re-run against a different
model. Two is the allowance, not the aim: if more than two went
quiet, the report says so, because a failure nobody was seen to commit is by
construction not one your setup compelled. A rubric whose five all fired is the
better one.

## Check the judge read you correctly

Grading writes the whole grade to a page:

```
~/flc/task/review/grade-<run>.html
```

Download that file and open it in your own browser. It is every criterion with
the verdict and the judge's reasoning underneath it, which is a great deal
easier to read than the same thing scrolling past in a terminal.

Then:

```
/flc-check-grade
```

It takes you through the criteria one at a time and asks a single question about
each: **did the judge understand this criterion the way you meant it?**

That question matters because of how the grading works. The judge sees one
criterion at a time and nothing else -- not your other criteria, not your ground
truth, not what you were getting at. It answers from the wording alone. So when
a criterion is ambiguous, or quietly asks for two things, or turns on a value
the judge has to eyeball, it can reach a verdict that is perfectly reasonable
for the words in front of it and wrong about your task.

That is a criterion to fix. It is not a result about the model, and it is the
one thing in the whole grade that nobody but you can spot.

**Ask it about the judge, not about the score.** If the model passed something
you wanted it to fail, that is the model doing well and your task being too
easy -- the section above is what that means. Rewording criteria until the
number falls is not the fix, and what you flag here is written into the delivery
record, where it stays with the task.

Four things can be wrong, and the command asks which:

- **the criterion was ambiguous** or carried two facts -- reword it
- **the judge simply got it wrong** on a sound criterion -- grade again, once;
  it is not deterministic. If it reads the same way twice, say the fact more
  plainly
- **it checks an exact value in a file the model produced** -- that is an
  automated check rather than a criterion. See
  [06-unit-tests.md](06-unit-tests.md): a program compares the value exactly,
  where the judge is being asked to eyeball it
- **it asks for something your ground truth does not support** -- then the
  criterion is wrong. What you wrote in step 3 does not move

**Anything you flag means grading again.** Fix the criterion, `/flc-rubrics`,
`/flc-grade`, then `/flc-check-grade` once more. The score on record belongs to
the criteria it was taken against, so a rubric changed after grading leaves
`/flc-deliver` refusing a score that no longer applies. The second pass is
short: criteria that came back unchanged keep the answer you already gave.

Finding nothing is the ordinary outcome. It means nothing was flagged as
misread.

## The last two labels

Once the verdicts stand, answer the last two headings of `solution/labels.md`.
They describe this run, which is why they wait until now.

**What went wrong.** Most tasks have one. Choose more only where each has its
own evidence, a claim or step you can point to, and never the consequence of
one you already chose: a wrong answer because it misread a figure or never
opened the file is `grounding` or `exploration`, not also
`correctness_reasoning`.

- `grounding` -- it read the right source and stated something the source does
  not show.
- `synthesis` -- every source was read correctly and it combined or attributed
  them wrongly.
- `correctness_reasoning` -- what it asserted is wrong on its own terms: the
  arithmetic, a fact about the world, or a conclusion the method cannot support.
- `exploration` -- it never reached the information it needed.
- `conflict_resolution` -- two things in your material disagree, and it neither
  reconciled them nor said which governs.

**Why.** At most three sentences, in plain prose, that someone who has never
seen your task or your field could follow: what the model was supposed to do,
what it did instead, and why that was wrong. The most important failure only.

`/flc-check-grade` checks both when it finishes, and `/flc-deliver` refuses
until they read cleanly. It will also say if the run disagrees with your
browsing answer; that is worth a second look and does not stop anything.

## Judging your task by the result

**It scored 50% or more.** Your task is too easy, and you will not be able to
deliver it as it stands. This step is where that is meant to surface. What
usually works: give it more to rule out, ask for something that needs two files
combined rather than one read off directly, or remove whatever made it too
direct.

Do not clear the bar by weakening the completion criteria. Those came from your
ground truth, and rewriting them to make the model look worse is the one change
that would make the number meaningless.

Nor by weighing what the model got right for less. When a grade comes in under
the bar after a grade of the same run at the bar or over it, and nothing changed
between them but weights, `/flc-grade` says so at once and `/flc-deliver`
refuses it. A weight moved to the one `/flc-check-rubric` named for that line is
not counted: that is a fix it asked for.

**It scored zero because it never found the right files.** That is a broken task
rather than a hard one. The folder may be too large to navigate at all, or the
question too vague about the part you *do* expect answered. Loosen it slightly.

**It scored zero with a confident, wrong, well-argued answer.** This is exactly
what you were trying to build.

**It scored zero because it asked instead of answering, and you meant it to
ask.** Not a broken task and not a failure -- your criteria did not credit the
question. Go back to `/flc-rubrics` and add it under `## Clarification`. This is
the one case where a low score is telling you about your criteria rather than
about the model.

**A criterion failed because the model could not install something.** Not a
finding about the model at all. `/flc-grade` says so at the top when it happens:
add the package and run again.

## Changing things and running again

A task gets five counted runs, so make each one change something the model has
to do -- the question, the files or the block list -- then `/flc-run-solver`
again. Each run goes to its own folder, so nothing is overwritten and you can
compare. Changing only your criteria needs no new run: grade again. *Running it
more than once* in [04-run-the-solver.md](04-run-the-solver.md) has the rest.

If you change the question, check it again with `/flc-prompt-check` before the
run. If you change the files or the question, reread your criteria before
rerunning: criteria written against the old answer can quietly stop applying.

Two rules follow from that, and the tools hold you to both rather than leaving
them to memory. **Change your criteria, grade again** -- the score you have is
of the criteria the judge was given, and packaging refuses one taken against
criteria that have since moved. **Change the question or the files, run the
solver again** -- the model was given the earlier version, and a score for it
says nothing about what you would be shipping. Grading alone cannot repair
that, so `/flc-grade` will not pretend otherwise.

Next: [08-delivery.md](08-delivery.md)
