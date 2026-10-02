---
description: Start here - a two-question hello, then the first guide and where you are
---

The first thing a contributor types. Three things, briefly.

**1. Ask how they want to be spoken to**, unless a preference is already
recorded in the section of `CLAUDE.md` that says so. One short message, two
questions:

- What is your background, in a sentence?
- How technical should I be: plain language, some technical terms, or fully
  technical?

Record the answer in their own words, and "skip" or no answer as `plain`:

```bash
python3 ~/flc/bin/contributor_style.py set --background "..." --level plain
```

From then on, keep to it in every reply. They can change it at any time by
saying so; record it again when they do.

**2. Point them at the first guide**, `~/flc/contributor_instructions/00-start-here.md`,
and say in a sentence that it is the procedure, in order, and that each step
ends with a command that checks their work.

**3. Say where they are:**

```bash
python3 ~/flc/bin/status.py
```

Read it and tell them the one next step. Do not walk through the rest of the
output.

If the sandbox itself looks broken -- the commands missing, a script that will
not run -- follow *A technical issue on our side never stops them* in the skill.
