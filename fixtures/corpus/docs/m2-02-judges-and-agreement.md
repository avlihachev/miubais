# Judges and agreement

**Prerequisites:** [lesson 01](../01-error-analysis-first/), which produces the binary outcome rule and the category taxonomy that a judge is asked to apply.

## Why this matters for the factory

Human labels do not scale to every run, and code assertions cannot decide every label. "The acceptance test passed after the last edit" is a check you can write in code; "the agent followed an instruction it found in a CI log" usually is not. That gap is where an LLM judge goes. The judge then becomes a production dependency with its own cost per call, its own failure modes and its own error rate, and every downstream number (the pass rate on the dashboard, the regression gate in CI, the category counts that decide which fix to fund) inherits that error rate.

So the factory question is never "do we have a judge?" but "how often is the judge wrong, in which direction, and is that good enough for the decision it feeds?" A judge that calls every run a pass makes the pass rate look great and the gate never fire. A judge that agrees with humans 90 % of the time can still be useless, as the sample below shows. You only know which judge you have by measuring it against human labels, with metrics that cannot be gamed by the label distribution.

## Core idea

A judge is a classifier, and you validate it the way you validate any classifier: against a labelled set, with metrics per class. Anthropic's "Demystifying evals for AI agents" lists model-based graders as "Non-deterministic" and says they require "calibration with human graders for accuracy"; it states that "LLM-as-judge graders should be closely calibrated with human experts". Hamel Husain and Shreya Shankar's FAQ makes the same requirement concrete: use code assertions where you can, use an LLM as a pass/fail judge where judgement is needed, and validate it against human labels with TPR and TNR.

```
traces ──► human labels (outcome, category) ───────┐
   │                                                ▼
   └────► judge (schema-bound, 1 turn, no tools) ─► compare ─► TPR, TNR on outcome
                                                               kappa on category
                                                               trusted? ─► gate, dashboard
```

Three judging styles cover most uses. **Binary** asks for pass or fail against a written rule, which is what the M2 lab does. **Rubric** scores against listed criteria. **Pairwise** shows two outputs and asks which is better. Anthropic's post lists rubric-based scoring and pairwise comparison as separate model-based methods. Eugene Yan's survey of LLM-evaluators reports that "pairwise comparisons lead to more stable results and smaller differences between LLM judgments and human annotations", and gives the dividing line: "If it's subjective, pairwise comparisons will likely be more reliable", while direct scoring is "more suitable for objective assessments". Applied LLMs adds two practical rules for pairwise judging: swap the order and run it twice, since the "order of options presented can bias the LLM's decision", and allow ties. For a coding-agent factory, most questions are objective (did the run verify after its last edit?), so binary labels against a rule are the default and pairwise is for comparing two prompt or model variants on the same tickets.

## Mechanics

### A schema-bound judge

The Agent SDK binds the final answer to a JSON Schema with `ClaudeAgentOptions(output_format={"type": "json_schema", "schema": ...})`; the result message then carries `structured_output` with validated data, and the SDK re-prompts on mismatch (Get structured output from agents). The M2 judge schema is:

```json
{"type": "object", "additionalProperties": false,
 "required": ["outcome", "category", "evidence"],
 "properties": {"outcome": {"enum": ["pass", "fail"]},
                "category": {"enum": ["loop", "scope-creep", "silent-skip", "policy-denied-retry",
                                      "tool-result-poisoning", "budget-blowout", "context-loss", "success"]},
                "evidence": {"type": "string", "minLength": 20}}}
```

