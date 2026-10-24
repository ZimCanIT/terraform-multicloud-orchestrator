# Eval result fixtures

Trimmed copies of real `claude plugin eval` results (`aggregate-result.json`, schema
version 1) for `tests/test_classify_eval_run.py`. The runs used Claude Code 2.1.310
(`cost-ceiling-partial.json`: 2.1.308) on 24 October 2026.

What was changed from the originals: the model replies (`evidence`), the prompt text
and the judge criteria were removed, trace paths were replaced with placeholders and
the plugin paths were made relative. In `gate-pass.json`, `gate-mixed.json` and
`authoring-single.json`, cases were also dropped to keep the files small, so the run
totals (`costUsd` and `aggregates`) were recomputed from the cases that remain, the way
the runner computes them for a full result: `costUsd` sums the agent cost of every
attempt, and `casesPassed` counts the cases whose attempts all passed. In
`authoring-single.json` one grader was renamed with the `advisory-` prefix, as the
checked-in case now names it. `cost-ceiling-partial.json` keeps every case the run
reached. Nothing else was edited.

| File | Run | What it shows |
| --- | --- | --- |
| `gate-pass.json` | Gate suite, on the model the cases pin | Four cases that pass, including two attempts that hit the turn limit and still passed. |
| `gate-mixed.json` | Gate suite, with `--model` set to a smaller model than the cases pin | A guardrail that failed once, a capability case that passed two attempts in three, one that passed one in three, and a grader that threw on an invalid regular expression. |
| `authoring-single.json` | Authoring suite, on the model the cases pin, one attempt per case | A failed LLM-judged grader and a failed advisory grader. |
| `cost-ceiling-partial.json` | Gate suite, a $0.03 ceiling | A run stopped by the cost ceiling. The one attempt that ran has its judged grader reported as failed with the text `skipped: cost ceiling`, and `skippedPaidGraders` is true. |
