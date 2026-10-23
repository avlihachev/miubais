export type ModuleStatus = "merged" | "in progress" | "not started";
export type MarkStatus = "passed" | "failed" | "skipped" | "pending";
export type LiveRecord = Record<string, any>;

export interface LiveSpec {
  file: string;
  format: (record: LiveRecord) => string;
}

export interface CheckRun {
  title: string;
  source: string;
  cells: { value: string; label: string }[];
}

export const NO_RECORD = "not recorded";
const UNWRITTEN = "stage not written yet";

export function fixed2(n: number): string {
  return n.toFixed(2);
}

export function usd(n: number): string {
  return `$${n.toFixed(2)}`;
}

export function seconds(ms: number): string {
  return `${Math.round(ms / 1000)} s`;
}

export function moduleStatus(id: string, hasExercise: boolean, merged: readonly string[]): ModuleStatus {
  if (hasExercise && merged.includes(id)) return "merged";
  return hasExercise ? "in progress" : "not started";
}

export function liveRecordLine(spec: LiveSpec | string | null, records: Record<string, LiveRecord>): string {
  if (typeof spec === "string") return spec;
  const record = spec ? records[spec.file] : undefined;
  return record ? spec!.format(record) : NO_RECORD;
}

export function newestVerifiedOn(dates: (Date | string | undefined)[]): string | null {
  const iso = dates
    .filter((d): d is Date | string => d !== undefined)
    .map((d) => (d instanceof Date ? d.toISOString() : d).slice(0, 10));
  return iso.length ? iso.reduce((a, b) => (b > a ? b : a)) : null;
}

export function stagesWritten(testFiles: string[], sources: Record<string, string>): number {
  return testFiles.filter((f) => sources[f] !== undefined && !sources[f].includes(UNWRITTEN)).length;
}

export function markStatus(
  progress: Record<string, Record<string, { status: string }>>,
  exercise: string,
  stage: string,
): MarkStatus {
  const status = progress[exercise]?.[stage]?.status;
  return status === "passed" || status === "failed" || status === "skipped" ? status : "pending";
}

export function checkRun(record: LiveRecord, source: string): CheckRun {
  const { metrics, totals } = record;
  return {
    title: `Capstone reviewer, run on ${totals.prs} pull requests`,
    source: `${source} · ${record.model}`,
    cells: [
      { value: fixed2(metrics.blocker_recall), label: "blocker recall" },
      { value: fixed2(metrics.overall.precision), label: "precision of findings" },
      { value: `${record.verdicts_agreeing_with_key} / ${totals.prs}`, label: "verdicts agree with the key" },
      { value: usd(totals.cost_usd), label: `total cost, ${seconds(totals.duration_ms)}` },
    ],
  };
}
