---
description: Build the readable page of the run, to download and open in a browser
---

Render the finished run as one HTML page and tell them where it is.

```bash
python3 ~/flc/bin/view_run.py
```

It writes `~/flc/task/review/<job>.html`. Say these two things about it:

- **Download it and open it in your own browser.** It is one self-contained
  file with nothing loaded from the internet, so it works offline and looks the
  same anywhere.
- It is the run in full and unedited: what the model reasoned, every command it
  ran, what came back from each one, and the final answer that gets graded.
  What came back opens on a click, so the page reads as the model's thinking
  with the evidence underneath it.

Then run this and show them the output, which resolves the rest of the paths:

```bash
python3 ~/flc/bin/view_run.py --where
```

## When to reach for it

Any time somebody wants to see what the model actually did. It is the answer to
"where is the trajectory" -- nobody should be asked to read `trajectory.json`.

`/flc-inspect` is still where the reading happens: it builds the review
document, which is a *reading* of the run and says which claims look worth
checking. This page has no opinion about the run at all. Both are wanted, and
the review document is the one to start from.

## What it does not do

It does not judge, summarise, shorten or reorder anything, and it never writes
into `tests/rubrics.md`. If they ask why some number is not flagged on the page,
that is `/flc-inspect`'s job, not this one.

If the run collected no finished workspace, the page says so in its footer. That
is a broken run rather than a model that wrote nothing, and our tooling rather
than theirs: it does not count towards their five, `/flc-grade` refuses it when
a criterion is about a file the model wrote, and the remedy is another run.