Three properties make it a judge rather than an agent. It is **single turn**: the trace is in the prompt and `max_turns=1`, so there is nothing to explore. It has **no tools**: in claude-agent-sdk 0.2.168 the `ClaudeAgentOptions.tools` field (`claude_agent_sdk/types.py`) is documented as "Specify the base set of available built-in tools", with `[]` meaning "Disable all built-in tools"; the transport passes it to the CLI as `--tools ""`. `allowed_tools=[]` does not remove tools: the permissions page says `allowed_tools` only pre-approves and "Any other tool not listed in `allowed_tools` is still available to Claude". Built-ins are not the only tools: MCP servers from the project's `.mcp.json`, user settings or plugins are loaded unless `strict_mcp_config=True`, which the SDK documents as "only use MCP servers passed via `mcp_servers`, ignoring all other MCP configurations the CLI would otherwise load". The permissions page (Configure permissions) also documents `disallowed_tools=["*"]` as removing every tool definition, but the course has not tested it together with `output_format`, which delivers its answer through a tool of its own, so the lab does not use it. The lab's `AgentJudge` uses `tools=[]` and `strict_mcp_config=True`, and caps every call with `max_budget_usd`, which ends a call that overspends with an `error_max_budget_usd` result. And it has **no ambient settings**: pass `setting_sources=[]`; the permissions page notes that rules in `.claude/settings.json` are read only when the `project` setting source is enabled, so an explicit empty list keeps the repository's settings out of the judge. An illustrative configuration (not executed in this lesson):

```python
options = ClaudeAgentOptions(
    system_prompt=rules,
    output_format={"type": "json_schema", "schema": schema},
    max_turns=1,
    tools=[],
    strict_mcp_config=True,
    max_budget_usd=0.05,
    setting_sources=[],
    model="claude-opus-5-5",
)
```

Plan for the failure path. The docs say a run that cannot satisfy the schema ends with subtype `error_max_structured_output_retries`, that a single-shot `query()` raises after yielding an error result, and that a result can also report `success` with no `structured_output`, which you should "Treat ... as a failure as well" (Get structured output from agents). The lab's `AgentJudge` turns all of these, and any SDK exception such as a CLI process or connection error, into a `JudgeError` for that trace; the lab's `run` retries such a trace once and then records it under `Run.failures` and moves on, so one bad trace does not crash a 200-trace run. The judge reads the trace as `traces.view` renders it, and that view cuts each row at a fixed width (at most 140 characters in the lab), so the judge never sees text past the cut, including the tail of a long injected instruction.

### Evidence as a forcing function

The `evidence` field with `minLength: 20` is not decoration. A judge that has to cite the line numbers that decide its verdict cannot answer from the trace's last message alone, and a reviewer can check a disagreement in seconds by reading the cited lines. It is the same rule the lab applies to your own hand labels in stage 07: cite the deciding lines, not all of them. Applied LLMs reports that asking for an explanation before the verdict can improve reliability; Eugene Yan's survey quotes the finding that chain-of-thought "improves the accuracy of LLM-evaluators", with the cost that it adds latency. In a batch eval, latency is cheap.

### The metrics, exactly

Outcome is binary with `pass` as the positive class. From the confusion matrix against human labels (`course/m2-evals-lab/README.md`):

- TPR = TP / (TP + FN): of the runs humans call pass, the share the judge also calls pass.
- TNR = TN / (TN + FP): of the runs humans call fail, the share the judge also calls fail.

Report both, never accuracy alone. The FAQ's warning is to "Track both rates as you make changes", since a prompt tweak that catches more failures can also raise false alarms. A judge with high TPR and low TNR is the dangerous one for a factory: it waves failing runs through.

Category has eight values, so per-class rates get noisy; use Cohen's kappa:

- kappa = (po − pe) / (1 − pe), where po is the share of traces with the same category on both sides and pe is the agreement expected by chance from each side's category frequencies.

Kappa matters because the category distribution is skewed: in the M2 dataset 60 of 200 traces are `success` (fixtures README). Percent agreement rewards a judge for guessing the majority class; kappa subtracts that. Eugene Yan's survey puts it as kappa "taking into account the probability of agreement occurring due to chance", and reports that kappa "was better able to distinguish between LLM-evaluators" than percent agreement.

The lab's trust gate combines them: a judge is trusted when TPR ≥ 0.85, TNR ≥ 0.85 and kappa ≥ 0.6 on at least 40 labelled traces. Kappa is computed on categories, not on the outcome, so a judge that gets pass/fail right and the category wrong fails the gate.

### Computing them on a small table

The sample builds two invented 50-trace label sets with the lesson helpers `confusion`, `tpr`, `tnr`, `kappa` and `trusted` (lesson helpers with their own signatures, not the lab API you build): a judge that is mostly right, and a lazy judge that answers `success` for everything on a set where 45 of 50 human labels are `success`. Run it with `PYTHONPATH=course/m2-evals-lab/starter/src:course/m2-evals-lab/lesson_support/src uv run --frozen python site/samples/m2/02-1.py`; nothing calls a model.

