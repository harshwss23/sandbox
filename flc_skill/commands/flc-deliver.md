---
description: Step 8 - rebuild clean, verify, and package the task
---

Package the task for delivery.

## What this does, and why it takes a while

It throws away every container that has been running and rebuilds the image from
`environment/` alone, ignoring all cached layers, then runs the shipped verifier
inside that image to prove it works there, and only then packages anything.

Explain this if they ask why it is slow: it is the only check that the task
works for someone who has nothing but these files. A package that works here and
nowhere else is the failure this step exists to catch, and it stays invisible
until someone else runs the task.

Expect several minutes for the rebuild.

**It does not grade.** The score comes from `/flc-grade`, which ran the same
verifier the delivered task carries. What this step checks is that the score still
belongs to what is being packaged -- the prompt, the material and the rubric it
was taken against. If any of them moved, it says which and stops.

Nobody has to re-grade "just in case" before delivering. If the rubric has
changed since the grade, this will say so.

## Run

```bash
python3 ~/flc/bin/package_delivery.py
```

## If it fails

- **The image did not build** -- something was installed into the live container
  by hand rather than with `/flc-add-package`, or a package name is wrong. The
  build error is in the finding and in `~/flc/.build.log`. Re-add the package
  properly and run again.
- **The shipped verifier did not run in the rebuilt image** -- the captured
  output is in the finding. That file runs in exactly that image wherever the
  task goes next, so it has to work before anything ships.
- **The run has not been graded** -- `/flc-grade` first. The score is read here,
  not measured, so there has to be one.
- **The grade was a deferral** -- the run itself scores nothing; scoring
  happens at `/flc-grade`. Run it.
- **The rubric changed after the grade** -- the score on record is of the
  earlier criteria. `/flc-grade` again; nothing else needs redoing.
- **Fewer than 20 checks** -- criteria and unit tests together. `/flc-grade`
  refuses below this too, so reaching delivery with it means something was
  removed since. No override. Go through the parts of a rubric with them, as
  `/flc-rubrics` does; the missing checks are usually in their ground truth
  already. They write the lines, then `/flc-grade` again.
- **Too few separate checks** -- lines `/flc-check-rubric` found, in every
  reading, to only repeat another do not count towards the 20; the line they
  repeat still does. The finding names them. They take each one out or fold it
  into the line it repeats -- that is theirs to do, never yours -- and add lines
  for an ask no line covers yet, a hallucination criterion from the run, or a
  hard trajectory line. Then `/flc-rubrics`, `/flc-check-rubric`, `/flc-grade`.
- **The score came under the bar through weights alone** -- an earlier grade of
  the same run was at the bar or over it, and only weights changed since. The
  finding names the lines and both weights. The remedy is to put the weights
  back and make the task harder; never suggest another weight. A weight moved to
  the one `/flc-check-rubric` named for that line is not counted.
- **A note that the score rests on defects** -- when the weights and repeated
  lines the check counted, put right, would bring the score to the bar, delivery
  says so and goes on. Pass it on in a sentence: fixing those lines is still
  right, and the task would then need to get harder.
- **The score counts unit tests that are not being shipped** -- there is no
  `tests/verifier.py`, so the task is graded on the rubric alone while the
  score on record still carries the suite's points, and that is the number the
  difficulty bar was read against. `/flc-grade` again. Do not offer to restore a
  suite to match the score: the score is the thing that is out of date.
- **A skipped suite is still in the graded path** -- `tests/verifier.py` is on
  disk on a task marked as graded by rubrics alone. What runs the tests reads
  that file and never the state, so it would be graded and shipped against the
  contributor's own decision -- and on a task that asked for no suite, what
  ships is the template's examples failing against files nobody wrote.
  `/flc-skip-tests` sets it aside; `/flc-enable-tests` then `/flc-check-tests`
  if it should count after all. Then `/flc-grade` either way. Do not offer to
  leave it as it is.
- **No suite, and nothing recorded that as a decision** -- an absent
  `tests/verifier.py` scores nothing whether or not anyone meant it to.
  `/flc-skip-tests` records the intention, and is the right answer for a task
  whose answer is a finding rather than a file; otherwise the suite is still to
  be written.
- **The prompt or the workspace changed after the run** -- this is the serious
  one, and it needs a new run rather than a new grade. The model was given the
  earlier version, so the bundle would ship one task and the evidence for it
  would be a run of another. `/flc-run-solver`, then `/flc-grade`.
  Do not offer to work around this; the evidence is the point of the delivery.
