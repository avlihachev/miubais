# Mum, I wanna be an AI Engineer

A course for engineers who already build agents and want the production half of the job: inference economics, enforced harnesses, evals, observability, retrieval, security, serving. The repository is also the proof that its author can build and run a small AI software factory: lessons are pinned and dated, exercises are graded by tests, the tutor is bounded by failing tests, and a freshness pipeline opens review branches when the world moves.

## Start

```bash
git clone https://github.com/avlihachev/miubais
cd miubais
uv sync
uv run miubais doctor
uv run miubais start m0-cost-lab
uv run miubais check m0-cost-lab
```

The last command fails at stage 01: the starter raises on purpose, and the lessons at https://factory.lihachev.pro tell you what to build.

## Prerequisites

Required:

- Python 3.12
- uv
- a Claude Code login (tutor)

Optional, per module: Node 22+ and pnpm (the local site), Node 26+ (M7), Go 1.27 (M7), Docker (M4 stages 02-09 run Postgres with pgvector), Helm, kubeconform, Ollama, an Anthropic API key (M0 live stages), the embedding models `BAAI/bge-small-en-v1.5` and `Xenova/ms-marco-MiniLM-L-6-v2` (M4 stage 08, 66.5 MB and 91 MB, about 160 MB; the live stage downloads them on first run into `~/.cache/fastembed` (or `$FASTEMBED_CACHE_PATH`); `uv run miubais doctor` shows `embed-model`). `miubais doctor` lists each prerequisite and whether this machine has it.

## Commands

```bash
uv sync
uv run miubais doctor
uv run miubais start <exercise>
uv run miubais check <exercise>
uv run miubais reset <exercise>    # forget recorded progress (or --all); start --force does it too
uv run miubais hint <exercise>
```

The site and its local API:

```bash
uv run miubais serve              # API at http://127.0.0.1:8787
cd site && pnpm install && pnpm dev   # site at http://localhost:4321
```

## How exercises are graded

Stages are declared in each exercise's `stages.yaml`. `miubais start` copies the starter into `workspace/`; the copy is imported through `PYTHONPATH`, not installed, and exercise dependencies live in the root `exercises` dependency group, so `uv.lock` stays unchanged. `start` also records hashes of the starter files in `workspace/<exercise>/.miubais-starter.json`; when a pull changes the starter afterwards, `check` lists the new, changed and removed files before running, marks changed files you have not edited, and leaves your copy alone. Deterministic tests decide pass or fail. Live stages are skipped when a requirement (Docker, API key, ...) is missing. Reference solutions and the selftest gate stay in the author's private checkout.

## The tutor

`miubais hint` explains a failing test from its output and the learner's diff; it never gives the solution. A leak filter rejects hints containing reference-only identifiers or long code blocks. The tutor's Read/Grep/Glob calls are confined to the learner workspace and the exercise README.

## Layout

- `course/`: exercises (starter, tests, stages, README)
- `site/`: Astro + Starlight lessons, progress and freshness pages
- `tools/miubais/`: the CLI, grader, tutor, freshness pipeline, local API

## Licence

Code under MIT (`LICENSE`); lessons and exercise READMEs under CC BY-NC-SA 4.0 (`LICENSE-CONTENT`).
