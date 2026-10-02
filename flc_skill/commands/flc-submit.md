---
description: Confirm the finished task is ready to be collected
---

Run:

```bash
python3 ~/flc/bin/submit.py
```

This is not a step: the same check runs by itself when they finish the task,
and `/flc-deliver` is the last step. It confirms the delivery is complete and that nothing has
changed since `/flc-deliver` checked it, and it writes `readiness.json` into
`delivery/` recording the check and a digest of every file being handed over.

Nothing is archived, downloaded or uploaded. The platform collects
`flc/task/delivery/` and `flc/task/review/` from the sandbox when the
contributor finishes the task, so the folders as they stand at that moment are
the submission.

"Nothing has changed" covers the copies in `delivery/authoring/` as well: each
one has to match the file it was copied from, and both copies of the
justification have to be the version `/flc-check-justification` passed.

If it refuses, say which file moved and run `/flc-deliver` again. When the file
is the justification, `/flc-check-justification` comes first, because what
changed is the thing that check read. If it prints a
note about the run not having been read, that is a note and not a refusal --
offer `/flc-inspect`, do not treat it as blocking.

When it passes, tell them two things and no more: they are ready to finish the
task, and they should now stop -- no more edits and no more commands, including
`/flc-inspect` and `/flc-view`, which rewrite `review/` even though they only
display things.

If they ask for anything after that, or you find yourself about to run a command
for them, say that it will need `/flc-submit` run again afterwards, and then do
run it. The record is only worth anything if it describes what actually gets
collected, and quietly leaving it stale is worse than the edit itself.

Do not tell them to download anything or look for an archive. There is neither.
