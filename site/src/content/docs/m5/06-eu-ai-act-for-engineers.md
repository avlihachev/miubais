---
title: The EU AI Act for engineers
description: The AI Act dates after the 2026 Omnibus, what Article 12 asks of logs and Article 50 asks of transparency in their own words, why a coding agent inside a software factory is not an Annex III system as written, and the audit log and ten-item checklist the course derives from those articles anyway.
module: m5
order: 6
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:mcp": "2.3.0"
  "model:default": claude-opus-5-5
sources:
  - url: https://artificialintelligenceact.eu/implementation-timeline/
    title: EU AI Act implementation timeline
    checked: 2026-10-17
  - url: https://artificialintelligenceact.eu/article/12/
    title: "Article 12: Record-Keeping"
    checked: 2026-10-17
  - url: https://artificialintelligenceact.eu/article/50/
    title: "Article 50: Transparency Obligations for Providers and Deployers of Certain AI Systems"
    checked: 2026-10-17
  - url: https://artificialintelligenceact.eu/annex/3/
    title: "Annex III: High-Risk AI Systems Referred to in Article 6(2)"
    checked: 2026-10-17
  - url: https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/
    title: Digital AI Omnibus delays key deadlines, introduces new rules (Cooley)
    published: 2026-08-03
    checked: 2026-10-17
  - url: https://natlawreview.com/article/eu-digital-omnibus-ai-enters-force
    title: EU Digital Omnibus on AI Enters Into Force (K&L Gates, National Law Review)
    published: 2026-07-31
    checked: 2026-10-17
---

**Prerequisites:** [lesson 02](../02-indirect-injection-and-provenance/), whose taint and denials are the events the audit log in this lesson records.

## Why this matters for the factory

Someone will ask whether the agent factory is "AI Act compliant". The honest answer starts with which obligations apply to what, and engineers are the people who can say what the system actually does. This lesson gives you enough of the text to have that conversation precisely: the dates as they stand after the 2026 amendments, the two articles an engineer touches most (record-keeping and transparency), what applies to a coding agent and what does not, and the audit log the course builds anyway.

This is not legal advice. Where this lesson reports the Omnibus, it relies on secondary sources and says so. Where it quotes the Act, it quotes the text as shown by the AI Act Explorer at artificialintelligenceact.eu, checked on 2026-10-17.

## Core idea

The AI Act regulates by use, not by technology. A system's obligations depend on where it falls: prohibited practices, high-risk systems (those listed in Annex III, or safety components of products under Annex I), systems with transparency duties under Article 50, general-purpose AI models, and everything else. A coding agent that writes code for your own products, reviewed by your engineers, is not on the Annex III list as written. So the heavy high-risk duties, including Article 12's logging requirement, do not bind it.

That does not make Article 12 irrelevant. It states what an AI system's logs are for: tracing risks, monitoring after deployment, and letting the operator watch it work. Those are the questions you need to answer after an injection incident. The course therefore treats Article 12 as a design brief for its audit log and treats Article 50 as a real duty in the places where generated text reaches the public.

## Mechanics

### The dates after the Omnibus

The AI Act Explorer's implementation timeline (last updated 31 August 2026) lists: prohibitions and AI literacy from 2 February 2025; the general-purpose AI rules and governance from 2 August 2025; on 2 August 2026, "The remainder of the AI Act starts to apply, unless specified otherwise"; Chapter III, Sections 1 to 3 from 2 December 2027 for high-risk systems under Article 6(2) and Annex III; and from 2 August 2028 for high-risk systems under Article 6(1) and Annex I. Providers of systems generating synthetic content that were on the market before 2 August 2026 must comply with Article 50(2) by 2 December 2026.

The high-risk dates moved because of the AI Omnibus. From secondary sources only: Cooley reports that Regulation (EU) 2026/1744 "was published in the Official Journal of the European Union" on 24 July 2026, "entering into force on the third day following publication, i.e. 27 July 2026", with a "four-month transitional period, until 2 December 2026" for the Article 50(2) marking duty; K&L Gates (via the National Law Review, 31 July 2026) states it "entered into force on 27 July 2026", that the Annex III date "moves from 2 August 2026 to 2 December 2027", and that compliance for systems embedded in regulated products is "deferred further, until 2 August 2028". Read the Official Journal text before you rely on a date in a contract.

