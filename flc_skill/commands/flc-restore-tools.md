---
description: Put the sandbox's own scripts back the way the seed shipped them
---

Restore the sandbox's machinery to what the seed shipped: $ARGUMENTS

```bash
python3 ~/flc/bin/restore_tools.py $ARGUMENTS
```

Run it with no arguments first. That reports what has been changed and what
would be put back, and writes nothing; then run it again with `--apply`. Tell
the contributor one sentence: one of the sandbox's own scripts had been changed
and is now put back, and nothing they wrote is affected. The list is for you.

A file changed by a repair recorded with `technical_issue.py` is left alone,
because putting it back brings back the fault it fixed. `--include-repairs`
puts those back too; use it only when the repair itself is the problem.

Reach for this when a step refuses because one of the grading or run scripts is
not the one the seed shipped. The refusal names the files; this puts exactly
those files back, taking the bytes out of the seed zip on the VM and checking
each one against the recorded digest before it overwrites anything. A file it
cannot verify is not written -- it says so and stops, which is the right
outcome: a half-restored copy of the machinery would be a third version, and
the point of the command is that there is only one.

It does not touch anything the contributor wrote. `prompt.md`, the workspace,
`tests/rubrics.md` and `solution/ground_truth.md` are not the seed's files and
are not in the manifest.

Afterwards, whatever the refusal asked for still has to be done again. Putting
the file back does not restore the evidence that was taken with the edited one
in place -- if the run or the grade was cleared, run it again.

**You are the likeliest cause of this refusal.** If a script was edited during
this session without `check_integrity.py --may-edit` allowing it, put it back
and record what the edit was for with `technical_issue.py`: the problem it
worked around is still there, and the project team needs to hear about it.
Follow *A technical issue on our side never stops them* in the skill for what
to say to the contributor.
