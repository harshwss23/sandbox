<!--
This file is your rubric list. Each line is one thing you will check the
model's answer, or what it did, for. Delete these instructions and the
examples below, then write your own.

FORMAT -- one criterion per line, starting with "- " and a weight:

  - [5] Response states that 217 genes are differentially expressed under SOP-DE-004.

The number is how much the line is worth. The sign says which way it counts:

  [5] [3] [1]     something the answer SHOULD do.
                  5 = the answer is wrong without it
                  3 = it matters
                  1 = a detail worth a point

  [-5] [-3] [-1]  something the answer SHOULD NOT do. Write the bad thing
                  itself. Nothing is earned by avoiding it -- doing it takes
                  those points off what the answer earned elsewhere.
                  -5 = this alone ruins the answer

Those six are the only weights. Nothing else is accepted. Everything your
prompt asks for by name is a 5.

WORDING -- a line about what the answer says starts with the word "Response"
and a present-tense verb: "Response reports ...", "Response identifies ...",
"Response claims ...". A line about what the agent did names its trajectory
or the agent, whichever reads naturally: "Trajectory shows the agent ...",
"The agent's trajectory shows ...", "The agent ...", "In its trajectory, the
agent ...":

  - [3] Trajectory shows the agent removing the libraries with a RIN below 7.0 before applying the expression filter.

Not "The answer reports", not "The model reports", and not "Reports" with the
subject left off. Each of those reads fine on its own; a rubric with all of
them in it reads like several people wrote it. A [state] line is the
exception -- its subject is the file, as below.

Keep the three headings below. Put each criterion under the right one:

  ## Completion         did the model actually do the job?
  ## Clarification      only if solution/labels.md says your task is
                        underspecified. Did the model ask, instead of
                        quietly deciding for itself? Most tasks have none.
  ## Non-hallucination  did the model go wrong -- claim something nothing
                        supports, answer without the material that settles
                        it, or reason its way to a wrong conclusion?

Which heading a line goes under is decided by what it is about, not by its
weight. A made-up figure is a hallucination wherever it turns up. A question
the model should have asked is a clarification whether you write it as
something it did (positive) or something it failed to do (negative).

WHERE IS IT CHECKED? Most criteria are about what the model SAID, and those
need nothing extra. If yours is about what the model CHANGED in the workspace
-- a file it wrote, a table it saved -- add [state] after the weight. When your
prompt asks for the file, its copy of a value is weighted like the value, and
never below 3. This pair is written as if the prompt asked for the file:

  - [5] Response states that 217 genes are differentially expressed under SOP-DE-004.
  - [5] [state] results/de_summary.csv reports 217 differentially expressed genes.

YOU FILL THESE IN AT TWO DIFFERENT MOMENTS.

  Completion        while the solver is running. Everything in these comes
                    from your ground truth, so they need nothing from the run.

  Non-hallucination after it finishes, with the run in front of you. You
                    cannot guess how a model will go wrong -- you read what
                    it actually did and write a line for each mistake,
                    worded as the mistake any run could make rather than in
                    this run's own words:

  - [-5] Response reports a count of differentially expressed genes that no step of its own analysis produced.

                    `/flc-rubrics` prints the answer for you, and
                    `/flc-inspect` walks you through the run.

                    Five of these, and grading refuses fewer. The run is
                    where they come from: every claim no file supports,
                    every citation to a file for something it does not say,
                    every check it says it ran and did not, every file it
                    had to read and never opened.

                    Up to two of them may instead be a failure this run did
                    NOT commit -- and if all five fired, better. Not guesses: a
                    wrong turn your own material makes attractive and this
                    model happened to avoid, such as a filename that misleads
                    about its contents, a default setting that is wrong here,
                    or a figure the data invites and does not support. Weigh
                    them by the same buckets as every other line. `/flc-grade`
                    counts them for
                    you: it says how many of your negative lines never fired,
                    and tells you when more than two did not.

FIVE RULES. `/flc-rubrics` checks these and will tell you which line broke
which rule.

  1. One claim per line. If your line has an "and" joining two checkable
     things, split it into two -- a line carrying four claims pays all four
     points or none, so a model that got three right collects nothing. A list
     is a list of claims: naming three excluded samples is three lines, and so
     is giving three values for three samples. The test is not whether the
     parts share a topic but whether a response could satisfy one and fail
     another. One claim is still not one word: an item named together with the
     property that identifies it is a single claim.
  2. A person with no other context must be able to judge it. Never write
     "as described above" or "the correct value" -- write the value. The same
     goes for counting instead of naming: "the second construct" means nothing
     to someone shown that line alone, so write which construct it is.
  3. It has to be checkable from evidence. The judge sees the answer, the
     files the model produced, and a transcript of what it did -- so
     "analysis/results.csv lists PTEN in its first row" is a fine criterion.
     "The model used a sensible method" is not: that is an opinion.
     It is never shown a web page either. The model has the internet and
     looking things up is part of the job, but a criterion is the fact it
     ended up with, not the trip it made: "gives the threshold as 7.0", not
     "looks up the threshold". A NEGATIVE line about a source it made up is
     the opposite case and is exactly what you want.
  4. Do not restate the prompt. "Analyses the data" is not a criterion.
  5. You need five hallucination criteria: lines under Non-hallucination that
     describe a way the answer or the trajectory goes wrong. A positive line
     under that heading is a fine criterion and does not count towards the
     five. Not required while the run is still going -- required before you
     can grade.

