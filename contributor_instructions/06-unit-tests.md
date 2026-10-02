# Step 6: automated checks

A check is a few lines of Python that look at what the model produced and say
whether it is right. They are scored exactly as your criteria are.

## Do you need them?

**Does your prompt ask the model to write a file with a fixed shape?** A JSON
file with named keys, a CSV with named columns, anything where you have said
what goes where. Then yes, and the values in that file belong here rather than
in your rubric.

That is the rule worth taking seriously, because getting it wrong is expensive
and does not look like a mistake at the time. A criterion like
`output.json reports total_variants as 1184` is a language model being asked to
eyeball a number. An assertion compares it. The assertion is exact, it is free,
it runs in a second, and it says which value was wrong instead of a paragraph
about it. Thirty of those as criteria is a rubric that has to be rewritten, and
it has happened here on a real task.

**Then check that you actually pinned the thing you are about to compare.**
Naming a file does not pin everything in it. If your prompt gave a key, a row
label or a number format as an *example* rather than requiring it, the model may
reasonably write it another way, and a check that insists on your spelling marks
a correct model wrong. That is worse than a criterion being generous: the
delivery is a record of real failures, and a manufactured one spoils it. Step 5
works this through on a real prompt, under
[Pinned, or only given as an example?](05-rubrics.md). Facts like that stay in
the rubric, where the judge can read any spelling of them.

**Does your task ask the model to tell you something rather than to build
something?** Then no, and your rubrics already grade it. Reading an answer for
whether a claim is supported is the judge's job and there is no assertion for
it.

**And if you do not write Python, skip this step.** Nothing is lost. A task
with no checks is graded on its rubrics alone, and a task is never marked down
for having none. Say so in `/flc-rubrics` instead and write the values as
criteria -- that is the right trade when the alternative is not writing the
task.

One thing to know either way: **tests count towards the floor of 20 checks
alongside your criteria.** Skipping this step does not raise the bar, it just
means all 20 are criteria. Writing five tests here means fifteen criteria is
enough. Where a fact goes is decided by which instrument can settle it, never
by which side of the count needs filling.

To skip:

```
/flc-skip-tests
```

Then go on to step 7. The suite is set aside as `tests/verifier.py.skipped`, so
nothing runs it and nothing ships it, and the results record that unit tests were
skipped, not failed. `/flc-enable-tests` brings it back if you change your mind.

## What a check can see

- **`WORKSPACE`** -- the workspace as the model left it, so any file it wrote
- **`SOURCE`** -- the files you uploaded, as they were before the run
- **`ANSWER`** -- the text of the model's final answer
- **`opened(path)` and `ran(fragment)`** -- what the model did, from the
  transcript

`ANSWER` is there, but be careful with it: matching text against free prose is
brittle in a way that matching a JSON key is not. The model may write `1.2e-5`
where you looked for `0.000012` and be perfectly correct. Values stated in prose
are better as criteria, where the judge reads for the number rather than the
characters. Values in a file you specified the shape of are better here.

## If you do want them

Open `~/flc/task/tests/verifier.py`. It has worked examples in it, written as
pytest tests. **Delete them once you have read them.** They check files belonging to the imaginary task
they were written for, so leaving one in means the model loses points for work
your prompt never asked for. `/flc-check-tests` refuses while any are left.

These are pytest tests. Each one is a function whose name starts with `test_`.
Inside, use `assert` with a message saying what you expected:

```python
def test_results_file_exists():
    """The model was asked to write results.csv."""
    assert (WORKSPACE / "results.csv").exists(), \
        "the model did not create /workspace/results.csv"


def test_top_gene_is_correct():
    """results.csv should name GENE0421 in its first row."""
    lines = read_text("results.csv").splitlines()
    assert len(lines) > 1, "results.csv has no data rows"
    assert "GENE0421" in lines[1], \
        f"expected GENE0421 in the first row, found {lines[1]!r}"
```

## What each test is worth

Every test carries a weight of **5, 3 or 1** -- the same scale as a rubric
criterion -- and those points count towards the model's score exactly as the
rubrics do.

You set them in `~/flc/task/tests/test_weights.md`, which is generated for you.
`/flc-check-tests` adds a line for every new test at `[3]` and never changes a
number you have set, so the only thing you ever do in that file is change
numbers:

```
- [5] test_top_gene_is_correct  # results.csv should name GENE0421 in its first row.
- [3] test_results_file_exists  # The model was asked to write results.csv.
- [1] test_header_is_lowercase  # The columns are spelled as the prompt asked.
```