- **The run was started with another model or agent** -- `--model` or `--agent`
  on `run_solver.sh` is for comparing models, and the score of a run started
  that way belongs to what it asked for rather than to the model this sandbox
  measures. The finding names both. `/flc-run-solver` again without them, then
  `/flc-inspect` and `/flc-grade`. Their prompt, files and ground truth stand;
  the hallucination criteria were written from the other run, so they go
  through those against the new one. Never start a run with `--model` or
  `--agent` on a contributor's behalf.
- **The model looked the answer up instead of working it out** -- a figure
  their own ground truth gives as the answer came back from a web request, and
  appears in none of their files, in nothing the model produced, and in the
  output of nothing else it ran. `/flc-inspect` reports the same thing and
  names the site. The remedy is `/flc-block-domain <site>` and another run, and
  say plainly that nothing they wrote is at fault: their files, prompt, ground
  truth and criteria all stand, and it is the run being replaced. There is no
  override, and none is needed -- this refuses a run, never the task.
  If instead the line reads that it *could not be checked* because the
  sandbox's own check failed, delivery went on without it and nothing about the
  task needs to change. Say nothing about it unless they ask: it is recorded for
  the project team (see *A technical issue on our side* in the skill).

- **The bundle carries fewer than five hallucination criteria** --
  `/flc-rubrics` holds the same floor and cannot see this, because a criterion
  the judge would not grade is dropped on the way into the bundle, which takes
  the count under without changing anything they wrote. The finding says whether
  that is what happened: if it is, the remedy is rewording those to say the same
  thing differently and `/flc-grade` again; if not, it is more lines under
  `## Non-hallucination`. No override.
- **More than two criteria describe a failure the run did not commit** -- the
  judge never charged the model for them, so they are wrong turns the task did
  not compel rather than ones it recorded, and a rubric made mostly of those
  measures what one model happened to avoid. Only a line firing or going brings
  the count down, and neither repair weakens a criterion that is right: run the
  solver again against material that pulls harder towards the wrong turns those
  lines describe, so that they fire, or drop one they cannot point at in the
  answer at all. Criteria for mistakes the run did make are worth writing
  (`/flc-inspect`), but they do not reduce this count. Say
  plainly that this is not an instruction to make anything easier -- the
  difficulty bar is a ceiling, so the temptation here runs the wrong way.
- **The justification was never checked, was checked before its last change or
  a change to the files, or has a finding to answer** --
  `/flc-check-justification` reads `solution/underspecification_justification.md`
  against the prompt, the ground truth and the files, and its verdict is only
  about the versions it read. Run it, and again after any edit to that file or
  to the files. Every remedy for a finding adds: name what
  determines the answer, close the path, add the material that closes it, or
  make the gap deliberate. If it could not be checked, that is recorded and
  blocks nothing.
- **The labels do not read cleanly or do not agree** -- `solution/labels.md`
  is checked again here: every heading answered in a spelling it lists, yes
  with `l5 - full` and a *What the model cannot know* section, Clarification
  criteria only on a task marked yes, and the failure justification in at most
  three plain sentences. The message names the heading and the line. The
  formatting rule in `SKILL.md` applies: ask before fixing it, fix the
  formatting only, and ask them to confirm. A value is theirs to choose; if
  they change the first answer, the rubric has to follow it (`/flc-rubrics`,
  then `/flc-grade`).
- **The criteria have not been checked, or changed after the check** --
  delivery reads what `/flc-check-rubric` recorded and does not check again, so
  the check has to be of the criteria, prompt, ground truth, files and run
  being delivered. `/flc-check-rubric`, then deliver again.
- **Findings in the criteria stop delivery** -- the refusal names them, and
  `/flc-check-rubric` explains each one and its fix. None of them can be set
  aside. They fix them, then `/flc-rubrics`, `/flc-check-rubric` and
  `/flc-grade`. None of the remedies is to make a criterion easier: each is the
  line saying more plainly what they meant, a weight moved to its bucket, or a
  line removed because another line already contains it.
