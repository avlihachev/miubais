---
title: Routing and fallback
description: Routes as a model with its caps, which stops may fall back and why a policy denial never does, the SDK's fallback_model next to a client-side router, what resuming a session on fallback does to cost, and measuring each route's quality.
module: m3
order: 5
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:opentelemetry-sdk": "1.45.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://code.claude.com/docs/en/agent-sdk/configuration
    title: Configure your agent
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/model-config
    title: Model configuration
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/python
    title: Agent SDK reference - Python
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/cost-tracking
    title: Track cost and usage
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/agent-loop
    title: How the agent loop works
    checked: 2026-10-17
---

**Prerequisites:** [lesson 04](../04-cost-per-task/), which defines the per-attempt cost and the budget stop this lesson routes on.

## Why this matters for the factory

Tickets in a factory are not alike. A typo fix needs a few turns on a small model; a cross-module bug may need a large model and many turns. Running everything on the strongest model overpays on the easy majority. Running everything on the cheapest fails the hard minority, and each failed run is paid for again when it is redone. One answer is a ladder: try a cheap route first, move to a stronger one only when the cheap one runs out of room, and keep enough records per route to know whether the ladder is actually saving money without losing quality.

A run that hit its turn cap may succeed with more turns or a stronger model. A run the policy hook stopped because it tried to touch a forbidden path should not be handed to a more capable model to try again. Stage 05 of the exercise builds that router, and this lesson explains its rules.

## Core idea

A route is a model together with its caps: in the exercise, `Route(name, model, max_budget_usd, max_turns)`. A router holds an ordered list of routes and runs a ticket on the first one. When the attempt ends, its `stopped_by` decides what happens next:

| `stopped_by` | meaning | router |
| --- | --- | --- |
| `success` | the run ended normally | stop, done |
| `max_turns` | the turn cap was hit | next route |
| `budget` | the spend cap or the guard was hit | next route |
| `error` | the run failed or ended without a result | next route |
| `policy` | the policy hook denied an action | stop, never fall back |

The three fallback classes share one property: more room (turns, money, a different model) could plausibly change the outcome. A policy stop does not have it. The denial is a statement about the action, not about the model's ability, and a stronger model may be better at finding another way to do the forbidden thing. Stage 05's `Router` rejects a `fallback_on` set that contains `policy` or `success` with a `ValueError`, so the rule cannot be configured away.

The router also counts. For every route it keeps attempts, successes, cost and turns, accumulated across tickets, which is the raw material for deciding whether the ladder's order is right.

## Mechanics

### Each attempt is a harness run with the route's settings

The router calls `run_fn(ticket_path, repo, model=route.model, max_turns=route.max_turns, max_budget_usd=route.max_budget_usd, **kwargs)`, where `run_fn` defaults to `harnesskit.runner.run_ticket`. The route's values reach `ClaudeAgentOptions` unchanged. In the SDK both caps are off unless set (the harness's own defaults are 12 turns and 0.50 USD; the router overrides both), and "When a session hits a cap, the run ends with a result message whose subtype names the cap, `error_max_turns` or `error_max_budget_usd`" (Configure your agent). The harness maps those subtypes to `max_turns` and `budget`, maps a run that ended in error with a recorded policy denial to `policy`, and maps the budget guard's stop from lesson 04 to `budget` as well.

One SDK detail matters for routing on these values. The reference says "When the final request fails, such as on an API error, Claude Code reports `subtype` `"success"` with the cause in `terminal_reason`, for example `"api_error"`; when a limit you set ends the run, such as `max_turns` or `max_budget_usd`, it reports an `error_*` subtype", and advises "check `terminal_reason` before `subtype`" (Agent SDK reference - Python). The course harness follows the flag the SDK sets on that result: a `success` subtype with `is_error` set maps to `error`, not `success`, so the router falls back on a run whose last request failed instead of stopping there. Code that reads the SDK directly should do the same, looking at `terminal_reason` first and routing an `api_error` as an `error`.

### `fallback_model` is not this router

The SDK has its own fallback. `ClaudeAgentOptions.fallback_model` is documented as "Fallback model to use if the primary model fails. Accepts a comma-separated list" (Agent SDK reference - Python), and the Python SDK 0.2.168 passes it to the CLI as `--fallback-model`. Its scope is provider failure: "When the primary is overloaded or unavailable, the session switches to the backup. The primary is retried at the start of each user turn, so the session returns to it once the outage passes" (Configure your agent). Claude Code's model page draws the boundary: it switches when the primary "is overloaded, unavailable, or returns another non-retryable server error", while "Authentication, billing, rate-limit, request-size, and transport errors, and a denial by your organization's policy check, never trigger a switch", and it "caps chains at three models after duplicate removal" (Model configuration).

