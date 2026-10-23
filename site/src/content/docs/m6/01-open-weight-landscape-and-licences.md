---
title: Open-weight landscape and licences
description: The 2026 open-weight families (Qwen3.5, Gemma 4, gpt-oss, DeepSeek V4, Llama 4) with their sizes and licences quoted from the model cards, what "open weight" grants and what it leaves out, the Llama 4 clauses on 700 million monthly users, attribution and EU-based companies, and how to shortlist a model for a factory workload.
module: m6
order: 1
verified_on: 2026-10-22
executed: none
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "model:default": claude-opus-5-5
sources:
  - url: https://huggingface.co/Qwen/Qwen3.5-27B
    title: Qwen3.5-27B model card
    checked: 2026-10-22
  - url: https://huggingface.co/Qwen/Qwen3.5-0.8B
    title: Qwen3.5-0.8B model card
    checked: 2026-10-22
  - url: https://huggingface.co/google/gemma-4-31B-it
    title: Gemma 4 31B IT model card
    checked: 2026-10-22
  - url: https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/
    title: "Gemma 4: Our most capable open models to date"
    published: 2026-04-02
    checked: 2026-10-22
  - url: https://ai.google.dev/gemma/terms
    title: Gemma Terms of Use
    published: 2026-04-01
    checked: 2026-10-22
  - url: https://huggingface.co/openai/gpt-oss-120b
    title: gpt-oss-120b model card
    checked: 2026-10-22
  - url: https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro
    title: DeepSeek-V4-Pro model card
    checked: 2026-10-22
  - url: https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct
    title: Llama-4-Scout-17B-16E-Instruct model card
    checked: 2026-10-22
  - url: https://dev.meta.ai/llama/llama4/license/
    title: Llama 4 Community License Agreement
    published: 2025-04-05
    checked: 2026-10-22
  - url: https://developer.meta.com/ai/llama4/use-policy
    title: Llama 4 Acceptable Use Policy
    checked: 2026-10-22
  - url: https://www.apache.org/licenses/LICENSE-2.0
    title: Apache License, Version 2.0
    checked: 2026-10-22
  - url: https://opensource.org/license/mit
    title: The MIT License
    checked: 2026-10-22
  - url: https://opensource.org/ai/open-weights
    title: "Open Weights: not quite what you've been told"
    checked: 2026-10-22
  - url: https://opensource.org/ai/open-source-ai-definition
    title: The Open Source AI Definition 1.0
    checked: 2026-10-22
---

**Prerequisites:** [M0 lesson 02](../../m0/02-kv-cache-and-batching/), for why memory, more than parameter count, decides what a model costs to serve.

## Why this matters for the factory

Until now the course's generation calls went to `claude-opus-5-5` through the Agent SDK; only M4's embedder and reranker ran locally. A factory that runs at volume ends up with workloads where that is the wrong default: a classifier that runs on every ticket, an embedding step over a help-centre index, a judge that grades thousands of transcripts, a support assistant whose inputs are customer data that must stay in one region. For those, an open-weight model on your own hardware is a candidate, and M6 is about running one properly.

The first decision comes before any GPU: which model you are allowed to run, for what, and under which obligations. That is a licence question, and the 2026 families differ on it more than on benchmarks. Four of the five families below ship under a standard permissive licence. The fifth comes with a custom agreement that withholds rights from one class of companies, and the factory you are building may be in that class.

## Core idea

"Open weight" means the trained parameters are published and come with a licence. The licence decides what you may do with them; the files decide what you can do with them. Keep the two apart:

- **What you get.** The weights, a tokenizer and chat template, a model card with the architecture, and a licence file. Sometimes an acceptable use policy that the licence incorporates.
- **What you do not get.** The Open Source Initiative puts it this way: "Open Weights refer to the final weights and biases of a trained neural network", and they "differ significantly from Open Source AI because they do not include" the training code and the training dataset. Its Open Source AI Definition requires, besides the parameters, "Sufficiently detailed information about the data used to train the system so that a skilled person can build a substantially equivalent system." None of the families below publishes that.
- **What the licence covers.** Use, modification, redistribution and, for Apache 2.0, a patent grant. It does not cover trademarks, it gives no warranty, and it binds only the release it ships with: the next version of the same family can come under different terms.

