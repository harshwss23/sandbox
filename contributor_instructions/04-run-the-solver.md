# Step 4: start the run

## First, five minutes on what the model can reach

**Do this before you start the run, because afterwards it is too late.** A run
where the model found your answer on a web page is a run to throw away, and
getting another one costs you the same wait again.

The model works with the internet on, and that is deliberate -- step 2 says to
expect it to look things up. What it must not be able to do is read the answer
somewhere instead of working it out. So your task starts with a list of sites
it cannot reach: Wikipedia everywhere, plus the reference databases for your
field, the ones that would hand over an answer outright.

Look at that list, and ask one question about your own task:

```
/flc-status
```

It prints what is blocked. Now think of the single page that would most spoil
your task -- the paper this dataset came from, the database entry for the
accession you are asking about, a public copy of one of your files, the vendor
page with the figure in it -- and if it is not on the list, put it there:

```
/flc-block-domain example.com
```

A URL works as well as a domain. There is no cost to blocking one too many: a
site your task genuinely needs can come back off the list -- run
`/flc-block-domain` and ask for it to be unblocked.

Two honest limits, so you know what you are relying on:

- **It blocks by name.** A model that asks for a raw IP address is not stopped.
  In practice they do not, but this is a speed bump and not a wall.
- **It does not empty search results.** The site is unreachable; a summary of
  it in a search result is not. So if your answer is a thing the whole internet
  repeats, no block list saves the task -- that is a question to make more
  specific to your own data, and step 2 is where that gets fixed.

If you find yourself blocking five sites to protect one figure, that is the
signal. The question is asking for something public, and the fix is upstream.

## Then start it

It will not start until *The answer* and *How it is derivable* are written in
`solution/ground_truth.md` -- step 3's first part.

```
/flc-run-solver
```

The model gets your folder at `/workspace` and your question, and works on it
the way you would: exploring, opening files, running code, and finally writing
an answer.

**It runs in the background, so you can carry on with the next step.** You are
not meant to sit and watch it, and there is no useful estimate of how long it will
take -- it depends entirely on your task. The next step is written while this
runs, and you check on it whenever you like.

To check on it at any time:

```
/flc-status
```

## Why the run comes before the grading criteria

Half of your criteria cannot be written yet.

The criteria that say what a right answer contains come from your ground truth,
and you can write those now -- that is what you do while this runs.

The hallucination criteria are different. Nobody can guess which number a
model will make up, which file it will cite for something the file does not
say, or which step it will skip. You find that out by reading what it actually
did. So those get written after this run lands, against the real run.

That is the whole reason for this order. Writing them first would limit you to
the mistakes you happened to think of.

## What is happening while it runs

The model works on its own copy of your files, on a machine of its own. Any
files it writes land there too, and those can be graded as well as its answer.
It has the internet, minus what the section above has blocked -- and it will
use it, which is what that section is for.

Nothing you do now can disturb it. Editing your criteria does not affect a run in
progress: the run uses the prompt and files as they were when it started.

## When it finishes

`/flc-status` stops saying the run is still going. There is a step here that is
easy to walk past, and it is the one that makes the second half of your criteria
possible:

```
/flc-inspect
```

It opens with your answer as you wrote it before the run, beside the model's,
so the first thing you see is whether the task held. Then it reads the run for
you and lists the claims worth checking. Going straight to
`/flc-rubrics` instead means writing those criteria from the answer alone --
where an invented figure looks exactly like a correct one, because a model
states both in the same confident voice.

It also answers the question the block list was for. If the model read your
answer off a web page instead of working it out, this is where you find out,
and it says which site. **That run cannot be delivered** -- block the site and
run the solver again:

```
/flc-block-domain example.com
/flc-run-solver
```

Nothing you have written is at fault and none of it is lost. Your files, your
prompt, your ground truth and your criteria all stand; it is the run that gets
replaced. The same check runs again at `/flc-deliver`, so there is nothing to
be gained by carrying on.

It also lists every site the run visited, which is the useful part when you are
deciding what else to block before the next one.

### Where everything is

`/flc-inspect` prints the paths, in full, and so does `/flc-view`. Two of them
are worth your time:

| What | Where |
|---|---|
| The read of the run -- start here | `~/flc/task/review/<run>.md` |
| The run itself, to open in a browser | `~/flc/task/review/<run>.html` |

Start with the first. It is a reading of the run: what the model claimed, and
which claims look worth checking.

Then open the second. **Download it out of the sandbox and open it in your own
browser** -- it is a single file that loads nothing from the internet, so it
works offline and looks the same anywhere. It is the run in full and unedited:
the model's reasoning, every command it ran, what came back from each one, and
the answer that gets graded. What came back is behind a click, so it reads as the
model thinking rather than as a wall of output. `/flc-view` rebuilds it.

The same list points at the files the model produced and at what scrolled past
while it ran. You are unlikely to need either, and nothing else it leaves
behind is meant for reading.

The produced files are only the ones the model added or changed -- your own
uploaded files are not copied there, which is how you can tell the two apart.
They should always be there. If they are missing, the run stopped before it got
that far: that is a broken run rather than a model that wrote nothing, and not
something you did. It does not count towards your five, and if any of your
criteria is about a file the model wrote it cannot be graded either: run the
solver again.

### The order from here

1. `/flc-inspect` -- read the run, with your answer beside the model's
2. If the model got there: change the prompt or the files, and run again
   (`/flc-prompt-check` first if you changed the prompt).
   If it did not: finish step 3 -- the rest of the ground truth, the
   justification and the labels -- and run `/flc-check-justification`
3. `/flc-rubrics` -- the second sitting, the non-hallucination criteria
4. `/flc-check-rubric` -- check the criteria against your task
5. `/flc-grade` -- score it, then `/flc-check-grade`

## If it stops early

`/flc-status` will stop saying the run is still going. If it finished
suspiciously fast, `/flc-grade` will tell you what went wrong -- most often a
missing package, which is `/flc-add-package` and another run.

## Running it more than once

A task gets **five counted runs**. The sandbox has a spending cap, and reaching
it stops grading and delivery as well as runs, so the limit is what keeps
enough back to finish. A run that crashed, never gave an answer, came back
without the model's files, or read the answer off the web does not count --
nothing you did caused those.

Run again when something changed what the model has to do: the prompt, the
files, or the block list. Running the same task again mostly shows the same
thing again, so a rerun whose files are unchanged and whose prompt differs by a
word or two stops and asks you to confirm it first. Say yes if you mean it.

After five, another run needs a reason, in your own words. It is recorded with
the task, and nothing about delivering it changes.

Each run is one run, and each goes to its own folder, so nothing is
overwritten and you can read them side by side.

Next, while it runs: [05-rubrics.md](05-rubrics.md) -- and when it lands, come
back to *When it finishes* above before you write the second half.
