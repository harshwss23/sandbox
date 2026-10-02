---
description: Step 2 - check whether the prompt is hard enough for the task to be worth building
---

Check how hard this task's prompt is.

```bash
python3 ~/flc/bin/prompt_check.py
```

It reads `prompt.md`, asks a model a few times how hard the request is, and
records the answer. `/flc-check-inputs` reads what it recorded, so run this
before that step.

Show them the output as it comes back. It takes about a minute.

This uses budget. Run it again after a change to the prompt, not in the hope
of a different reading of the same one.

## What it is measuring

One thing: whether someone who is *not* in their field could work out what the
prompt is asking, and what would count as having answered it. Not whether the
words are unfamiliar -- anyone can look a term up. Whether the terms have to be
understood in relation to each other before the request means anything.

That is the bar because of what the task is for. We are collecting cases where
a model answers confidently and wrongly. If an outsider could tell what a right
answer looks like, the model can too, and there is nothing here to catch.

It also reports a level from 1 to 6, whether an outsider could spot a wrong
answer, and what makes the task hard -- reading the contributor's own data,
conventions the prompt leaves unstated, a specialised literature, the sheer
amount of material, something needed that was never supplied, or nothing
field-specific. None of these decide anything on their own. The last is worth
reading aloud to them even on a PASS: two prompts often land on the same level
for quite different reasons, and it is the one line that says which reason
theirs is.

## What to do with each result

**PASS or WARN** -- it clears the bar. Move on to `/flc-check-inputs`. A WARN
means the work sits at the bar rather than above it, which is fine and worth
mentioning, but not on its own a reason to rework the prompt.

**FAIL** -- the prompt is not hard enough yet, and `/flc-check-inputs` will not
pass until it is. Read them the reasoning: it says what the check understood
the prompt to be asking, which is usually where the problem shows. What moves a
prompt up is asking for something only a practitioner could pin down:

- their own data, figures or instrument output rather than a public dataset
- a judgement between readings of the same evidence that look equally reasonable
- a convention, control or caveat they would take for granted and an outsider
  would not know to apply

What does *not* move it up is harder vocabulary or a longer prompt. Do not
suggest padding it. Offer to work through the prompt with them.

Underspecification is not the same thing and is not the problem here -- a
prompt that deliberately leaves something out for the model to ask about is a
legitimate design, and this check ignores that entirely.

**NOT MEASURED** -- our check failed, not their task. Run it once more
yourself; if it still cannot measure, say the one
sentence in *A technical issue on our side* in the skill and move on.
`/flc-check-inputs` lets the task through when this could not measure it, and
it is recorded for the project team. Do not explain the cause unless they ask.

## Once, after the result

Mention what the criteria will be made of, once, in a sentence or two: at
least 20, of which an outcome line for every ask in the prompt and at least
five hallucination criteria are the required and most important part;
clarification criteria when the task is underspecified; and, optionally, a few
lines about hard steps every correct route takes. It is information for the
question they are writing, not a reason to change it. Do not push a change to
the question on the strength of it, and never suggest adding deliverables.
Step 2's guide says the same under *What the criteria will be made of*.

## If they ask why the model gets a say

It does not get the final say -- it is one reading of the prompt, taken three
times, and the check reports when the three disagree. What it is good at is
noticing when someone outside the field could work out what a prompt asks and
what would count as answering it, which is hard to see from the inside because
everything in it looks obvious.
