export type DriftLevel = "none" | "patch" | "minor" | "major" | "unknown";
export type BadgeColor = "green" | "amber" | "red";
export type Executed = "local" | "docker" | "cloud" | "none";

export interface Drift {
  pinned: string | null;
  latest: string | null;
  level: DriftLevel;
}

export interface LinkStatus {
  url: string;
  ok: boolean;
  redirected: boolean;
}

export interface LessonEntry {
  slug: string;
  path: string;
  title: string;
  verified_on: string;
  executed: Executed;
  badge: BadgeColor;
  drifts: Record<string, Drift>;
  links: LinkStatus[];
}

export interface FreshnessReport {
  generated_at: string;
  lessons: LessonEntry[];
}

export interface LessonFrontmatter {
  verified_on: Date | string;
  executed: Executed;
  pins?: Record<string, string>;
}

export interface Badge {
  color: BadgeColor;
  label: string;
  verifiedOn: string;
  executed: Executed;
  drifts: [string, Drift][];
}

const DAY_MS = 86_400_000;
const GREEN_DAYS = 90;
const RED_DAYS = 180;
const RANK: Record<BadgeColor, number> = { green: 0, amber: 1, red: 2 };
const STALE_LEVELS: DriftLevel[] = ["minor", "major", "unknown"];

function isoDate(value: Date | string): string {
  return (value instanceof Date ? value.toISOString() : value).slice(0, 10);
}

function worst(...colors: BadgeColor[]): BadgeColor {
  return colors.reduce((a, b) => (RANK[b] > RANK[a] ? b : a), "green");
}

function colorFromAge(verifiedOn: string, executed: Executed, now: Date): BadgeColor {
  const ageDays = Math.floor((now.getTime() - Date.parse(verifiedOn)) / DAY_MS);
  if (ageDays > RED_DAYS) return "red";
  if (executed === "none" || ageDays > GREEN_DAYS) return "amber";
  return "green";
}

function colorFromReport(entry: LessonEntry): BadgeColor {
  if (entry.links.some((l) => !l.ok)) return "red";
  const stalePin = Object.values(entry.drifts).some((d) => STALE_LEVELS.includes(d.level));
  if (stalePin || entry.links.some((l) => l.redirected)) return "amber";
  return "green";
}

export function badgeFor(
  lesson: LessonFrontmatter,
  report: LessonEntry | undefined,
  now: Date = new Date(),
): Badge {
  const verifiedOn = isoDate(lesson.verified_on);
  const current = report && isoDate(report.verified_on) === verifiedOn ? report : undefined;
  const ageColor = colorFromAge(verifiedOn, lesson.executed, now);
  const pinCount = Object.keys(lesson.pins ?? current?.drifts ?? {}).length;
  return {
    color: current ? worst(ageColor, colorFromReport(current)) : ageColor,
    label: `verified ${verifiedOn} · ${lesson.executed} · ${pinCount} pins`,
    verifiedOn,
    executed: lesson.executed,
    drifts: Object.entries(current?.drifts ?? {}).filter(([, d]) => d.level !== "none"),
  };
}
