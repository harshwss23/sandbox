---
description: Step 6 - check the unit tests run, test something, and are weighted
---

Check `~/flc/task/tests/verifier.py`.

**First, decide whether this step applies at all.** Unit tests are for things a
program can check: a file the model was asked to produce, a number in it, a
format. If the answer is prose -- a finding, an explanation, a judgement -- the
rubrics already grade it and unit tests add nothing.

Ask before pushing anyone into writing Python. If the answer is prose, say so
and offer `/flc-skip-tests`. Skipping is a first-class outcome, not a shortcut.

**If the prompt does ask for a file with a fixed shape, look at their rubric
before anything else.** The values in that file belong here, and the ordinary
mistake is that they are already written as criteria -- a task arrived with
thirty-six of them. Each one is a judge call spent having a language model
eyeball a number that an assertion settles exactly. Moving them costs nothing:
a test and a criterion are weighted on the same scale.

A number stated in the answer's prose is the exception and stays a criterion.
The model may write `1.2e-5` or `0.000012`, and the judge reads for the value
where a text match would need every spelling of it.

## Run it

```bash
python3 ~/flc/bin/check_tests.py
```

This builds the task image and runs their tests under pytest against the task
**unsolved** -- the exact state the model starts in. It takes a few minutes the
first time. It also refreshes `tests/test_weights.md` against the suite and
compiles it.

Once the suite is settled and only the weights are being changed:

```bash
python3 ~/flc/bin/check_tests.py --weights-only
```

which does the reading and the compiling and builds nothing.

## What it can and cannot tell them

It cannot confirm that a passing test means a correct answer; there is no gold
solution to check against, and writing one is not part of this job.

It confirms the other half, which is where broken verifiers actually land:

- **the tests run at all** -- a typo makes a test that can never pass, and a
  solver run is a bad place to discover that
- **the tests fail before the task is solved** -- a check that passes on the
  untouched workspace would pass for a model that did nothing

So "N of M tests fail" is the good outcome here, and worth saying plainly,
because it looks alarming.

## Weighting the tests

Every test is worth 5, 3 or 1, on the same scale as a rubric criterion, and the
points count towards the model's score the same way. `tests/test_weights.md` is
generated: a new test gets a line at `[3]`, and a number already set is never
changed by the tool.

**Propose a weight for each test and let them accept or change it.** Read what
the test asserts rather than what it is called:

- **5** -- it would let a wrong answer through unnoticed: a value that has to be
  right, a file the model must not have altered, something private or excluded
  that must not appear
- **3** -- it says the work was done: a file exists, has the right structure,
  the right keys, the right number of rows, the right order
- **1** -- it tidies: a filename spelling, a header or column format, a file
  that parses, a size or length bound

Weight anything the prompt asked for explicitly at 5, and when torn between two,
take the higher.

**Do not help anyone reweight their way under the difficulty bar.** By the time
weights are being adjusted the score may already be known, and lowering a
passing test's weight is an easy way to get under 50%. The weights ship with the
task and stay on the record. If the model scored too well the task was too
easy, which is a finding about the task and not a number to be managed.

## Explaining the findings

- **Parametrized test** -- a FAIL, and not negotiable. `@pytest.mark.parametrize`,
  `@pytest.fixture(params=...)` and `pytest_generate_tests` are all refused. One
  test is one named thing carrying one weight; a parametrized one is several
  under names that move whenever the case list is edited. Help them write the
  cases out separately -- usually they turn out to be different facts deserving
  different weights.
- **Crashes instead of failing** -- a raised exception, not a failed assertion.
  Usually a typo or a missing import. The detail is in the finding. Point at the
  `flc_testkit` helpers: they give a clear message instead of a crash when a file
  is missing.
- **Every test passes before the task has been solved** -- a FAIL. These tests
  measure nothing. Ask what the model is supposed to produce, and check that.
- **These are still the template's example tests** -- a FAIL. The examples check
  a prediction file, an evidence file and a manifest belonging to a task nobody
  wrote, so they would run against this task and fail, and the model would lose
  those points for work it was never asked to do. Delete them and write checks
  about this task's own material, or run `/flc-skip-tests` if there is nothing
  worth checking exactly.
- **verifier.py defines no tests** -- pytest collects functions named `test_`.
  A function named anything else is not a test and is not run.
- **The tests could not be run** -- often a package the image lacks.
  `/flc-add-package <name>` fixes it. This is never scored as a failing suite:
  a suite that did not run is not a model that got things wrong.
- **A line in test_weights.md cannot be read** -- the format is
  `- [5] test_name`, and the only weights are 5, 3 and 1.
- **The image did not build** -- read `~/flc/.build.log` before suggesting
  anything.

When it passes, move on to `/flc-grade`. The solver run was started at step 4 and has probably landed by now.
