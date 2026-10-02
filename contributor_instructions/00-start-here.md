# Start here

You are going to build one research task: a folder of real files, a question
about them, and the criteria for judging an answer. An AI research agent will
then attempt it, and we will find out where it goes wrong.

You need to be an expert in your own field. You do not need to be a programmer.

## What makes a task worth building

We are not looking for questions that are hard because they are obscure. We are
looking for questions where a capable model can produce an answer that reads
perfectly and is wrong.

That happens when the model has to work through a lot of material and can take a
shortcut somewhere: read the wrong file, misread a column, assume a convention
that does not hold here, or quietly fill a gap with something plausible.

So the best tasks look like real work. A folder as it actually exists on
someone's machine -- current files and old ones, notes, a couple of things that
turned out not to matter -- and a question you would really ask about it. Real
messages also leave things out, and a question that does not quite say which
batch you meant is a fair thing to send: step 2 covers when that is worth doing.

A task where every file matters and the answer is on page one is not measuring
anything.

## The task has to defeat the model

This is the part that surprises people, so it is worth saying at the start
rather than at the grading step.

**A task the model gets right is not delivered.** The measured score has to come
in under 50%, and that is checked before anything can be packaged.

We are not measuring how often models go wrong. We are collecting the cases
where they do, so the patterns behind them can be studied. A run where the model
sailed through leaves a transcript with nothing in it -- no mistake to look at,
nothing to learn. The work that went into the task is not what makes it
valuable; the mistake it provokes is.

So when the model does well, the task is not finished. Expect to strengthen a
task at least once, and treat that as the normal course of the job rather than a
setback.

## Runs and checks cost money

Running the model, grading, and several of the checks use paid models, and your
sandbox has a fixed budget for the whole task. If it runs out, nothing more can
run and you can't finish. The budget is generous: used with care, you won't
come near it. What wastes it is running something again without a meaningful
change, hoping for a different result. Change something first (the prompt, a
file, a criterion), then run it again.

## It also has to be big enough to grade properly

**Your task needs at least 20 checks.** Grading criteria and automated checks
count together towards that. It is enforced before the model's answer can be
scored, and again before the task can be packaged.

Worth knowing now rather than at step 5, because it is a fact about the task
rather than about the criteria. If your question has one short answer and
nothing behind it, no amount of careful writing at step 5 will reach 20 -- and
padding it out with near-duplicates makes a worse task, not a longer one.

A rubric is made of these parts:

- **Required, and the most important part:**
  - **An outcome criterion for every ask in your prompt.** Each figure,
    conclusion or identification the prompt asks for has its line, and none
    may be missing:

    ```markdown
    - [5] Response states that 217 genes are differentially expressed under SOP-DE-004.
    ```

  - **At least five hallucination criteria.** Each is a way the answer goes
    wrong, of any kind, not only a false claim: answering without the
    material that settles it, a wrong inference from the right material, a
    figure nothing supports:

    ```markdown
    - [-5] Response reports a count of differentially expressed genes that no step of its own analysis produced.
    ```

- **Required when your task is underspecified: clarification criteria.** Step
  5 has them, under *Clarification criteria* in [05-rubrics.md](05-rubrics.md).
- **Optional, for depth: a few lines about what the model should do**, and
  they have to be hard to pass:

  ```markdown
  - [3] Trajectory shows the agent removing the libraries with a RIN below 7.0 before applying the expression filter.
  ```

The way tasks reach 20 naturally is that the checks cover the **route** and
not only the destination. A good answer had to work out an intermediate figure
before it could work out the final one, reconcile two files that disagree, and
follow a step in your procedure that the material only states once. Each of
those is something an answer cannot skip and still be right, so each is a fair
thing to check -- and when the model does go wrong, they are what tell you
*where*. A step every run takes anyway, like opening a file, is not one of them:
a line about the route has to be hard to pass, and a step every correct route
takes.

No list of deliverables is needed to get to 20. Your prompt's own asks, the
hallucination criteria and a few of these lines get there, and automated
checks, where you write them, count towards it alongside them.

So when you are picking a question at step 2, pick one with some distance in
it. That is the same property that makes a task hard, so this is not a second
demand on top of the last section; it is the same demand, counted.