A turn cap or a spend cap is none of those. The provider answered every request; the run simply used up the room it was given, and `fallback_model` never sees that. So the two layers do different jobs and a factory wants both: `fallback_model` inside an attempt keeps a run alive through an outage, and the client-side router between attempts decides whether a capped or failed run deserves a bigger route. Keep the policy rule consistent across both: the SDK's chain already refuses to switch on a policy denial, and the router refuses too.

### Falling back resumes the session

With the real `run_ticket`, a fallback attempt does not start from scratch. The harness stores each ticket's session id when a run returns a result, marked `open` unless it succeeded, and the next `run_ticket` call for that ticket passes it as `resume`. The stronger model therefore continues the conversation the failed attempt left, with its file reads and edits in context, and the repository still holds the changes the earlier attempt made. That is usually what you want: the expensive model starts from the cheap model's progress instead of paying to redo it.

It changes the arithmetic. The cost guide says "A resumed call's results report the session's whole spend, not just that call's own", and "summing results double-counts the restored spend" (Track cost and usage). The harness subtracts the stored session cost, so each attempt's `cost_usd` is that attempt's own spend, and the ticket's total is the sum of its attempts. The caps are per attempt too: `max_budget_usd` "counts only the call's own spend; totals restored from a resumed session don't count" (Agent SDK reference - Python). The worst case for one ticket is therefore the sum of every route's budget, plus the headroom the SDK allows, because "Spend can therefore pass the cap by up to the cost of that one response" (How the agent loop works). Write that sum down when you choose the caps.

A run the budget guard stops has produced no result, and the harness stores no new session for it, so the next route resumes whichever session an earlier attempt stored, or starts fresh if none did, and the guard-stopped attempt's own messages are not part of it. The repository still holds whatever the stopped run changed. And if a stored session cannot be resumed, the harness notes `resume failed` and starts fresh.

### Per-route quality

`stopped_by="success"` means the agent finished, not that the ticket is fixed. Route stats on their own tell you cost and finishing rate; they do not tell you whether moving tickets from the strong route to the cheap one made the work worse. That needs the M2 eval harness: run the suite once per route on the same dataset, compare pass rates with the regression gate from [M2 lesson 05](../../m2/05-ci-gating-and-tracking/), and keep the scores in its history next to the route stats. Then the useful numbers are cost per passed ticket per route and the pass-rate gap between routes. A cheap first route that passes evals as often as the strong one and costs a tenth is a win; one that finishes as often but passes less is a hidden regression.

With a `tracer_provider`, stage 05 records each attempt as its own trace with the root attribute `trace_lab.route`, so a backend such as the Langfuse from lesson 03 can group costs and failures by route.

### The sample

The sample drives the lesson helper's `LessonRouter`, which follows stage 05's rules, with a fake `run_fn` over three invented tickets and three routes. Nothing calls a model. Run it with `PYTHONPATH=course/m3-trace-lab/starter/src:course/m3-trace-lab/lesson_support/src uv run --frozen python site/samples/m3/05-1.py`.

Sample: `site/samples/m3/05-1.py`.

```python
from trace_lab_lessons import LessonRouter, Outcome, Route

routes = [
    Route("cheap", "claude-haiku-5-5", 0.05, 8),
    Route("default", "claude-sonnet-5-5", 0.40, 15),
    Route("strong", "claude-opus-5-5", 1.00, 25),
]

scripted = {
    ("readme-typo", "claude-haiku-5-5"): Outcome("success", 0.004, 3),
    ("flaky-test", "claude-haiku-5-5"): Outcome("max_turns", 0.012, 8),
    ("flaky-test", "claude-sonnet-5-5"): Outcome("budget", 0.402, 11),
    ("flaky-test", "claude-opus-5-5"): Outcome("success", 0.310, 6),
    ("drop-table", "claude-haiku-5-5"): Outcome("policy", 0.002, 2),
}


def fake_run(ticket_id, *, model, max_turns, max_budget_usd):
    return scripted[(ticket_id, model)]


router = LessonRouter(routes)
for ticket in ("readme-typo", "flaky-test", "drop-table"):
    final, attempts = router.run(ticket, fake_run)
    steps = " -> ".join(f"{name}:{outcome.stopped_by}" for name, outcome in attempts)
    spent = sum(outcome.cost_usd for _, outcome in attempts)
    print(f"{ticket:<12} {steps:<50} ends on {final:<7} {spent:.3f} USD")

print()
print(router.table())
```

