---
description: Step 4 - stop the solver reaching a website
---

Block a site the solver should not be able to reach: $ARGUMENTS

```bash
python3 ~/flc/bin/task_config.py block-domain DOMAIN
```

The task already starts with a list for its domain -- Wikipedia everywhere, plus
the reference databases that would hand over an answer in this field. This
command adds to that list. Show them what is already blocked before they add
anything:

```bash
python3 ~/flc/bin/status.py
```

Its `blocked` line is the readable form. `task_config.py show` prints the whole
state as JSON if you need the exact list.

This is the counterpart to the model having the internet, which it does on
purpose: browsing is part of doing the job, and a question that needs something
looked up is a better question. What the list protects is the difference
between looking something up and looking the *answer* up.

A URL is fine -- it is reduced to the domain, and the `www.` form is covered
either way.

Use this when a public source would hand the model the answer directly: the
paper the dataset came from, a database page for the exact accession, a public
copy of the file. The point of the task is deriving the answer from the files,
not looking it up.

Be honest about what it is: name-level blocking, so a solver that dials a raw IP
address is not stopped. It is a guard against the model wandering onto the page
that gives the answer away, not a security boundary. If the answer is trivially
findable across the whole internet, blocking one domain will not save the task
-- the question probably needs to be more specific to their data.

To undo -- including removing one of the starting blocks, which is a normal
thing to want. A task whose material genuinely needs a blocked site (pulling
model weights from Hugging Face, reading a filing from SEC EDGAR) should unblock
it rather than work around it:

```bash
python3 ~/flc/bin/task_config.py unblock-domain DOMAIN
```
