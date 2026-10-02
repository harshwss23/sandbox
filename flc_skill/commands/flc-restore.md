---
description: Move a task handed over for review into this sandbox
---

Move the task being reviewed into the sandbox: $ARGUMENTS

```bash
python3 ~/flc/bin/restore_task.py $ARGUMENTS
```

This is the first thing a reviewer runs, and only a reviewer runs it. A review
sandbox comes up fresh, with the work being reviewed dropped in beside it
rather than in it -- usually at `~/task` and `~/jobs`. Nothing in the workflow
looks there, so without this the reviewer is told the solver never ran and sent
to make a new run, which would be a different run from the one every criterion
was written against.

Run it with no arguments first: it says what it would move and changes nothing.
Then run it again with `--apply`.

What it does, and each of these is worth reading back to them:

- moves `task/` and `jobs/` into `~/flc/`, so every command finds them where it
  already looks;
- re-points the recorded job path at where the runs actually landed, since it
  was written on somebody else's machine and is an absolute path;
- checks what arrived against the receipt the last person left in
  `delivery/readiness.json`, and says which files are missing or changed;
- records that this session is a review pass, which travels into the delivery
  record so a second delivery is legible as a review rather than as somebody's
  own second attempt.

It refuses one thing outright: moving a task in on top of work that is already
here. Two people's files in one task folder cannot be told apart afterwards, so
if `~/flc/task` has been started, this is the wrong sandbox and the answer is a
fresh one rather than a merge.

A handover with no receipt is not refused. The receipt is the last person's to
have left and a reviewer cannot be stopped from reviewing by its absence -- it
is recorded as missing and the review goes ahead.

Once it has run, `/flc-status` shows the task as it was delivered. Start from
`/flc-inspect` and the delivery record in `delivery/AUDIT.md`, not from a new
run.
