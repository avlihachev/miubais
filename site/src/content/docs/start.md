---
title: Start here
description: One command block from an empty directory to the first failing stage.
freshness: skip
---

## What you need

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- A Claude Code login, for hints.
- Node, Go, Docker and Ollama only in the modules that say so.

`uv run miubais doctor` lists each requirement and whether this machine has it.

## Run this

```bash
git clone https://github.com/avlihachev/miubais
cd miubais
uv sync
uv run miubais doctor
uv run miubais start m0-cost-lab
uv run miubais check m0-cost-lab
```

## What you will see

- `doctor` prints a table of requirements.
- `start` copies the starter into `workspace/m0-cost-lab`.
- `check` stops at stage 01 with the test output, because the starter raises on purpose.

## Then

Open the [M0 module index](/m0/) and read [lesson 01](/m0/01-tokens-prefill-decode/). Edit the code in `workspace/m0-cost-lab` and run `uv run miubais check m0-cost-lab` again. `uv run miubais hint m0-cost-lab` explains what the failing test checks and never shows the solution.
