---
description: Grade this task by rubrics alone, with no unit tests
---

Mark this task as graded by rubrics alone.

Check first that it is the right call. Unit tests are worth writing when the
model has to **produce something a program can check** -- a file, a value in it,
a specific format. They are not worth writing when the answer is a finding, an
explanation, or a judgement, which the rubrics already grade.

So ask: does your task ask the model to create a file, or to tell you something?

If it is the second, this is the right choice and not a lesser one. A great many
of these tasks are rubric-only by nature.

```bash
python3 ~/flc/bin/task_config.py skip-tests
```

The suite is set aside as `tests/verifier.py.skipped`, so nothing runs it and
nothing ships it: the score is the rubric alone, and the results record that unit
tests were skipped rather than failed, so a skipped suite can never be read as a
failing one.

Reversible at any time with `/flc-enable-tests`, which puts the file back under
its own name.

Use the command rather than moving the file yourself, in either direction. What
runs the checks looks at `tests/verifier.py` and nothing else, so a file deleted
by hand scores nothing while nothing records that as a decision, and a file put
back by hand would be graded and shipped against this one. `/flc-deliver`
refuses both, because a task that lost its checks and a task graded by rubrics
alone would otherwise look identical.

Skipping after `/flc-grade` means the score on record still counts the suite, so
grade again before delivering. `/flc-deliver` says so if it happens.

Then move on to `/flc-grade`.