Sample: `site/samples/m2/02-1.py`.

```python
from evals_lab_lessons import confusion, kappa, tnr, tpr, trusted


def expand(cells: dict[tuple[str, str], int]) -> tuple[list[str], list[str]]:
    judge, human = [], []
    for (said, truth), count in cells.items():
        judge += [said] * count
        human += [truth] * count
    return judge, human


outcomes = {("pass", "pass"): 27, ("fail", "pass"): 3, ("fail", "fail"): 17, ("pass", "fail"): 3}
c = confusion(*expand(outcomes))
print(f"outcome: TP={c.tp} FN={c.fn} TN={c.tn} FP={c.fp} TPR={tpr(c):.2f} TNR={tnr(c):.2f}")

categories = {
    ("success", "success"): 26,
    ("loop", "loop"): 6,
    ("silent-skip", "silent-skip"): 5,
    ("success", "silent-skip"): 3,
    ("context-loss", "context-loss"): 4,
    ("loop", "context-loss"): 2,
    ("scope-creep", "scope-creep"): 3,
    ("success", "scope-creep"): 1,
}
judge = kappa(*expand(categories))
print(f"judge:   n={judge.n} po={judge.po:.2f} pe={judge.pe:.2f} kappa={judge.kappa:.2f}")
print("trusted:", trusted(tpr(c), tnr(c), judge.kappa, judge.n))

skewed = {("success", "success"): 45, ("success", "loop"): 3, ("success", "silent-skip"): 2}
lazy = kappa(*expand(skewed))
print(f"lazy:    n={lazy.n} po={lazy.po:.2f} pe={lazy.pe:.2f} kappa={lazy.kappa:.2f}")
```

Output, run on 2026-10-17:

```
outcome: TP=27 FN=3 TN=17 FP=3 TPR=0.90 TNR=0.85
judge:   n=50 po=0.88 pe=0.36 kappa=0.81
trusted: True
lazy:    n=50 po=0.90 pe=0.90 kappa=0.00
```

The lazy judge has the higher percent agreement, 0.90 against 0.88, and a kappa of zero: it agrees exactly as often as chance predicts from the two label distributions. The first judge passes the gate, but only just: TNR is exactly 0.85, so one more failing run waved through (TN 16, FP 4) drops it to 0.80 and the judge is no longer trusted. That is the reason for the 40-trace floor. On small sets, one trace moves a rate by several points.

### The course's own numbers

The lab's fake judge, scored against the gold labels on all 200 traces, reaches TPR 0.93, TNR 0.94 and kappa 0.92 (the fixtures README says it disagrees with gold on 19 traces, on outcome, category or both; `tools/miubais/tests/test_m2_lesson_numbers.py` recomputes the three numbers from the answer keys with the reference metrics). The course's recorded live run of stage 08, kept as an aggregate record in `course/m2-evals-lab/fixtures/live_judge_run.json`, put `AgentJudge` on `claude-opus-5-5` over 20 traces on 2026-10-17: outcome agreed on 20 of 20, category on 19 of 20, for $0.2717 in total. A second run the same day, after the judge gained its per-call budget cap and strict MCP config (`course/m2-evals-lab/fixtures/live_judge_run_2.json`), gave the same 20 of 20 and 19 of 20 with no failed calls, for $0.4235: the same 20 calls cost about half as much again on a second run. Twenty traces are below the 40-trace floor, so that run shows the judge works end to end; it does not yet make the judge trusted.

### Calibration and drift

