# The last check

```
/flc-submit
```

You do not have to run this. The same check runs by itself when you finish the
task, so the record goes into the folder either way.

What it does is confirm your delivery is complete and that nothing has changed
since `/flc-deliver` checked it, and write that confirmation into the folder.
Run it yourself when you want that answer now -- after packaging, or after
changing something and wanting to know whether it mattered -- rather than
finding out at the end.

There is nothing to download, attach or upload. When you finish the task, your
`delivery/` and `review/` folders are collected from the sandbox as they stand.
So the only thing that matters is that they are right at the moment you finish
-- which is exactly what this checks.

## Once it says Ready, stop

Do not edit anything, and do not run any more commands. That includes
`/flc-inspect` and `/flc-view`: they only show you things, but they rewrite the
files in `review/` to do it, and `review/` is collected too.

Anything that changes after this point goes with the task without having been
checked. If you do change something -- deliberately or not -- just run
`/flc-submit` again afterwards. It is quick, and it brings the record back in
line with what will actually be collected.

## If it refuses

**Something changed after you packaged.** It names the file. Run `/flc-deliver`
again -- it is the same few minutes -- and then `/flc-submit`. That includes
the copies in `delivery/authoring/`: each one has to match the file it was
copied from.

**Your justification changed after it was checked.** What gets collected has
to be the version `/flc-check-justification` passed, both in `solution/` and
in the delivery. Run `/flc-check-justification` on the version you want to
keep, then `/flc-deliver`, then `/flc-submit`.

**Delivery has not run, or did not pass.** There is nothing to check yet. Go
back to [08-delivery.md](08-delivery.md).

## If it mentions the run not being read

That is a note rather than a refusal. `review/` is collected alongside your
delivery, and it is where the read of your solver run lives. If it is not there,
`/flc-inspect` writes it. It is worth having: it is the evidence that your task
does what you say it does.

Next, if something is still not working: [10-troubleshooting.md](10-troubleshooting.md)
