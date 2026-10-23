import type { FreshnessReport, LessonEntry } from "./badge";

export * from "./badge";

const reports = import.meta.glob<FreshnessReport>("../../../freshness/latest.json", {
  eager: true,
  import: "default",
});

export function loadLatest(): FreshnessReport | null {
  return Object.values(reports)[0] ?? null;
}

export function reportEntry(slug: string): LessonEntry | undefined {
  return loadLatest()?.lessons.find((l) => l.slug === slug);
}