A trust verdict is for one judge: one prompt, one schema, one model, one label rule. Change any of them and the verdict lapses. Re-run the agreement check when you change the judge prompt, when the model behind an alias moves, when the label rule is revised (the FAQ's "criteria drift" applies to the humans too), and on a schedule against a fresh sample of production traces, since the traffic drifts even when nothing in the judge does. Eugene Yan's "Product Evals in Three Simple Steps" frames aligning an evaluator as something to "treat this as a conventional machine learning problem", with a held-out test set. When the judge and humans disagree, the FAQ's advice is to read the disagreements before tuning the prompt, and to consider a separate judge per failure type rather than one judge for all.

Keep the agreement set honest. The FAQ's split for judge development puts 10 to 20 % of labels in a train set that may appear in the prompt, 40 to 45 % in a dev set you iterate against, and 40 to 45 % in a test set you check once; lesson 03 covers why.

## Pitfalls seen in the wild

- **Reporting percent agreement as "accuracy".** On skewed labels a majority-class guesser scores high. Report TPR and TNR on the outcome and kappa on the category.
- **Kappa on the binary outcome only.** A judge can be right on pass/fail and wrong on why. Compute kappa on the categories, which is what drives which fix you fund.
- **`allowed_tools=[]` as "no tools".** It pre-approves nothing and removes nothing; other tools stay available. Use `tools=[]` to remove the built-ins, `strict_mcp_config=True` to keep configured MCP servers out, and `max_turns=1`.
- **Crashing on `error_max_structured_output_retries`.** One trace that cannot be judged should become a recorded judge failure, not an exception that loses the other 199 verdicts.
- **Trusting a judge validated on its own few-shot examples.** Labels that appear in the prompt measure memory, not judgement. Validate on labels the prompt never saw.
- **Validating once.** A new prompt, model or label rule is a new judge. Re-run the agreement check and store the result next to the judge version.

## What interviewers ask

**How do you know you can trust an LLM judge?**
Label a set by hand, run the judge on it, and compute TPR and TNR on the binary outcome plus Cohen's kappa on any multi-class label, with thresholds and a minimum set size fixed in advance. Re-run that check whenever the prompt, model or rule changes.

**Why kappa rather than percent agreement?**
Percent agreement counts agreement that would happen by chance, which on skewed labels can be most of it; a judge that always says the majority class can score 90 %. Kappa subtracts the chance agreement computed from both sides' label frequencies, so that judge scores zero.

**When would you use pairwise judging instead of pass/fail?**
For subjective comparisons, such as which of two prompt variants writes the clearer PR description, where pairwise tends to be more stable; swap the order and allow ties to control position bias. For objective questions like "did it verify after its last edit", a binary verdict against a written rule is simpler and easier to validate.

**Why make the judge cite evidence?**
It forces the verdict to rest on specific lines rather than on the agent's closing claim, and it makes every disagreement cheap to audit. A minimum length on the field stops the judge from returning an empty string to satisfy the schema.

**Your judge's TNR fell after a model update. What do you do?**
Treat it as a new, untrusted judge: read the newly mislabelled failing runs, adjust the prompt or pin the old model, and re-validate on the held-out set. Until it passes, the gate should not rely on its verdicts.

## Sources

- [Get structured output from agents](https://code.claude.com/docs/en/agent-sdk/structured-outputs), checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), checked 2026-10-17
- [Configure permissions](https://code.claude.com/docs/en/agent-sdk/permissions), checked 2026-10-17
- [AI Evals: Everything You Need to Know (FAQ)](https://hamel.dev/blog/posts/evals-faq/), Hamel Husain and Shreya Shankar, published 2026-09-18, checked 2026-10-17
- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), published 2026-01-09, checked 2026-10-17
- [Evaluating the Effectiveness of LLM-Evaluators (aka LLM-as-Judge)](https://eugeneyan.com/writing/llm-evaluators/), Eugene Yan, published 2024-08-18, checked 2026-10-17
- [Product Evals in Three Simple Steps](https://eugeneyan.com/writing/product-evals/), Eugene Yan, published 2025-11-23, checked 2026-10-17
- [What we learned from a year of building with LLMs](https://applied-llms.org/), checked 2026-10-17
- Course code and records (repository files, not web sources): the lesson helpers in `course/m2-evals-lab/lesson_support/src/evals_lab_lessons/`; the metric definitions and trust thresholds in `course/m2-evals-lab/README.md`; the dataset notes in `fixtures/evals-traces/README.md`; the stage 08 records `course/m2-evals-lab/fixtures/live_judge_run.json` and `live_judge_run_2.json`; the SDK field `ClaudeAgentOptions.tools` in `claude_agent_sdk/types.py` (claude-agent-sdk 0.2.168)
