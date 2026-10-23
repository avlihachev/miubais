import { existsSync, readdirSync, readFileSync } from "node:fs";
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import { parse } from "yaml";

const modules = [
  ["m0", "M0 Inference economics"],
  ["m1", "M1 Enforced harness"],
  ["m2", "M2 Evals as engineering"],
  ["m3", "M3 Observability and cost"],
  ["m4", "M4 Retrieval as a component"],
  ["m5", "M5 Security and compliance"],
  ["m6", "M6 Serving and platform"],
  ["m7", "M7 Capstone: pre-review"],
];

const courseDir = new URL("../course/", import.meta.url);

const exercises = readdirSync(courseDir, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(new URL(`${d.name}/stages.yaml`, courseDir)))
  .map((d) => parse(readFileSync(new URL(`${d.name}/stages.yaml`, courseDir), "utf8")))
  .sort((a, b) => a.exercise.localeCompare(b.exercise));

const exerciseLink = (e) => ({ label: `Exercise: ${e.title}`, link: `/exercises/${e.exercise}/` });
const moduleIds = new Set(modules.map(([dir]) => dir));
const unassigned = exercises.filter((e) => !moduleIds.has(e.module));

const head = [
  { tag: "link", attrs: { rel: "preconnect", href: "https://fonts.googleapis.com" } },
  { tag: "link", attrs: { rel: "preconnect", href: "https://fonts.gstatic.com", crossorigin: true } },
  {
    tag: "link",
    attrs: {
      rel: "stylesheet",
      href: "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap",
    },
  },
];

if (process.env.CF_BEACON_TOKEN) {
  head.push({
    tag: "script",
    attrs: {
      defer: true,
      src: "https://static.cloudflareinsights.com/beacon.min.js",
      "data-cf-beacon": JSON.stringify({ token: process.env.CF_BEACON_TOKEN }),
    },
  });
}

export default defineConfig({
  site: "https://factory.lihachev.pro",
  integrations: [
    starlight({
      title: "Mum, I wanna be an AI Engineer",
      description: "A test-graded, version-pinned course for engineers who already build agents.",
      customCss: ["./src/styles/custom.css"],
      head,
      components: { PageTitle: "./src/components/PageTitleWithBadge.astro" },
      sidebar: [
        { label: "Start here", link: "/start/" },
        ...modules.map(([dir, label]) => ({
          label,
          items: [
            { autogenerate: { directory: dir } },
            ...exercises.filter((e) => e.module === dir).map(exerciseLink),
          ],
        })),
        {
          label: "Course tools",
          items: [
            { label: "Factory map", link: "/map/" },
            { label: "Progress", link: "/progress/" },
            { label: "Freshness", link: "/freshness/" },
            ...unassigned.map(exerciseLink),
          ],
        },
      ],
    }),
  ],
});