What the three mean:

| | |
|---|---|
| **5** | the test that would let a wrong answer through unnoticed -- a value that has to be right, a file the model must not have altered, something private or excluded that must not appear |
| **3** | the test that says the work was done -- a file exists, has the right structure, the right keys, the right number of rows, the right order |
| **1** | the test that tidies -- a filename spelling, a header format, a file that parses, a size or length bound |

Read what the test asserts rather than what it is called, weight anything your
prompt asked for explicitly at 5, and when you cannot decide between two, take
the higher.

Write the tests that matter rather than a long tail of easy ones. Ten trivial
tests that any run passes make a task look easier than it is, and the score is
what decides whether it is hard enough to ship.

**One more thing about that.** You will see the model's score before you
deliver, and the bar is a ceiling -- so there is a version of this where a
passing test gets quietly reweighted down to get under it. Do not. A weight is
your judgement about how much the fact matters, made before you know what it
costs; the weights ship with the task and stay on the record. If the model
scored too well, the task was too easy, and that is the finding.

## Parametrized tests are not allowed

No `@pytest.mark.parametrize`, no `@pytest.fixture(params=...)`, no
`pytest_generate_tests`. `/flc-check-tests` refuses them and names the fix.

One test is one named thing that is either true or false, and it carries one
weight. A parametrized test is several tests sharing a name that changes
whenever you edit the list of cases, so the weights could never stay in step
with the suite. Write the cases out separately -- if that feels repetitive, it
is usually several different facts wearing one name, and they are worth
different amounts.

`WORKSPACE` and `read_text` come from `flc_testkit`, already imported at the top
of the file, along with `read_json`, `read_lines` and `source_json`. They give a
clear failure message when a file is missing instead of an unreadable crash.

## Checking values, which is what this step is mostly for

If your prompt asked for a JSON file with named keys, one check per key is the
right shape, and `read_json` is what reads it:

```python
def test_total_variants():
    """output.json should report 1184 variants."""
    got = read_json("output.json").get("total_variants")
    assert got == 1184, f"expected total_variants 1184, found {got!r}"


def test_mean_depth():
    """output.json should report a mean depth of 42.7, give or take rounding."""
    got = read_json("output.json").get("mean_depth")
    assert isinstance(got, (int, float)), f"mean_depth is {got!r}, not a number"
    assert abs(got - 42.7) < 0.05, f"expected mean_depth near 42.7, found {got}"
```

Two things that example is doing deliberately. It **decides the tolerance
itself** -- `< 0.05` is your judgement about how exact the answer has to be, and
writing it down is the part a criterion cannot do. And it **says what it found**
in the failure message, so the grade tells you which value was wrong rather than
that something was.

**Keep each check to one fact.** If a check about a value also insists the
column is spelled your way, then one cosmetic choice by the model fails two
checks, and the grade says the value was wrong when it was not. Where two checks
share a helper, make sure the helper only does the part they both genuinely
need.

Both of those are worth 5: a wrong number here is exactly the kind of confident,
fluent mistake the task is being built to catch, and nothing else in the grade
would notice it.

## Checking what the model did, not just what it produced

Two more helpers look at the transcript of the run rather than the finished
files:

```python
def test_it_consulted_the_manifest():
    assert opened("data/metadata.csv"), \
        "the model never opened the manifest it was told to start from"
```

`opened(path)` and `ran(fragment)` search everything the model ran and saw. They
are trustworthy when they say yes and **untrustworthy when they say no**: a
model can read a file without ever naming it, with `cat data/*.csv` or a glob in
Python. So use them to confirm a file *was* used, never to prove one was
ignored.

There is also no way to measure how much of a file was read. The transcript
records the command, not the reading. If you want to check that the model was
not dragged into a huge distractor file, write that as a rubric -- the judge
reads the same transcript and can weigh it properly.

## The one rule that matters

**A check that passes before the model runs is testing nothing.** It would pass
for a model that did absolutely nothing.

`/flc-check-tests` runs your checks against the task in its untouched state and
tells you if any of them pass there. It is meant to report that most of your
checks fail -- that is the correct result, because they are waiting on work the
model has not done yet.

## Then

```
/flc-check-tests
```

That runs everything, and refreshes `tests/test_weights.md` so any test you have
just written has a line in it. Once you are only changing weights, this does the
same without rebuilding anything:

```
/flc-check-tests --weights-only
```

Next: [07-grade.md](07-grade.md)
