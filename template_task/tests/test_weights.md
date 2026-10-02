<!--
What each of your unit tests is worth. Generated from tests/verifier.py --
/flc-check-tests adds a line for every new test at [3], and never changes a
number you have set.

You edit the numbers. Nothing else on these lines is yours: the name comes from
the test and the note after the # is its first docstring line, both rewritten
each time this is refreshed.

    5   the test that would let a wrong answer through unnoticed
        a value that has to be right, a file the model must not have altered,
        something private or excluded that must not appear

    3   the test that says the work was done
        a file exists, has the right structure, the right keys, the right
        number of rows, the right order

    1   the test that tidies
        a filename spelling, a header or column format, a file that parses, a
        size or length bound, no leftover scratch files

Those three are the only weights. Read what the test asserts rather than what
it is called, weight anything your prompt asked for explicitly at 5, and when
you cannot decide between two, take the higher.

A test's points count towards the model's score exactly as a rubric criterion's
do, so this is the same scale as tests/rubrics.md. Four tests at 3 outweigh one
at 5: write the checks that matter rather than a long tail of easy ones.
-->

- [3] test_prediction_file_exists  # The model was asked to leave its answer in a file.
- [3] test_evidence_has_required_fields  # A JSON file the model produced has the fields it should.
- [3] test_it_consulted_the_manifest  # Confirm a file the task depends on was actually opened.
- [5] test_reported_median_matches_the_data  # Recompute the number instead of believing the model's version of it.