For an engineer, the practical consequence is that you can serve, quantise and fine-tune these models, but you cannot audit their training data, and you inherit whatever the licence asks of anyone who distributes them or a product built on them.

## Mechanics

### The 2026 families

Sizes, licences and context lengths below are quoted from each model card on 2026-10-22. MoE (mixture-of-experts) models list total and active parameters: memory is set by the total, per-token compute by the active count.

| Family | Sizes on the cards | Licence on the card | Context |
| --- | --- | --- | --- |
| Qwen3.5 | 0.8B, 2B, 27B, 35B-A3B, 122B-A10B among others | "License: apache-2.0" | 262,144 tokens natively |
| Gemma 4 | E2B, E4B, 12B, 26B A4B, 31B | "License: apache-2.0" | 128K (E2B, E4B), 256K (larger) |
| gpt-oss | 120b: 117B, 5.1B active; 20b: 21B, 3.6B active | "License: apache-2.0" | not stated on the card |
| DeepSeek V4 | Pro: 1.6T, 49B activated; Flash: 284B, 13B activated | "License: mit" | one million tokens |
| Llama 4 | Scout: 109B total, 17B activated; Maverick: 400B total, 17B activated | "License: llama4" | 10M (Scout), 1M (Maverick) |

A few details from the cards matter when you shortlist:

- **Qwen3.5-27B** is the size the course uses as its single-GPU reference: stage 06's invented benchmark and stage 07's scenario both assume a 27B model in FP8 on one H100. Its card also lists an unusual layout, "16 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))", which [lesson 02](../02-serving-internals/) turns into a KV-cache budget. The 0.8B model from the same family is what stages 02 and 08 run locally.
- **Gemma 4** changed licence. Google's launch post of 2026-04-02 says "Gemma 4 is released under a commercially permissive Apache 2.0 license", and the Gemma Terms of Use page, last modified 2026-04-01, now says "For Gemma 4 terms, see the Gemma 4 license." Earlier Gemma generations stay under those terms, which incorporate a Prohibited Use Policy and require you to pass the use restrictions on to anyone you distribute to. The launch post announced four sizes; the model card now lists five, adding the 12B. The post also states that the 26B and 31B "unquantized bfloat16 weights fit efficiently on a single 80GB NVIDIA H100 GPU".
- **gpt-oss** ships pre-quantised: "The models were post-trained with MXFP4 quantization of the MoE weights, making gpt-oss-120b run on a single 80GB GPU (like NVIDIA H100 or AMD MI300X) and the gpt-oss-20b model run within 16GB of memory." Its card adds that both models "should only be used with the harmony format", OpenAI's response format, so your serving stack has to apply that chat template.
- **DeepSeek V4** calls itself "a preview version" on the card, and its licence section reads "This repository and the model weights are licensed under the MIT License." At 1.6T total parameters the Pro model is a multi-GPU deployment before any KV cache is counted.
- **Llama 4** is gated: the Hugging Face page asks for "your full legal name, date of birth, and full organization name" before it lets you download, and the licence is Meta's own.

### What Apache 2.0 and MIT grant

Apache 2.0 gives a copyright licence and, in section 3, a patent licence: each contributor grants "a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable (except as stated in this section) patent license to make, have made, use, offer to sell, sell, import, and otherwise transfer the Work". The conditions are about redistribution: give recipients a copy of the licence, mark modified files ("You must cause any modified files to carry prominent notices stating that You changed the files"), and keep the NOTICE file if there is one. Section 6 sets a limit on names: "This License does not grant permission to use the trade names, trademarks, service marks, or product names of the Licensor". You can ship a fine-tuned Qwen3.5 inside your product without the right to use Qwen's name for it.

