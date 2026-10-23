import { existsSync } from "node:fs";
import { defineCollection } from "astro:content";
import { glob } from "astro/loaders";
import { z } from "astro/zod";
import { docsLoader } from "@astrojs/starlight/loaders";
import { docsSchema } from "@astrojs/starlight/schema";

const lessonFields = z
  .object({
    verified_on: z.coerce.date().optional(),
    executed: z.enum(["local", "docker", "cloud", "none"]).optional(),
    pins: z.record(z.string(), z.string()).optional(),
    sources: z
      .array(
        z.object({
          url: z.string().url(),
          title: z.string(),
          published: z.coerce.date().optional(),
          checked: z.coerce.date(),
        }),
      )
      .optional(),
    freshness: z.literal("skip").optional(),
    module: z.string().optional(),
    order: z.number().optional(),
  })
  .refine(
    (d) => d.freshness === "skip" || (d.verified_on && d.executed && d.pins && d.sources),
    { message: "lesson needs verified_on, executed, pins, sources (or freshness: skip)" },
  );

const requirement = z.enum(["claude-auth", "api-key", "docker", "go", "node", "helm", "kubeconform", "ollama", "embed-model"]);

const stage = z
  .object({
    id: z.string(),
    title: z.string(),
    tests: z.string(),
    live: z.boolean().default(false),
    requires: z.array(requirement).default([]),
    timeout: z.number().int().positive().optional(),
    lesson: z.string().optional(),
  })
  .strict()
  .refine((s) => !s.live || s.requires.length > 0, { message: "live stage needs requires" });

const exercises = defineCollection({
  loader: glob({ pattern: "*/stages.yaml", base: "../course" }),
  schema: z
    .object({
      exercise: z.string(),
      module: z.string(),
      title: z.string(),
      package: z.string(),
      stages: z.array(stage).min(1),
    })
    .strict(),
});

const exerciseReadmes = defineCollection({
  loader: glob({ pattern: "*/README.md", base: "../course" }),
  schema: z.object({}).passthrough(),
});

const book = defineCollection({
  loader: glob({ pattern: "**/*.{md,mdx}", base: "./src/content/book" }),
  schema: z.object({ title: z.string(), description: z.string().optional() }).passthrough(),
});

// the public export ships without the book
const hasBook = existsSync(new URL("./content/book", import.meta.url));

export const collections = {
  ...(hasBook ? { book } : {}),
  exercises,
  exerciseReadmes,
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({ extend: lessonFields }),
  }),
};