### Article 12, in full

Article 12 sits in Chapter III, Section 2 (requirements for high-risk systems), and per the Explorer applies from 2 December 2027 for Annex III systems. Its text:

> 1. High-risk AI systems shall technically allow for the automatic recording of events (logs) over the lifetime of the system.
>
> 2. In order to ensure a level of traceability of the functioning of a high-risk AI system that is appropriate to the intended purpose of the system, logging capabilities shall enable the recording of events relevant for:
>
> (a) identifying situations that may result in the high-risk AI system presenting a risk within the meaning of Article 79(1) or in a substantial modification;
>
> (b) facilitating the post-market monitoring referred to in Article 72; and
>
> (c) monitoring the operation of high-risk AI systems referred to in Article 26(5).
>
> 3. For high-risk AI systems referred to in point 1 (a), of Annex III, the logging capabilities shall provide, at a minimum:
>
> (a) recording of the period of each use of the system (start date and time and end date and time of each use);
>
> (b) the reference database against which input data has been checked by the system;
>
> (c) the input data for which the search has led to a match;
>
> (d) the identification of the natural persons involved in the verification of the results, as referred to in Article 14(5).

The logs are automatic: a person writing notes does not count. They are for the lifetime of the system, so they must survive restarts and reopenings. And paragraph 2 says what an event is worth recording for: situations that may present a risk, monitoring after deployment, and the deployer's monitoring. Paragraph 3 is specific to remote biometric identification (Annex III point 1(a)) and is the only place the article lists minimum fields.

### Article 50, the parts that matter here

Article 50 applies from 2 August 2026 and is not limited to high-risk systems. Paragraphs 1, 2 and 4, verbatim:

> 1. Providers shall ensure that AI systems intended to interact directly with natural persons are designed and developed in such a way that the natural persons concerned are informed that they are interacting with an AI system, unless this is obvious from the point of view of a natural person who is reasonably well-informed, observant and circumspect, taking into account the circumstances and the context of use. This obligation shall not apply to AI systems authorised by law to detect, prevent, investigate or prosecute criminal offences, subject to appropriate safeguards for the rights and freedoms of third parties, unless those systems are available for the public to report a criminal offence.
>
> 2. Providers of AI systems, including general-purpose AI systems, generating synthetic audio, image, video or text content, shall ensure that the outputs of the AI system are marked in a machine-readable format and detectable as artificially generated or manipulated. Providers shall ensure their technical solutions are effective, interoperable, robust and reliable as far as this is technically feasible, taking into account the specificities and limitations of various types of content, the costs of implementation and the generally acknowledged state of the art, as may be reflected in relevant technical standards. This obligation shall not apply to the extent the AI systems perform an assistive function for standard editing or do not substantially alter the input data provided by the deployer or the semantics thereof, or where authorised by law to detect, prevent, investigate or prosecute criminal offences.
>
> 4. Deployers of an AI system that generates or manipulates image, audio or video content constituting a deep fake, shall disclose that the content has been artificially generated or manipulated. This obligation shall not apply where the use is authorised by law to detect, prevent, investigate or prosecute criminal offence. Where the content forms part of an evidently artistic, creative, satirical, fictional or analogous work or programme, the transparency obligations set out in this paragraph are limited to disclosure of the existence of such generated or manipulated content in an appropriate manner that does not hamper the display or enjoyment of the work. Deployers of an AI system that generates or manipulates text which is published with the purpose of informing the public on matters of public interest shall disclose that the text has been artificially generated or manipulated. This obligation shall not apply where the use is authorised by law to detect, prevent, investigate or prosecute criminal offences or where the AI-generated content has undergone a process of human review or editorial control and where a natural or legal person holds editorial responsibility for the publication of the content.

Paragraph 5 adds that this information must be given "in a clear and distinguishable manner at the latest at the time of the first interaction or exposure."

### What applies to a coding agent, and what does not

The course's position, stated as a position and not as legal advice:

- **Not high-risk as written.** Annex III lists areas such as biometrics, critical infrastructure, education, employment, essential services, law enforcement, migration and justice. A coding agent that changes your own code under engineer review is not one of them, so Article 12 is not a legal duty for it.
- **Watch the employment line.** Annex III point 4(b) covers systems "intended to be used to make decisions affecting terms of work-related relationships ... to allocate tasks based on individual behaviour or personal traits or characteristics or to monitor and evaluate the performance and behaviour of persons in such relationships." If the factory's logs start being used to rate the engineers who supervise the agents, that use is a different system with a different answer.
- **Article 50 where text meets the public.** Generated release notes, support replies or status pages leave the factory. Paragraph 2 is a provider duty for systems generating text (with an exception for assistive editing), and paragraph 4 makes deployers disclose AI-generated text published to inform the public on matters of public interest, unless it has had human review or editorial control with someone holding editorial responsibility. Product docs and changelogs are rarely "matters of public interest", but a public incident report might be; decide per channel, and keep the human review that the exception names.
- **Code is not exempt by being code**, but whether code counts as synthetic "text content" under 50(2) is a question for your counsel, not for this lesson.

### The audit log the course builds anyway

Stage 06 writes an append-only JSONL log with one event per line: `ts` (UTC ISO with microseconds), `run_id`, `ticket_id`, `event` (`run.start`, `tool.call`, `tool.denied`, `taint.set`, `taint.cleared`, `secret.redacted`, `approval`, `run.end`), `actor` (`model`, `host`, `human`), a scrubbed `payload`, `tool_use_id`, `prev_sha256` and `sha256`. Each line's hash covers the canonical JSON of the line without the hash, including the previous line's hash, so the lines form a chain. The sample builds a four-line chain with the lesson helper, then edits one line, deletes one, and cuts the tail.

Sample: `site/samples/m5/06-1.py`.

```python
import json

from injection_lab_lessons import chain, verify_chain

events = [
    {"ts": "2026-10-17T09:00:00.000000+00:00", "event": "run.start", "actor": "host"},
    {"ts": "2026-10-17T09:00:04.120000+00:00", "event": "tool.call", "actor": "model"},
    {
        "ts": "2026-10-17T09:00:04.130000+00:00",
        "event": "tool.denied",
        "actor": "host",
        "reason": "untrusted content in context: approval required",
    },
    {"ts": "2026-10-17T09:00:09.500000+00:00", "event": "run.end", "actor": "host"},
]
lines = chain(events)
print(json.loads(lines[1])["prev_sha256"][:16], json.loads(lines[1])["sha256"][:16])
print("intact:", verify_chain(lines))

edited = json.loads(lines[2])
edited["reason"] = "allowed by policy"
print("edited line 3:", verify_chain([*lines[:2], json.dumps(edited), *lines[3:]]))
print("deleted line 3:", verify_chain([*lines[:2], *lines[3:]]))
print("cut after line 2:", verify_chain(lines[:2]), "<- needs the recorded head to catch")
```

Output, run on 2026-10-17:

```
a7dad53fd2a3fa6d 82a090a09128ca9f
intact: (True, None, 'ok')
edited line 3: (False, 3, 'sha256 does not match the line')
deleted line 3: (False, 3, 'prev_sha256 does not match the line before')
cut after line 2: (True, None, 'ok') <- needs the recorded head to catch
```

An edited line fails at its own number, because its stored hash no longer matches its content. A deleted line fails at the line after it, because that line's `prev_sha256` points at a line that is gone. A log cut after a complete line still verifies, which is why the exercise's `AuditLog` keeps the last hash as `head` and `audit.verify(path, head=)` fails when the file ends before it. A chain makes tampering visible; it does not prevent it, and anyone who can rewrite the whole file can recompute the chain. Shipping the head somewhere the agent cannot write, or the lines to a write-once store, closes that gap.