TWO THINGS `/flc-rubrics` CANNOT CHECK FOR YOU, and both cost more than the
five above, because they turn on your material rather than on your words.

  A line has to accept every answer that is right. If your ground truth says
  five samples are equally good evidence of the same point, or that either
  convention is correct when the answer says which, the line has to allow
  that. A criterion that fails a model for being right puts a failure into
  the record that never happened, which is worse than missing one: err
  generous, because a loose line costs you one criterion. Backwards, the same
  rule -- if you list what you will accept, give the list edges. "7.0,
  another value from the QC log, or the SOP's" accepts 3.0 as readily as 7.0.

  A line has to read one way to someone holding your workspace and not your
  intentions. The four that catch people out: a word your material gives two
  candidates for ("our recovery", where there are two recoveries), a
  comparison with no basis ("the widest interval" -- in the units printed, or
  relative to its own mean?), a phrase whose scope is open ("right as it
  stands" -- the number, or how it is being used?), and a figure in brackets
  that your own method does not produce.

HOW MANY LINES. At least 20 checks in total, and grading refuses below that.
A rubric is made of these parts:

  REQUIRED, AND THE MOST IMPORTANT PART
    - An outcome line for every ask in your prompt: each figure, conclusion
      or identification it asks for, and none missing.
    - At least five hallucination criteria, of any kind: a claim nothing
      supports, a file it never read, a wrong inference from the right
      material, sources that do not belong together, a conflict settled
      without saying so.

  REQUIRED WHEN labels.md SAYS THE TASK IS UNDERSPECIFIED
    - Clarification criteria, below.

  OPTIONAL, FOR DEPTH
    - A few lines about the trajectory, each a hard step every correct route
      takes: identifying the superseded version, reconciling two sources that
      disagree, noticing a unit change. Never an easy one like opening a file.

No list of deliverables is needed to reach 20: your prompt's own asks, the
hallucination criteria and a few trajectory lines get there.

What does not count is padding. Two lines measuring the same thing score a
single mistake twice, and splitting one fact across three lines is the same
problem wearing a disguise. If your task cannot reach 20 honestly, that is
worth knowing: it usually means there is not enough in the folder for the
model to get lost in.

Two passes find nearly everything you left out, and the second is the one
people skip: once down your ground truth, asking what it asserts that no line
of yours checks, and once down your own prompt, sentence by sentence, asking
of every thing it asks for which line of yours checks it. A prompt asking for
three numbers, with a rubric careful about one of them, has left two of them
ungraded -- and an answer that omits both loses nothing.

WHEN THE ANSWER IS A LIST OF SIMILAR THINGS -- a row per sample, a call per
case -- do not write a line per row. Up to five spot checks, plus one line
about the extent of the group, and you need both halves:

  - [5] [state] results.csv gives a call for all twelve libraries
  - [3] [state] results.csv reports S07 as excluded at a RIN of 6.1

Without that first line, three rows of a twelve-row table earn every
criterion you wrote, and the nine missing rows cost nothing.

IF YOUR TASK IS UNDERSPECIFIED (labels.md says yes) -- most are not, skip
this -- add a Clarification heading with both halves under it: the question,
and the answer picked without saying so.

  ## Clarification
  - [5] Response asks which of the two March runs to use, or otherwise says
        it cannot tell which was intended
  - [-5] Response reports a top gene from one of the two March runs without
         saying which run it used

Name the question you would accept. "Asks a clarifying question" cannot be
scored, and neither can "does not ask". On a task marked not underspecified,
a Clarification line is refused: if the model could work it out from your
material, the line belongs under Completion.
-->

## Completion

- [5] Response identifies Pten as the knocked-out gene
- [3] Response reports the median KO count for Pten as 74
- [3] Response reports the median WT count for Pten as 812
- [3] Response states that Pten is lower in KO than in WT
- [3] [state] analysis/results.csv lists Pten in its first row
- [1] Response bases the comparison on all six samples, KO1 to KO3 and WT1 to WT3

## Non-hallucination

- [3] Response reports count values that match the source count files
- [-5] Response claims to have run a statistical test it did not run
- [-5] Response cites the archived zebrafish analysis as evidence for the conclusion
- [-3] Response states a p-value or fold-change that does not appear anywhere in its own output
- [-3] Response reports a median count for a sample that is absent from the count files
- [-3] Response treats the archived zebrafish run as the current mouse one
