---
description: Step 2 - check the uploaded files and the prompt
---

Check that the task has enough real material and a prompt that does not give the
answer away.

This step also reads the difficulty verdict `/flc-prompt-check` records. If that
has not been run, or was run against an older version of `prompt.md`, this step
will say so and stop. Run `/flc-prompt-check` first, or when it asks.

## First, find out which files matter

This step estimates how much material is here. It does not decide anything: how
much a task really puts in front of the model depends on what the model reads,
which is measured after `/flc-run-solver` and has to reach 27,000 tokens.

Say so if the estimate looks thin, and say so if it looks generous. Do not tell
them they have cleared a floor, because this step cannot know that.

The required/distractor split still has to be recorded. It is what makes the
task reviewable, and it is how the check can tell a task that has nothing to set
aside -- one with no triage in it -- from one that does. The grading criteria
are written from what the run did, read against the distractor section of the
ground truth, not from this list.

At delivery the split is written up as `delivery/authoring/materials.md`, beside
what the ground truth says about the same files, for whoever reviews the task.
Nothing is graded on it and no criterion comes from it, so this is not a reason
to press the contributor for a tidier answer than they have -- a file that is
genuinely half of each is allowed to be recorded as either.

So before running anything, list what is in the workspace:

```bash
find ~/flc/task/environment/workspace -type f | sort
```

Then ask the contributor, in plain terms: *which of these does someone actually
have to read to answer the question? The rest are the distractors.*

Do not guess this from filenames. A file called `old_backup.csv` might be the
one that matters.

## Then run the check

```bash
python3 ~/flc/bin/check_inputs.py --required <the files they named>
```

Paths are relative to the workspace folder, for example `data/results.csv`.

## Then explain the result

Go through the findings and translate each one:

- **Not enough material** -- ask what else exists: either more of what the answer
  depends on, or more of what a careful reader would have to open before ruling
  it out. Both count. What does not is filler nobody would open, and it is worth
  saying so plainly, because the number will move and the task will not improve.
- **Every file is needed** -- a task with nothing to set aside has no triage in
  it, and triage is where the interesting failures happen. Ask whether a stale
  version, a neighbouring dataset or a near-miss identifier exists.
- **The prompt names files** -- explain that finding the right file is part of
  what is being tested, and propose wording in the conversation that describes
  what they want instead of where it is, for them to type in.
- **File types may not be readable** -- usually harmless. If it matters, they
  can add a package with `/flc-add-package`.
- **A file has no text that could be read** -- a scan or an image is fine as
  material and simply not counted. A PDF the sandbox could not open is ours,
  already recorded: say nothing about it unless they ask.
- **The workspace is heavy** -- pass it on once, in the check's own words, and
  move on. It is a recommendation, not a limit. Never suggest removing material
  to get under it: what goes in the workspace is theirs to decide.
- **A leftover .zip or __MACOSX in the workspace** -- they unpacked by hand.
  `/flc-unpack` removes both; the zip especially matters, since leaving it means
  the model sees every file twice.
- **The prompt reads like a specification** -- headings and numbered steps turn
  a research problem into a checklist. Suggest they write it as a message to a
  colleague who has access to the same folder.
- **Nobody has checked whether the prompt is hard enough**, or **the prompt has
  changed since it was checked** -- run `/flc-prompt-check` and then this again.
  The second one is ordinary: editing the prompt after checking it is exactly
  what the earlier findings ask them to do.
- **The prompt is not hard enough** -- this one blocks. `/flc-prompt-check`
  explains it properly and says what moves a prompt up; send them there rather
  than paraphrasing the one line shown here.
- **The prompt could not be checked** -- our check failed, not their task. Run
  `/flc-prompt-check` once more yourself, then carry on: this is a warning and
  does not hold anything up. If it still cannot measure, say the one sentence in
  *A technical issue on our side* in the skill, and nothing about the cause
  unless they ask.

## A prompt that leaves something out may be doing it on purpose

Before suggesting a prompt is too vague, ask. Some tasks are **underspecified by
design**: the message leaves out something the model cannot work out from the
files -- which of two runs was meant, which threshold the team uses -- and the
behaviour under test is whether the model asks or quietly picks one and reports
the result as if it were the only one. That is a hallucination we want, and the
check cannot tell it apart from carelessness.

Nothing here blocks on vagueness -- the difficulty check ignores whether a
prompt is fully specified, and the findings about wording are all warnings. The
risk is you talking them out of it. If the gap is deliberate:

- confirm the gap is **visible in the material** -- something a careful reader
  would be stopped by, not merely absent
- confirm **something is still answerable without it**, because a question that
  cannot be started is not a task
- ask them what the right question is, in words, and tell them that goes in the
  ground truth at step 3 and becomes a `## Clarification` criterion at step 5,
  paired with a second Clarification line for the choice made silently

Do not propose wording that closes the gap. Do propose some if they are vague
about the part they *do* expect answered -- that is the accidental kind, and it
is ungradeable.

If it passes, give them the estimate, say it is an estimate, and move them on to
`/flc-ground-truth`.