MIT is shorter: it permits anyone "to deal in the Software without restriction" provided the copyright and permission notice is kept, with no warranty. It carries no explicit patent grant.

Neither licence asks anything of you for running a model on your own servers and returning its output to your users. The obligations start when you distribute the weights or a derivative, for example by shipping a fine-tuned model to a customer or publishing it on a hub.

### The Llama 4 clauses

The Llama 4 Community License Agreement (effective date April 5, 2025) grants broad rights and then adds conditions that Apache 2.0 does not have. Three of them matter for a company.

**The 700 million monthly active users clause.** Section 2, "Additional Commercial Terms":

> If, on the Llama 4 version release date, the monthly active users of the products or services made available by or for Licensee, or Licensee’s affiliates, is greater than 700 million monthly active users in the preceding calendar month, you must request a license from Meta, which Meta may grant to you in its sole discretion, and you are not authorized to exercise any of the rights under this Agreement unless or until Meta otherwise expressly grants you such rights.

The threshold is measured once, on the release date, and it counts affiliates, so a factory inside a large group checks the group's numbers.

**Attribution and naming.** Section 1.b.i: if you distribute the Llama Materials or "a product or service (including another AI model) that contains any of them", you must "prominently display “Built with Llama” on a related website, user interface, blogpost, about page, or product documentation." And if you use the materials "or any outputs or results of the Llama Materials to create, train, fine tune, or otherwise improve an AI model, which is distributed or made available, you shall also include “Llama” at the beginning of any such AI model name." The second sentence covers outputs: a model you distribute that was trained on Llama-generated data carries the name.

**The EU clause.** It sits in the Acceptable Use Policy, which the licence incorporates "by reference":

> With respect to any multimodal models included in Llama 4, the rights granted under Section 1(a) of the Llama 4 Community License Agreement are not being granted to you if you are an individual domiciled in, or a company with a principal place of business in, the European Union. This restriction does not apply to end users of a product or service that incorporates any such multimodal models.

Scout and Maverick both take "Multilingual text and image" input according to their card, so both are multimodal. A company whose principal place of business is in the EU gets no Section 1(a) licence to them, which is the clause that lets you use, modify and distribute them. Its users may use a product built on them by someone else; the company itself may not build it. For an EU-based factory, Llama 4 drops off the shortlist on this clause alone.

### Licence, regulation and residency

A licence is a contract with the model's publisher; regulation applies whatever it says, and [M5 lesson 06](../../m5/06-eu-ai-act-for-engineers/) covers what the EU AI Act asks of a factory. Data residency is a third input and one reason self-hosting is on the table: an open-weight model on your own GPUs in your region keeps prompts and outputs inside your infrastructure, while a hosted API for the same model is a different contract under the provider's terms.

### Choosing by task

Work from the workload backwards, with a leaderboard as a source of candidates at most:

1. **Licence.** Can your company accept it as written? Apache 2.0 and MIT need no legal review beyond notices; a custom licence does, and an EU-based company cannot take Llama 4's multimodal models at all.
2. **Memory at the quantisation you trust.** The weights must fit with room for the KV cache (lesson 02). The cards give anchors: gpt-oss-120b on one 80 GB GPU in MXFP4, gpt-oss-20b within 16 GB, Gemma 4 26B and 31B in bfloat16 on one 80 GB H100. DeepSeek V4 Pro does not fit one GPU in any format.
3. **Context.** A support assistant that sends 3,000 tokens a turn does not need 262,144, and lesson 02 shows that a smaller `--max-model-len` buys concurrency.
4. **Behaviour you depend on.** Tool calling, structured output, a controllable reasoning mode. Gemma 4 lists "configurable thinking modes", gpt-oss "Configurable reasoning effort" and Qwen3.5's chat template has an `enable_thinking` switch. [Lesson 03](../03-running-locally/) shows what happens when a reasoning model spends its token budget thinking.
5. **Your eval set.** M2's harness, run on two or three shortlisted models against the workload's own examples, makes the final call. A public benchmark measures someone else's task, and a ticket classifier for your taxonomy is not on any of them.

