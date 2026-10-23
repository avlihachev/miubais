import { fixed2, type LiveSpec } from "../lib/landing.ts";

export const ORDER = ["m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7"] as const;
export const MERGED = ["m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7"] as const;
export const CAPSTONE_RECORD = "m7-capstone/fixtures/live_review_run.json";

export const WHAT_YOU_BUILD: Record<string, string> = {
  m0: "Tool loop, streaming, prefix caching, cost ledger, batch builder",
  m1: "Policy engine, PreToolUse hooks, durable sessions, caps, reviewer subagent",
  m2: "Trace loader, labels and kappa, schema-bound judge, trust and regression gates",
  m3: "GenAI spans, cost from spans, budget guard, Langfuse export, router",
  m4: "Chunker, pgvector store, hybrid RRF, reranker, metrics, cited answers",
  m5: "Injection detector, provenance and taint, secrets, remote MCP auth, audit log",
  m6: "Load generator, local models, K8s manifests, autoscaling, gateway",
  m7: "Rule loader, read-only reviewer, verify gate, blocker ranking, metrics",
};

const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);
const minor = (v: string) => v.split(".").slice(0, 2).join(".");

export const LIVE_RECORD: Record<string, LiveSpec | string | null> = {
  m0: "synthetic transports",
  m1: null,
  m2: {
    file: "m2-evals-lab/fixtures/live_judge_run_2.json",
    format: (r) => `judge ${r.outcome_agreement}/${r.n} outcome`,
  },
  m3: {
    file: "m3-trace-lab/fixtures/live_traced_run.json",
    format: (r) => `${sum(r.spans)} spans · Langfuse ${minor(r.langfuse)}`,
  },
  m4: {
    file: "m4-retrieval-lab/fixtures/live_local_models_run.json",
    format: (r) => `recall@${r.k} ${fixed2(r.reranked.recall)} · MRR ${fixed2(r.reranked.mrr)}`,
  },
  m5: {
    file: "m5-injection-lab/fixtures/live_injection_run.json",
    format: (r) => `injection ${r.denied > 0 ? "denied" : "not denied"} · checklist ${r.checklist_passed}/${r.checklist_total}`,
  },
  m6: {
    file: "m6-serving-lab/fixtures/live_gateway_run.json",
    format: (r) => `gateway ${r.routes.ollama.requests + r.routes.claude.requests}/${r.prompts.length} routed · $${r.total_cost_usd.toFixed(3)}`,
  },
  m7: {
    file: CAPSTONE_RECORD,
    format: (r) => `${r.totals.prs} PRs · recall ${fixed2(r.metrics.blocker_recall)}`,
  },
};
