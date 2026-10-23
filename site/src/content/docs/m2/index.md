---
title: M2 Evals as engineering
freshness: skip
---

Error analysis, judges, agreement, CI gating.

## Lessons

- [01 Error analysis first](./01-error-analysis-first/)
- [02 Judges and agreement](./02-judges-and-agreement/)
- [03 Datasets and contamination](./03-datasets-and-contamination/)
- [04 Agent evals](./04-agent-evals/)
- [05 CI gating and tracking](./05-ci-gating-and-tracking/)
- [06 Evals for code agents](./06-evals-for-code-agents/)
- [07 Interview angle](./07-interview-angle/)

## Exercise

[M2 evals lab](/exercises/m2-evals-lab/): build the eval loop for a coding agent's traces, from loading and labelling them to a trusted judge, a regression gate and a score history, with tests and hints.

1. `01-trace-loader`: load the recorded traces and render one as numbered lines for a human or a judge.
2. `02-labels-and-agreement`: a labels file that rejects unknown traces and categories by line, and Cohen's kappa between two labellers.
3. `03-judge-interface`: the judge protocol, a fake judge with recorded answers, and an agent judge bound to a JSON schema.
4. `04-trust-gate`: TPR, TNR and kappa against gold labels decide whether the judge can be trusted.
5. `05-regression-gate`: a CLI gate that fails a run against the stored baseline and says why.
6. `06-score-history`: an append-only history of run summaries with a trend over the last runs.
7. `07-hand-labels`: label 40 traces yourself with evidence notes (judgment stage).
8. `08-live-judge`: the agent judge on 20 traces against the real Agent SDK (needs a Claude login).
