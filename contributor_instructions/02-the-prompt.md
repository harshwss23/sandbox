# Step 2: the question

Write it in `~/flc/task/prompt.md`. Delete everything already in there.

## Write it as a message, not a specification

You are writing to a capable colleague who has the same folder and no other
context. That is all.

Good:

> We ran the differential expression analysis back in March and I need to know
> which gene came out strongest once multiple testing is accounted for. Can you
> dig through what's there and tell me, with the numbers behind it?

Bad:

> ## Task
> 1. Load `data/counts_matrix_final.csv`
> 2. Filter for padj < 0.05
> 3. Report the gene with the lowest adjusted p-value
> 4. Output your answer as JSON

The second one is a specification. It names the file, gives the method, and
sets the threshold -- so it tests whether the model can follow instructions,
which we already know it can. Everything hard about the task has been solved in
the prompt.

## Do not name your files

The prompt should describe **what you want to know**, never **where to look**.
Working out which of forty files matters is a large part of what is being
measured, and one filename hands it over.

The check in step 2 warns you about this.

## Be specific about the answer, vague about the route

Every part of the question you expect answered needs one defensible answer, or
you cannot grade it. But how to get there should be for the model to work out.

- "which gene came out strongest after multiple testing" -- one answer, route
  not given
- "tell me about the expression results" -- no answer to grade
- "run DESeq2 with the default parameters and report the top row" -- no work
  left

## The model can look things up, and you should expect it to

It has the internet while it works. That is deliberate, and a question that
needs something looked up is a better question rather than a spoiled one -- a
colleague handed your folder would check what the convention is for this
instrument, or how a method is normally parameterised, before touching your
data. Write yours the same way.

What matters is not whether the model can search. It is whether searching can
produce the **answer**:

- fine: the method is public, the threshold is in a standard, the numbers are
  yours and have to be worked out from your files
- not fine: the figure you are asking for is printed in the paper your dataset
  came from, or on the database page for the accession you are asking about

The first is a task. The second is not made into one by hoping the model does
not think to look -- and it is what step 4's block list is for, since one
particular page is easier to keep out of reach than the whole internet.

None of this goes into your grading criteria. A criterion says what the answer
got right, never where the model went to get it; step 5 says why.

## Leaving something out, on purpose

The rule above is about accidental vagueness. **Deliberate** vagueness is a
different thing and we want some of it.

A real colleague's message often leaves out something they did not realise you
needed: which of two batches they meant, which threshold their team uses, which
of three people's spreadsheets is the current one. A good colleague notices the
gap and asks. A model under pressure to be helpful usually picks one, does not
mention that it picked, and reports the result as if it were the only one.

That is a hallucination worth catching, so if your material gives you a natural
gap, use it:

> We ran the analysis back in March and I need to know which gene came out
> strongest. Can you dig through what's there and tell me, with the numbers?

If the folder holds a March run and a March re-run under a corrected sample
sheet, the model cannot know which you meant. The behaviour you want is that it
says so and asks -- while still doing the part it *can* do.

Three things make this work rather than just being a bad prompt:

- **The gap has to be real and visible in the files.** Something a careful
  reader would actually notice and be stopped by, not a detail you left out that
  nobody would miss.
- **Something must still be answerable.** A question where nothing can be done
  until you reply is not a task. There should be work the model can complete,
  and one thing it has to come back on.
- **You have to be able to say what the right question is.** You will write a
  criterion for it, so you need to know what you would accept: "asks which of
  the two March runs to use" is checkable, "asks a sensible question" is not.

Step 3 has a place to write the gap down, and step 5 has the criteria for it. If
you do this, say so when you get there.

## It has to be a question only someone in your field could pin down

This is the one thing here that can stop a task, so it is worth getting right
before you go further.

Ask yourself: could a smart person from outside your field -- good general
education, a search engine, no training in what you do -- work out what you are
asking and what a right answer would have to establish? If they could, the model
can too, and there is nothing here for us to catch. We are collecting the cases
where a model answers confidently and *wrongly*. That only happens where telling
right from wrong takes an expert.

Unfamiliar words are not enough. Anyone can look up what a plasmid is. What
counts is whether the things you name have to be understood *in relation to each
other* before the question means anything -- why these controls, why this
comparison, what follows from them.

What tends to clear it:

- your own data, figures or instrument output, rather than a public dataset
- a judgement between two readings of the same evidence that both look reasonable
- something you would take for granted that an outsider would not know to apply

What does not: longer sentences, more jargon, or more background. Padding the
prompt does not make the task harder, and it is obvious when it has been done.

Run this to find out where yours sits:

```
/flc-prompt-check
```

It reads your prompt, and tells you whether it clears and why. It takes about a
minute. If it says the prompt is not hard enough, it explains what it understood
you to be asking, which is usually where you can see the problem. Edit
`prompt.md` and run it again.

If it says it could not check the prompt, that is our tool failing rather than
anything about your task -- it happens on ordinary biological and clinical
prompts. Try once more, then carry on regardless.

## Length

Two to five sentences is usually right. Long enough to say what you want and why
you want it, short enough that it is not a checklist.

## What the criteria will be made of

Worth knowing while you pick the question: a task needs at least 20 grading
criteria, and they come from the question and the run. A rubric is made of
these parts:

- **Required, and the most important part:**
  - **An outcome criterion for every ask in your prompt**: each figure,
    conclusion or identification it asks for.
  - **At least five hallucination criteria**: the ways an answer goes wrong on
    your material, of any kind -- a figure nothing supports, the material that
    settles it left unread, a wrong inference from the right material.
- **Required when your task is underspecified: clarification criteria.**
- **Optional, for depth: a few lines about hard steps** every correct route
  takes -- identifying the superseded version, reconciling two sources that
  disagree -- and never an easy one like opening a file.

For example, for the worked example's March 2024 HepG2 series, analysed under
its SOP-DE-004:

```markdown
- [5] Response states that 217 genes are differentially expressed under SOP-DE-004.
- [-5] Response reports a count of differentially expressed genes that no step of its own analysis produced.
- [3] Trajectory shows the agent removing the libraries with a RIN below 7.0 before applying the expression filter.
```

This is for choosing the question, not a reason to change it. No list of
deliverables is needed: the prompt's own asks, the hallucination criteria and a
few trajectory lines reach 20, and a prompt that lists deliverables reads as the
specification the first section warns against.

## Then

Run:

```
/flc-check-inputs
```

It will ask you which files are actually needed to answer the question, which is
what tells it whether the task has any triage in it, and then check the prompt.
It reads the result of `/flc-prompt-check`, so run that one first.

Next: [03-ground-truth.md](03-ground-truth.md)
