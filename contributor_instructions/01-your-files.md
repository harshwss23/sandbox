# Step 1: your files

Put everything the task is about into:

```
~/flc/task/environment/workspace/
```

Whatever structure you build here is exactly what the model sees at
`/workspace`.

## Getting your files in: zip, upload, `/flc-unpack`

1. On your computer, **compress your task's files into a single zip.**
   Right-click, "Compress" on a Mac, or "Send to" then "Compressed (zipped)
   folder" on Windows.
2. **Upload that one zip** into `workspace/` using the file browser on the
   left.
3. Type **`/flc-unpack`**.

That is the whole thing. The file browser takes files rather than folders, so a
zip is the only practical way to move a folder tree across in one piece --
otherwise it goes a folder at a time and the structure, which is much of what
makes a task worth anything, is the first thing to get lost.

`/flc-unpack` does the rest: unpacks the zip, deletes it, clears out the
`__MACOSX` folder and `.DS_Store` files your computer hides inside archives,
and lifts your files up a level if you zipped the containing folder rather than
its contents. Then it prints the layout so you can see what actually arrived.

It changes nothing else. Your files are not renamed, tidied or reorganised.

Adding more material later is the same three steps -- a second zip unpacks
alongside the first.

We don't recommend workspaces over 500 MB. It isn't a hard limit, and a little
over (say 600 MB) may still work, but a heavy workspace makes the sandbox slow
to work in and can make the task fail to collect when you finish.

## Make it look like real work

The single biggest difference between a task that measures something and one
that does not is whether the folder looks like a real folder.

Real:

```
workspace/
  data/
    counts_matrix_final.csv
    counts_matrix_v2.csv        <- superseded, still lying around
    sample_metadata.xlsx
  analysis/
    deseq_run_march.R
    notes.md
  Downloads/
    Zhang_2021_supplementary.pdf
  README_old.txt
```

Not real:

```
workspace/
  input.csv
  question_data.txt
```

The second one tells the model that everything present is relevant. That is the
one hint you most want to withhold, because deciding what matters is a large
part of the work you are testing.

## Does it read as built for a test?

There is a subtler version of the same problem, and it cost us a real run. The
model wrote in its own reasoning that it had spotted "two deliberate traps" and
went looking for more. Nothing had leaked -- it had no access to the answer or
to the grading criteria. It worked out from the shape of the folder alone that
the folder had been built for it, and started hunting for planted mistakes
instead of doing the work.

That matters because of what the task is for. A model hunting for traps is not
behaving the way it behaves on your real material, so what gets measured stops
being "does it invent things when the work is tedious" and becomes "can it spot
what was planted". Your task is re-run against a different model, and the
giveaway travels with it.

The tell is density: every file mattering, exactly one per consideration, and
documents that answer precisely the question a careless reader would get wrong.
Three cheap ways to break it:

- **Say important things more than once, in different words and different
  places.** In real material a rule appears in the procedure, is half-remembered
  in an email, and is mentioned in passing in someone's notes. A fact that
  exists in exactly one sentence in one file reads as placed.
- **Include material that is real and simply does not matter.** An equipment
  log, an inventory, minutes from a meeting about something else. Not everything
  needs to lead somewhere.
- **Let the index be stale.** A README that lists every file with a line on why
  it is there is a map of your design. Real ones miss things and describe folders
  that were reorganised months ago.

Watch for prose written to be cited. If a procedure spells out the boundary case
that a trap in your folder turns on -- and spells out nothing else at that level
of detail -- that sentence exists for the test and reads like it. The rule still
has to be unambiguous, or grading it is unfair; it just should not be the one
crisp sentence in an otherwise ordinary document.

## Distractors

Include files that look relevant and are not. Each of these should lead
somewhere specific and wrong:

- **an old version** of the file that matters, with different numbers
- **a related dataset** that answers a similar but different question
- **notes describing a method** that was tried and abandoned
- **a near-miss identifier** -- a similarly named gene, ticker, case number

You will write these down in step 3. In step 5 they are the traps to look for
in the run: one the model took is among your best grading criteria, and up to
two it avoided can be criteria too. A distractor you cannot name the wrong answer for is not a distractor
-- but that does not make it unwelcome. It is ordinary material, and a folder
made only of files that each lead somewhere is the folder described above.

## How much material

The task has to give the model a lot to hold at once. That is counted in
**tokens** -- the unit a model reads in, each one about three quarters of a
word -- and your task has to reach **27,000** of them. That is roughly 20,000
words, or forty pages.

The figure is measured from the run rather than from your folder.
`/flc-check-inputs` estimates it beforehand, but only the run settles it.

**A big dataset is not the same as a lot of material.** This is the thing most
worth knowing here, and it is the opposite of what most people expect. What
counts is what the model has to read, not what is on disk. A spreadsheet with a
hundred thousand rows gets opened, described in a line, and queried -- a few
hundred tokens of a file that took an hour to prepare. Fifteen pages of case
notes get read from top to bottom.

Roughly, per file:

| Material | What reaches the model |
|---|---|
| Reports, notes, emails, procedures, transcripts | All of it |
| Code and configuration | All of it |
| Small tables, a few hundred rows | Usually all of it |
| Large tables, thousands of rows | A couple of thousand tokens, however large it gets |
| Images and scans | All of it, and figures are expensive |

So prose is the dependable way to get there. It is not the only way -- an analysis intricate enough that
the model has to work through it at length builds up context of its own -- but
that is harder to predict, and if you are relying on it, expect to run the
solver more than once.

Three folders that work:

- **Documents only.** Around fifteen files: six case or visit notes of a page or
  two each, three procedures, an extract from a standard or guideline, a couple
  of email threads, a small reference table, and a README that is out of date.
  Nothing here is a dataset, and it clears the floor on reading alone.
- **A dataset and its paper trail.** One table doing the analytical work, plus
  the fifteen thousand words that would surround it in reality -- the protocol,
  last quarter's report, the correspondence about the anomaly in March. The
  table carries the question; the prose carries the context.
- **A dataset alone.** Four spreadsheets and a short question. This one measured
  33,000, almost all of it the model's own working rather than the files. It
  cleared the floor, but only just, and it would not have taken much for it not
  to. If this is your shape, add the notebooks and write-ups that would really
  be there.

Distractors count, because working out that a file is irrelevant means reading
it. That is the work being measured, and it is real work.

What does *not* count is padding: files nobody would open in the first place. A
folder bulked out with material that has no plausible bearing on the question
adds nothing to the task. The test to apply to each file is whether a careful
person would open it before ruling it out. If the answer is no, it is filler.

Note what that test does *not* require: that the file matter. Something a person
would reasonably open and then set aside is doing real work in this task even
though it leads nowhere, and it is what stops the folder reading as a set of
clues.

## What can be in the files

Anything you can open on a normal analysis machine: spreadsheets, CSVs, PDFs,
Word documents, images, compressed archives, R data files, common
bioinformatics formats. If something needs an unusual package, that is fine --
you can add it later with `/flc-add-package`.

**Nothing confidential, nothing personal, nothing you do not have the right to
share.** If the data is real but sensitive, use a public equivalent or
anonymise it before it goes in this folder.

## Then

Delete `PUT_YOUR_FILES_HERE.txt`, and go to
[02-the-prompt.md](02-the-prompt.md).