- **Their answer states something a check shows is wrong, and graded material
  repeats it** -- `/flc-check-justification` or `/flc-check-rubric` found a
  statement in `solution/ground_truth.md` wrong, three independent readings
  confirmed it, and a line, a test or the justification repeats it. The refusal
  names the statement, what is wrong and what repeats it. They correct the
  answer and everything that repeats it, then `/flc-check-justification`,
  `/flc-check-rubric` and `/flc-grade`. Changing the answer after the run is
  expected here and is recorded with the task. You never edit the answer.
- **Too much of the rubric went ungraded** -- the judge's safety filter declined
  to read some criteria, and between them they are more than a tenth of the
  rubric by weight, so the score covers too little of the task to stand for it.
  Reword those criteria to say the same thing differently and `/flc-grade`
  again; the finding names them. Grading again unchanged is worth one try first,
  because the filter is inconsistent. There is no override for this one, and the
  reason is that unlike a gateway that will not answer, the wording is something
  the contributor can change.

## Noted, not blocking

Delivery also notes which single criterion, read the other way by the judge,
would put the score at the bar. `/flc-check-grade` is where to check it, and it
blocks nothing.

## What comes out

```
~/flc/task/delivery/
  bundle/          the task itself, ready to run
  run/             what the solver did and how it scored
  run_removals/    the rest of the run's files, kept for reference
  authoring/       prompt, rubrics source and ground truth -- internal only
  validation.json  the record that these checks passed
  AUDIT.md         the same record in prose, including anything acknowledged
```

`bundle/` is a plain task folder with nothing extra in it. `run/` holds the
transcript, the score and the final workspace; the rest of what the grading run
wrote is in `run_removals/`, and `AUDIT.md` lists it.

This is the last step. The check `/flc-submit` makes -- that nothing has moved
since these checks ran -- also runs by itself when they finish the task, so
they only need `/flc-submit` if they want that answer now. It packs nothing:
the folder is collected from the sandbox as it stands when they finish the
task.

## If it refuses because the task was too thin

**The context floor is a gate too, and it is measured from the run** -- what the
model actually had in front of it, not the size of `environment/workspace/`. So
a large folder it barely opened does not clear it, and no edit to the workspace
changes the number until the solver has run again.

Say what the remedy is rather than the size: material the question cannot be
answered without, or a prompt that makes the work cover more of what is already
there. Then `/flc-run-solver` and `/flc-grade` again, in that order.

If instead it says the context could not be **measured**, that is our
instrument, not their task. It can be recorded and moved past:

```bash
python3 ~/flc/bin/package_delivery.py --acknowledge context_unmeasured --reason "..."
```

Only do that once you have read why it could not be measured and are satisfied
the run was real. The reason is written into the audit record and is read later
by someone who was not here, so write it for them.

## If it refuses over the prompt difficulty check

Three refusals come from the difficulty verdict, and the remedy differs.

**Never checked, or checked against an earlier prompt** -- run
`/flc-prompt-check`. The second one is the common case and is not a mistake on
their part: editing `prompt.md` after the check is ordinary, and nothing else
in delivery notices, because rerunning the solver and grading again satisfies
every other freshness check. It takes about a minute and nothing else has to be
redone.

**The verdict was FAIL** -- the prompt reads as something an outsider could
work out, and that has to be fixed in the wording, not waved through. Changing
it means the run no longer matches the prompt, so it is `/flc-prompt-check`,
then `/flc-run-solver`, then `/flc-grade`. Worth being straight with them that
this is the expensive one.

**It could not be checked** -- recorded, not blocking. Nothing to do. The score
in hand is better evidence than the prediction that failed.

## If it refuses because the model scored too well

**The task cannot be delivered unless the solver scored below 50%.** This is a
gate, not a warning, and there is no override. A task the model already passes
measures nothing: the project collects the cases where models go wrong, and a
run with no mistake in it is a transcript nobody can learn anything from.

Do not soften this or imply it might be waved through on review. The check is in
`/flc-deliver` and it fails the run.

This is the one failure here that is not a bug to fix but a task to strengthen,
so say which it is. What usually works, in order of how often it does:

- **Give it more to rule out.** A second plausible source that a careful reader
  has to open and set aside is worth more than another required file.
- **Ask for something the shortcut does not give.** If the answer can be read
  off one file, ask for the thing that needs two of them combined.
- **Bury the answer deeper.** Not more files for their own sake -- material
  where the answer-bearing part is not the first thing found.

Then rerun the solver and grade it again. The completion criteria do not move:
they came from the ground truth, and weakening them to clear the bar is the one
thing that would make the number meaningless.
