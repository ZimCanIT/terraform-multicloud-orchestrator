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
| `gate-pass.json` | Gate suite, run with `--model` | Four cases that pass, including two attempts that hit the turn limit and still passed. `suite.modelOverride` differs from the `model` the cases carry. |
| `gate-mixed.json` | Gate suite, run with `--model` | A guardrail that failed once, a capability case that passed two attempts in three, one that passed one in three, and a grader that threw on an invalid regular expression. |
| `authoring-single.json` | Authoring suite, run with `--model`, one attempt per case | A failed LLM-judged grader and a failed advisory grader. |
| `cost-ceiling-partial.json` | Gate suite, run with `--max-cost-usd 0.03` and no `--model` | A run stopped by the cost ceiling. The one attempt that ran has its judged grader reported as failed with the text `skipped: cost ceiling`, and `skippedPaidGraders` is true. |

`--model` replaces the model of every case, so `suite.modelOverride` is the model the agent ran on
when it is present, and the classifier records it as such (`models.agent`). Without it, the models
the cases carry are the agent models. The cases have changed since these runs: the cases in
`gate-pass.json` and `gate-mixed.json` carry another model than the cases pin now, and their
trigger probes have three turns where the cases now have two. The fixtures keep what the runner
recorded.
