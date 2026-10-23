import type { Job } from "./api.ts";
import { statusLabel } from "./status.ts";

export function formatHours(hours: number): string {
  if (hours < 1) {
    return `${Math.round(hours * 60)} min`;
  }
  return `${hours.toFixed(1)} h`;
}

export function formatLanguages(source: string, target: string): string {
  return `${source} -> ${target}`;
}

export function formatDate(iso: string): string {
  return iso.slice(0, 10);
}

export function formatSummary(job: Job): string {
  const languages = formatLanguages(job.source_lang, job.target_lang);
  const hours = formatHours(job.hours_estimate);
  return `${job.reference}: ${languages}, ${hours} (${statusLabel(job.status)})`;
}
