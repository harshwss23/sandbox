"""Your unit tests.

WRITE TESTS HERE WHEN YOUR PROMPT ASKS FOR A FILE WITH A FIXED SHAPE.
A JSON file with named keys, a CSV with named columns -- anything where you
said what goes where. The values in that file belong here and not in your
rubric. A criterion checking one is a language model eyeballing a number that
`assert got == 1184` settles exactly, in a second, for nothing. A rubric of
thirty such lines is the shape to watch for; it has happened, and it had to be
rewritten.

A number stated in the answer's PROSE is the exception and stays a criterion.
The model may write 1.2e-5 or 0.000012 and both are right, which the judge
handles and a text match does not.

If your task asks the model to tell you something rather than to build
something, or if you do not write Python, run /flc-skip-tests and move on --
this file is then left out of the delivery entirely. Nothing is lost by it.

HOW IT WORKS
------------
These are pytest tests. Write functions whose names start with `test_`. Use
`assert`. That is all. A function that raises is a failing test; one that
returns is a passing test.

    def test_prediction_file_exists():
        assert (WORKSPACE / "analysis" / "prediction.txt").exists()

The message after the comma is what you will see when it fails, so write one:

    def test_prediction_names_pten():
        text = read_text("analysis/prediction.txt")
        assert "pten" in text.lower(), f"prediction.txt said: {text!r}"

WHAT EACH TEST IS WORTH
-----------------------
Every test carries a weight of 5, 3 or 1, the same scale as a rubric criterion,
and those points count towards the model's score exactly as the rubrics do.
The weights live in tests/test_weights.md, one line per test. /flc-check-tests
adds a line for every new test at 3, and you change the number.

    5   the test that would let a wrong answer through unnoticed: a value that
        has to be right, a file the model must not have altered, something
        private that must not appear
    3   the test that says the work was done: a file exists, has the right
        structure, the right number of rows, the right keys
    1   the test that tidies: a filename spelling, a header format, a size or
        length bound

PARAMETRIZED TESTS ARE NOT ALLOWED
----------------------------------
No `@pytest.mark.parametrize`, no `@pytest.fixture(params=...)`, no
`pytest_generate_tests`. /flc-check-tests refuses them. One test is one named
thing that is either true or false, and it carries one weight; a parametrized
test is several, under names that change whenever you edit the list. Write them
out separately -- if that feels repetitive, it is usually several weights'
worth of different facts wearing one name.

WHAT YOU CAN USE
----------------
    WORKSPACE          the model's finished folder, as a pathlib.Path
    ANSWER             the model's written answer, as a string
    read_text(rel)     read a file from the workspace as text
    read_json(rel)     read a file from the workspace as JSON
    source_json(rel)   read a file from the ORIGINAL inputs you uploaded,
                       so you can recompute a number instead of trusting
                       the one the model reported
    opened(rel)        did the model appear to open this file?
    ran(fragment)      did the model run a command containing this text?

Then run /flc-check-tests. It runs everything here and tells you what broke.

ABOUT opened() AND ran()
------------------------
Both search the transcript of what the model did. They are reliable when they
say yes and unreliable when they say no, because a model can read a file without
naming it (`cat data/*.csv`, a glob in Python, `find | xargs grep`).

    def test_it_consulted_the_manifest():
        assert opened("data/metadata.csv")          # good

    def test_it_ignored_the_big_file():
        assert not opened("counts_full.csv")        # BAD -- passes by accident

To check a file was ignored, or that the model spent its run on the wrong data,
write a rubric. The judge reads the same transcript and can weigh what the model
did against what it found. There is no way to measure how many bytes of a file
were read; the transcript records the command, not the reading.

THREE THINGS THAT DO NOT WORK
-----------------------------
  - Do not test the wording of the answer. That is what rubrics are for.
  - Do not require an exact string -- a filename, a key, a row label, a number
    format -- unless your prompt required it too. A prompt that gives one as an
    example leaves the model free to write it another way, and a check that
    insists on your spelling fails a model that was right. Those belong in the
    rubric, where the judge reads any spelling of them.
  - Do not hardcode a number you have not checked against your own data.

Delete the examples below before you write your own.
"""

from flc_testkit import (
    WORKSPACE, ANSWER, read_text, read_json, source_json, opened, ran,
)


# ---------------------------------------------------------------------------
# EXAMPLES -- delete these.
# ---------------------------------------------------------------------------

def test_prediction_file_exists():
    """The model was asked to leave its answer in a file."""
    assert (WORKSPACE / "analysis" / "prediction.txt").exists(), \
        "no analysis/prediction.txt in the finished workspace"


def test_evidence_has_required_fields():
    """A JSON file the model produced has the fields it should."""
    evidence = read_json("analysis/evidence.json")
    for field in ("prediction", "ko_median_raw", "wt_median_raw"):
        assert field in evidence, f"evidence.json is missing {field!r}"


def test_it_consulted_the_manifest():
    """Confirm a file the task depends on was actually opened.

    Only ever assert that a file WAS used. `assert not opened(...)` looks like
    the mirror image and is not one: it passes for a model that read the file
    under a name this cannot see.
    """
    assert opened("data/metadata.csv"), \
        "the model never opened the manifest it was told to start from"


def test_reported_median_matches_the_data():
    """Recompute the number instead of believing the model's version of it.

    This is the most valuable kind of test you can write: it catches an answer
    that is confidently stated and wrong.
    """
    evidence = read_json("analysis/evidence.json")
    counts = source_json("data/ko_counts.json")
    expected = sorted(counts.values())[len(counts) // 2]
    reported = evidence["ko_median_raw"]
    assert abs(reported - expected) <= 1, \
        f"model reported a KO median of {reported}, the data says {expected}"