## The model has the internet, and that cuts both ways

It browses while it works, and that is on purpose: a question that needs a
standard looked up or a convention checked is a better question, and step 2
says to write yours expecting it.

The thing it must not be able to do is **read your answer off a page** instead
of working it out from your files. Your task starts with a block list for your
field -- Wikipedia, plus the reference databases that would hand over an answer
outright -- and step 4 asks you to add the one page that would spoil your own
task before you spend a run. That order matters: a run where the model looked
the answer up is a run to throw away.

`/flc-status` prints what is currently blocked, at any time.

## A few words you will see

| | |
|-|-|
| **the run** | one attempt at your task by the AI, start to finish |
| **transcript** | the record of that attempt -- everything the model thought, ran and saw |
| **token** | the unit a model reads in, each one about three quarters of a word |
| **workspace** | your folder of files, as the model sees it |
| **the judge** | the model that scores an answer against your criteria |

## What you will do

Eight steps. Each one is a command you type into Claude Code, which will run the
checks, explain what it finds, and tell you what to fix.

| | Command | What you do |
|-|---------|-------------|
| 1 | `/flc-unpack` | upload a zip of your files and unpack it |
| 2 | `/flc-prompt-check` | write the question, check it is hard enough |
| | `/flc-check-inputs` | check your files and the question together |
| 3 | `/flc-ground-truth` | write down the correct answer and how it is reached, before the model runs |
| | `/flc-check-justification` | once a run shows the task holds: finish the ground truth, why it is the only answer and three short labels, and check them |
| 4 | `/flc-block-domain` | keep the model off the pages that would hand over your answer |
| | `/flc-run-solver` | start the model working on your task |
| 5 | `/flc-rubrics` | write the grading criteria while it runs, then check them |
| | `/flc-inspect` | when the run lands, read it before the second half |
| | `/flc-check-rubric` | check the criteria against your task, not just their wording |
| 6 | `/flc-check-tests` | write automated checks, or `/flc-skip-tests` |
| 7 | `/flc-grade` | see how it performed |
| | `/flc-check-grade` | check the judge read your criteria the way you meant, then the last two labels |
| 8 | `/flc-deliver` | package it up |

A row with no number belongs to the step above it.

Step 3 is split around the first run. The answer goes on record before the
model is seen; the rest waits until a run shows the task holds, so an
afternoon of polish is not spent on a prompt the model solves at once. A task
gets five counted runs, so make each one change something.

`/flc-deliver` is the last step. `/flc-submit` used to be one and is not any
more: the same check runs by itself when you finish the task, so the folder
that gets collected carries the record whether or not you asked for it. Run it
yourself if you want to know now rather than at the end.

The run comes before the criteria on purpose. It takes a while and runs in the
background, so you write the criteria for a right answer while you wait -- and
the hallucination criteria can only be written once you have seen what the
model actually did. That is what `/flc-inspect` is for: it reads the finished
run and lists the claims worth checking, so you write that second half against
what the model really did rather than from memory.

## The other commands

| Command | When |
|---------|------|
| `/flc-start` | the very first thing: two quick questions about how you want Claude Code to talk to you |
| `/flc-view` | see the run itself, as a page you can open in your browser |
| `/flc-add-package` | the model needs software that is not installed |
| `/flc-restore-tools` | a step says the sandbox's own scripts have been changed |
| `/flc-submit` | check that nothing moved after you packaged |
| `/flc-status` | where am I |
| `/flc-help` | anything else |

## The files you write

Everything else is generated for you. You never need to touch a config file, a
Dockerfile, or anything ending in `.toml` or `.json` -- if one of those looks
wrong, flag it to the project team rather than editing it.

| File | What goes in it |
|------|-----------------|
| `environment/workspace/` | your files |
| `prompt.md` | the question, in your own words |
| `solution/ground_truth.md` | the correct answer in text |
| `solution/underspecification_justification.md` | why that answer is the only one an expert could reach |
| `solution/labels.md` | short answers about the task and the run, in the spellings it lists |
| `tests/rubrics.md` | the criteria for judging an answer |
| `tests/verifier.py` | automated checks (optional) |
| `tests/test_weights.md` | what each of those checks is worth -- generated, you change the numbers |
