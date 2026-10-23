import { getCollection } from "astro:content";
import { CAPSTONE_RECORD, LIVE_RECORD, MERGED, ORDER, WHAT_YOU_BUILD } from "../data/modules.ts";
import {
  checkRun,
  liveRecordLine,
  moduleStatus,
  newestVerifiedOn,
  stagesWritten,
  type CheckRun,
  type LiveRecord,
  type ModuleStatus,
} from "./landing.ts";

export interface Lesson {
  title: string;
  href: string;
}

export interface CourseModule {
  id: string;
  label: string;
  title: string;
  href: string;
  what: string;
  exercise: string | null;
  stages: { id: string; title: string }[];
  stagesWritten: number;
  lessons: Lesson[];
  live: string;
  status: ModuleStatus;
}

export interface Course {
  modules: CourseModule[];
  merged: number;
  verifiedOn: string | null;
  sdkPin: string | null;
  capstone: CheckRun;
}

const COURSE = "../../../course/";

const records = Object.fromEntries(
  Object.entries(
    import.meta.glob<LiveRecord>("../../../course/*/fixtures/live_*.json", { eager: true, import: "default" }),
  ).map(([path, record]) => [path.slice(COURSE.length), record]),
);

const testSources = Object.fromEntries(
  Object.entries(
    import.meta.glob<string>("../../../course/*/tests/test_*.py", { eager: true, query: "?raw", import: "default" }),
  ).map(([path, source]) => [path.slice(COURSE.length), source]),
);

function testPaths(exercise: string, tests: string[]): string[] {
  return tests.map((t) => `${exercise}/${t}`);
}

let cached: Promise<Course> | undefined;

export function loadCourse(): Promise<Course> {
  cached ??= buildCourse();
  return cached;
}

async function buildCourse(): Promise<Course> {
  const exercises = (await getCollection("exercises")).map((e) => e.data);
  const docs = await getCollection("docs");
  const modules = ORDER.map((id): CourseModule => {
    const exercise = exercises.find((e) => e.module === id) ?? null;
    const index = docs.find((d) => d.id === `${id}/index` || d.id === id);
    const lessons = docs
      .filter((d) => d.id.startsWith(`${id}/`) && d.id !== `${id}/index`)
      .sort((a, b) => (a.data.order ?? 0) - (b.data.order ?? 0) || a.id.localeCompare(b.id))
      .map((d) => ({ title: d.data.title, href: `/${d.id}/` }));
    const stages = exercise?.stages ?? [];
    return {
      id,
      label: id.toUpperCase(),
      title: (index?.data.title ?? id).replace(/^M\d+\s+/, ""),
      href: `/${id}/`,
      what: WHAT_YOU_BUILD[id] ?? "",
      exercise: exercise?.exercise ?? null,
      stages: stages.map(({ id, title }) => ({ id, title })),
      stagesWritten: exercise ? stagesWritten(testPaths(exercise.exercise, stages.map((s) => s.tests)), testSources) : 0,
      lessons,
      live: liveRecordLine(LIVE_RECORD[id] ?? null, records),
      status: moduleStatus(id, exercise !== null, MERGED),
    };
  });
  const lessonData = docs.map((d) => d.data);
  return {
    modules,
    merged: modules.filter((m) => m.status === "merged").length,
    verifiedOn: newestVerifiedOn(lessonData.map((d) => d.verified_on)),
    sdkPin: lessonData.map((d) => d.pins?.["pypi:claude-agent-sdk"]).find(Boolean) ?? null,
    capstone: checkRun(records[CAPSTONE_RECORD], `fixtures/${CAPSTONE_RECORD.split("/").pop()}`),
  };
}
