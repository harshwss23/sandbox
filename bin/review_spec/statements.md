### Statements that something in the task is inaccurate

An inaccuracy is a statement in the task's material that the material itself, or a check anyone can rerun, shows is wrong. It is any of:

- a wrong value: a figure, count, unit or threshold the material or a recomputation contradicts;
- a wrong statement: a statement of fact that does not hold;
- a misattribution: a real value or quote attached to the wrong quantity, source, file or condition;
- a wrong reference: a section, table, file, run or identifier that does not say or hold what is claimed;
- a contradiction: a statement that conflicts with itself, the prompt, the workspace, the ground truth, the rubric or the tests;
- a misleading or overstated claim: "only", "none", "every", "rules out" or "cannot" where the material shows otherwise;
- wrong reasoning: a stated cause or mechanism that does not hold, even where the conclusion does.

The author's answer is one of the files you check, not the reference you check against: a statement is not accurate because the ground truth says the same, and where the justification, a criterion or a test repeats a statement of the ground truth, check the ground truth's statement as well.

**The bar.** File an inaccuracy only when all three hold: a check anyone can rerun settles it -- a calculation with its numbers, a value in a named file, a condition a document in the task states; you are highly confident of it; and something graded rests on it, or it is in the ground truth. Anything short of that is a doubt: write it in `notes`, naming the statement and your doubt, where it is printed unscored. Erring toward reporting does not reach this: an inaccuracy says the author got something wrong, and it is filed only once you have settled it.

`bears_on` is required on a statement in the ground truth, and it decides whether the task has to change before it is delivered, so it lists only what repeats the statement or depends on its being true: a criterion or a test that uses the wrong value, the justification restating it. Where the graded material states something else, or does not use the statement at all, nothing rests on it and `bears_on` is `[]`. It holds names and quotes, never a note about why.