Output, run on 2026-10-17:

```
readme-typo  cheap:success                                      ends on cheap   0.004 USD
flaky-test   cheap:max_turns -> default:budget -> strong:success ends on strong  0.724 USD
drop-table   cheap:policy                                       ends on cheap   0.002 USD

route    model              tries  ok      usd turns
cheap    claude-haiku-5-5       3   1   0.0180    13
default  claude-sonnet-5-5      1   0   0.4020    11
strong   claude-opus-5-5        1   1   0.3100     6
```

The easy ticket ends on the cheap route. The flaky test climbs the whole ladder, and its 0.724 USD is the sum of three attempts' own spend, as it would be with resumed sessions. The middle attempt's 0.402 USD is slightly above its 0.40 cap, the headroom the SDK documents. That stop came from the SDK cap, which ends with a result, so the harness stored the default attempt's session and the strong route resumes it. Had the budget guard stopped the default attempt instead, the strong route would resume the session the cheap attempt stored, without the default attempt's messages. The `drop-table` ticket stops after one attempt on a policy denial, even though two stronger routes were available. In the table, the cheap route finished one ticket in three, and the strong route's single success cost more than all cheap attempts together; on real traffic those columns, joined with eval pass rates, tell you whether to reorder the ladder or change a cap.

## Common pitfalls

- **Falling back on a policy denial.** The stronger model may be better at working around the denial. Stop and report.
- **Using `fallback_model` as the router.** It reacts to overload and unavailability, not to a run that hit its turn or spend cap.
- **Trusting `subtype == "success"`.** A failed final request reports `success` with `terminal_reason` set. Check it first.
- **Summing session totals across resumed attempts.** Each resumed result already includes the earlier spend. Use each attempt's own cost.
- **Caps that ignore the ladder.** The ticket's worst case is the sum of all route budgets plus headroom, not the last route's budget.
- **Counting finishes as quality.** A route that finishes cheaply but passes evals less often is a regression. Measure per route with the eval suite.

## What interviewers ask

**How would you route agent tasks across models of different cost?**
An ordered list of routes, each a model with its own turn and spend caps. Run the cheapest first and fall back only on stops that more room could fix: turn cap, budget, error. Record attempts, successes, cost and turns per route and check quality per route with the eval suite.

**Why must a policy denial never trigger fallback?**
The denial is about the action, not the model's ability. Retrying on a stronger model rewards the agent for attempting something forbidden and raises the chance it finds a way around the hook. Stop, report, let a person decide.

**The SDK has `fallback_model`. Why write a router at all?**
`fallback_model` switches when the provider is overloaded or the model is unavailable. Budget and turn stops are not provider errors; the run completed and used up its room. A client-side router handles those, and the two layers work together.

**What happens to cost when a fallback attempt resumes the failed session?**
The new model continues the conversation, so it does not redo the work, but the SDK's result reports the whole session's spend. Subtract the stored total to get the attempt's own cost, sum attempts for the ticket, and budget for the sum of all route caps plus headroom.

**How do you know a cheaper first route is not hurting quality?**
Run the same eval dataset per route, compare pass rates with the CI gate, and look at cost per passed ticket. Finishing rate from `stopped_by` alone does not measure correctness.

## Sources

- [Configure your agent](https://code.claude.com/docs/en/agent-sdk/configuration), sections Choose a model and Limit turns and spend, Claude Agent SDK docs, checked 2026-10-17
- [Model configuration](https://code.claude.com/docs/en/model-config), section Fallback model chains, Claude Code docs, checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), `ClaudeAgentOptions` and `ResultMessage`, checked 2026-10-17
- [Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking), Claude Agent SDK docs, checked 2026-10-17
- [How the agent loop works](https://code.claude.com/docs/en/agent-sdk/agent-loop), section Budget headroom, Claude Agent SDK docs, checked 2026-10-17
- Course code (repository files, not web sources): stage 05 in `course/m3-trace-lab/README.md`; the runner's resume and cost logic in `fixtures/harnesskit/src/harnesskit/runner.py` and the stop mapping in `fixtures/harnesskit/src/harnesskit/report.py`; the lesson helpers in `course/m3-trace-lab/lesson_support/src/trace_lab_lessons/`
