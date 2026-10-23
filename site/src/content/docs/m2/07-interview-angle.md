---
title: "Interview angle: evals as engineering"
description: The questions an interviewer asks about judge validation, agreement, reliability, regression gates, contamination and the cost of evals, a system-design prompt for the eval loop of a ticket-to-PR agent, and what a short take-home on this topic looks like.
module: m2
order: 7
freshness: skip
---

**Prerequisites:** lessons 01 to 06 of [M2](../), which this page assumes you have read.

This page collects what lessons 01 to 06 prepare you to answer out loud. Each answer points back to the lesson that covers it in depth.

## What they ask

**1. How do you validate an LLM judge before you let it gate anything?**
Label a set by hand against a written rule, run the judge on the same traces, and compute TPR and TNR on the binary outcome plus Cohen's kappa on the category, with thresholds and a minimum set size fixed before you look; the lab trusts a judge at TPR and TNR of at least 0.85 and kappa of at least 0.6 on 40 or more traces. Validate on a held-out slice you did not tune the prompt on, and repeat the check whenever the judge model, the prompt or the rule changes ([lesson 02](../02-judges-and-agreement/)).

**2. Why kappa rather than percent agreement?**
Percent agreement counts the matches two labellers would get by chance from their label frequencies alone, which on a skewed label set can be most of the score. Kappa is (po − pe) / (1 − pe): it subtracts that expected agreement, so a judge that always answers the majority category scores zero however high its raw agreement looks ([lesson 02](../02-judges-and-agreement/)).

**3. What is pass^k and when does it matter more than pass@k?**
pass@k is the chance that at least one of k runs succeeds, pass^k the chance that all k do; they agree at k = 1 and pull apart as k grows. A factory that auto-merges needs the task to work every time it is attempted, so it gates on pass^k per task class, and an 80% average can hide tasks that pass only half the time ([lesson 04](../04-agent-evals/)).

**4. How would you design the regression gate?**
Summarise each run to a pass rate and per-category counts, compare against a stored baseline with explicit thresholds (the lab fails on a pass-rate drop of more than 2 points or any category rising by more than 3), and exit non-zero with one reason per failed check. Compare against the stored baseline, never the previous run, because a series of small drops each passes against its predecessor, and compare in integer units so float noise at the threshold does not decide the build ([lesson 05](../05-ci-gating-and-tracking/)).

**5. Your eval flakes. What do you do?**
Pin the environment, then run the unchanged baseline several times to measure your own run-to-run spread before trusting the threshold. Retry only infrastructure errors, quarantine unstable tasks with an owner and an expiry while still running and reporting them, and never rerun the suite until it is green, because that reports the best of several tries as one run ([lesson 05](../05-ci-gating-and-tracking/)).

**6. How can an eval set be contaminated, and how do you guard against it?**
Test examples leak into the prompt or the tuning loop, trials share state such as git history or answer files in the agent's workspace, or the answers sit in training data, as happened with SWE-bench Verified. Keep a test slice you check once, group splits by ticket so near-duplicates do not straddle them, isolate every trial, hash the split manifest and labels, and keep a keyword baseline on synthetic data to prove the labels need reading ([lesson 03](../03-datasets-and-contamination/), [lesson 06](../06-evals-for-code-agents/)).

**7. How do you measure a code-review agent?**
Precision and recall of its findings per severity against a labelled set of PRs that includes clean ones, under a written matching rule, gating on blocker recall with a floor on blocker precision. Build, test and lint results are deterministic verify gates kept separate from the findings, so the agent is not credited for what the test runner found ([lesson 06](../06-evals-for-code-agents/)).

**8. What does an eval run cost, and how do you keep it in check?**
Cost is a metric of the eval, recorded per run next to pass rate: the course's two live judge runs scored the same 20 traces with `claude-opus-5-5` for $0.2717 and $0.4235, so a 200-trace run would be roughly $2.70 to $4.20 of judge calls by extrapolation. Prefer deterministic assertions where they can answer the question, reserve the judge for what needs reading, and treat a prompt change that doubles judge cost as a regression ([lesson 05](../05-ci-gating-and-tracking/)).

## System design prompt

"Design the eval loop for an agent that takes a ticket and opens a PR. What do you label, what gates a merge, what do you track, and how do you keep the numbers honest?"

A short model outline:

- **Start from traces.** Read a sample of real runs plus every run that hit a cap, write a note on the first failure in each, and group the notes into a taxonomy (loop, scope creep, silent skip, retry around a denial, acting on tool output, budget blowout, lost context). Label each trace with a binary outcome against a written rule and a category; that labelled set is the first eval set, grown from failures rather than invented.
- **Grade outcome first, trajectory where it is part of correctness.** The outcome checks are deterministic: the acceptance test passes after the last edit, the suite is green, no test file changed. Trajectory checks cover what the outcome cannot show, such as verifying after the final edit or acting on instructions found in a tool result.
- **Judge with a schema and validate it.** An LLM judge returns outcome, category and evidence that cites trace lines, bound to a JSON schema; a schema failure is a judge failure, not a crash. The judge gates nothing until TPR, TNR and kappa against human labels clear thresholds fixed in advance on a held-out slice.
- **Gate in CI against a stored baseline.** A fixed, versioned dataset, a summary with pass rate and per-category counts, thresholds in integer units, one reason per failure, and a baseline that changes only through a reviewed commit. Merge on pass^k per task class rather than a single run.
- **Keep the numbers honest.** Isolated trials with no shared workspace or git history, dataset and label hashes stored with every score, a test slice checked once, flakes retried only for infrastructure errors and quarantined with an owner.
- **Track.** An append-only history per run with commit, dataset hash, judge model and prompt version, pass rate, counts, cost and wall time; cost per PR, time to merge and revert rate as lagging checks.

Close with the trade: every threshold you tighten blocks some good changes, every task you add raises the cost of a run, and a judge you stop re-validating drifts silently. You would review the disagreements between judge and humans, the quarantine list and the cost trend on a fixed cadence.

## Take-home shape

A good 2 to 4 hour take-home on this topic hands the candidate a folder of 100 to 200 recorded agent traces, a partial set of human labels and a recorded judge output, and asks for three things:

1. **An agreement and trust report.** Code that computes TPR, TNR and Cohen's kappa of the judge against the human labels, with tests that include a chance-level case, and a one-paragraph verdict on whether the judge can gate a merge and why.
2. **A regression gate with tests.** A CLI that compares a run summary to a stored baseline, exits non-zero with reasons, and has tests for an exact-threshold case, a just-over case and a slow drift that passes run to run but fails against the baseline.
3. **A short error-analysis write-up.** Twenty traces labelled by hand with a note citing the lines that decide each label, the categories that came out of them, and which failure the candidate would build an eval for first.

Grade on the tests at the edges (exact threshold, chance agreement, empty overlap), on whether the gate compares against the baseline, on evidence notes that cite specific lines rather than restate the label, and on whether the write-up names a decision with a number behind it. A submission that reports percent agreement as kappa, or a gate that reruns until green, fails regardless of polish.
