---
title: M6 Serving and platform
freshness: skip
---

Open models served as a platform: choosing an open-weight model by its licence, what a vLLM replica does with its GPU memory, running a model locally and reading its numbers without overclaiming, Kubernetes manifests and queue-based autoscaling for inference, TTFT, TPS and the cost per million tokens, and when to fine-tune.

## Lessons

- [01 Open-weight landscape and licences](./01-open-weight-landscape-and-licences/)
- [02 Serving internals](./02-serving-internals/)
- [03 Running locally](./03-running-locally/)
- [04 Kubernetes for inference](./04-kubernetes-for-inference/)
- [05 Measuring TTFT, TPS and cost](./05-measuring-ttft-tps-and-cost/)
- [06 Fine-tuning, when and how](./06-fine-tuning-when-and-how/)
- [07 Interview angle](./07-interview-angle/)

## Exercise

[M6 serving lab](/exercises/m6-serving-lab/): build `serving_lab`, the measuring and platform side of serving open models, against a fake OpenAI-compatible server that needs no GPU, with tests and hints.

1. `01-load-generator`: a streaming load generator that measures TTFT, TPS and throughput against the fake server, with nearest-rank percentiles.
2. `02-local-model`: run the load generator against `qwen3.5:0.8b` in Ollama (needs Ollama and the model, about 1.3 GB).
3. `03-k8s-manifests`: render the vendored vLLM production stack chart and validate it, with gateway, pool and scaling manifests, offline (needs Helm and kubeconform).
4. `04-autoscaling-policy`: a KEDA-style scaling policy replayed over an invented day of queue metrics (needs kubeconform).
5. `05-gateway-routing`: a gateway between a local model and the Claude API with health probes, fallback rules and cost per route.
6. `06-benchmark-report`: a GPU benchmark report with a cost-per-million-tokens model, from an invented H100 run.
7. `07-serving-plan`: place four factory workloads on a local model, self-hosted vLLM or the API, with capacity arithmetic and risks (judgment stage).
8. `08-live-gateway`: run the gateway over the local model and the Claude API (needs Ollama, the model and a Claude login).
