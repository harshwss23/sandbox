---
description: Step 7 - check the judge read each criterion the way you meant it
---

Walk the contributor through the judge's verdicts.

## Why this step exists

The score is worth exactly what the judge's reading of each criterion is worth.
It answers each criterion on its own, from the wording alone, and where it read
one differently from the way the contributor meant it, the verdict describes the
wording rather than the model. That is a criterion to fix, and this is the only
step that looks for it.

Say that plainly at the start, because the natural reading of a grade is that
the numbers are the finding and the job is done.

## Open the page first

Grading wrote the whole grade to `~/flc/task/review/grade-<run>.html`. Give them
the path and tell them to download it and open it in their own browser. A rubric
of thirty criteria with a paragraph of reasoning on each is not readable in a
terminal, and this step asks them to read all of it.

If they would rather stay in the terminal, `python3 ~/flc/bin/grade_report.py`
is the same content.

## Then walk them through it

```bash
python3 ~/flc/bin/check_grade.py
```

It shows one criterion at a time -- the verdict, the weight, and the judge's
reasoning -- and asks whether the judge read it correctly. Work through it with
them rather than answering on their behalf: they are the only one who knows what
the criterion was meant to say.

**The question is whether the judge understood the criterion, never whether the
verdict is the one they wanted.** Be firm about this. A contributor whose task
scored 50% or more cannot deliver it, and the temptation at that point is to
call the criteria the model passed misjudged and reword until the number falls.
That is not what this is for, the completion criteria come from the ground truth
and do not move to clear the bar, and what was flagged is recorded in the
delivery record, where it stays with the task.

If the score is too high, the fix is a harder task -- see `/flc-grade`.

## The four things that can be wrong

The command names these; the point of choosing between them is that they are
different repairs.

- **ambiguous** -- the criterion was unclear, or carried two facts, so the judge
  answered a different question from the one intended. Reword it.
- **misread** -- the criterion is sound and the judge simply got it wrong.
  Grading again is worth one attempt, because the judge is not deterministic.
  If it reads the same way twice, the criterion has to name the fact more
  plainly.
- **belongs_in_a_test** -- it checks an exact value in a file the model
  produced. A program can compare that exactly; the judge is being asked to
  eyeball it, and will sometimes get it wrong for reasons that have nothing to
  do with the model. Move it into `tests/verifier.py`.

  Confirm first that the prompt **required** what the check would compare rather
  than giving it as an example. Where the row label or the number's format is
  the contributor's example and not their instruction, the criterion is right
  where it is and a check would fail a model that answered correctly in another
  spelling. This flag is also the one most available to a contributor looking
  for a reason to move a criterion the model passed, so ask what the prompt
  said rather than taking the case on the verdict.
- **unsupported** -- the criterion asks for something the ground truth does not
  support. Then the criterion is wrong, not the model. `ground_truth.md` is the
  fixed point of the task and does not move to accommodate a criterion.

## After a flag

**Every flag ends in grading again, and that is not optional.** Tell them before
they start editing. The score on record is tied to the criteria it was taken
against, so a rubric edited after grading leaves `/flc-deliver` refusing a stale
score -- which reads like a broken sandbox if nobody warned them.

The order is: make the edits, `/flc-rubrics`, `/flc-grade`, then
`/flc-check-grade` again. The second pass is short -- criteria that came back
unchanged carry their confirmation over, so only what moved is asked about.

Nothing here edits `tests/rubrics.md`. The criterion is theirs to change.

## What it is not

It is not a gate. `/flc-deliver` records whether the verdicts were checked and
does not block on it, because a contributor who disagrees with nothing has
nothing to act on and blocking would strand them. That means whether this
happens at all is down to how you introduce it.

If they have nothing to flag, that is the ordinary outcome and worth saying so:
it means nothing was flagged as misread.

## The last two labels

When nothing is flagged, the command ends by checking `solution/labels.md` for
the two answers written after grading: what went wrong in this run, and why.
If they are not written yet, ask for them now, in their words:

- **What went wrong** is one or more of `grounding`, `synthesis`,
  `correctness_reasoning`, `exploration` and `conflict_resolution`. Most tasks
  have one, and a consequence is not a second one: a wrong answer because the
  model misread or never opened a file is that earlier failure alone.
- **Why** is at most three plain sentences an outsider could follow.

Which failure it was is their call, made from the transcript and the grade.
You may say what you see in the run, and you never choose. If the check
reports a formatting problem, the rule in `SKILL.md` applies: ask before
fixing it, fix the formatting only, show them, and ask them to confirm. Never
shorten or reword the justification to fit three sentences -- say which
sentences are over, and they cut them. Run `python3 ~/flc/bin/labels.py --stage
post` again afterwards.

A note that the run disagrees with their browsing answer blocks nothing. It is
worth one question -- does a correct answer need something only online? -- and
the answer is theirs.

Then `/flc-deliver`.