`CHECKLIST.md` maps ten checks to the field or event that satisfies them and to the provision each is modelled on, and `audit.checklist(path, head=)` evaluates them: every run has a start and a later end (Art. 12(1)); every denial has a reason (Art. 12(2)(a)); every taint is closed by an approval and a clearing, or by the end of the run (Art. 14, Art. 12(2)(a)); no payload still contains a secret pattern (Art. 15(5)); the chain verifies (Art. 12(1), Art. 15(5)); timestamps never go backwards (Art. 12(2)); every event names its actor (Art. 12(2)(c), Art. 26(5)); every event carries a run and ticket id (Art. 12(2)(b), Art. 72); tool events carry their `tool_use_id` (Art. 12(2)); and the log was not truncated (Art. 12(1), Art. 19). The live run in stage 08 passed all ten. The checklist's own header says it: this is "good practice modelled on the high-risk logging duty, not a legal obligation."

## Common pitfalls

- **Quoting old dates.** The Omnibus moved the high-risk dates to 2 December 2027 and 2 August 2028. Check the date of whatever you cite.
- **Calling everything high-risk, or nothing.** Classification is by use; the same agent can be minimal-risk in the factory and high-risk when it rates people.
- **Logs a person writes.** Article 12 says automatic. Record at the hook and observer level, not in the agent's own summary.
- **A hash chain without a head.** It catches edits and deletions, not a cut tail. Record the head elsewhere.
- **Secrets in the audit log.** A log that keeps every tool input keeps every leaked key. Scrub payloads before they are written.
- **Forgetting Article 50 at the edge.** The factory's output that reaches customers is where transparency duties live.

## What interviewers ask

**Does the EU AI Act apply to our coding agents?**
The Act applies by use. A coding agent writing code for your own products under engineer review is not an Annex III high-risk use as written, so the high-risk duties, including Article 12 logging, do not bind it. Article 50 transparency, in force since 2 August 2026, matters where generated text reaches the public. Using the same system to evaluate employees would fall under Annex III point 4(b).

**What does Article 12 require of logs?**
That high-risk systems "technically allow for the automatic recording of events (logs) over the lifetime of the system", with events relevant for identifying risk situations, post-market monitoring and the deployer's monitoring. Only biometric identification systems get a minimum field list. For an agent, that translates into run boundaries, every tool call and denial with its reason, approvals with who gave them, and tamper evidence.

**How do you make an audit log tamper-evident?**
Hash each line over its canonical content plus the previous line's hash, verify the chain on read, and record the last hash outside the log so a truncated tail is detected. Scrub secrets before writing. It is evidence, not prevention: also ship lines to storage the agent cannot rewrite.

**What changed with the AI Omnibus?**
From secondary sources: Regulation (EU) 2026/1744 was published on 24 July 2026 and entered into force on 27 July 2026; the Annex III high-risk obligations move to 2 December 2027 and those for regulated products to 2 August 2028. Article 50 still applies from 2 August 2026, with systems already on the market given until 2 December 2026 for the 50(2) marking duty.

## Sources

- [EU AI Act implementation timeline](https://artificialintelligenceact.eu/implementation-timeline/), AI Act Explorer, last updated 31 August 2026, checked 2026-10-17
- [Article 12: Record-Keeping](https://artificialintelligenceact.eu/article/12/), AI Act Explorer, checked 2026-10-17
- [Article 50: Transparency Obligations for Providers and Deployers of Certain AI Systems](https://artificialintelligenceact.eu/article/50/), AI Act Explorer, checked 2026-10-17
- [Annex III: High-Risk AI Systems](https://artificialintelligenceact.eu/annex/3/), AI Act Explorer, point 4, checked 2026-10-17
- [Digital AI Omnibus delays key deadlines, introduces new rules](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/), Patrick Van Eecke and Bartholomäus Regenhardt, Cooley, 2026-08-03, secondary source, checked 2026-10-17
- [EU Digital Omnibus on AI Enters Into Force](https://natlawreview.com/article/eu-digital-omnibus-ai-enters-force), Sarah Pearce and Thomas Nietsch, K&L Gates, National Law Review, 2026-07-31, secondary source, checked 2026-10-17
- Course code (repository files, not web sources): stage 06 in `course/m5-injection-lab/README.md`, `course/m5-injection-lab/CHECKLIST.md`, the live record `course/m5-injection-lab/fixtures/live_injection_run.json`, the lesson helpers in `course/m5-injection-lab/lesson_support/src/injection_lab_lessons/`