## Common pitfalls

- **Calling it open source.** Open-weight releases publish parameters, not training data or training code. Say "open weight" in design documents, and do not promise auditability you cannot deliver.
- **Assuming the family licence carries over.** Gemma 4 is Apache 2.0; Gemma 3 is under the Gemma Terms of Use. Check the licence of the exact release you deploy, and record it next to the model revision.
- **Reading only the licence file.** Llama 4's EU restriction is in the Acceptable Use Policy, which the licence pulls in by reference. Read every document the licence incorporates.
- **Forgetting the distribution triggers.** Self-hosting for your own product needs little; shipping a fine-tuned model to a customer triggers notices, Llama’s “Built with Llama” notice and its naming rule.
- **Sizing by active parameters.** A 284B MoE with 13B active computes like a 13B model per token and needs memory like a 284B one.
- **Treating "fits on one GPU" as a deployment.** The cards' claims count weights; a serving replica also needs KV cache for every concurrent request, which is lesson 02's subject.

## What interviewers ask

**What does an open-weight licence give you, and what does it not?**
The trained parameters with rights to use, modify and redistribute them under the licence's conditions. Not the training data or training code, so you cannot reproduce or audit training; not trademark rights; no warranty. Apache 2.0 adds an explicit patent grant, MIT does not.

**Your company is headquartered in Germany. Can you build a product on Llama 4 Maverick?**
Not under the community licence. The Acceptable Use Policy withholds the Section 1(a) rights for Llama 4's multimodal models from companies with their principal place of business in the EU; only end users of someone else's product are exempt. Shortlist an Apache 2.0 or MIT model instead.

**How do you pick an open model for a new workload?**
Licence first, then whether it fits your hardware at a quantisation you have evaluated, with KV cache for the concurrency you need, then context and features such as tool calling, then your own eval set decides among the remaining two or three.

## Sources

- [Qwen3.5-27B model card](https://huggingface.co/Qwen/Qwen3.5-27B), licence, layout and context length, checked 2026-10-22
- [Qwen3.5-0.8B model card](https://huggingface.co/Qwen/Qwen3.5-0.8B), licence and the sizes in its benchmark table, checked 2026-10-22
- [Gemma 4 31B IT model card](https://huggingface.co/google/gemma-4-31B-it), licence, sizes, context lengths, thinking modes, checked 2026-10-22
- [Gemma 4: Our most capable open models to date](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/), Google, 2026-04-02, the licence change, launch sizes and single-H100 claim, checked 2026-10-22
- [Gemma Terms of Use](https://ai.google.dev/gemma/terms), last modified 2026-04-01, sections 3.1 and 3.2, checked 2026-10-22
- [gpt-oss-120b model card](https://huggingface.co/openai/gpt-oss-120b), sizes, MXFP4, harmony format, checked 2026-10-22
- [DeepSeek-V4-Pro model card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro), sizes, context, licence section, checked 2026-10-22
- [Llama-4-Scout-17B-16E-Instruct model card](https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct), sizes, modalities, the access form, checked 2026-10-22
- [Llama 4 Community License Agreement](https://dev.meta.ai/llama/llama4/license/), effective 2025-04-05, sections 1.b.i and 2, checked 2026-10-22
- [Llama 4 Acceptable Use Policy](https://developer.meta.com/ai/llama4/use-policy), the multimodal EU clause, checked 2026-10-22
- [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0), sections 3, 4 and 6, checked 2026-10-22
- [The MIT License](https://opensource.org/license/mit), Open Source Initiative, checked 2026-10-22
- [Open Weights: not quite what you've been told](https://opensource.org/ai/open-weights), Open Source Initiative, checked 2026-10-22
- [The Open Source AI Definition 1.0](https://opensource.org/ai/open-source-ai-definition), Open Source Initiative, "Preferred form to make modifications", checked 2026-10-22
- Course files (repository files, not web sources): the stage 06 and 07 descriptions in `course/m6-serving-lab/README.md`
