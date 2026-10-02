---
description: Turn unit tests back on after skipping them
---

Turn unit tests back on:

```bash
python3 ~/flc/bin/task_config.py enable-tests
```

A suite that `/flc-skip-tests` set aside comes back under its own name. If there
is none, this starts from the template.

Then open `~/flc/task/tests/verifier.py`. It has worked examples at the top and
the `flc_testkit` helpers for reading the model's finished workspace without
having to handle missing files by hand.

These are pytest tests. Write each one as a function whose name starts with
`test_`, with a plain `assert` and a message saying what was expected. No
parametrized tests -- `/flc-check-tests` refuses them.

When they are written, run `/flc-check-tests`. It runs them and adds each one to
`tests/test_weights.md`, where a test is weighted 5, 3 or 1 the way a rubric
criterion is.
